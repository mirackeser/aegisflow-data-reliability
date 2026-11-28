# SPDX-License-Identifier: Apache-2.0
"""The Command Center's live simulated plant: a background clock, controls, KPIs and agent investigations.

The plant itself (readings, faults, baseline, monitor) is ``aegisflow_dr.simulation``; this module only drives it in
real time x speed and adds what the page needs. Every KPI is computed from the simulator state or from the retained,
digest-verified agent run records (``agent_summary.summarize``); a KPI with nothing to count is ``None`` (n/a).
"""
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
import time

import hashlib

from aegisflow_dr.agents.context import reference
from aegisflow_dr.agents.runtime import verify_record
from aegisflow_dr.baseline import canonical_digest
from aegisflow_dr.casefile import (LINKS, MISMATCH, MISSING, VERIFIED, build_chain, chain_intact, decision_intact,
                                   decision_record, digest)
from aegisflow_dr.hypotheses import investigate, verify_investigation
from aegisflow_dr.pipeline import InputRejected
from aegisflow_dr.simulation import (FAULTS, READY, REFERENCE_WINDOWS, SENSOR_FAULTS, SENSORS, STREAM_FAULTS, UNITS,
                                     WINDOW_SECONDS, EvidenceNotReady, Plant, timestamp)
from agent_summary import summarize

SPEEDS = (1, 5, 20)
DEFAULT_SPEED, SEED = 5, 7
TICK_S, MAX_STEPS_PER_TICK, MODEL_TTL_S, RECENT_RUNS, MAX_INVESTIGATIONS = 0.25, 120, 30.0, 5, 20
ACTIONS = ("start", "pause", "reset", "speed")
BASELINE_LABEL = "simulated-plant"


def _wall():
    return datetime.now(timezone.utc)


def _verified(check, value):
    try:
        check(value)
    except InputRejected:
        return False
    return True


def _investigation_ok(record):
    return _verified(verify_investigation, record)


def _run_ok(record):
    return _verified(verify_record, record)


