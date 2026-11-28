# SPDX-License-Identifier: Apache-2.0
"""Case-level measurement of the 36-role agent runtime on simulated incidents, with the local model (plan Task 6).

This is the first measurement of a real language model in the project. The corpus reuses the fourteen scenario
injections of ``hypotheses_eval`` (imported, not copied) on fresh groups 120-159, so no group, base series or payload is
shared with the baseline comparison evaluation (D05c, groups 0-59) or the hypothesis loop evaluation (F04, groups
60-119). Groups are split by hash buckets of 6/2/2 out of 10 with the salt ``aegisflow-agents-eval-v1`` (realized as
development 21, validation 9 and held-out 10 of the 40 groups); every scenario of a group stays in its split. Each case
is ``run_case`` with the baseline built from the group's three reference batches, the scenario's current batch and
``as_of``, and no second file, no retriever and no history; transports are in process and no context cache is used.

The expected specialists per scenario (``EXPECTED_SELECTED``) were written down here, from the binding role table and the
injections, before any measurement. The model is ``qwen3:4b`` through ``agents.llm.LocalModel`` (127.0.0.1 only,
temperature 0, seed 7, thinking off, JSON-schema constrained). A live run (``--live``) records every model response by
the SHA-256 of its exact request into ``fixtures/evaluations/agents-llm-recording-v1.json``; the report is always
produced by replaying that recording (``ReplayModel``), so CI regenerates it exactly without Ollama. An unknown request
hash is a typed MODEL_UNAVAILABLE with a clear message, never a guess. Latencies in the report are the recorded live
latencies; the replay clock advances by them so budgets and deadlines behave as they did live.

Two protocols exist (``PROTOCOLS``). The description above is v1 (prompt version 2), committed and never re-scored.
v2 runs the same scenarios on fresh groups 160-199 (salt ``aegisflow-agents-eval-v2``) with prompt version 3, where A23
reads deterministic qualitative readings (``aegisflow_dr.readings``) instead of the catalog list; it has its own
recording, saved facts and report (docs/superpowers/specs/2026-11-28-a23-readings-design.md). A recording carries its
version, so it is always replayed under its own protocol.

Scope, stated plainly: simulated scenarios on generated series, written by the same authors as the catalog, the role
table and the prompts. A model suggestion that agrees with an injected label is not diagnostic accuracy on real data.
The model is advisory and Judge-gated; nothing here is a root cause, a production connection or a remediation. Rates
carry counts and a Wilson 95% interval and are ``None`` (shown ``n/a``) when the denominator is zero or the metric does
not apply.
"""
import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
from threading import Lock
from time import monotonic, perf_counter

from .. import baseline, baseline_eval as be, hypotheses, hypotheses_eval as he
from ..baseline_eval import _rate, _show
from ..check_evaluation import wilson
from . import llm
from .executors.orchestration import SPECIALISTS
from .executors.reasoning import ADVISORY_CLAIMS, _explains
from .llm import INVALID_OUTPUT, MODEL_UNAVAILABLE, TIMEOUT, LocalModel
from .registry import role
from .runtime import MODEL_ROLES, Case, canonical, run_case

SPLITS = be.SPLITS
GROUPS = range(120, 160)  # after baseline_eval's 0-59 and hypotheses_eval's 60-119
SCENARIOS = he.SCENARIOS
MODEL = "qwen3:4b"
LLM_AGENTS = tuple(sorted(MODEL_ROLES))
RECORDING = Path(__file__).resolve().parents[3] / "fixtures" / "evaluations" / "agents-llm-recording-v1.json"
CASES = RECORDING.with_name("agents-cases-v1.json")  # the scored facts of every committed case (see ``collect``)


@dataclass(frozen=True)
class Protocol:
    """One version of this evaluation: its groups, split salt, prompt version and committed files.

    A recording, its saved facts and its report carry the version, so each is always replayed and scored under its own
    protocol. v1 (groups 120-159, prompt version 2) is committed and never re-scored; v2 (groups 160-199, prompt version
    3, A23 with qualitative readings; docs/superpowers/specs/2026-11-28-a23-readings-design.md) is a fresh corpus.
    """
    version: str
    groups: range
    prompt_version: str
    recording: Path
    cases: Path
    report: str

    def split_of(self, group):
        bucket = int(sha256(("aegisflow-agents-eval-v%s:%d" % (self.version, group)).encode()).hexdigest(), 16) % 10
        return SPLITS[0] if bucket < 6 else SPLITS[1] if bucket < 8 else SPLITS[2]

    @property
    def recording_name(self):
        return "fixtures/evaluations/" + self.recording.name


PROTOCOLS = {"1": Protocol("1", GROUPS, "2", RECORDING, CASES, "docs/evaluation/agents.md"),
             "2": Protocol("2", range(160, 200), "3", RECORDING.with_name("agents-llm-recording-v2.json"),
                           RECORDING.with_name("agents-cases-v2.json"), "docs/evaluation/agents-v2.md")}
V1, LATEST = PROTOCOLS["1"], PROTOCOLS["2"]
SCOPE_V2 = ("The 36-role agent runtime on simulated incident cases with a local 4B model (qwen3:4b) that is advisory and "
            "Judge-gated; A23 reads a deterministic qualitative reading of each observation (prompt version 3). Simulated "
            "scenarios on generated series only: no real incidents, no root cause, no production connection, no "
            "autonomous remediation.")
NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)  # stamps the run records; not used by any metric
ERRORS = (None, INVALID_OUTPUT, TIMEOUT, MODEL_UNAVAILABLE)
_HEX = re.compile(r"[0-9a-f]{64}")
SCOPE = ("The 36-role agent runtime on simulated incident cases with a local 4B model (qwen3:4b) that is advisory and "
         "Judge-gated. Simulated scenarios on generated series only: no real incidents, no root cause, no production "
         "connection, no autonomous remediation.")

