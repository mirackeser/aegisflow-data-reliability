# SPDX-License-Identifier: Apache-2.0
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import baseline_store as bs
from aegisflow_dr import baseline as core, hypotheses as hy, hypotheses_eval as he
from aegisflow_dr.pipeline import InputRejected

REF = b"ts,v\n2026-01-01T00:00:00,1\n2026-01-01T01:00:00,2\n2026-01-01T02:00:00,3\n"
CUR = b"ts,v\n2026-01-02T00:00:00,1\n2026-01-02T01:00:00,2\n"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.store = bs.BaselineStore(self.dir, clock=lambda: 1_700_000_000)

    def test_save_overview_persist_and_reload(self):
        entry = self.store.save("Orders Daily", [REF])
        self.assertEqual(entry["name"], "orders-daily")
        self.assertEqual(entry["created"], "2023-11-14T22:13:20+00:00")
        self.assertEqual((entry["references"], entry["records"], entry["time_column"], entry["time_aware"]), (1, 3, "ts", False))
        self.assertEqual(len(entry["digest"]), 64)
        path = self.dir / "baselines.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        data = json.loads(path.read_text())
        self.assertEqual(data["format_version"], "1")
        self.assertEqual(data["baselines"]["orders-daily"]["created"], entry["created"])
        again = bs.BaselineStore(self.dir)
        self.assertEqual(again.overview(), {"baselines": [entry], "rejected_on_load": False})
        self.assertEqual(again.get("orders-daily")["digest"], entry["digest"])

    def test_file_bytes_are_kept_and_hashed_as_sent(self):
        bom = b"\xef\xbb\xbf" + "ts,v,ad\r\n2026-01-01T00:00:00,1,ş\r\n2026-01-01T01:00:00,2,ı\r\n".encode("utf-8")
        with patch("baseline_store.build_baseline", wraps=core.build_baseline) as spy:
            self.store.save("t", [bom])
        self.assertEqual(spy.call_args[0][0], [bom])
        self.assertEqual(self.store.get("t")["references"][0]["sha256"], hashlib.sha256(bom).hexdigest())
        self.assertEqual(self.store.compare("t", bom)["source_sha256"], hashlib.sha256(bom).hexdigest())
        with self.assertRaisesRegex(InputRejected, "UTF-8"):
            self.store.save("cp1254", ["ts,ad\n2026-01-01T00:00:00,ş\n".encode("cp1254")])

    def test_from_base64(self):
        self.assertEqual(bs.from_base64(base64.b64encode(REF).decode()), REF)
        for bad in ("@@@@", "abc", "YQ==\n", None, 5, b"YQ==", ["YQ=="]):
            with self.assertRaises(InputRejected, msg=repr(bad)):
                bs.from_base64(bad)

    def test_overview_says_whether_time_is_aware(self):
        aware = b"ts,v\n" + b"".join(b"2026-01-01T0%d:00:00Z,%d\n" % (i, i) for i in range(3))
        plain = b"a,b\n1,2\n3,4\n"
        self.assertIs(self.store.save("aware", [aware])["time_aware"], True)
        self.assertIs(self.store.save("naive", [REF])["time_aware"], False)
        self.assertIsNone(self.store.save("plain", [plain])["time_aware"])
        self.assertEqual({b["name"]: b["time_aware"] for b in self.store.overview()["baselines"]},
                         {"aware": True, "naive": False, "plain": None})
        blank = b"ts,v\n" + b"2026-01-01T00:00:00,1\n" + b",2\n" * 3
        self.store.save("blank", [blank, b"ts,v\n,1\n,2\n"])
        self.assertIs({b["name"]: b for b in self.store.overview()["baselines"]}["blank"]["time_aware"], False)

    def test_failed_write_leaves_memory_and_disk_unchanged(self):
        self.store.save("a", [REF])
        before, on_disk = self.store.overview(), (self.dir / "baselines.json").read_bytes()
        with patch.object(bs.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.save("b", [REF])
            with self.assertRaises(OSError):
                self.store.save("a", [REF, REF], replace=True)
            with self.assertRaises(OSError):
                self.store.remove("a")
        self.assertEqual(self.store.overview(), before)
        self.assertEqual((self.dir / "baselines.json").read_bytes(), on_disk)
        self.assertEqual(self.store.get("a")["references"][0]["records"], 3)
        self.assertEqual(len(self.store.get("a")["references"]), 1)

    def test_slug_rules(self):
        self.assertEqual(bs.slug("ışık"), "isik")
        self.assertEqual(bs.slug("  A__b  "), "a-b")
        self.assertEqual(len(bs.slug("x" * 80)), 64)
        for bad in ("", "   ", "!!!", "x" * 81, None, 5):
            with self.assertRaises(InputRejected):
                bs.slug(bad)

    def test_replace_required_and_applied(self):
        first = self.store.save("a", [REF])
        with self.assertRaisesRegex(InputRejected, "A baseline with this name exists"):
            self.store.save("a", [REF])
        with self.assertRaises(InputRejected):
            self.store.save("a", [REF], replace=1)
        later = bs.BaselineStore(self.dir, clock=lambda: 1_700_000_100)
        second = later.save("a", [REF, CUR.replace(b"2026-01-02", b"2026-01-03")], replace=True)
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertEqual(len(later.overview()["baselines"]), 1)

    def test_limit_50_and_bad_references(self):
        for i in range(50):
            self.store.save(f"n{i}", [REF])
        with self.assertRaises(InputRejected):
            self.store.save("extra", [REF])
        self.store.save("n0", [REF], replace=True)
        for bad in ("x", [], [REF] * 6, [1], [REF, None], [REF.decode()], [bytearray(REF)]):
            with self.assertRaises(InputRejected):
                self.store.save("fresh", bad)
        self.store.remove("n1")
        self.store.save("fresh", [REF], freshness_sla_seconds=99)
        self.assertEqual(self.store.get("fresh")["freshness_sla_seconds"], 99)

    def test_compare_remove_get_unknown(self):
        self.store.save("a", [REF])
        result = self.store.compare("a", CUR, as_of="2026-01-02T02:00:00")
        self.assertEqual(result["name"], "a")
        self.assertEqual(result["status"], core.compare(self.store.get("a"), CUR, as_of="2026-01-02T02:00:00")["status"])
        with self.assertRaises(KeyError):
            self.store.compare("zzz", CUR)
        with self.assertRaises(KeyError):
            self.store.get("zzz")
        with self.assertRaises(KeyError):
            self.store.remove("zzz")
        for bad in (5, CUR.decode(), None):
            with self.assertRaises(InputRejected):
                self.store.compare("a", bad)
        self.assertEqual(self.store.remove("a"), {"removed": "a"})
        self.assertEqual(bs.BaselineStore(self.dir).overview()["baselines"], [])

    def test_investigate_mirrors_compare(self):
        references, current, as_of, _ = he.scenario(0, "partial_load")
        self.store.save("plant", references)
        result = self.store.investigate("plant", current, as_of=as_of)
        self.assertEqual(result["name"], "plant")
        record = {k: v for k, v in result.items() if k != "name"}
        self.assertEqual(hy.verify_investigation(record), record)
        self.assertEqual(record, hy.investigate(self.store.get("plant"), current, as_of=as_of))
        self.assertEqual(record["observations"][0]["evidence_sha256"],
                         self.store.compare("plant", current, as_of=as_of)["source_sha256"])
        self.assertIn("partial_load", [h["mechanism"] for h in record["hypotheses"] if h["status"] == "supported"])
        with self.assertRaises(KeyError):
            self.store.investigate("zzz", current)
        for bad in (5, current.decode(), None, bytearray(current)):
            with self.assertRaises(InputRejected):
                self.store.investigate("plant", bad)
        with self.assertRaises(InputRejected):
            self.store.investigate("plant", current, as_of="junk")
        clean = self.store.investigate("plant", references[0])
        self.assertEqual((clean["verdict"], clean["stop_reason"], clean["probes"]), ("no_observations", "no_observations", []))

    def _rejected(self, content):
        (self.dir / "baselines.json").write_bytes(content)
        store = bs.BaselineStore(self.dir)
        self.assertTrue(store.overview()["rejected_on_load"])
        self.assertEqual(store.overview()["baselines"], [])
        self.assertFalse((self.dir / "baselines.json").exists())
        self.assertEqual((self.dir / "baselines.rejected.json").read_bytes(), content)
        (self.dir / "baselines.rejected.json").unlink()

    def test_unverifiable_files_are_moved_aside(self):
        self.store.save("a", [REF])
        good = json.loads((self.dir / "baselines.json").read_text())
        tampered = json.loads(json.dumps(good))
        tampered["baselines"]["a"]["record"]["volume"]["max_records"] = 99
        self._rejected(json.dumps(tampered).encode())
        self._rejected(b"not json")
        self._rejected(b"[]")
        self._rejected(json.dumps({"format_version": "2", "baselines": {}}).encode())
        self._rejected(json.dumps({"format_version": "1", "baselines": []}).encode())
        entry = good["baselines"]["a"]
        self._rejected(json.dumps({"format_version": "1", "baselines": {"a": {"record": entry["record"]}}}).encode())
        self._rejected(json.dumps({"format_version": "1", "baselines": {"a": {"created": 5, "record": entry["record"]}}}).encode())
        self._rejected(json.dumps({"format_version": "1", "baselines": {"A b": entry}}).encode())
        self._rejected(json.dumps({"format_version": "1", "baselines": {"a": "x"}}).encode())
        self._rejected(b" " * (bs.MAX_FILE_BYTES + 1))

    def test_default_clock_is_utc_now(self):
        entry = bs.BaselineStore(self.dir).save("a", [REF])
        self.assertTrue(entry["created"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
