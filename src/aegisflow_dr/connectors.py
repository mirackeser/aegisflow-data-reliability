# SPDX-License-Identifier: Apache-2.0
"""Read-only access to CSV and SQLite files placed in one operator-chosen directory.

Only plain files directly inside that directory are reachable: no path separators, no symbolic links and no
other directory. SQLite files are opened read-only, every statement is checked by an authorizer that permits
only reads, and each query has a wall-clock deadline. Data leaves as bounded CSV bytes that then go through the
same deterministic inspection as an upload; nothing is written back to the source.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
import sqlite3
import time

from .pipeline import MAX_INPUT_BYTES, MAX_ROWS, InputRejected

SUFFIX_KIND = {".csv": "csv", ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite"}
MAX_SOURCES = 200
MAX_TABLES = 200
MAX_SQLITE_BYTES = 200_000_000
QUERY_SECONDS = 5.0
PROGRESS_STEPS = 10_000
_ALLOWED_ACTIONS = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION})
_UNREADABLE = "The database could not be read: it is not a SQLite file, is locked, or answered too slowly"


def _authorizer(action: int, *_arguments) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _open(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only=ON")
    connection.set_authorizer(_authorizer)
    deadline = time.monotonic() + QUERY_SECONDS
    connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, PROGRESS_STEPS)
    return connection


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return "binary"
    return repr(value) if isinstance(value, float) else str(value)


class SourceCatalog:
    """The set of files an operator has chosen to expose to the workbench."""

    def __init__(self, directory) -> None:
        self.directory = Path(directory).resolve()
        if not self.directory.is_dir():
            raise InputRejected("The source directory does not exist")

    def sources(self) -> list[dict]:
        found = []
        for entry in sorted(self.directory.iterdir(), key=lambda p: p.name):
            kind = SUFFIX_KIND.get(entry.suffix.lower())
            if kind is None or entry.is_symlink() or not entry.is_file():
                continue
            found.append({"id": entry.name, "kind": kind, "bytes": entry.stat().st_size})
        return found[:MAX_SOURCES]

    def _resolve(self, name) -> tuple[Path, str]:
        match = next((s for s in self.sources() if type(name) is str and s["id"] == name), None)
        if match is None:
            raise InputRejected("Unknown source")
        return self.directory / match["id"], match["kind"]

    def tables(self, name) -> dict:
        path, kind = self._resolve(name)
        if kind == "csv":
            return {"kind": kind, "tables": []}
        if path.stat().st_size > MAX_SQLITE_BYTES:
            raise InputRejected("The database file is larger than the 200 MB limit")
        try:
            with _open(path) as connection:
                names = self._table_names(connection)
                described = []
                for table in names:
                    cursor = connection.execute(f"SELECT * FROM {_quote(table)} LIMIT 0")
                    count = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
                    described.append({"name": table, "columns": [c[0] for c in cursor.description], "rows": count})
        except sqlite3.Error as error:
            raise InputRejected(_UNREADABLE) from error
        return {"kind": kind, "tables": described}

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> list[str]:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
                                  "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT ?", (MAX_TABLES,))
        return [row[0] for row in rows]

    def export(self, name, table=None) -> tuple[bytes, dict]:
        """Return bounded CSV bytes and honest provenance (total rows, whether the export is a sample)."""
        path, kind = self._resolve(name)
        if kind == "csv":
            with path.open("rb") as stream:
                payload = stream.read(MAX_INPUT_BYTES + 1)
            if len(payload) > MAX_INPUT_BYTES:
                raise InputRejected("The file exceeds the 1 MB limit")
            return payload, {"connector": "csv", "table": None, "total_rows": None, "sampled": False}
        if path.stat().st_size > MAX_SQLITE_BYTES:
            raise InputRejected("The database file is larger than the 200 MB limit")
        try:
            with _open(path) as connection:
                if type(table) is not str or table not in self._table_names(connection):
                    raise InputRejected("Unknown table")
                cursor = connection.execute(f"SELECT * FROM {_quote(table)} LIMIT ?", (MAX_ROWS + 1,))
                header = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                total = connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
        except sqlite3.Error as error:
            raise InputRejected(_UNREADABLE) from error
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows([[_cell(value) for value in row] for row in rows[:MAX_ROWS]])
        payload = stream.getvalue().encode("utf-8")
        if len(payload) > MAX_INPUT_BYTES:
            raise InputRejected("The table export exceeds the 1 MB limit; expose fewer columns in a view")
        return payload, {"connector": "sqlite", "table": table, "total_rows": total, "sampled": total > MAX_ROWS}