# -- Expected specialists, fixed before any measurement ------------------------------------------------------------------
# Case facts per scenario, from the case inputs and the injection only (never from a run): every case has a baseline,
# no run history, no retriever, no second extract, a sensor-style header (ts, temp_c, pressure_kpa, flow_lpm) that is not
# an order extract, and keeps its ``ts`` time column; no injection changes a column's type or role (values stay numbers,
# an emptied value is missing, not a different type), so no type signal is expected.
CASE_FACTS = {name: {"baseline": True, "history": False, "retriever": False, "second_order_extract": False,
                     "order_extract": False, "time_column": True, "type_signal": False} for name in SCENARIOS}
# The role table's specialist triggers applied to those facts: A08 schema drift, A11 freshness/volume and A20 statistical
# drift (baseline given), A10 profiling (always the first specialist) and A15 incremental load (time column present).
# Not expected anywhere: A07 (no history), A09/A13/A14/A19 (not an order extract), A12/A16 (no log or CDC source),
# A17 (no type or role change injected), A18/A21 (no second extract), A22 (no retriever or history).
EXPECTED_SELECTED = {
    "unit_change": ("A08", "A10", "A11", "A15", "A20"),
    "calibration_offset": ("A08", "A10", "A11", "A15", "A20"),
    "noise_increase": ("A08", "A10", "A11", "A15", "A20"),
    "stuck_sensor": ("A08", "A10", "A11", "A15", "A20"),
    "sampling_config_change": ("A08", "A10", "A11", "A15", "A20"),
    "partial_load": ("A08", "A10", "A11", "A15", "A20"),
    "duplicate_delivery": ("A08", "A10", "A11", "A15", "A20"),
    "delivery_delay": ("A08", "A10", "A11", "A15", "A20"),
    "source_outage": ("A08", "A10", "A11", "A15", "A20"),
    "field_outage": ("A08", "A10", "A11", "A15", "A20"),
    "intermittent_loss": ("A08", "A10", "A11", "A15", "A20"),
    "clean": ("A08", "A10", "A11", "A15", "A20"),
    "unmodelled_sign_flip": ("A08", "A10", "A11", "A15", "A20"),
    "unmodelled_amplitude": ("A08", "A10", "A11", "A15", "A20"),
}


def split_of(group, protocol=V1):
    return protocol.split_of(group)


def case_id(group, name):
    return "g%d.%s" % (group, name)


def truth_of(name):
    return he.TRUTH[name] and he.TRUTH[name][0]


# -- Recording and replay ----------------------------------------------------------------------------------------------
def new_recording(model=MODEL, created=None, protocol=V1):
    return {"version": protocol.version, "model": model, "prompt_version": protocol.prompt_version,
            "created": created or date.today().isoformat(), "calls": [], "runs": []}


def _count(value):
    return type(value) is int and value >= 0


def _call_ok(c):
    return (type(c) is dict and type(c.get("case_id")) is str and type(c.get("prompt_sha256")) is str
            and bool(_HEX.fullmatch(c["prompt_sha256"])) and type(c.get("response_json")) in (str, type(None))
            and c.get("error") in ERRORS and all(_count(c.get(k)) for k in ("tokens_in", "tokens_out", "latency_ms")))


def _run_ok(r):
    return (type(r) is dict and type(r.get("case_id")) is str and r.get("split") in SPLITS and _count(r.get("wall_ms"))
            and type(r.get("outcome_sha256")) is str and bool(_HEX.fullmatch(r["outcome_sha256"])))


def check_recording(recording):
    """Return ``recording`` when it is a well-formed recording of a known protocol; else raise ValueError."""
    if (type(recording) is not dict or recording.get("version") not in PROTOCOLS or type(recording.get("model")) is not str
            or type(recording.get("created")) is not str or type(recording.get("calls")) is not list
            or type(recording.get("runs")) is not list or not all(_call_ok(c) for c in recording["calls"])
            or not all(_run_ok(r) for r in recording["runs"])):
        raise ValueError("Invalid model recording")
    expected = PROTOCOLS[recording["version"]].prompt_version
    if recording.get("prompt_version") != expected:
        raise ValueError("The recording was made with prompt version %r; protocol v%s uses %r. Record again with --live."
                         % (recording.get("prompt_version"), recording["version"], expected))
    return recording


def load_recording(path):
    return check_recording(json.loads(Path(path).read_text("utf-8")))


def save_recording(recording, path):
    Path(path).write_text(json.dumps(check_recording(recording), indent=1, ensure_ascii=False) + "\n", "utf-8")


def _envelope(entry):
    if entry["response_json"] is None:
        return b""  # the live reply was not a readable chat envelope; LocalModel reports INVALID_OUTPUT again
    return json.dumps({"message": {"role": "assistant", "content": entry["response_json"]}, "done": True,
                       "prompt_eval_count": entry["tokens_in"], "eval_count": entry["tokens_out"]}).encode()


def _timed_out(error):
    return isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)


def _reply(raw):
    """The recorded part of a live reply: (content text or None, tokens in, tokens out, error)."""
    try:
        reply = json.loads(raw)
        content = reply["message"]["content"]
        if type(content) is not str:
            raise ValueError("content")
    except (ValueError, TypeError, KeyError):
        return None, 0, 0, INVALID_OUTPUT
    tokens = [reply.get(k) if _count(reply.get(k)) else 0 for k in ("prompt_eval_count", "eval_count")]
    return content, tokens[0], tokens[1], None


class ReplayMiss(Exception):
    """No recorded response for a request; LocalModel turns this into MODEL_UNAVAILABLE."""


class RecordedFailure(Exception):
    """The live call failed without a timeout; replayed as MODEL_UNAVAILABLE."""


class VirtualClock:
    """Monotonic time plus the recorded latency of every replayed model call (thread-safe)."""

    def __init__(self, base=monotonic):
        self._base, self._offset, self._lock = base, 0.0, Lock()

    def __call__(self):
        with self._lock:
            return self._base() + self._offset

    def advance(self, seconds):
        with self._lock:
            self._offset += seconds


