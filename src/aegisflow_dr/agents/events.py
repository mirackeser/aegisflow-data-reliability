# SPDX-License-Identifier: Apache-2.0
"""The typed, ordered event log of one agent run (see the "Live flow" section of the agent runtime design).

Every event is ``{"seq", "t_ms", "agent_id", "type", "data"}``: ``seq`` is the publication order (1, 2, ...), ``t_ms``
the run clock reading when the event happened (milliseconds since the run started), ``agent_id`` the role it belongs
to (run-level events belong to A01, the supervisor) and ``data`` a JSON object. An event is *stamped* when it happens
and *published* when the runtime records it; the runtime publishes the events of concurrent agents in agent-id order,
so ``seq`` is deterministic while ``t_ms`` stays the real moment. Publishing appends a detached copy to the log and
then calls ``on_event`` synchronously with another copy, so the callback sees exactly the recorded events and cannot
change them. A callback exception is counted and never stops the run. The callback runs under the log lock, so a
subscriber must not block (the flow page's run manager should only enqueue). Every event's ``data`` is validated on
stamping against its type's schema in ``data/agent-run-v1.json`` (``$defs/event_<type>``). The log is bounded: the
last of ``max_events`` slots is reserved for ``run_finished``, so a live view always sees the run end; any other event
beyond the bound is neither recorded nor delivered, and the record reports how many were dropped.
"""
import json
import re
from threading import RLock

from ..pipeline import InputRejected
from .contracts import validate_event

EVENT_TYPES = ("run_started", "agent_selected", "agent_skipped", "agent_started", "tool_call", "llm_call", "retrieval",
               "cache", "agent_finished", "judge_verdict", "approval_requested", "run_finished")
MAX_EVENTS = 4096
_AGENT = re.compile(r"A(?:0[1-9]|[12][0-9]|3[0-6])")


def _copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


class EventLog:
    """Thread-safe, bounded, ordered event log with a synchronous subscriber."""

    def __init__(self, clock, started, on_event=None, *, max_events=MAX_EVENTS):
        if not callable(clock) or (on_event is not None and not callable(on_event)) or type(max_events) is not int \
                or max_events < 2:
            raise ValueError("Invalid event log settings")
        self._clock, self._started, self._on_event, self._max = clock, started, on_event, max_events
        self._events, self._lock = [], RLock()  # a subscriber may emit from its callback
        self.dropped = self.callback_errors = 0

    def stamp(self, agent_id, kind, data):
        """An unpublished event with the current run time; raises ValueError for an unknown type or agent."""
        if kind not in EVENT_TYPES or type(agent_id) is not str or not _AGENT.fullmatch(agent_id) \
                or type(data) is not dict:
            raise ValueError("Invalid event")
        t_ms = max(0, round((self._clock() - self._started) * 1000))
        pending = {"t_ms": t_ms, "agent_id": agent_id, "type": kind, "data": _copy(data)}
        try:
            validate_event({"seq": 1, **pending})
        except InputRejected:
            raise ValueError("Invalid event") from None
        return pending

    def publish(self, pending):
        """Record ``pending`` with the next ``seq`` and deliver it to the subscriber."""
        with self._lock:
            room = self._max if pending["type"] == "run_finished" else self._max - 1
            if len(self._events) >= room:
                self.dropped += 1
                return None
            event = {"seq": len(self._events) + 1, **pending}
            self._events.append(event)
            delivered = _copy(event)
            if self._on_event is not None:
                try:
                    self._on_event(delivered)
                except Exception:  # a subscriber failure must not break or alter the run
                    self.callback_errors += 1
            return event

    def emit(self, agent_id, kind, data):
        return self.publish(self.stamp(agent_id, kind, data))

    def events(self):
        with self._lock:
            return _copy(self._events)
