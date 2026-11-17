# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path

from aegisflow_dr import capability_map as cm
from aegisflow_dr.execution_view import build_plan


class CapabilityMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = cm.capability_map()

    def test_all_thirty_six_roles_are_accounted_for_exactly_once(self):
        ids = [r["agent_id"] for r in self.report["roles"]]
        self.assertEqual((len(ids), len(set(ids)), self.report["total"]), (36, 36, 36))
        self.assertEqual(sum(self.report["counts"].values()), 36)
        self.assertEqual(self.report["counts"], {"implemented": 9, "partial": 6, "unavailable": 1, "disabled": 1, "planned": 19})

    def test_only_catalog_roles_are_mapped_and_statuses_are_known(self):
        ids = {r["agent_id"] for r in self.report["roles"]}
        self.assertTrue(set(cm.COVERAGE) <= ids)
        self.assertTrue(all(status in cm.STATUSES for status, _ in cm.COVERAGE.values()))

    def test_every_claimed_implementation_points_at_code_that_exists(self):
        root = Path(__file__).resolve().parents[1]
        for agent_id, (status, anchors) in cm.COVERAGE.items():
            self.assertEqual(bool(anchors), status in ("implemented", "partial"), agent_id)
            for anchor in anchors:
                if anchor.startswith("apps/"):
                    path, name = anchor.split(":")
                    self.assertIn("def " + name.split(".")[-1], (root / path).read_text("utf-8"), anchor)
                else:
                    self.assertTrue(callable(cm.resolve(anchor)), anchor)

    def test_resolve_fails_loudly_for_missing_code(self):
        for anchor in ("aegisflow_dr.pipeline:does_not_exist", "aegisflow_dr.no_such_module:x"):
            with self.assertRaises((AttributeError, ImportError)):
                cm.resolve(anchor)

    def test_unavailable_and_disabled_roles_match_the_execution_plan(self):
        plan = {s["role"]: s for s in build_plan(tools_run=set(), source_failed=False, profiled=False, has_actions=False,
                                                 judge_decision=None, retained=False)}
        for role, (status, _) in cm.COVERAGE.items():
            if status in ("unavailable", "disabled"):
                self.assertEqual(plan[role]["status"], status, role)
        for role in plan:
            self.assertIn(cm.COVERAGE[role][0], ("implemented", "unavailable", "disabled"), role)

    def test_names_and_priorities_come_from_the_catalog(self):
        first = self.report["roles"][0]
        self.assertEqual((first["agent_id"], first["name"], first["priority"], first["status"]), ("A01", "Global Supervisor", "P0", "planned"))


if __name__ == "__main__":
    unittest.main()