class ReplayModel:
    """Serves a recording's model responses by the SHA-256 of the exact request, per case and in recorded order.

    ``model(case_id)`` returns a ``LocalModel`` whose transport answers only from the recording: a request whose hash
    was not recorded for that case raises ``ReplayMiss`` (a MODEL_UNAVAILABLE result, listed in ``misses``); a recorded
    timeout or failure is raised again, so the runtime sees the same typed outcome as live.
    """

    def __init__(self, recording):
        check_recording(recording)
        self.model_id, self.misses, self._calls = recording["model"], [], {}
        for entry in recording["calls"]:
            self._calls.setdefault(entry["case_id"], {}).setdefault(entry["prompt_sha256"], []).append(entry)

    def transport(self, case, clock=None, log=None):
        queues = {digest: list(entries) for digest, entries in self._calls.get(case, {}).items()}
        log = [] if log is None else log

        def serve(url, body, timeout):
            digest = sha256(body).hexdigest()
            if not queues.get(digest):
                self.misses.append((case, digest))
                log.append({"prompt_sha256": digest, "miss": True})
                raise ReplayMiss("No recorded response for prompt sha256 %s in case %s; replay never guesses"
                                 % (digest, case))
            entry = queues[digest].pop(0)
            if clock is not None:
                clock.advance(entry["latency_ms"] / 1000)
            log.append({"prompt_sha256": digest, "latency_ms": entry["latency_ms"], "miss": False})
            if entry["error"] == TIMEOUT:
                raise TimeoutError("recorded timeout")
            if entry["error"] == MODEL_UNAVAILABLE:
                raise RecordedFailure("recorded model failure")
            return _envelope(entry)
        return serve

    def model(self, case, clock=None, log=None):
        return LocalModel(model=self.model_id, transport=self.transport(case, clock, log))


def recorder(live, case, calls):
    """A transport that calls ``live`` and appends each request's recording entry to ``calls``."""
    def call(url, body, timeout):
        entry = {"case_id": case, "prompt_sha256": sha256(body).hexdigest(), "response_json": None, "error": None,
                 "tokens_in": 0, "tokens_out": 0}
        calls.append(entry)
        started = perf_counter()
        try:
            raw = live(url, body, timeout)
        except Exception as error:
            entry["error"] = TIMEOUT if _timed_out(error) else MODEL_UNAVAILABLE
            raise
        finally:
            entry["latency_ms"] = max(0, round((perf_counter() - started) * 1000))
        entry["response_json"], entry["tokens_in"], entry["tokens_out"], entry["error"] = _reply(raw)
        return raw
    return call


# Roles whose claims the outcome digest covers: specialists and the reasoning and model roles. Control roles are left
# out because their claims carry timings (A05 elapsed time, A35 latencies) that differ between a live run and a replay.
_COMPARED = frozenset(SPECIALISTS) | frozenset(LLM_AGENTS) | {"A24", "A25", "A28"}


def outcome(record):
    """SHA-256 of what the metrics read from a run record, to compare a replay with the live run it recorded."""
    return sha256(canonical({
        "status": record["status"], "exceeded": record["budget"]["exceeded"],
        "selected": [s["agent_id"] for s in record["selection"] if s["selected"]],
        "agents": {a["agent_id"]: [a["result"]["status"], a["result"]["error_code"]] for a in record["agents"]},
        "claims": {a["agent_id"]: a["result"]["claims"] for a in record["agents"] if a["agent_id"] in _COMPARED},
        "verdicts": record["judge"]["verdicts"],
        "llm": [[e["agent_id"], e["data"]["prompt_sha256"], e["data"]["ok"], e["data"]["error_code"]]
                for e in record["events"] if e["type"] == "llm_call"]})).hexdigest()


# -- Cases -------------------------------------------------------------------------------------------------------------
def cases(splits, scenarios=SCENARIOS, groups=None, protocol=V1):
    """Yield (group, split, scenario, baseline record, current payload, as_of) in group then scenario order; ``groups``
    defaults to the protocol's."""
    for group in protocol.groups if groups is None else groups:
        split = protocol.split_of(group)
        if split not in splits:
            continue
        record = None
        for name in scenarios:
            references, current, as_of, _ = he.scenario(group, name)
            record = record or baseline.build_baseline(references)
            yield group, split, name, record, current, as_of


def run_one(group, name, record, current, as_of, model, clock, prompt_version=V1.prompt_version):
    identifier = case_id(group, name)
    return run_case(Case(payload=current, case_id=identifier, baseline=record, as_of=as_of,
                         prompt_version=prompt_version),
                    model=model, clock=clock, transport="in_process", now=lambda: NOW, run_id=identifier)


class ModelStopped(RuntimeError):
    """The live model stopped answering during a recording."""


def record_live(recording, splits, *, transport=None, scenarios=SCENARIOS, groups=None, checkpoint=None):
    """Run every case of ``splits`` not yet in ``recording`` against the live model and record it (in place).

    ModelStopped when a call finds the model unavailable; the cases recorded before it stay in ``recording``.
    """
    protocol = PROTOCOLS[check_recording(recording)["version"]]
    live = transport or llm._urllib_transport
    done = {run["case_id"] for run in recording["runs"]}
    for group, split, name, record, current, as_of in cases(splits, scenarios, groups, protocol):
        identifier = case_id(group, name)
        if identifier in done:
            continue
        calls = []
        model = LocalModel(model=recording["model"], transport=recorder(live, identifier, calls))
        started = perf_counter()
        result = run_one(group, name, record, current, as_of, model, monotonic, protocol.prompt_version)
        wall = max(0, round((perf_counter() - started) * 1000))
        if any(call["error"] == MODEL_UNAVAILABLE for call in calls):
            # A model that stops answering must not be recorded as the model's behaviour: stop, keep what is done, and
            # leave this case unrecorded so the next --live run retries it.
            raise ModelStopped("The local model stopped answering during %s; %d cases are recorded. Start the model "
                               "and run --live again to continue." % (identifier, len(recording["runs"])))
        recording["calls"] += calls
        recording["runs"].append({"case_id": identifier, "split": split, "wall_ms": wall,
                                  "outcome_sha256": outcome(result)})
        if checkpoint is not None:
            checkpoint(identifier, wall)
    return recording


