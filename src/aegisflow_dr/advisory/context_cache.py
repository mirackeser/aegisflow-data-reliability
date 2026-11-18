# SPDX-License-Identifier: Apache-2.0
"""A bounded, isolated cache of prepared evidence contexts for repeated model requests.

This is the cache half of cache-augmented generation: it keeps an already built context so that several
requests over the same evidence reuse it. It is not a model key-value cache and generates nothing. Entries are
found only by exact identity (tenant, kind, version, evidence digest and scope), never by a hash of them, so a
different tenant, grant set, prompt version or changed evidence cannot reach another entry. Stored bytes are
re-hashed on every hit; a mismatch drops the entry and rebuilds it. Entries expire, the cache is bounded in
count and bytes, and entries can be invalidated by tenant, kind, version or evidence digest.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import re
from threading import RLock
from time import monotonic

from .contracts import AdvisoryError

_NAME = re.compile(r"[a-z0-9-]{1,64}")
_HASH = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class CacheIdentity:
    tenant: str
    kind: str
    version: str
    evidence_sha256: str
    scope: tuple = ()

    def __post_init__(self):
        if (any(type(v) is not str or not _NAME.fullmatch(v) for v in (self.tenant, self.kind, self.version))
                or type(self.evidence_sha256) is not str or not _HASH.fullmatch(self.evidence_sha256)
                or type(self.scope) is not tuple or len(self.scope) > 64
                or any(type(s) is not str or not _NAME.fullmatch(s) for s in self.scope)
                or list(self.scope) != sorted(set(self.scope))):
            raise AdvisoryError("Invalid cache identity")


class ContextCache:
    def __init__(self, *, clock=monotonic, ttl=300, capacity=64, max_entry_bytes=16384, max_total_bytes=262144):
        if (type(ttl) is not int or not 1 <= ttl <= 3600 or type(capacity) is not int or not 1 <= capacity <= 1024
                or type(max_entry_bytes) is not int or not 1 <= max_entry_bytes <= 1_000_000
                or type(max_total_bytes) is not int or not max_entry_bytes <= max_total_bytes <= 64_000_000):
            raise AdvisoryError("Invalid cache limits")
        self._clock, self._ttl, self._capacity = clock, ttl, capacity
        self._max_entry, self._max_total = max_entry_bytes, max_total_bytes
        self._entries: OrderedDict[CacheIdentity, tuple[float, bytes, str]] = OrderedDict()
        self._lock = RLock()
        self._counters = dict.fromkeys(("hits", "misses", "evictions", "expirations", "invalidations", "corrupt"), 0)

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not 0 <= now < float("inf"):
            raise AdvisoryError("Invalid cache clock")
        return now

    def _drop(self, identity: CacheIdentity, counter: str) -> None:
        del self._entries[identity]
        self._counters[counter] += 1

    def get_or_build(self, identity: CacheIdentity, builder) -> bytes:
        """Return the cached bytes for exactly this identity, or build, check and store them.

        The builder runs under the cache lock, so concurrent callers with the same identity build once.
        A builder that raises, or returns something other than 1..max_entry_bytes of bytes, caches nothing.
        """
        if type(identity) is not CacheIdentity:
            raise AdvisoryError("Cache identity required")
        with self._lock:
            now = self._now()
            for key, (stored_at, _, _) in list(self._entries.items()):
                if now >= stored_at + self._ttl:
                    self._drop(key, "expirations")
            entry = self._entries.get(identity)
            if entry is not None:
                if sha256(entry[1]).hexdigest() == entry[2]:
                    self._entries.move_to_end(identity)
                    self._counters["hits"] += 1
                    return entry[1]
                self._drop(identity, "corrupt")
            self._counters["misses"] += 1
            value = builder()
            if type(value) is not bytes or not 1 <= len(value) <= self._max_entry:
                raise AdvisoryError("Invalid cache entry")
            self._entries[identity] = (now, value, sha256(value).hexdigest())
            while len(self._entries) > self._capacity or sum(len(e[1]) for e in self._entries.values()) > self._max_total:
                self._drop(next(iter(self._entries)), "evictions")
            return value

    def invalidate(self, *, tenant=None, kind=None, version=None, evidence_sha256=None) -> int:
        """Remove every entry matching all given filters; at least one filter is required."""
        wanted = {"tenant": tenant, "kind": kind, "version": version, "evidence_sha256": evidence_sha256}
        wanted = {name: value for name, value in wanted.items() if value is not None}
        if not wanted:
            raise AdvisoryError("Invalidation needs a filter")
        with self._lock:
            matching = [key for key in self._entries if all(getattr(key, name) == value for name, value in wanted.items())]
            for key in matching:
                self._drop(key, "invalidations")
            return len(matching)

    def stats(self) -> dict:
        with self._lock:
            return {**self._counters, "entries": len(self._entries), "bytes": sum(len(e[1]) for e in self._entries.values())}
