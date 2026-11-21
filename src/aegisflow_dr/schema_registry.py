# SPDX-License-Identifier: Apache-2.0
"""Versioned schema snapshots, deterministic schema diff and contract drift (work package D04).

Schemas here are column names with a type inferred from observed values (``integer``,
``decimal``, ``text`` or ``empty``). An inferred type is evidence about the sample that was
read, not a declaration by the data owner, so every result is a statement about that sample.
"""
from copy import deepcopy
import re

from .pipeline import InputRejected
from .storage.store import canonical, sha

TYPES = ("empty", "integer", "decimal", "text")
_RANK = {name: rank for rank, name in enumerate(TYPES)}
MAX_SUBJECTS, MAX_VERSIONS, MAX_COLUMNS, MAX_NAME = 100, 200, 500, 128
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _reject(message):
    raise InputRejected(message)


def clean_columns(columns):
    """Validate and copy a column list; the order is the position."""
    if type(columns) is not list or not columns or len(columns) > MAX_COLUMNS:
        _reject("Schema needs 1 to %d columns" % MAX_COLUMNS)
    result, names = [], set()
    for column in columns:
        if type(column) is not dict or set(column) != {"name", "type"}:
            _reject("Each column needs exactly a name and a type")
        name, kind = column["name"], column["type"]
        if (type(name) is not str or not name or len(name) > MAX_NAME or name != name.strip()
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)):
            _reject("Invalid column name")
        if type(kind) is not str or kind not in TYPES:
            _reject("Unknown column type")
        if name in names:
            _reject("Duplicate column name")
        names.add(name)
        result.append({"name": name, "type": kind})
    return result


def columns_from_discovery(discovery):
    """Turn the output of ``analysis.discover_schema`` into registry columns."""
    return clean_columns([{"name": c["name"], "type": c["inferred_type"]} for c in discovery["columns"]])


def schema_sha256(columns):
    return sha(canonical(clean_columns(columns)))


def diff_columns(old, new):
    """Compare two schemas. ``BREAKING`` means a reader of ``old`` can meet data it did not expect."""
    old, new = clean_columns(old), clean_columns(new)
    before, after = {c["name"]: c["type"] for c in old}, {c["name"]: c["type"] for c in new}
    removed = [c["name"] for c in old if c["name"] not in after]
    added = [c["name"] for c in new if c["name"] not in before]
    widened, narrowed, uninformative = [], [], []
    for column in old:
        name = column["name"]
        if name not in after or after[name] == before[name]:
            continue
        change = {"name": name, "from": before[name], "to": after[name]}
        if "empty" in (before[name], after[name]):
            uninformative.append(change)
        elif _RANK[after[name]] > _RANK[before[name]]:
            widened.append(change)
        else:
            narrowed.append(change)
    common_old = [c["name"] for c in old if c["name"] in after]
    common_new = [c["name"] for c in new if c["name"] in before]
    reordered = common_old != common_new
    renames = [{"from": o["name"], "to": n["name"], "basis": "same position and type"}
               for o, n in zip(old, new)
               if o["name"] in removed and n["name"] in added and o["type"] == n["type"] != "empty"]
    changed = removed or added or widened or narrowed or uninformative or reordered
    status = "BREAKING" if removed or widened else "COMPATIBLE" if changed else "IDENTICAL"
    return {"status": status, "removed": removed, "added": added, "widened": widened, "narrowed": narrowed,
            "uninformative": uninformative, "reordered": reordered, "possible_renames": renames}


def _record_sha(subject, version, schema, parent):
    return sha(canonical({"subject": subject, "version": version, "schema_sha256": schema, "parent_sha256": parent}))