# -- Scoring -----------------------------------------------------------------------------------------------------------
def catalog_order(observations):
    """The catalog mechanisms that explain at least one of ``observations`` (as the Judge checks it), in catalog order."""
    return [m for m in hypotheses.MECHANISMS if any(_explains(m, o) for o in observations)]


def _empty_row():
    return {"cases": 0, "exact": 0, "tp": 0, "fp": 0, "fn": 0, "extra": {}, "missed": {}, "a23_lengths": {},
            "a23_echo": 0, "a23_repeated": 0, "a23_selected": 0,
            "a23_suggested": 0, "a23_top1": 0, "a23_any": 0, "a23_misattributed": 0, "loop_sole": 0, "loop_any": 0,
            "loop_misattributed": 0}


def _empty_llm():
    return {"calls": 0, "valid": 0, "invalid": 0, "timeout": 0, "unavailable": 0, "latencies": [], "advisory": 0,
            "rejected": 0, "reasons": {}}


def _empty_bucket(scenarios=SCENARIOS):
    return {"groups": 0, "scenarios": {name: _empty_row() for name in scenarios}, "agents": {},
            "judge": {"claims": 0, "accepted": 0, "reasons": {}},
            "a23_judge": {"claims": 0, "advisory": 0, "reasons": {}},
            "llm": {agent: _empty_llm() for agent in LLM_AGENTS},
            "runs": {"cases": 0, "statuses": {}, "exceeded": {}, "walls": [], "compared": 0, "matched": 0,
                     "misses": 0}}


def _add(counter, key, amount=1):
    counter[key] = counter.get(key, 0) + amount


def _label(result):
    return result["status"] if result["error_code"] is None else "%s/%s" % (result["status"], result["error_code"])


def _suggested(result):
    """A23's suggested mechanisms in the order the model listed them, or None when A23 did not complete."""
    if result["status"] != "COMPLETED":
        return None
    return next((c["params"]["mechanisms"] for c in result["claims"] if c["text_key"] == "a23.suggested"), None)


def case_facts(name, record, calls, investigation, recorded=None):
    """The measurements of one case that scoring needs, as plain JSON: ``record`` is the run record, ``calls`` the replay
    log of its model calls, ``investigation`` the deterministic loop's record for the same case and ``recorded`` the live
    run's entry in the recording (or None). Saved facts let the report be re-rendered without replaying every case."""
    selected = sorted(s["agent_id"] for s in record["selection"] if s["selected"])
    results = {a["agent_id"]: a["result"] for a in record["agents"]}
    judge, advisory = {"claims": 0, "accepted": 0, "reasons": {}}, []
    for verdict in record["judge"]["verdicts"]:
        agent = verdict["agent"]
        if agent in SPECIALISTS:
            judge["claims"] += 1
            if verdict["verdict"] == "accepted":
                judge["accepted"] += 1
            else:
                _add(judge["reasons"], verdict["reason"])
        elif verdict.get("text_key") in ADVISORY_CLAIMS.get(agent, ()):
            advisory.append([agent, verdict["text_key"], verdict["verdict"],
                             None if verdict["verdict"] == "advisory" else verdict["reason"]])
    latencies = {}
    for call in calls:
        if not call["miss"]:
            latencies.setdefault(call["prompt_sha256"], []).append(call["latency_ms"])
    model_calls = []
    for event in record["events"]:
        if event["type"] == "llm_call":
            data = event["data"]
            key = {True: "valid", INVALID_OUTPUT: "invalid", TIMEOUT: "timeout"}.get(data["ok"] or data["error_code"],
                                                                                   "unavailable")
            queue = latencies.get(data["prompt_sha256"])
            model_calls.append([event["agent_id"], key, queue.pop(0) if queue else None])
    mechanisms = _suggested(results["A23"])
    return {"selected": selected, "labels": {agent: _label(results[agent]) for agent in selected}, "judge": judge,
            "advisory": advisory, "model_calls": model_calls, "a23": mechanisms,
            "catalog_order": None if mechanisms is None else catalog_order(record["intake"]["observations"]),
            "supported": sorted({h["mechanism"] for h in investigation["hypotheses"] if h["status"] == "supported"}),
            "status": record["status"], "exceeded": list(record["budget"]["exceeded"]),
            "misses": sum(call["miss"] for call in calls),
            "wall_ms": None if recorded is None else recorded["wall_ms"],
            "matched": None if recorded is None else outcome(record) == recorded["outcome_sha256"]}


