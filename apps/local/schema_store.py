# SPDX-License-Identifier: Apache-2.0
"""Local persistence for the schema registry: atomic 0600 writes and a refusal to trust edited files."""
import json
import os
from pathlib import Path
from threading import Lock

from aegisflow_dr.pipeline import InputRejected
from aegisflow_dr.schema_registry import SchemaRegistry

FILE = "schemas.json"
REJECTED = "schemas.rejected.json"
MAX_FILE_BYTES = 8_000_000


class SchemaStore:
    def __init__(self, directory):
        self.path = Path(directory) / FILE
        self.lock = Lock()
        self.rejected_on_load = False
        self.registry = SchemaRegistry()
        if self.path.exists():
            try:
                if self.path.stat().st_size > MAX_FILE_BYTES:
                    raise InputRejected("Registry file too large")
                self.registry = SchemaRegistry.load(json.loads(self.path.read_text("utf-8")))
            except (InputRejected, ValueError, OSError):
                # Keep the unverifiable file for inspection instead of overwriting it with a new history.
                os.replace(self.path, self.path.with_name(REJECTED))
                self.rejected_on_load = True

    def _save(self):
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(self.registry.dump(), stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def overview(self):
        with self.lock:
            return self._overview()

    def _overview(self):
        return {"subjects": [{**item, "history": self.registry.versions(item["subject"])} for item in self.registry.subjects()],
                "rejected_on_load": self.rejected_on_load}

    def register(self, subject, columns):
        with self.lock:
            result = self.registry.register(subject, columns)
            if result["created"]:
                self._save()
            return {**result, "drift": self.registry.drift(subject, columns)}

    def set_contract(self, subject, version):
        with self.lock:
            pinned = self.registry.set_contract(subject, version)
            self._save()
            return {"subject": subject, "contract": pinned}

    def drift(self, subject, columns):
        with self.lock:
            return self.registry.drift(subject, columns)
