# SPDX-License-Identifier: Apache-2.0
"""The per-case context every agent executor receives, and the run's digest-addressed evidence store.

``AgentContext`` holds the case inputs of the binding role table (payload, baseline, as_of, second_payload,
retriever, history, tenant_id, case_id), the run's evidence store, the optional local model and context cache, and
``prior`` (agent id -> result of the agents that already ran in this run). ``for_task`` binds a copy to one task:
the bound copy enforces the task's tool allowlist (itself a subset of the role's, see ``contracts.validate_task``)
and its tool budget, and counts tool calls and their latency. Executors reach existing modules only through
``tool``; the case intake (``executors.orchestration.triage``) is the one deliberate exception and is labelled so.

Evidence is stored as canonical JSON. A reference is ``{"id", "sha256"}`` where the id is the kind plus the first
32 hex digits of the digest, so the same object always gets the same reference and a reference cannot silently
point at changed content: ``get`` re-hashes the stored bytes before returning a fresh copy.
"""
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import re
from threading import RLock
from time import perf_counter
from typing import Any, Callable

from ..advisory.context_cache import ContextCache
from ..pipeline import InputRejected
from .llm import LocalModel
from .registry import role

MAX_EVIDENCE_ITEMS, MAX_EVIDENCE_BYTES = 4096, 32_000_000
_KIND = re.compile(r"[a-z][a-z0-9_]{0,30}")
_TENANT = re.compile(r"[a-z0-9-]{1,64}")
_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{64}")


class PolicyDenied(Exception):
    """A request outside the bound task's policy; ``code`` is the result's error code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ToolBudgetExceeded(Exception):
    """The bound task already used its ``max_tool_calls``."""


class ToolError(Exception):
    """A tool raised something other than InputRejected; the original error is not carried into results."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class EvidenceStore:
    """In-memory, digest-addressed, bounded and thread-safe store of JSON evidence for one run."""

    def __init__(self, *, max_items=MAX_EVIDENCE_ITEMS, max_bytes=MAX_EVIDENCE_BYTES):
        self._items, self._kinds, self._lock = {}, {}, RLock()
        self._max_items, self._max_bytes, self._bytes = max_items, max_bytes, 0

    def put(self, kind, obj):
        """Store ``obj`` under ``kind``; return its reference. Storing equal content twice returns the same reference."""
        if type(kind) is not str or not _KIND.fullmatch(kind):
            raise InputRejected("Invalid evidence kind")
        try:
            body = _canonical(obj)
        except (TypeError, ValueError, RecursionError):
            raise InputRejected("Evidence must be finite JSON") from None
        digest = sha256(body).hexdigest()
        ref = {"id": "%s:%s" % (kind, digest[:32]), "sha256": digest}
        with self._lock:
            stored = self._items.get(ref["id"])
            if stored is not None:
                if stored[1] != digest:  # a 128-bit prefix collision; refuse rather than alias
                    raise InputRejected("Evidence identifier collision")
                return dict(ref)
            if len(self._items) >= self._max_items or self._bytes + len(body) > self._max_bytes:
                raise InputRejected("Evidence store is full")
            self._items[ref["id"]] = (body, digest)
            self._kinds[ref["id"]] = kind
            self._bytes += len(body)
        return dict(ref)

    def _entry(self, ref):
        if (type(ref) is not dict or set(ref) != {"id", "sha256"} or type(ref["id"]) is not str
                or type(ref["sha256"]) is not str):
            return None
        with self._lock:
            stored = self._items.get(ref["id"])
        if stored is None or stored[1] != ref["sha256"] or sha256(stored[0]).hexdigest() != ref["sha256"]:
            return None
        return stored[0]

    def has(self, ref):
        """True when ``ref`` names stored content whose bytes still hash to ``ref["sha256"]``."""
        return self._entry(ref) is not None

    def get(self, ref):
        """Return a fresh copy of the referenced object; raise InputRejected for an unknown or mismatched reference."""
        body = self._entry(ref)
        if body is None:
            raise InputRejected("Unknown or altered evidence reference")
        return json.loads(body)

    def kind(self, ref):
        """The kind ``ref`` was stored under, or None when the reference does not resolve."""
        return self._kinds[ref["id"]] if self.has(ref) else None

    def refs(self, kind=None):
        """References of every stored item (optionally of one kind), in insertion order."""
        with self._lock:
            return [{"id": key, "sha256": digest} for key, (_, digest) in self._items.items()
                    if kind is None or self._kinds[key] == kind]


@dataclass
class Usage:
    tool_calls: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def _payload_ok(value, required):
    return (value is None and not required) or (type(value) is bytes and len(value) > 0)


@dataclass(frozen=True)
class AgentContext:
    payload: bytes
    tenant_id: str
    case_id: str
    baseline: Any = None
    as_of: Any = None
    second_payload: Any = None
    retriever: Any = None
    history: Any = None
    evidence: EvidenceStore = field(default_factory=EvidenceStore)
    model: Any = None
    cache: Any = None
    prior: dict = field(default_factory=dict)
    clock: Callable = perf_counter
    started: float = None
    agent_id: Any = None
    allowed_tools: tuple = ()
    max_tool_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    memo: dict = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        if (not _payload_ok(self.payload, True) or not _payload_ok(self.second_payload, False)
                or type(self.tenant_id) is not str or not _TENANT.fullmatch(self.tenant_id)
                or type(self.case_id) is not str or not _ID.fullmatch(self.case_id)
                or (self.baseline is not None and type(self.baseline) is not dict)
                or (self.as_of is not None and type(self.as_of) is not str)
                or (self.retriever is not None and not callable(self.retriever))
                or (self.history is not None and type(self.history) is not list)
                or type(self.evidence) is not EvidenceStore
                or (self.model is not None and type(self.model) is not LocalModel)
                or (self.cache is not None and type(self.cache) is not ContextCache)
                or type(self.prior) is not dict or not callable(self.clock)):
            raise InputRejected("Invalid agent context")
        if self.started is None:
            object.__setattr__(self, "started", self.clock())

    def for_task(self, task):
        """A copy bound to ``task`` (already validated): its agent, tool allowlist, tool budget and fresh usage."""
        role(task["agent_id"])
        return replace(self, agent_id=task["agent_id"], allowed_tools=tuple(task["allowed_tools"]),
                       max_tool_calls=task["budget"]["max_tool_calls"], usage=Usage(), memo=self.memo)

    def elapsed_ms(self):
        return max(0, round((self.clock() - self.started) * 1000))

    def tool(self, name, fn, *args, **kwargs):
        """Call ``fn`` as the tool ``name``: allowlist and budget first, then the call; count it either way."""
        if self.agent_id is None:
            raise InputRejected("Agent context is not bound to a task")
        if name not in self.allowed_tools:
            raise PolicyDenied("TOOL_NOT_ALLOWED")
        if self.usage.tool_calls >= self.max_tool_calls:
            raise ToolBudgetExceeded()
        self.usage.tool_calls += 1
        try:
            return fn(*args, **kwargs)
        except InputRejected:
            raise
        except Exception:  # any tool-side failure (including injected retrievers) becomes a typed outcome
            raise ToolError() from None

    def remember(self, key, build):
        """Case-scoped memo shared by every bound copy (for the deterministic case intake).

        Concurrent first calls may both build; the builders are deterministic, so the first stored value wins.
        """
        if key not in self.memo:
            self.memo.setdefault(key, build())
        return self.memo[key]
