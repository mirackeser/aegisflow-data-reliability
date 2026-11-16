# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from aegisflow_dr import connectors
from aegisflow_dr.connectors import SourceCatalog, _authorizer, _cell
from aegisflow_dr.pipeline import InputRejected


def make_db(path, rows=3, extra_table=False):
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE "or""ders" (order_id TEXT, total REAL, note BLOB, gone TEXT)')
    connection.executemany('INSERT INTO "or""ders" VALUES (?,?,?,?)',
                           [(f"O{i}", i + 0.5, b"x", None) for i in range(rows)])
    if extra_table:
        connection.execute("CREATE VIEW v AS SELECT order_id FROM \"or\"\"ders\"")
    connection.commit()
    connection.close()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "a.csv").write_text("order_id\nO1\n")
        make_db(self.dir / "b.sqlite", extra_table=True)
        (self.dir / "notes.txt").write_text("ignored")
        (self.dir / "folder.csv").mkdir()
        self.catalog = SourceCatalog(self.dir)

    def test_missing_directory_rejected(self):
        with self.assertRaises(InputRejected):
            SourceCatalog(self.dir / "nope")

    def test_lists_only_plain_supported_files(self):
        self.assertEqual([(s["id"], s["kind"]) for s in self.catalog.sources()],
                         [("a.csv", "csv"), ("b.sqlite", "sqlite")])

    def test_symlinks_are_not_exposed(self):
        outside = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        os.symlink(outside.name, self.dir / "link.csv")
        self.assertNotIn("link.csv", [s["id"] for s in self.catalog.sources()])

    def test_source_names_cannot_escape_the_directory(self):
        for name in ("../a.csv", "/etc/passwd", "sub/a.csv", None, 5, "missing.csv"):
            with self.assertRaises(InputRejected):
                self.catalog.export(name)

    def test_tables_of_csv_are_empty(self):
        self.assertEqual(self.catalog.tables("a.csv"), {"kind": "csv", "tables": []})

    def test_tables_of_sqlite(self):
        info = self.catalog.tables("b.sqlite")
        self.assertEqual([t["name"] for t in info["tables"]], ['or"ders', "v"])
        self.assertEqual(info["tables"][0]["rows"], 3)
        self.assertEqual(info["tables"][0]["columns"], ["order_id", "total", "note", "gone"])

    def test_non_sqlite_file_is_rejected_without_leaking_details(self):
        (self.dir / "bad.db").write_text("not a database")
        for call in (lambda: self.catalog.tables("bad.db"), lambda: self.catalog.export("bad.db", "x")):
            with self.assertRaises(InputRejected) as caught:
                call()
            self.assertIn("could not be read", str(caught.exception))

    def test_oversized_database_rejected(self):
        with mock.patch.object(connectors, "MAX_SQLITE_BYTES", 1):
            with self.assertRaises(InputRejected):
                self.catalog.tables("b.sqlite")
            with self.assertRaises(InputRejected):
                self.catalog.export("b.sqlite", "v")

    def test_export_csv_is_verbatim_and_bounded(self):
        payload, meta = self.catalog.export("a.csv")
        self.assertEqual(payload, b"order_id\nO1\n")
        self.assertEqual(meta, {"connector": "csv", "table": None, "total_rows": None, "sampled": False})
        with mock.patch.object(connectors, "MAX_INPUT_BYTES", 3):
            with self.assertRaises(InputRejected):
                self.catalog.export("a.csv")

    def test_export_sqlite_renders_cells_honestly(self):
        payload, meta = self.catalog.export("b.sqlite", 'or"ders')
        lines = payload.decode().splitlines()
        self.assertEqual(lines[0], "order_id,total,note,gone")
        self.assertEqual(lines[1], "O0,0.5,binary,")
        self.assertEqual(meta, {"connector": "sqlite", "table": 'or"ders', "total_rows": 3, "sampled": False})

    def test_export_marks_row_limited_samples(self):
        with mock.patch.object(connectors, "MAX_ROWS", 2):
            payload, meta = self.catalog.export("b.sqlite", 'or"ders')
        self.assertEqual(len(payload.decode().splitlines()), 3)
        self.assertTrue(meta["sampled"])
        self.assertEqual(meta["total_rows"], 3)

    def test_unknown_or_malformed_table_rejected(self):
        for table in (None, 3, "missing", 'or"ders" ; DROP TABLE x --'):
            with self.assertRaises(InputRejected):
                self.catalog.export("b.sqlite", table)

    def test_export_size_limit(self):
        with mock.patch.object(connectors, "MAX_INPUT_BYTES", 10):
            with self.assertRaises(InputRejected):
                self.catalog.export("b.sqlite", 'or"ders')

    def test_source_is_never_modified(self):
        before = (self.dir / "b.sqlite").read_bytes()
        self.catalog.tables("b.sqlite")
        self.catalog.export("b.sqlite", 'or"ders')
        self.assertEqual((self.dir / "b.sqlite").read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["a.csv", "b.sqlite", "folder.csv", "notes.txt"])

    def test_connection_refuses_writes(self):
        with connectors._open(self.dir / "b.sqlite") as connection:
            for statement in ('DELETE FROM "or""ders"', "CREATE TABLE t (x)", "ATTACH DATABASE ':memory:' AS m",
                              "PRAGMA writable_schema=ON"):
                with self.assertRaises(sqlite3.Error, msg=statement):
                    connection.execute(statement)

    def test_authorizer_decisions(self):
        self.assertEqual(_authorizer(sqlite3.SQLITE_SELECT), sqlite3.SQLITE_OK)
        self.assertEqual(_authorizer(sqlite3.SQLITE_DELETE), sqlite3.SQLITE_DENY)

    def test_slow_queries_are_interrupted(self):
        with mock.patch.object(connectors, "QUERY_SECONDS", -1.0), mock.patch.object(connectors, "PROGRESS_STEPS", 1):
            with self.assertRaises(InputRejected):
                self.catalog.tables("b.sqlite")

    def test_cell_rendering(self):
        self.assertEqual([_cell(v) for v in (None, b"x", 1.5, 2, "s")], ["", "binary", "1.5", "2", "s"])

    def test_source_list_is_capped(self):
        with mock.patch.object(connectors, "MAX_SOURCES", 1):
            self.assertEqual(len(self.catalog.sources()), 1)


if __name__ == "__main__":
    unittest.main()
