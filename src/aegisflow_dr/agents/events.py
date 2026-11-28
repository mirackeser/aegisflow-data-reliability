# SPDX-License-Identifier: Apache-2.0
"""The typed, ordered event log of one agent run (see the "Live flow" section of the agent runtime design).

Every event is ``{"seq", "t_ms", "agent_id", "type", "data"}``: ``t_ms`` is the run clock reading when the event
happened (milliseconds since the run started), ``agent_id`` the role it belongs to (run-level events belong to A01, the
supervisor) and ``data`` a JSON object. An event is *stamped* when it happens and *published* when the runtime
records it; an agent's own events (tool, model, retrieval and cache) are published together with its
``agent_finished`` as soon as that agent completes, so concurrent agents arrive in completion order.

There are two orders. The **live** order is arrival: ``on_event`` receives each event at publication with ``seq`` =
its arrival position, which is what a live view and ``Last-Event-ID`` use. The **sealed** order, returned by
``events()`` and stored in the run record, is canonical: within each span the runtime ``seal``s (a wave's completion
blocks), events are ordered by agent id, keeping each agent's own order, and ``seq`` is renumbered 1, 2, ... in that
order. The sealed record therefore does not depend on thread timing, and both orders contain exactly the same events.
Publishing appends a detached copy to the log and then calls ``on_event`` synchronously with another copy, so the
callback cannot change the record. A callback exception is counted and never stops the run. The callback runs under
the log lock, so a subscriber must not block (the flow page's run manager should only enqueue). Every event's ``data`` is validated on
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

    def stamp(self, agent_id, kind, data, at=None):
        """An unpublished event at run clock reading ``at`` (default: now); ValueError for an invalid event."""
        if kind not in EVENT_TYPES or type(agent_id) is not str or not _AGENT.fullmatch(agent_id) \
                or type(data) is not dict:
            raise ValueError("Invalid event")
        t_ms = max(0, round(((self._clock() if at is None else at) - self._started) * 1000))
        pending = {"t_ms": t_ms, "agent_id": agent_id, "type": kind, "data": _copy(data)}
        try:
            validate_event({"seq": 1, **pending})
        except InputRejected:
            raise ValueError("Invalid event") from None
        return pending

    def publish(self, pending):
        """Record ``pending`` and deliver it to the subscriber with its arrival ``seq``."""
        with self._lock:
            room = self._max if pending["type"] == "run_finished" else self._max - 1
            if len(self._events) >= room:
                self.dropped += 1
                return None
            event = {"seq": len(self._events) + 1, **pending}
            self._events.append(pending)
            delivered = _copy(event)
            if self._on_event is not None:
                try:
                    self._on_event(delivered)
                except Exception:  # a subscriber failure must not break or alter the run
                    self.callback_errors += 1
            return event

    def emit(self, agent_id, kind, data):
        return self.publish(self.stamp(agent_id, kind, data))

    def mark(self):
        """The position where a span to be sealed starts."""
        with self._lock:
            return len(self._events)

    def seal(self, mark):
        """Order the events published since ``mark`` by agent id, keeping each agent's own order (a stable sort)."""
        with self._lock:
            self._events[mark:] = sorted(self._events[mark:], key=lambda event: event["agent_id"])

    def events(self):
        """The sealed events, ``seq`` numbered in sealed order."""
        with self._lock:
            return [{"seq": number, **event} for number, event in enumerate(_copy(self._events), 1)]
