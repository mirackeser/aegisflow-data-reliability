# SPDX-License-Identifier: Apache-2.0
"""Local persistence for saved profile baselines: atomic 0600 writes and a refusal to trust edited files."""
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from aegisflow_dr.baseline import build_baseline, compare as compare_baseline, load_baseline
from aegisflow_dr.pipeline import InputRejected

FILE = "baselines.json"
REJECTED = "baselines.rejected.json"
FORMAT = "1"
MAX_FILE_BYTES = 8_000_000
MAX_BASELINES = 50
MAX_NAME_CHARS = 80
# Same folding as the knowledge base: NFKD does not decompose these letters.
_TRANSLIT = str.maketrans({"ı": "i", "ß": "ss", "ø": "o", "đ": "d", "ł": "l", "æ": "ae", "œ": "oe"})
_SLUG = re.compile(r"[a-z0-9_-]{1,64}")


def slug(name) -> str:
    if type(name) is not str or not 1 <= len(name) <= MAX_NAME_CHARS:
        raise InputRejected(f"The baseline name must be 1 to {MAX_NAME_CHARS} characters")
    value = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name.lower()).translate(_TRANSLIT).encode("ascii", "ignore").decode()).strip("-")[:64].strip("-")
    if not value:
        raise InputRejected("The baseline name needs at least one letter or digit")
    return value


def _stamp(clock) -> str:
    return datetime.fromtimestamp(clock(), timezone.utc).isoformat(timespec="seconds")


def _entry(name, item):
    record = item["record"]
    return {"name": name, "created": item["created"], "references": len(record["references"]),
            "records": sum(r["records"] for r in record["references"]), "time_column": record["time_column"],
            "digest": record["digest"]}


class BaselineStore:
    def __init__(self, directory, *, clock=time.time):
        self.path = Path(directory) / FILE
        self.clock = clock
        self.lock = Lock()
        self.rejected_on_load = False
        self.items = {}
        if self.path.exists():
            try:
                if self.path.stat().st_size > MAX_FILE_BYTES:
                    raise InputRejected("Baseline file too large")
                self.items = self._parse(json.loads(self.path.read_text("utf-8")))
            except (InputRejected, ValueError, OSError):
                # Keep the unverifiable file for inspection instead of overwriting it.
                os.replace(self.path, self.path.with_name(REJECTED))
                self.rejected_on_load = True
                self.items = {}

    @staticmethod
    def _parse(data):
        if type(data) is not dict or set(data) != {"format_version", "baselines"} or data["format_version"] != FORMAT \
                or type(data["baselines"]) is not dict or len(data["baselines"]) > MAX_BASELINES:
            raise InputRejected("Baseline file is malformed")
        items = {}
        for name, item in data["baselines"].items():
            if not _SLUG.fullmatch(name) or type(item) is not dict or set(item) != {"created", "record"} \
                    or type(item["created"]) is not str:
                raise InputRejected("Baseline file is malformed")
            items[name] = {"created": item["created"], "record": load_baseline(item["record"])}
        return items

    def _save(self):
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"format_version": FORMAT, "baselines": self.items}, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def overview(self):
        with self.lock:
            return {"baselines": [_entry(name, self.items[name]) for name in sorted(self.items)],
                    "rejected_on_load": self.rejected_on_load}

    def _find(self, name):
        key = slug(name)
        if key not in self.items:
            raise KeyError(key)
        return key

    def get(self, name):
        with self.lock:
            return self.items[self._find(name)]["record"]

    def save(self, name, references, freshness_sla_seconds=None, replace=False):
        key = slug(name)
        if type(references) is not list or any(type(r) is not str for r in references):
            raise InputRejected("references must be a list of CSV texts")
        with self.lock:
            if key in self.items and replace is not True:
                raise InputRejected("A baseline with this name exists")
            if key not in self.items and len(self.items) >= MAX_BASELINES:
                raise InputRejected(f"At most {MAX_BASELINES} baselines can be saved")
            record = build_baseline([r.encode("utf-8") for r in references], freshness_sla_seconds=freshness_sla_seconds)
            self.items[key] = {"created": _stamp(self.clock), "record": record}
            self._save()
            return _entry(key, self.items[key])

    def compare(self, name, csv_text, as_of=None):
        if type(csv_text) is not str:
            raise InputRejected("The CSV must be text")
        with self.lock:
            key = self._find(name)
            record = self.items[key]["record"]
        return {**compare_baseline(record, csv_text.encode("utf-8"), as_of=as_of), "name": key}

    def remove(self, name):
        with self.lock:
            key = self._find(name)
            del self.items[key]
            self._save()
            return {"removed": key}