class PlantController:
    def __init__(self, agents, *, model_status=None, seed=SEED, clock=time.monotonic, wall=_wall, thread=True,
                 tick_s=TICK_S, decisions=None):
        # ``agents`` returns the run manager (the workbench may replace its manager after construction).
        self._agents, self._model_status, self.seed = agents, model_status, seed
        self._clock, self._wall, self._threaded, self._tick_s = clock, wall, thread, tick_s
        self.lock = Lock()
        self._stop, self._thread = Event(), None
        self._model, self._model_at = None, None
        self._summary_key, self._summary = None, None
        self.launched = []  # agent runs started from plant incidents in this process, oldest first
        self._investigations = {}  # (baseline digest, evidence digest, as_of) -> probe loop summary, oldest first
        self._cache_lock = Lock()
        self._decisions = decisions  # DecisionStore, or None without a state folder
        self._fresh()

    def _fresh(self):
        # The commissioning period ends now, so the live readings carry the current wall-clock time.
        commissioning = timedelta(seconds=WINDOW_SECONDS * REFERENCE_WINDOWS)
        self.plant = Plant(seed=self.seed, start=self._wall() - commissioning)
        self.running, self.speed, self._carry, self._last = False, DEFAULT_SPEED, 0.0, self._clock()

    # -- clock --------------------------------------------------------------------------------------------------------
    def _loop(self):
        while not self._stop.wait(self._tick_s):
            self.tick()

    def close(self):
        self._stop.set()

    def tick(self):
        """Advance the plant by the real time elapsed since the last tick x speed (whole simulated seconds)."""
        with self.lock:
            self._advance()

    def _advance(self):
        now = self._clock()
        if self.running:
            elapsed = (now - self._last) * self.speed + self._carry
            whole = int(elapsed)
            steps = min(whole, MAX_STEPS_PER_TICK)
            self._carry = elapsed - whole if steps == whole else 0.0  # a stall is dropped, not replayed
            self.plant.advance(steps)
        self._last = now

    # -- controls -----------------------------------------------------------------------------------------------------
    def control(self, action, speed=None):
        if action not in ACTIONS:
            raise InputRejected("Unknown action")
        if action == "speed" and (type(speed) is not int or speed not in SPEEDS):
            raise InputRejected("Speed must be one of %s" % ", ".join(map(str, SPEEDS)))
        with self.lock:
            self._advance()
            if action == "start":
                self.running = True
            elif action == "pause":
                self.running = False
            elif action == "reset":
                self._fresh()
            else:
                self.speed = speed
        if action == "start" and self._threaded and self._thread is None:
            self._thread = Thread(target=self._loop, name="simulated-plant", daemon=True)
            self._thread.start()
        return self.status()

    def inject(self, fault, sensor=None):
        if sensor is not None and type(sensor) is not str:
            raise InputRejected("The sensor must be a name")
        with self.lock:
            self._advance()
            return self.plant.inject(fault, sensor)

    def clear(self, fault_id):
        with self.lock:
            self._advance()
            return self.plant.clear(fault_id)

    def investigate(self, incident_id):
        """Start an agent run on the incident's frozen evidence window with the plant baseline.

        KeyError (unknown incident), EvidenceNotReady (evidence still being collected) and Busy propagate.
        """
        with self.lock:
            plant = self.plant
            incident = plant.incident(incident_id)
            payload, as_of = plant.evidence(incident_id)
            record = plant.baseline
        run_id = self._agents().start(payload, baseline_record=record, baseline_label=BASELINE_LABEL, as_of=as_of,
                                   name="%s %s %s" % (BASELINE_LABEL, incident_id, incident["sensor"]))
        with self.lock:
            self.launched.append(run_id)
            if self.plant is plant:
                plant.incident(incident_id)["run_id"] = run_id
        return run_id

    # -- views --------------------------------------------------------------------------------------------------------
    def incident(self, incident_id):
        """One incident with its surrounding readings, the probe loop on its frozen evidence and, when it was
        investigated, the run summary; KeyError."""
        with self.lock:
            self._advance()
            plant = self.plant
            view = plant.incident_view(incident_id)
            evidence = plant.evidence(incident_id) if view["incident"]["evidence"]["state"] == READY else None
        view["investigation"] = None if evidence is None else self._investigation(plant, view["incident"], evidence)[0]
        view["decision"] = (self._decisions.latest(view["incident"]["evidence"]["sha256"])
                            if self._decisions and evidence is not None else None)
        runs, run_id = self._agents().summaries(), view["incident"]["run_id"]
        view["runs_active"] = runs["active"]
        view["run"] = next((r for r in runs["runs"] if r["run_id"] == run_id), None)
        return view

    def _investigation(self, plant, incident, evidence):
        """The deterministic probe loop on the frozen evidence: the same call, on the same bytes, as the agents' A24.

        Returns (summary for the page, full record). The summary's evidence reference lets the page check that a run's
        A24 evidence is exactly this record, and so show the measured probe values the run record does not carry.
        Cached per input under its own small lock.
        """
        payload, as_of = evidence
        key = (plant.baseline["digest"], incident["evidence"]["sha256"], as_of)  # the probe loop's whole input
        with self._cache_lock:
            cached = self._investigations.get(key)
        if cached is not None:
            return cached
        record = investigate(plant.baseline, payload, as_of=as_of)  # deterministic and slow-ish: outside the locks
        summary = {"ref": reference("investigation", record), "verdict": record["verdict"], "probes": record["probes"],
                   "trace_sha256": record["trace_sha256"],
                   "hypotheses": [{k: h[k] for k in ("id", "mechanism", "column", "status")} for h in record["hypotheses"]]}
        with self._cache_lock:
            self._investigations[key] = (summary, record)
            while len(self._investigations) > MAX_INVESTIGATIONS:
                self._investigations.pop(next(iter(self._investigations)))
        return summary, record

    # -- case file: evidence chain and human decision -----------------------------------------------------------------
    def _case_sources(self, incident_id):
        """(plant, incident view, evidence bytes and as_of or None, probe summary and record or None, run detail or None)."""
        with self.lock:
            self._advance()
            plant = self.plant
            incident = plant.incident_view(incident_id)["incident"]
            evidence = plant.evidence(incident_id) if incident["evidence"]["state"] == READY else None
        probes = None if evidence is None else self._investigation(plant, incident, evidence)
        run = None
        if incident["run_id"] is not None:
            try:
                run = self._agents().detail(incident["run_id"])
            except KeyError:  # dropped from the bounded run history
                run = None
        return plant, incident, evidence, probes, run

    def case_file(self, incident_id):
        """The incident's evidence chain, every link re-verified from its source, and the decision history; KeyError."""
        plant, incident, evidence, probes, run = self._case_sources(incident_id)
        ev = incident["evidence"]
        record = (run or {}).get("record")
        items, checks = [], []

        def add(kind, record_sha256, at, summary, ok, reason=None):
            items.append((kind, record_sha256, at, summary))
            checks.append({"kind": kind, "status": VERIFIED if ok else MISMATCH, "reason": None if ok else reason})

        base = plant.baseline
        add("baseline", base["digest"], timestamp(plant.start, plant.live_start - 1),
            {"records": sum(r["records"] for r in base["references"]), "references": len(base["references"])},
            canonical_digest(base) == base["digest"], "baseline_digest")
        if evidence is not None:
            payload, as_of = evidence
            add("evidence", ev["sha256"], as_of,
                {"first_t": ev["first_t"], "as_of_t": ev["as_of_t"], "records": ev["records"], "method": ev["method"],
                 "onset_t": ev["onset_t"], "statistic": ev["statistic"]},
                hashlib.sha256(payload).hexdigest() == ev["sha256"], "evidence_bytes")
            summary, full = probes
            supported = sorted(h["mechanism"] for h in summary["hypotheses"] if h["status"] == "supported")
            add("probes", summary["trace_sha256"], as_of,
                {"verdict": summary["verdict"], "supported": supported, "ref": summary["ref"]["id"]},
                _investigation_ok(full), "probe_trace")
            if record is not None:
                a24 = next((a["result"] for a in record["agents"] if a["agent_id"] == "A24"), {}) or {}
                linked = summary["ref"] in [{"id": r["id"], "sha256": r["sha256"]} for r in a24.get("evidence_refs", [])]
                judge = record["judge"]
                add("agent_run", record["trace_sha256"], run["finished_at"],
                    {"run_id": record["run_id"], "status": record["status"],
                     "completed": sum(a["result"]["status"] == "COMPLETED" for a in record["agents"]),
                     "judge": {k: judge[k] for k in ("accepted", "advisory", "rejected")}, "a24_matches_probes": linked},
                    _run_ok(record) and linked, "run_trace_or_a24_evidence")
                decision = self._decisions.latest(ev["sha256"]) if self._decisions else None
                if decision is not None and decision["run_id"] == record["run_id"]:
                    add("decision", decision["sha256"], decision["decided_at"],
                        {k: decision[k] for k in ("decision", "candidate", "reviewer")}, decision_intact(decision),
                        "decision_digest")
        chain = build_chain(items)
        checks += [{"kind": kind, "status": MISSING, "reason": None} for kind in LINKS[len(checks):]]
        intact = chain_intact(chain)
        complete = intact and all(c["status"] == VERIFIED for c in checks)
        history = self._decisions.history(ev["sha256"]) if self._decisions and ev.get("sha256") else []
        head = chain[-1]["link_sha256"] if chain else None
        return {"incident_id": incident_id, "simulation": True, "chain": chain, "checks": checks, "intact": intact,
                "complete": complete, "head": head, "decisions": history,
                "content_sha256": digest({"chain": chain, "checks": checks, "decisions": history})}

    def decide(self, incident_id, body):
        """Record the human decision on an investigated incident (never executed); returns the case file.

        KeyError (unknown incident), EvidenceNotReady, InputRejected (no finished run, a candidate the probes do not
        support, invalid fields).
        """
        if type(body) is not dict or set(body) - {"decision", "candidate", "reviewer", "note"}:
            raise InputRejected("A decision has the fields decision, candidate, reviewer and note")
        if self._decisions is None:
            raise InputRejected("Decisions need the private state folder")
        plant, incident, evidence, probes, run = self._case_sources(incident_id)
        if evidence is None:
            raise EvidenceNotReady(incident["evidence"])
        if not run or run.get("record") is None:
            raise InputRejected("Decide after the agent investigation on this evidence has finished")
        summary, _ = probes
        record = decision_record(
            incident_id=incident_id, evidence_sha256=incident["evidence"]["sha256"], run_id=run["record"]["run_id"],
            decision=body.get("decision"), candidate=body.get("candidate"),
            supported=[h["mechanism"] for h in summary["hypotheses"] if h["status"] == "supported"],
            reviewer=body.get("reviewer"), note=body.get("note", ""),
            decided_at=self._wall().strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._decisions.add(record)
        return self.case_file(incident_id)

    def evidence_csv(self, incident_id):
        """The frozen evidence window as CSV bytes; KeyError, EvidenceNotReady propagate."""
        with self.lock:
            return self.plant.evidence(incident_id)[0]

    def status(self):
        return {"running": self.running, "speed": self.speed, "speeds": list(SPEEDS)}

    def model(self):
        """The local model check, cached for MODEL_TTL_S (the check itself may wait up to a second)."""
        now = self._clock()
        if self._model_status is not None and (self._model_at is None or now - self._model_at >= MODEL_TTL_S):
            self._model, self._model_at = self._model_status(), now
        return self._model

    def _agent_summary(self):
        records = self._agents().records()
        key = tuple(record["run_id"] for record, _ in records)
        if key != self._summary_key:
            self._summary_key, self._summary = key, summarize(records)
        return self._summary

    def state(self):
        with self.lock:
            self._advance()
            snap, status = self.plant.snapshot(), self.status()
            launched = list(self.launched)
        summary, runs = self._agent_summary(), self._agents().summaries()
        incidents = snap["incidents"]
        judge = summary["judge"]
        kpis = {
            "active_incidents": sum(i["status"] == "open" for i in incidents),
            "incidents": len(incidents),
            "detections": snap["detected"],
            "investigations": summary["runs"], "investigations_from_plant": len(launched),
            "judge_acceptance": judge["acceptance"], "judge_accepted": judge["accepted"], "judge_verdicts": judge["verdicts"],
            "median_investigation_ms": summary["durations"]["p50_ms"],
            "data_points": snap["emitted"] * len(SENSORS), "readings": snap["emitted"], "checks": snap["checks"],
        }
        recent = [{"run_id": r["run_id"], "state": r["state"], "status": r["status"], "started_at": r["started_at"],
                   "finished_at": r["finished_at"], "name": r["input"].get("name"), "from_plant": r["run_id"] in launched}
                  for r in runs["runs"][:RECENT_RUNS]]
        return {**snap, "status": status, "kpis": kpis, "model": self.model(),
                "catalog": {"faults": list(FAULTS), "sensor_faults": list(SENSOR_FAULTS),
                            "stream_faults": list(STREAM_FAULTS), "sensors": list(SENSORS), "units": dict(UNITS)},
                "agents": {"runs": summary["runs"], "layers": summary["layers"], "statuses": summary["agents"],
                           "active": runs["active"], "recent": recent}}