def score_facts(bucket, name, facts):
    """Add one case's facts (see ``case_facts``) to ``bucket``."""
    row, expected = bucket["scenarios"][name], set(EXPECTED_SELECTED[name])
    selected = set(facts["selected"])
    chosen = selected & set(SPECIALISTS)
    row["cases"] += 1
    row["exact"] += chosen == expected
    row["tp"] += len(chosen & expected)
    row["fp"] += len(chosen - expected)
    row["fn"] += len(expected - chosen)
    for agent in chosen - expected:
        _add(row["extra"], agent)
    for agent in expected - chosen:
        _add(row["missed"], agent)
    for agent, label in facts["labels"].items():
        _add(bucket["agents"].setdefault(agent, {}), label)
    judge = bucket["judge"]
    judge["claims"] += facts["judge"]["claims"]
    judge["accepted"] += facts["judge"]["accepted"]
    for reason, count in facts["judge"]["reasons"].items():
        _add(judge["reasons"], reason, count)
    for agent, text_key, verdict, reason in facts["advisory"]:
        stats = bucket["llm"][agent]
        if verdict == "advisory":
            stats["advisory"] += 1
        else:
            stats["rejected"] += 1
            _add(stats["reasons"], reason)
        if text_key == "a23.suggested":
            bucket["a23_judge"]["claims"] += 1
            if verdict == "advisory":
                bucket["a23_judge"]["advisory"] += 1
            else:
                _add(bucket["a23_judge"]["reasons"], reason)
    for agent, key, latency in facts["model_calls"]:
        stats = bucket["llm"][agent]
        stats["calls"] += 1
        stats[key] += 1
        if latency is not None:
            stats["latencies"].append(latency)
    truth, mechanisms, supported = truth_of(name), facts["a23"], set(facts["supported"])
    row["a23_selected"] += "A23" in selected
    row["a23_suggested"] += bool(mechanisms)
    if mechanisms is not None:
        _add(row["a23_lengths"], len(mechanisms))
        row["a23_echo"] += bool(mechanisms) and mechanisms == facts["catalog_order"][:len(mechanisms)]
        row["a23_repeated"] += len(set(mechanisms)) < len(mechanisms)
    if truth is not None:
        row["a23_top1"] += bool(mechanisms) and mechanisms[0] == truth
        row["a23_any"] += truth in (mechanisms or ())
        row["loop_sole"] += supported == {truth}
        row["loop_any"] += truth in supported
    else:
        row["a23_misattributed"] += bool(set(mechanisms or ()) - {"genuine_change"})
        row["loop_misattributed"] += bool(supported - {"genuine_change"})
    runs = bucket["runs"]
    runs["cases"] += 1
    _add(runs["statuses"], facts["status"])
    for limit in facts["exceeded"]:
        _add(runs["exceeded"], limit)
    runs["misses"] += facts["misses"]
    if facts["matched"] is not None:
        runs["walls"].append(facts["wall_ms"])
        runs["compared"] += 1
        runs["matched"] += facts["matched"]


def score_case(bucket, name, record, calls, investigation, recorded=None):
    """Add one run record to ``bucket`` (``case_facts`` then ``score_facts``)."""
    score_facts(bucket, name, case_facts(name, record, calls, investigation, recorded))


def percentile(values, p):
    """Nearest-rank percentile of ``values``, or None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def _finalize_row(name, row):
    modelled, cases_ = truth_of(name) is not None, row["cases"]
    row["rates"] = {
        "exact": _rate(row["exact"], cases_), "precision": _rate(row["tp"], row["tp"] + row["fp"]),
        "recall": _rate(row["tp"], row["tp"] + row["fn"]), "a23_suggested": _rate(row["a23_suggested"], cases_),
        "a23_echo": _rate(row["a23_echo"], row["a23_suggested"]),
        **{m: _rate(row[m], cases_) if modelled else None for m in ("a23_top1", "a23_any", "loop_sole", "loop_any")},
        **{m: None if modelled else _rate(row[m], cases_) for m in ("a23_misattributed", "loop_misattributed")}}


def _finalize(bucket):
    for name, row in bucket["scenarios"].items():
        _finalize_row(name, row)
    total = _empty_row()
    for row in bucket["scenarios"].values():
        for key in ("cases", "exact", "tp", "fp", "fn"):
            total[key] += row[key]
    bucket["selection"] = {"exact": _rate(total["exact"], total["cases"]),
                           "precision": _rate(total["tp"], total["tp"] + total["fp"]),
                           "recall": _rate(total["tp"], total["tp"] + total["fn"])}
    judge = bucket["judge"]
    judge["rate"] = _rate(judge["accepted"], judge["claims"])
    bucket["a23_judge"]["rate"] = _rate(bucket["a23_judge"]["advisory"], bucket["a23_judge"]["claims"])
    for stats in bucket["llm"].values():
        stats["rates"] = {"valid": _rate(stats["valid"], stats["valid"] + stats["invalid"]),
                          "advisory": _rate(stats["advisory"], stats["advisory"] + stats["rejected"])}
        stats["p50"], stats["p95"] = percentile(stats["latencies"], 50), percentile(stats["latencies"], 95)
        stats["latencies"] = len(stats["latencies"])
    runs = bucket["runs"]
    runs["p50"], runs["p95"] = percentile(runs["walls"], 50), percentile(runs["walls"], 95)
    runs["walls"] = len(runs["walls"])
    runs["fidelity"] = _rate(runs["matched"], runs["compared"])


def collect(recording, splits=SPLITS[:2], *, scenarios=SCENARIOS, groups=None):
    """Replay ``recording`` over the cases of ``splits`` and keep each case's facts (see ``case_facts``)."""
    protocol = PROTOCOLS[check_recording(recording)["version"]]
    replay = ReplayModel(recording)
    runs = {run["case_id"]: run for run in recording["runs"]}
    collected = {split: {"groups": 0, "cases": []} for split in splits}
    seen = set()
    for group, split, name, record, current, as_of in cases(splits, scenarios, groups, protocol):
        if group not in seen:
            seen.add(group)
            collected[split]["groups"] += 1
        identifier, clock, log = case_id(group, name), VirtualClock(), []
        result = run_one(group, name, record, current, as_of, replay.model(identifier, clock, log), clock,
                         protocol.prompt_version)
        facts = case_facts(name, result, log, hypotheses.investigate(record, current, as_of=as_of), runs.get(identifier))
        collected[split]["cases"].append({"case_id": identifier, "scenario": name, **facts})
    return {"version": protocol.version, "groups": len(protocol.groups if groups is None else groups),
            "scenarios": list(scenarios),
            "recording": {"model": recording["model"], "prompt_version": recording["prompt_version"],
                          "created": recording["created"], "calls": len(recording["calls"]),
                          "runs": len(recording["runs"])},
            "splits": collected}


