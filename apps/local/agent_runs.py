# SPDX-License-Identifier: Apache-2.0
"""Live agent runs for the workbench's Agent flow page.

One run at a time executes ``aegisflow_dr.agents.runtime.run_case`` in a background thread. The runtime's ``on_event``
callback only appends a copy of each event to the run's buffer (it runs under the event log lock, so it must not
block) and wakes the stream readers. Events keep the runtime's live ``seq`` (arrival position), which the stream
uses as its ``id:`` so a reader can resume with ``Last-Event-ID``. When the run ends its sealed, digest-verified
record (``agent-run-v1``) is kept unmodified next to the live events. Runs live in memory only: at most
``HISTORY`` finished runs are kept, oldest dropped first. With a ``RunStore`` the sealed records (and the human decisions
recorded beside them) are also retained in the state directory, so the history survives a restart; a restored run
replays its record's events (sealed order) on the stream.

The model is the loopback ``LocalModel`` (Ollama on 127.0.0.1); when it is not running the model roles report
``MODEL_UNAVAILABLE`` themselves. The retriever is the workbench knowledge base (verified passages only). A human
approval decision is recorded beside the record (never inside it, so its digest still verifies) and executes nothing.
"""
from collections import OrderedDict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Condition, Thread
from uuid import uuid4

from aegisflow_dr.advisory.context_cache import ContextCache
from aegisflow_dr.agents.events import MAX_EVENTS
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.agents.registry import ROLES
from aegisflow_dr.agents.runtime import Budget, Case, run_case, verify_record
from aegisflow_dr.baseline import load_baseline
from aegisflow_dr.pipeline import InputRejected

HISTORY = 50
STORE_FILE, STORE_REJECTED, STORE_FORMAT = "agent-runs.json", "agent-runs.rejected.json", "1"
MAX_STORE_BYTES = 64_000_000
HEARTBEAT_S = 15.0
MAX_FILE_BYTES = 1_000_000
MAX_AS_OF_CHARS = 64
MAX_NAME_CHARS = 80
RUN_ID = re.compile(r"run-[0-9a-f]{24}")
DECISIONS = ("approved", "rejected")
RUN_FAILED = "RUN_FAILED"  # the runtime raised instead of returning a record (sanitized; details are not exposed)


class Busy(Exception):
    """Another run is still executing."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file(value, label, required):
    if value is None and not required:
        return None
    if type(value) is not bytes or not 1 <= len(value) <= MAX_FILE_BYTES:
        raise InputRejected("The %s must be a CSV file of 1 byte to 1 MB" % label)
    return value


def _name(value):
    """A display name for the file: printable, without markup characters, at most 80 characters, or None."""
    if type(value) is not str:
        return None
    cleaned = "".join(c for c in value[:MAX_NAME_CHARS] if c.isprintable() and c not in "<>\"'\\/").strip()
    return cleaned or None


def knowledge_retriever(kb):
    """The runtime's retriever over the workbench knowledge base: verified passages with revision-bound citations."""
    def retrieve(query, limit):
        found = kb.search(query, max(1, min(10, limit)))
        return [{"source": item["source"], "revision": item["revision"], "citation": item["citation_sha256"],
                 "passage": item["text"]} for item in found if item["verified"]]
    return retrieve


def roles():
    """The 36 role specs (registry) and the run budget limits, for the page before any run exists."""
    return {"roles": [{"agent_id": r.agent_id, "name": r.name, "priority": r.priority, "kind": r.kind, "layer": r.layer,
                       "allowed_tools": list(r.allowed_tools), "trigger_summary": r.trigger_summary} for r in ROLES],
            "limits": Budget().limits()}