class SchemaRegistry:
    """Append-only history per subject; every version commits to its predecessor."""

    def __init__(self):
        self._subjects = {}

    def _subject(self, name):
        if type(name) is not str or not _SUBJECT.fullmatch(name):
            _reject("Invalid subject name")
        return name

    def _history(self, subject):
        if subject not in self._subjects:
            _reject("Unknown subject")
        return self._subjects[subject]

    def register(self, subject, columns):
        subject, columns = self._subject(subject), clean_columns(columns)
        entry = self._subjects.get(subject)
        if entry is None:
            if len(self._subjects) >= MAX_SUBJECTS:
                _reject("Subject limit reached")
            entry = self._subjects[subject] = {"contract": None, "versions": []}
        digest, versions = schema_sha256(columns), entry["versions"]
        if versions and versions[-1]["schema_sha256"] == digest:
            return {"subject": subject, "version": versions[-1]["version"], "created": False,
                    "schema_sha256": digest, "diff": None}
        if len(versions) >= MAX_VERSIONS:
            _reject("Version limit reached")
        parent = versions[-1]["record_sha256"] if versions else None
        version = len(versions) + 1
        change = diff_columns(versions[-1]["columns"], columns) if versions else None
        versions.append({"version": version, "columns": columns, "schema_sha256": digest, "parent_sha256": parent,
                         "record_sha256": _record_sha(subject, version, digest, parent)})
        return {"subject": subject, "version": version, "created": True, "schema_sha256": digest, "diff": change}

    def subjects(self):
        return [{"subject": name, "versions": len(entry["versions"]), "contract": entry["contract"]}
                for name, entry in sorted(self._subjects.items())]

    def versions(self, subject):
        return [{"version": v["version"], "schema_sha256": v["schema_sha256"], "columns": len(v["columns"])}
                for v in self._history(subject)["versions"]]

    def get(self, subject, version=None):
        versions = self._history(subject)["versions"]
        number = len(versions) if version is None else version
        if type(number) is not int or not 1 <= number <= len(versions):
            _reject("Unknown version")
        return deepcopy(versions[number - 1])

    def diff(self, subject, old, new):
        return diff_columns(self.get(subject, old)["columns"], self.get(subject, new)["columns"])

    def set_contract(self, subject, version=None):
        self._history(subject)["contract"] = self.get(subject, version)["version"]
        return self._subjects[subject]["contract"]

    def drift(self, subject, columns):
        """Compare observed columns with the pinned contract version."""
        pinned = self._history(subject)["contract"]
        if pinned is None:
            return {"status": "NO_CONTRACT", "contract_version": None, "diff": None}
        change = diff_columns(self.get(subject, pinned)["columns"], columns)
        status = {"IDENTICAL": "CONFORMS", "COMPATIBLE": "DRIFT_COMPATIBLE", "BREAKING": "DRIFT_BREAKING"}[change["status"]]
        return {"status": status, "contract_version": pinned, "diff": change}

    def dump(self):
        return deepcopy({"format_version": "1", "subjects": dict(sorted(self._subjects.items()))})

    @classmethod
    def load(cls, data):
        """Rebuild a registry and re-verify every hash, so an edited file cannot forge history."""
        if type(data) is not dict or set(data) != {"format_version", "subjects"} or data["format_version"] != "1" \
                or type(data["subjects"]) is not dict or len(data["subjects"]) > MAX_SUBJECTS:
            _reject("Invalid registry file")
        registry = cls()
        for name, entry in data["subjects"].items():
            registry._subject(name)
            if type(entry) is not dict or set(entry) != {"contract", "versions"} or type(entry["versions"]) is not list \
                    or not entry["versions"] or len(entry["versions"]) > MAX_VERSIONS:
                _reject("Invalid subject history")
            parent, restored = None, []
            for number, item in enumerate(entry["versions"], 1):
                if type(item) is not dict or set(item) != {"version", "columns", "schema_sha256", "parent_sha256", "record_sha256"}:
                    _reject("Invalid version record")
                columns = clean_columns(item["columns"])
                digest = schema_sha256(columns)
                if (item["version"] != number or type(item["version"]) is not int or item["schema_sha256"] != digest
                        or item["parent_sha256"] != parent
                        or item["record_sha256"] != _record_sha(name, number, digest, parent)):
                    _reject("Registry history does not verify")
                if restored and restored[-1]["schema_sha256"] == digest:
                    _reject("Registry history repeats a version")
                restored.append({**item, "columns": columns})
                parent = item["record_sha256"]
            contract = entry["contract"]
            if contract is not None and (type(contract) is not int or not 1 <= contract <= len(restored)):
                _reject("Invalid contract version")
            registry._subjects[name] = {"contract": contract, "versions": restored}
        return registry