def summarise_collected(collected):
    """The report of collected case facts (see ``collect``)."""
    report = {}
    for split, data in collected["splits"].items():
        bucket = report[split] = _empty_bucket(collected["scenarios"])
        bucket["groups"] = data["groups"]
        for case in data["cases"]:
            score_facts(bucket, case["scenario"], case)
        _finalize(bucket)
    return {"version": collected["version"], "scope": SCOPE if collected["version"] == "1" else SCOPE_V2,
            "groups": collected["groups"],
            "recording": collected["recording"], "splits": report}


def evaluate(recording, splits=SPLITS[:2], *, scenarios=SCENARIOS, groups=None):
    """Replay ``recording`` over the cases of ``splits`` and score them."""
    return summarise_collected(collect(recording, splits, scenarios=scenarios, groups=groups))


# -- Report ------------------------------------------------------------------------------------------------------------
def _ms(value):
    return "n/a" if value is None else "%d ms" % value


def _tally(counter):
    return ", ".join("%s: %d" % item for item in sorted(counter.items())) or "none"


def _share(count, total):
    return _show(_rate(count, total))


def _agent_rows(agents):
    out = []
    for agent in sorted(agents):
        labels = agents[agent]
        total = sum(labels.values())
        needs = {k: v for k, v in labels.items() if k.startswith("NEEDS_EVIDENCE")}
        other = {k: v for k, v in labels.items() if k != "COMPLETED" and k not in needs}
        out.append("| %s %s | %s | %d | %s | %s (%s) | %s (%s) |" % (
            agent, role(agent).name, role(agent).kind, total, _share(labels.get("COMPLETED", 0), total),
            _share(sum(needs.values()), total), _tally(needs), _share(sum(other.values()), total), _tally(other)))
    return out


V2_CHANGES = (
    "**What changed in v2.** A23 no longer receives the catalog list. Each observation carries a qualitative reading "
    "computed deterministically from aggregates (`aegisflow_dr.readings`: a mean scaled by a power of ten, shifted or "
    "unchanged; a wider, narrower or unchanged spread; rows that dropped or increased; late data; more empty values in "
    "one contiguous run or scattered), and the prompt states each mechanism's signature in those words and asks for a "
    "ranking (prompt version 3). The readings use the same aggregates and documented thresholds the probes use, so "
    "agreement now measures whether the model maps documented signatures to readings, not independent diagnosis. The "
    "prompt was written and tried on v1 development groups only and frozen before this corpus was recorded "
    "(docs/superpowers/specs/2026-11-28-a23-readings-design.md). The v1 report (`agents.md`, prompt version 2) stays "
    "as committed.")


