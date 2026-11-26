# SPDX-License-Identifier: Apache-2.0
"""The Command Center's live simulated plant: a background clock, controls, KPIs and agent investigations.

The plant itself (readings, faults, baseline, monitor) is ``aegisflow_dr.simulation``; this module only drives it in
real time x speed and adds what the page needs. Every KPI is computed from the simulator state or from the retained,
digest-verified agent run records (``agent_summary.summarize``); a KPI with nothing to count is ``None`` (n/a).
"""
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
import time

from aegisflow_dr.pipeline import InputRejected
from aegisflow_dr.simulation import (FAULTS, REFERENCE_WINDOWS, SENSOR_FAULTS, SENSORS, STREAM_FAULTS, UNITS,
                                     WINDOW_SECONDS, Plant)
from agent_summary import summarize

SPEEDS = (1, 5, 20)
DEFAULT_SPEED, SEED = 5, 7
TICK_S, MAX_STEPS_PER_TICK, MODEL_TTL_S, RECENT_RUNS = 0.25, 120, 30.0, 5
ACTIONS = ("start", "pause", "reset", "speed")
BASELINE_LABEL = "simulated-plant"


def _wall():
    return datetime.now(timezone.utc)


class PlantController:
    def __init__(self, agents, *, model_status=None, seed=SEED, clock=time.monotonic, wall=_wall, thread=True,
                 tick_s=TICK_S):
        # ``agents`` returns the run manager (the workbench may replace its manager after construction).
        self._agents, self._model_status, self.seed = agents, model_status, seed
        self._clock, self._wall, self._threaded, self._tick_s = clock, wall, thread, tick_s
        self.lock = Lock()
        self._stop, self._thread = Event(), None
        self._model, self._model_at = None, None
        self._summary_key, self._summary = None, None
        self.launched = []  # agent runs started from plant incidents in this process, oldest first
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
        """Start an agent run on the incident's evidence window with the plant baseline; KeyError, Busy propagate."""
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
