# SPDX-License-Identifier: Apache-2.0
"""User-added reference documents with provenance, persisted locally, searched with verified citations.

Added text is untrusted reference data: it is never an instruction, a tool grant or a source of authority. Every
document is size-bounded and control-character-checked, its revision is the hash of its normalised text (so any
edit is a new revision and old citations stop verifying), and the stored file is re-validated on load so a
hand-edited file cannot bypass the limits. Built-in documents cannot be replaced or removed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import RLock
import time
import unicodedata

from aegisflow_dr.pipeline import InputRejected
from knowledge import Document, Knowledge

TENANT = "local"
MAX_USER_DOCUMENTS = 50
MAX_TEXT_BYTES = 16384
MAX_NAME_CHARS = 80
MAX_RESULTS = 5
_ALLOWED_CONTROL = {"\n", "\t"}
# Letters that NFKD does not decompose; without this, Turkish dotless \u0131 would simply vanish from a name.
_TRANSLIT = str.maketrans({"\u0131": "i", "\u00df": "ss", "\u00f8": "o", "\u0111": "d", "\u0142": "l", "\u00e6": "ae", "\u0153": "oe"})


def slug(name) -> str:
    if type(name) is not str or not 1 <= len(name) <= MAX_NAME_CHARS:
        raise InputRejected(f"The document name must be 1 to {MAX_NAME_CHARS} characters")
    value = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name.lower()).translate(_TRANSLIT).encode("ascii", "ignore").decode()).strip("-")[:64].strip("-")
    if not value:
        raise InputRejected("The document name needs at least one letter or digit")
    return value


def clean(text) -> str:
    if type(text) is not str:
        raise InputRejected("The document text must be text")
    value = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs") and c not in _ALLOWED_CONTROL for c in value):
        raise InputRejected("The document text contains control characters")
    size = len(value.encode("utf-8"))
    if not 1 <= size <= MAX_TEXT_BYTES:
        raise InputRejected(f"The document text must be 1 to {MAX_TEXT_BYTES} bytes")
    return value


def _stamp(clock) -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat(timespec="seconds")


class KnowledgeBase:
    def __init__(self, directory, builtin, *, clock=time.time) -> None:
        self.path = Path(directory) / "knowledge.json"
        self.builtin = tuple(builtin)
        self._builtin_sources = {d.source for d in self.builtin}
        self.clock = clock
        self.lock = RLock()
        self.knowledge = Knowledge()
        self._user: dict[str, dict] = {}
        self.rejected_on_load = 0
        self._load()
        self._publish()

    # -- persistence -----------------------------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text("utf-8"))
            entries = stored["documents"] if type(stored) is dict and stored.get("version") == 1 else []
        except (ValueError, KeyError, OSError):
            self.rejected_on_load += 1
            return
        for entry in entries if type(entries) is list else []:
            try:
                self._store(entry["name"], entry["text"], added_at=entry["added_at"])
            except (InputRejected, KeyError, TypeError):
                self.rejected_on_load += 1

    def _persist(self) -> None:
        payload = json.dumps({"version": 1, "documents": [{"name": e["name"], "text": e["document"].text, "added_at": e["added_at"]}
                                                         for e in self._user.values()]}, ensure_ascii=False)
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(temporary, self.path)

    def _publish(self) -> None:
        self.knowledge.replace((*self.builtin, *(e["document"] for e in self._user.values())))

    # -- changes ---------------------------------------------------------------------------------------------
    def _store(self, name, text, *, added_at) -> str:
        source, value = slug(name), clean(text)
        if not isinstance(added_at, str) or not 1 <= len(added_at) <= 40:
            raise InputRejected("Invalid timestamp")
        if source in self._builtin_sources:
            raise InputRejected("That name is reserved by a built-in document")
        existing = self._user.get(source)
        if existing is None and len(self._user) >= MAX_USER_DOCUMENTS:
            raise InputRejected(f"At most {MAX_USER_DOCUMENTS} added documents are kept")
        revision = "c" + sha256(value.encode("utf-8")).hexdigest()[:12]
        if existing is not None and existing["document"].revision == revision:
            return "unchanged"
        self._user[source] = {"name": name, "added_at": added_at, "document": Document(TENANT, source, revision, value)}
        return "updated" if existing is not None else "added"

    def add(self, name, text) -> dict:
        with self.lock:
            before = dict(self._user)
            try:
                status = self._store(name, text, added_at=_stamp(self.clock))
                if status != "unchanged":
                    self._persist()
                    self._publish()
            except Exception:
                self._user = before
                raise
            source = slug(name)
            document = self._user[source]["document"]
            return {"status": status, "source": source, "revision": document.revision, "citation_sha256": document.citation}

    def remove(self, source) -> None:
        with self.lock:
            if type(source) is not str or source not in self._user:
                raise InputRejected("Unknown added document")
            before = dict(self._user)
            del self._user[source]
            try:
                self._persist()
            except Exception:
                self._user = before
                raise
            self._publish()

    # -- reading ---------------------------------------------------------------------------------------------
    def documents(self) -> list[dict]:
        with self.lock:
            rows = [{"source": d.source, "revision": d.revision, "citation_sha256": d.citation, "bytes": len(d.text.encode("utf-8")),
                     "origin": "built-in", "builtin": True, "name": None, "added_at": None} for d in self.builtin]
            rows += [{"source": s, "revision": e["document"].revision, "citation_sha256": e["document"].citation,
                      "bytes": len(e["document"].text.encode("utf-8")), "origin": "added", "builtin": False,
                      "name": e["name"], "added_at": e["added_at"]} for s, e in sorted(self._user.items())]
            return rows

    def search(self, query, limit=MAX_RESULTS) -> list[dict]:
        with self.lock:
            allowed = frozenset(self._builtin_sources | set(self._user))
            try:
                found = self.knowledge.retrieve_passages(TENANT, query, allowed_sources=allowed, limit=limit)
            except ValueError as error:
                raise InputRejected("The search must be 1 to 1024 bytes and the limit 1 to 10") from error
            return [{**item, "builtin": item["source"] in self._builtin_sources,
                     "verified": self.knowledge.verify_passage(TENANT, item["citation_sha256"], allowed_sources=allowed)} for item in found]