class RunStore:
    """Sealed run records in ``agent-runs.json``: atomic owner-only writes, every record re-verified on load.

    A file that does not parse or holds a record whose trace digest does not verify is moved aside to
    ``agent-runs.rejected.json`` (kept for inspection, never trusted) and the store starts empty, as the other stores do.
    """

    def __init__(self, directory, *, limit=HISTORY):
        self.path = Path(directory) / STORE_FILE
        self.limit, self.rejected_on_load, self.items = limit, False, []
        if self.path.exists():
            try:
                if self.path.stat().st_size > MAX_STORE_BYTES:
                    raise ValueError("Agent run file too large")
                self.items = self._parse(json.loads(self.path.read_text("utf-8")))
            except (InputRejected, ValueError, TypeError, KeyError, OSError, RecursionError):
                os.replace(self.path, self.path.with_name(STORE_REJECTED))
                self.rejected_on_load, self.items = True, []

    def _parse(self, data):
        if type(data) is not dict or set(data) != {"format_version", "runs"} or data["format_version"] != STORE_FORMAT \
                or type(data["runs"]) is not list or len(data["runs"]) > self.limit:
            raise ValueError("Agent run file is malformed")
        items = []
        for item in data["runs"]:
            if type(item) is not dict or set(item) != {"meta", "started_at", "finished_at", "record", "decisions"} \
                    or type(item["meta"]) is not dict or type(item["decisions"]) is not dict:
                raise ValueError("Agent run file is malformed")
            verify_record(item["record"])
            if not RUN_ID.fullmatch(item["record"]["run_id"]):
                raise ValueError("Agent run file is malformed")
            items.append(item)
        return items

    def save(self, runs):
        """Write the finished runs that have a sealed record (newest ``limit``), atomically and owner-only."""
        items = [{"meta": run.meta, "started_at": run.started_at, "finished_at": run.finished_at, "record": run.record,
                  "decisions": run.decisions} for run in runs if run.record is not None][-self.limit:]
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({"format_version": STORE_FORMAT, "runs": items}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        self.items = items


class _Run:
    def __init__(self, run_id, meta):
        self.run_id, self.meta = run_id, meta
        self.events, self.record, self.error, self.done = [], None, None, False
        self.started_at, self.finished_at = _now(), None
        self.decisions = {}

    @classmethod
    def restored(cls, item):
        """A finished run from the store: its events are the record's (sealed order, seq 1..n)."""
        run = cls(item["record"]["run_id"], item["meta"])
        run.record, run.done, run.events = item["record"], True, item["record"]["events"]
        run.started_at, run.finished_at, run.decisions = item["started_at"], item["finished_at"], item["decisions"]
        return run

    def summary(self):
        finished = next((e["data"] for e in self.events if e["type"] == "run_finished"), None)
        return {"run_id": self.run_id, "state": "error" if self.error else "finished" if self.done else "running",
                "status": finished["status"] if finished else None, "started_at": self.started_at,
                "finished_at": self.finished_at, "events": len(self.events), "input": dict(self.meta)}


class RunManager:
    def __init__(self, *, baselines=None, retriever=None, model_factory=LocalModel, runner=run_case,
                 history=HISTORY, heartbeat_s=HEARTBEAT_S, transport="auto", store=None):
        if type(history) is not int or history < 1 or not callable(model_factory) or not callable(runner):
            raise ValueError("Invalid run manager settings")
        self._baselines, self._retriever = baselines, retriever
        self._model_factory, self._runner, self._history, self._transport = model_factory, runner, history, transport
        self.heartbeat_s = heartbeat_s
        self.store_error = False
        self._cache = ContextCache()  # CAG across runs of this process: a repeated case reports cache hits
        self._cond = Condition()
        self._runs = OrderedDict()  # run_id -> _Run, oldest first
        self._active = None
        self._store = store
        for item in (store.items if store is not None else [])[-history:]:
            run = _Run.restored(item)
            self._runs[run.run_id] = run

    # -- starting a run -------------------------------------------------------------------------------------------
    def start(self, payload, *, baseline=None, as_of=None, second=None, name=None, baseline_record=None, baseline_label=None):
        """Start a run of ``payload`` and return its id; Busy while another runs, KeyError for an unknown baseline.

        A caller that holds a baseline record itself (the simulated plant) passes it as ``baseline_record`` with a
        display ``baseline_label`` instead of a saved baseline's name; the record is verified before use.
        """
        payload = _file(payload, "file", True)
        second = _file(second, "second file", False)
        if as_of is not None and (type(as_of) is not str or not 1 <= len(as_of) <= MAX_AS_OF_CHARS
                                  or not as_of.isprintable()):
            raise InputRejected("The as-of time must be 1 to %d printable characters" % MAX_AS_OF_CHARS)
        record = None
        if baseline is not None:
            if type(baseline) is not str or self._baselines is None:
                raise InputRejected("The baseline must be the name of a saved baseline")
            record = self._baselines.get(baseline)  # KeyError when it does not exist
        elif baseline_record is not None:
            record, baseline = load_baseline(baseline_record), _name(baseline_label)
        meta = {"name": _name(name), "sha256": sha256(payload).hexdigest(), "bytes": len(payload),
                "baseline": baseline, "as_of": as_of,
                "second_sha256": sha256(second).hexdigest() if second is not None else None}
        with self._cond:
            if self._active is not None:
                raise Busy()
            run = _Run("run-" + uuid4().hex[:24], meta)
            self._runs[run.run_id] = run
            self._active = run
            finished = [key for key, item in self._runs.items() if item.done]
            for key in finished[:max(0, len(self._runs) - self._history)]:
                del self._runs[key]
        case = Case(payload, "case-" + run.run_id[4:16], baseline=record, as_of=as_of, second_payload=second,
                    retriever=self._retriever)
        Thread(target=self._execute, args=(run, case), name="agent-run", daemon=True).start()
        return run.run_id

    def _execute(self, run, case):
        record = error = None
        try:
            record = self._runner(case, model=self._model_factory(), cache=self._cache, run_id=run.run_id,
                                  on_event=lambda event: self._publish(run, event), transport=self._transport)
        except Exception:  # sanitized: the stream and record say only that the run failed to complete
            error = RUN_FAILED
        with self._cond:
            run.record, run.error, run.done, run.finished_at = record, error, True, _now()
            self._active = None
            self._cond.notify_all()
            self._persist()

    def _persist(self):
        """Retain the sealed records; a failed write is reported in the summaries, never fatal to the run."""
        if self._store is None:
            return
        try:
            self._store.save(list(self._runs.values()))
            self.store_error = False
        except OSError:
            self.store_error = True

    def _publish(self, run, event):
        with self._cond:
            if len(run.events) < MAX_EVENTS:
                run.events.append(event)
            self._cond.notify_all()

    # -- reading ----------------------------------------------------------------------------------------------------
    def _get(self, run_id):
        if type(run_id) is not str or not RUN_ID.fullmatch(run_id) or run_id not in self._runs:
            raise KeyError("run")
        return self._runs[run_id]

    def exists(self, run_id):
        with self._cond:
            try:
                self._get(run_id)
            except KeyError:
                return False
            return True

    def wait(self, run_id, after, timeout):
        """Events with ``seq`` > ``after`` (waiting up to ``timeout`` s for one), whether the run is done, its error.

        KeyError when the run is unknown (or was dropped from the history while a reader waited).
        """
        with self._cond:
            run = self._get(run_id)
            self._cond.wait_for(lambda: run.done or (run.events and run.events[-1]["seq"] > after), timeout)
            run = self._get(run_id)
            return [dict(e) for e in run.events if e["seq"] > after], run.done, run.error

    def summaries(self):
        with self._cond:
            return {"runs": [run.summary() for run in reversed(self._runs.values())],
                    "active": self._active.run_id if self._active else None, "retained": self._store is not None,
                    "rejected_on_load": bool(self._store and self._store.rejected_on_load),
                    "store_error": self.store_error}

    def detail(self, run_id):
        """The run summary, its sealed record (None while it runs) and the recorded human decisions."""
        with self._cond:
            run = self._get(run_id)
            return {**run.summary(), "record": run.record, "decisions": dict(run.decisions)}

    def decide(self, run_id, item, decision):
        """Record a human decision on approval item ``item``; nothing is executed. KeyError/ValueError on bad input."""
        if decision not in DECISIONS or type(item) is not int:
            raise ValueError("Unsupported decision")
        with self._cond:
            run = self._get(run_id)
            approvals = (run.record or {}).get("approvals") or []
            if not approvals or not 0 <= item < len(approvals[0]["items"]):
                raise KeyError("item")
            run.decisions[str(item)] = {"decision": decision, "decided_at": _now(), "reviewer": "local-user",
                                        "executed": False}
            self._persist()
            return dict(run.decisions)

    def records(self):
        """(record, decisions) of every finished run with a sealed record, oldest first."""
        with self._cond:
            return [(run.record, dict(run.decisions)) for run in self._runs.values() if run.record is not None]