def render_markdown(report):
    protocol = PROTOCOLS[report["version"]]
    v2 = protocol.version != "1"
    sizes = [sum(protocol.split_of(g) == name for g in protocol.groups) for name in SPLITS]
    scored = ("development, validation and held-out (`--include-heldout`)" if "heldout" in report["splits"]
              else "development and validation; `--include-heldout` adds the held-out split")
    rec = report["recording"]
    out = ["# Agent runtime evaluation" + (" (v%s)" % protocol.version if v2 else ""), "",
           "Generated by `python -m aegisflow_dr.agents.agents_eval%s` by replaying `%s` (%s)."
           % (" --protocol %s" % protocol.version if v2 else "", protocol.recording_name, scored),
           "", "**Scope.** " + report["scope"], ""] + ([V2_CHANGES, ""] if v2 else []) + [
           "## Corpus", "",
           "%d groups (groups %d-%d) from the baseline evaluation's generator, with the fourteen scenario injections of "
           "the hypothesis loop evaluation (`hypotheses_eval.scenario`, imported, not copied). The corpus is disjoint from "
           "the baseline comparison evaluation (D05c, groups 0-%d) and the hypothesis loop evaluation (F04, groups %d-%d)%s: "
           "the generator is seeded by the group number, so no group, base series or payload is shared with them."
           % (report["groups"], protocol.groups[0], protocol.groups[-1], be.GROUPS - 1, he.GROUPS[0], he.GROUPS[-1],
              " and the v1 agents evaluation (groups %d-%d)" % (V1.groups[0], V1.groups[-1]) if v2 else ""), "",
           "Groups are split by a hash of the group number (salt `aegisflow-agents-eval-v%s`, buckets 6/2/2 out of 10), "
           "realized as development %d, validation %d and held-out %d groups; all scenarios of a group stay in one split. "
           "Held-out is small, so its intervals are wide: a perfect %d/%d has a Wilson 95%% lower bound of %.1f%%."
           % (protocol.version, sizes[0], sizes[1], sizes[2], sizes[2], sizes[2], wilson(sizes[2], sizes[2])[0] * 100),
           "",
           "Each case is one `run_case`: the baseline built from the group's %d reference batches, the scenario's current "
           "batch and `as_of`; no second file, no retriever and no run history. Transports are in process (no MCP or "
           "A2A hop), no context cache is used, and the budgets are the catalog defaults (8 specialists, 12 model calls, "
           "40,000 tokens, 90 s)." % be.REFERENCES, "",
           "## Expected specialists", "",
           "Written in `aegisflow_dr/agents/agents_eval.py` (`EXPECTED_SELECTED`) from the binding role table and the "
           "injections before any measurement. Every case has a baseline, keeps its `ts` time column, is not an order "
           "extract, has no second extract, retriever or history, and no injection changes a column's type or role. "
           "Not expected anywhere: A07 (no history), A09, A13, A14 and A19 (not an order extract), A12 and A16 (no log "
           "or CDC source), A17 (no type or role change injected), A18 and A21 (no second extract), A22 (no retriever "
           "or history).", "",
           "| Scenario | Injection | Expected specialists |", "|---|---|---|"]
    out += ["| %s | %s | %s |" % (name, he.INJECTION[name], ", ".join(EXPECTED_SELECTED[name])) for name in SCENARIOS]
    out += ["", "## Model and recording", "",
            "Model `%s` through Ollama on 127.0.0.1 (temperature 0, seed 7, thinking off, output constrained to each "
            "role's JSON Schema), prompt version %s, recorded on %s: %d model calls over %d live runs. The report replays "
            "the recording by the SHA-256 of each exact request; a request that was not recorded is MODEL_UNAVAILABLE, "
            "never a guess. Latencies are the live ones from the recording; the replay clock advances by them, so budgets "
            "and deadlines see the live timing." % (rec["model"], rec["prompt_version"], rec["created"], rec["calls"],
                                                    rec["runs"]), "",
            "Definitions. *Exact set*: the selected specialists (A07-A22) equal the expected set. *Precision* and *recall* "
            "pool every specialist decision of the split. *Schema-valid JSON*: calls whose reply parsed and validated, "
            "over calls that returned a reply (TIMEOUT and MODEL_UNAVAILABLE are counted separately). *Judge kept as "
            "advisory*: the role's model-based claims the Judge labelled advisory, over those it labelled advisory or "
            "rejected (model output is never accepted as a finding). *A23 top-1*: the first mechanism A23 lists is the "
            "injected one; *A23 any*: the injected mechanism is among its at most three; both over every case of a "
            "modelled scenario (no suggestion counts as no agreement); *mechanisms listed* tallies how many mechanisms "
            "each completed A23 suggestion named (a longer list makes *any* easier); *catalog-order echo*: among "
            "non-empty suggestions, the list equals the first catalog mechanisms that explain any of the case's "
            "observations, in catalog order (the model repeating the prompt's order rather than discriminating; this "
            "column and the repeated-mechanism count were added after a development and validation report had been "
            "rendered, and before held-out was scored). *Loop sole-supported*: the deterministic loop "
            "(`hypotheses.investigate`, as run by A24) supports exactly the injected mechanism and no other (mechanism "
            "level, columns ignored). For `clean` and the unmodelled scenarios, *misattributed* means a catalog "
            "mechanism other than `genuine_change` was suggested (A23) or supported (loop). Rates are `count/total = "
            "percent [95% Wilson interval]`; `n/a` means nothing to measure or the metric does not apply."]
    for split, bucket in report["splits"].items():
        out += ["", "## Split: %s (%d groups)" % (split, bucket["groups"]), "", "### Role selection", "",
                "| Scenario | Cases | Exact set | Precision | Recall | Extra selected | Missed |",
                "|---|---|---|---|---|---|---|"]
        for name, row in bucket["scenarios"].items():
            out.append("| %s | %d | %s | %s | %s | %s | %s |" % (
                name, row["cases"], _show(row["rates"]["exact"]), _show(row["rates"]["precision"]),
                _show(row["rates"]["recall"]), _tally(row["extra"]), _tally(row["missed"])))
        total = bucket["selection"]
        out += ["| all | %d | %s | %s | %s | | |" % (bucket["runs"]["cases"], _show(total["exact"]),
                                                     _show(total["precision"]), _show(total["recall"])),
                "", "### Agent outcomes (selected roles)", "",
                "| Agent | Kind | Selected | COMPLETED | NEEDS_EVIDENCE | Other |", "|---|---|---|---|---|---|"]
        out += _agent_rows(bucket["agents"])
        judge = bucket["judge"]
        out += ["", "Judge on specialist (A07-A22) claims: accepted %s; not accepted by reason: %s."
                % (_show(judge["rate"]), _tally(judge["reasons"])),
                "", "### Model calls", "",
                "| Agent | Calls | Schema-valid JSON | TIMEOUT | MODEL_UNAVAILABLE | Judge kept as advisory | Rejected by "
                "reason | Latency p50 | Latency p95 |", "|---|---|---|---|---|---|---|---|---|"]
        for agent, stats in bucket["llm"].items():
            out.append("| %s | %d | %s | %d | %d | %s | %s | %s | %s |" % (
                agent, stats["calls"], _show(stats["rates"]["valid"]), stats["timeout"], stats["unavailable"],
                _show(stats["rates"]["advisory"]), _tally(stats["reasons"]), _ms(stats["p50"]), _ms(stats["p95"])))
        a23 = bucket["a23_judge"]
        rows = bucket["scenarios"].values()
        out += ["", "A23 suggestions kept as advisory by the Judge: %s; rejected by reason: %s. Non-empty A23 "
                "suggestions that name one mechanism more than once: %s."
                % (_show(a23["rate"]), _tally(a23["reasons"]),
                   _share(sum(r["a23_repeated"] for r in rows), sum(r["a23_suggested"] for r in rows))),
                "", "### A23 suggestions and the deterministic loop", "",
                "| Scenario | A23 selected | A23 suggestion | Mechanisms listed | Catalog-order echo | A23 top-1 | A23 any "
                "| Loop sole-supported | Loop supported | A23 misattributed | Loop misattributed |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, row in bucket["scenarios"].items():
            rates = row["rates"]
            out.append("| %s | %d/%d | %s | %s | %s | %s |" % (
                name, row["a23_selected"], row["cases"], _show(rates["a23_suggested"]), _tally(row["a23_lengths"]),
                _show(rates["a23_echo"]),
                " | ".join(_show(rates[m]) for m in ("a23_top1", "a23_any", "loop_sole", "loop_any", "a23_misattributed",
                                                     "loop_misattributed"))))
        runs = bucket["runs"]
        out += ["", "### Runs", "",
                "Run statuses: %s. Budget limits reached: %s. Live wall time per run (%d recorded): p50 %s, p95 %s. "
                "Replay reproduced the live outcome in %s; requests missing from the recording: %d."
                % (_tally(runs["statuses"]), _tally(runs["exceeded"]), runs["walls"], _ms(runs["p50"]), _ms(runs["p95"]),
                   _show(runs["fidelity"]), runs["misses"])]
    out += ["", "## Reading these numbers", "",
            "- The model is a local 4B model (`qwen3:4b`, 4-bit quantised) used as an advisor. Its output is never "
            "evidence: the Judge labels model-based claims advisory at best, and only specialist claims can be accepted "
            "as findings. No result here is a root cause.",
            ("- Agreement of A23 with an injected label on simulated scenarios is not diagnostic accuracy on real data. "
             "The scenarios, the readings and their thresholds, the signatures in the prompt and the probes were written "
             "by the same authors from the same catalog, so agreement measures whether the model maps documented "
             "signatures to deterministic readings. A reading that fits two mechanisms equally cannot be told apart." if v2
             else "- Agreement of A23 with an injected label on simulated scenarios is not diagnostic accuracy on real "
             "data. The scenarios, the mechanism catalog (with the checks each mechanism explains, which A23 sees in its "
             "prompt) and the prompts were written by the same authors, so agreement measures whether the model maps "
             "observation checks to catalog mechanisms the way the catalog intends."),
            ("- A23's prompt asks for the candidates from the best fit to the worst, so *top-1* is the model's first "
             "choice. *Catalog-order echo* stays as a check that the list does not simply follow the catalog; for a list "
             "of one mechanism it is true whenever that mechanism is the first in catalog order that explains the "
             "observations, so it reads 100% on unit change, sampling change, delivery delay and field outage by "
             "construction." if v2
             else "- A23's prompt does not ask for a ranking, so *top-1* is the first mechanism the model happened to "
             "list, not a calibrated best guess; *any* is the fairer reading of a list of up to three."),
            ] + ([
            "- On duplicate delivery the model pads its list with `partial_load` and `sampling_config_change` and claims "
            "they explain the volume increase, which neither does; the Judge rejects those claims "
            "(`mechanism_does_not_explain`), so the A23 advisory rate is below 100% while its first choice is "
            "unaffected. This was seen on development after the prompt had been frozen and was not tuned away."] if v2
            else []) + [
            "- The deterministic loop and A23 answer different questions: the loop tests mechanisms with fixed probes, "
            "A23 only proposes. The side-by-side columns show both on the same cases, not a contest between equals.",
            "- Role selection is deterministic code implementing the role table, and the expected sets come from the "
            "same table, so precision and recall test the implementation on these cases (internal consistency), not "
            "whether the table picks the right experts for real incidents. All scenarios share the same case inputs, so "
            "the expected set is the same everywhere; a difference can only come from observation-driven triggers "
            "(A17).",
            "- Pooled precision and recall treat each role decision as independent; decisions within one case are "
            "correlated, so their intervals are optimistic. *Exact set* (one trial per case) is the conservative "
            "reading. Scenarios of one group share one baseline, so rates across scenarios are not independent.",
            "- Schema-valid JSON is measured under constrained decoding (Ollama's `format` with each role's schema), so "
            "it reflects the decoder plus the model, not the model's unaided formatting.",
            "- A22 and A30 make no model call on this corpus (no retriever or history; not an order extract), so their "
            "model behaviour is not measured here.",
            "- Latencies are one sequential live run on this machine with one model instance and no context cache; they "
            "vary with hardware and load. Run wall times include the in-process rule agents and are not the default "
            "`auto` transport (no MCP or mutual-TLS A2A hop).",
            "- Temperature 0 and a fixed seed do not guarantee identical output across Ollama versions or hardware; the "
            "recording fixes one live run, and the replay-fidelity line shows whether replay reproduces it.",
            "- Prompts (version %s) were fixed before development was scored and were not changed after looking at "
            "validation; held-out is scored once, and anything it reveals is reported as a weakness."
            % protocol.prompt_version]
    return "\n".join(out)


def main(argv=(), *, transport=None, err=sys.stderr):
    parser = argparse.ArgumentParser(prog="python -m aegisflow_dr.agents.agents_eval")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--live", action="store_true", help="call the local model for cases not yet recorded")
    source.add_argument("--from-cases", metavar="PATH", help="render the report from saved case facts, without replay")
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default=LATEST.version,
                        help="evaluation version (default: the latest); each has its own corpus and recording")
    parser.add_argument("--record", help="recording file (default: the protocol's committed one)")
    parser.add_argument("--include-heldout", action="store_true", help="also run and score the held-out split")
    parser.add_argument("--save-cases", metavar="PATH", help="also save the case facts the report is scored from")
    args = parser.parse_args(list(argv))
    if args.from_cases:
        return render_markdown(summarise_collected(json.loads(Path(args.from_cases).read_text("utf-8"))))
    splits = SPLITS if args.include_heldout else SPLITS[:2]
    protocol = PROTOCOLS[args.protocol]
    path = Path(args.record) if args.record else protocol.recording
    if args.live:
        recording = load_recording(path) if path.exists() else new_recording(protocol=protocol)

        def checkpoint(identifier, wall):
            save_recording(recording, path)
            print("%s %d ms" % (identifier, wall), file=err, flush=True)

        try:
            record_live(recording, splits, transport=transport, checkpoint=checkpoint)
        except ModelStopped as stopped:
            save_recording(recording, path)
            parser.exit(1, "%s\n" % stopped)
        save_recording(recording, path)
    elif not path.exists():
        parser.error("no recording at %s; make one with --live" % path)
    recording = load_recording(path)
    if recording["version"] != protocol.version:
        parser.error("%s is a v%s recording; pass --protocol %s" % (path, recording["version"], recording["version"]))
    collected = collect(recording, splits)
    if args.save_cases:
        Path(args.save_cases).write_text(json.dumps(collected, separators=(",", ":")) + "\n", "utf-8")
    return render_markdown(summarise_collected(collected))


if __name__ == "__main__":  # pragma: no cover
    print(main(sys.argv[1:]))
