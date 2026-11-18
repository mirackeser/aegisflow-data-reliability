# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import unittest

from aegisflow_dr import platform_map as pm
from aegisflow_dr.capability_map import resolve

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["MCP", "A2A", "LLM", "RAG", "CAG", "CONTRACTS", "CERTIFICATES", "TAG", "CONNECTIONS", "JUDGE"]


class PlatformMapTests(unittest.TestCase):
    def test_all_ten_components_in_order(self):
        self.assertEqual([c["id"] for c in pm.platform_map()["components"]], EXPECTED)

    def test_every_anchor_resolves_and_every_test_file_exists(self):
        for component in pm.COMPONENTS:
            for anchor in component["anchors"]:
                if anchor.startswith("apps/"):
                    path, name = anchor.split(":")
                    self.assertIn("def " + name.split(".")[-1], (ROOT / path).read_text("utf-8"), anchor)
                else:
                    self.assertTrue(callable(resolve(anchor)), anchor)
            for test in component["tests"]:
                self.assertTrue((ROOT / test).is_file(), test)

    def test_claims_need_evidence(self):
        for component in pm.COMPONENTS:
            self.assertIn(component["status"], pm.STATUSES)
            backed = component["status"] != "not_implemented"
            self.assertEqual(bool(component["anchors"]), backed, component["id"])
            self.assertEqual(bool(component["tests"]), backed, component["id"])

    def test_nothing_is_live_and_nothing_is_called_fully_implemented(self):
        summary = pm.platform_map()
        self.assertEqual(summary["live"], 0)
        self.assertEqual(summary["counts"], {"implemented": 0, "partial": 10, "not_implemented": 0})
        self.assertEqual(summary["total"], 10)

    def test_live_components_are_counted(self):
        original = pm.COMPONENTS
        try:
            pm.COMPONENTS = ({**original[0], "live": True},) + original[1:]
            self.assertEqual(pm.platform_map()["live"], 1)
        finally:
            pm.COMPONENTS = original


if __name__ == "__main__":
    unittest.main()
