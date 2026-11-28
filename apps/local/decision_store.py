# SPDX-License-Identifier: Apache-2.0
"""Human decisions on plant incidents, kept in ``incident-decisions.json`` in the private state folder.

Every version of a decision is kept (newest last, at most ``VERSIONS`` per incident evidence and ``INCIDENTS`` evidence
keys), keyed by the SHA-256 of the incident's frozen evidence, so a plant reset never attaches an old decision to a new
incident. Writes are atomic and owner-only. A file that does not parse, or holds a record whose digest does not verify,
is moved aside to ``incident-decisions.rejected.json`` (kept for inspection, never trusted) and the store starts empty.
"""
import json
import os
from pathlib import Path
from threading import Lock

from aegisflow_dr.casefile import decision_intact, is_digest

STORE_FILE, STORE_REJECTED, STORE_FORMAT = "incident-decisions.json", "incident-decisions.rejected.json", "1"
INCIDENTS, VERSIONS, MAX_STORE_BYTES = 200, 20, 2_000_000


class DecisionStore:
    def __init__(self, directory):
        self.path = Path(directory) / STORE_FILE
        self.rejected_on_load, self._items, self._lock = False, {}, Lock()
        if self.path.exists():
            try:
                if self.path.stat().st_size > MAX_STORE_BYTES:
                    raise ValueError("Decision file too large")
                self._items = self._parse(json.loads(self.path.read_text("utf-8")))
            except (ValueError, TypeError, KeyError, OSError, RecursionError):
                os.replace(self.path, self.path.with_name(STORE_REJECTED))
                self.rejected_on_load, self._items = True, {}

    @staticmethod
    def _parse(data):
        if type(data) is not dict or set(data) != {"format_version", "incidents"} or data["format_version"] != STORE_FORMAT \
                or type(data["incidents"]) is not dict or len(data["incidents"]) > INCIDENTS:
            raise ValueError("Decision file is malformed")
        for key, versions in data["incidents"].items():
            if not is_digest(key) or type(versions) is not list or not 1 <= len(versions) <= VERSIONS \
                    or not all(type(r) is dict and decision_intact(r) and r["evidence_sha256"] == key for r in versions):
                raise ValueError("Decision file is malformed")
        return data["incidents"]

    def add(self, record):
        """Keep ``record`` as the newest decision for its evidence and persist; returns its versions, newest last."""
        with self._lock:
            key = record["evidence_sha256"]
            versions = (self._items.pop(key, []) + [record])[-VERSIONS:]
            self._items[key] = versions  # re-inserted: the most recently decided incident is kept longest
            while len(self._items) > INCIDENTS:
                self._items.pop(next(iter(self._items)))
            self._save()
            return list(versions)

    def history(self, evidence_sha256):
        with self._lock:
            return list(self._items.get(evidence_sha256, []))

    def latest(self, evidence_sha256):
        versions = self.history(evidence_sha256)
        return versions[-1] if versions else None

    def _save(self):
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump({"format_version": STORE_FORMAT, "incidents": self._items}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
