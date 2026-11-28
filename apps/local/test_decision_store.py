# SPDX-License-Identifier: Apache-2.0
"""Human incident decisions: versions kept per evidence, bounded, owner-only atomic writes, tampering set aside."""
import json
import os
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import decision_store as ds
from aegisflow_dr.casefile import decision_record


def record(evidence="a" * 64, decision="rejected", reviewer="Reviewer", at="2026-11-28T00:00:00Z"):
    return decision_record(incident_id="INC-0001", evidence_sha256=evidence, run_id="run-1", decision=decision,
                           candidate=None, supported=[], reviewer=reviewer, note="", decided_at=at)


class DecisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_versions_are_kept_and_persisted_owner_only(self):
        store = ds.DecisionStore(self.tmp.name)
        self.assertIsNone(store.latest("a" * 64))
        first, second = record(), record(decision="more_evidence", at="2026-11-28T00:01:00Z")
        store.add(first)
        self.assertEqual(store.add(second), [first, second])
        self.assertEqual(store.latest("a" * 64), second)
        path = store.path
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        reloaded = ds.DecisionStore(self.tmp.name)
        self.assertEqual((reloaded.history("a" * 64), reloaded.rejected_on_load), ([first, second], False))

    def test_bounds_on_versions_and_incidents(self):
        store = ds.DecisionStore(self.tmp.name)
        with mock.patch.object(ds, "VERSIONS", 2), mock.patch.object(ds, "INCIDENTS", 2):
            for i in range(3):
                store.add(record(at="t%d" % i))
            self.assertEqual([r["decided_at"] for r in store.history("a" * 64)], ["t1", "t2"])
            store.add(record(evidence="b" * 64))
            store.add(record(evidence="c" * 64))
            self.assertEqual(store.history("a" * 64), [])  # the least recently decided incident was dropped
            self.assertEqual(len(store.history("c" * 64)), 1)

    def test_a_tampered_or_malformed_file_is_set_aside(self):
        store = ds.DecisionStore(self.tmp.name)
        store.add(record())
        data = json.loads(store.path.read_text("utf-8"))
        data["incidents"]["a" * 64][0]["decision"] = "accepted"  # edited after the fact: the digest no longer matches
        for bad in (json.dumps(data), "not json", json.dumps({"format_version": "1"}),
                    json.dumps({"format_version": "1", "incidents": {"x": [record()]}}),
                    json.dumps({"format_version": "1", "incidents": {"b" * 64: [record()]}})):
            with self.subTest(bad=bad[:30]):
                store.path.write_text(bad, "utf-8")
                reloaded = ds.DecisionStore(self.tmp.name)
                self.assertTrue(reloaded.rejected_on_load)
                self.assertEqual(reloaded.history("a" * 64), [])
                self.assertTrue(store.path.with_name(ds.STORE_REJECTED).exists())

    def test_an_oversized_file_is_set_aside(self):
        path = ds.DecisionStore(self.tmp.name).path
        path.write_text("{}", "utf-8")
        with mock.patch.object(ds, "MAX_STORE_BYTES", 1):
            self.assertTrue(ds.DecisionStore(self.tmp.name).rejected_on_load)


if __name__ == "__main__":
    unittest.main()
