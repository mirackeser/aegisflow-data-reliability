# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

import schema_store as ss
from aegisflow_dr.pipeline import InputRejected

BASE = [{"name": "order_id", "type": "integer"}, {"name": "order_total", "type": "decimal"}]
WIDER = [{"name": "order_id", "type": "text"}, {"name": "order_total", "type": "decimal"}]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_register_persists_privately_and_reloads(self):
        store = ss.SchemaStore(self.dir)
        first = store.register("orders", BASE)
        self.assertEqual((first["version"], first["created"], first["drift"]["status"]), (1, True, "NO_CONTRACT"))
        self.assertEqual(stat.S_IMODE(os.stat(self.dir / ss.FILE).st_mode), 0o600)
        self.assertEqual(store.set_contract("orders", 1), {"subject": "orders", "contract": 1})
        second = store.register("orders", WIDER)
        self.assertEqual((second["version"], second["drift"]["status"]), (2, "DRIFT_BREAKING"))
        reopened = ss.SchemaStore(self.dir)
        self.assertFalse(reopened.rejected_on_load)
        overview = reopened.overview()
        self.assertEqual([(s["subject"], s["versions"], s["contract"]) for s in overview["subjects"]], [("orders", 2, 1)])
        self.assertEqual(len(overview["subjects"][0]["history"]), 2)
        self.assertEqual(reopened.drift("orders", BASE)["status"], "CONFORMS")

    def test_unchanged_registration_does_not_rewrite(self):
        store = ss.SchemaStore(self.dir)
        store.register("orders", BASE)
        before = (self.dir / ss.FILE).stat().st_mtime_ns
        again = store.register("orders", BASE)
        self.assertFalse(again["created"])
        self.assertEqual((self.dir / ss.FILE).stat().st_mtime_ns, before)

    def test_invalid_input_is_rejected_without_writing(self):
        store = ss.SchemaStore(self.dir)
        with self.assertRaises(InputRejected):
            store.register("bad name", BASE)
        with self.assertRaises(InputRejected):
            store.set_contract("missing", 1)
        self.assertFalse((self.dir / ss.FILE).exists())

    def test_edited_file_is_set_aside_not_trusted_or_overwritten(self):
        store = ss.SchemaStore(self.dir)
        store.register("orders", BASE)
        data = json.loads((self.dir / ss.FILE).read_text())
        data["subjects"]["orders"]["versions"][0]["columns"][0]["type"] = "text"
        (self.dir / ss.FILE).write_text(json.dumps(data))
        reopened = ss.SchemaStore(self.dir)
        self.assertTrue(reopened.rejected_on_load)
        self.assertEqual(reopened.overview()["subjects"], [])
        self.assertTrue((self.dir / ss.REJECTED).exists())
        self.assertFalse((self.dir / ss.FILE).exists())
        self.assertEqual(json.loads((self.dir / ss.REJECTED).read_text()), data)

    def test_garbage_and_oversize_files_are_set_aside(self):
        for content in (b"not json", b"[]", b"\xff\xfe"):
            (self.dir / ss.FILE).write_bytes(content)
            self.assertTrue(ss.SchemaStore(self.dir).rejected_on_load)
        (self.dir / ss.FILE).write_bytes(b" " * (ss.MAX_FILE_BYTES + 1))
        self.assertTrue(ss.SchemaStore(self.dir).rejected_on_load)


if __name__ == "__main__":
    unittest.main()
