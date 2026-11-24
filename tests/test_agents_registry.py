# SPDX-License-Identifier: Apache-2.0
import dataclasses
import json
import re
import unittest
from importlib.resources import files
from pathlib import Path

from aegisflow_dr.agents import registry
from aegisflow_dr.agents.registry import KINDS, LAYERS, ROLES, TOOLS, RoleSpec, role
from aegisflow_dr.pipeline import InputRejected

CATALOG = json.loads(files("aegisflow_dr").joinpath("data", "agent-catalog.json").read_text(encoding="utf-8"))
# Binding role table (docs/superpowers/specs/2026-11-24-agent-runtime-roles.md), transcribed independently here.
EXPECTED_KIND = {
    "A01": "control", "A02": "hybrid", "A03": "control", "A04": "control", "A05": "control", "A06": "control",
    **{"A%02d" % n: "rule" for n in range(7, 22)},
    "A22": "hybrid", "A23": "llm", "A24": "rule", "A25": "rule", "A26": "control", "A27": "control", "A28": "rule",
    "A29": "llm", "A30": "llm", "A31": "rule", "A32": "rule",
    "A33": "control", "A34": "control", "A35": "control", "A36": "control",
}
LAYER_RANGES = (("orchestration", 1, 6), ("specialists", 7, 22), ("reasoning", 23, 28), ("remediation", 29, 32),
                ("governance", 33, 36))
EXECUTOR_REF = re.compile(r"aegisflow_dr\.agents\.executors\.([a-z_]+):([a-z][a-z0-9_]*)\Z")


class Registry(unittest.TestCase):
    def test_thirty_six_unique_roles_in_catalog_order(self):
        self.assertEqual(len(ROLES), 36)
        self.assertEqual([spec.agent_id for spec in ROLES], ["A%02d" % n for n in range(1, 37)])
        self.assertEqual([spec.agent_id for spec in ROLES], [entry["agent_id"] for entry in CATALOG])
        self.assertEqual(len({spec.name for spec in ROLES}), 36)

    def test_names_and_priorities_come_from_the_catalog(self):
        for spec, entry in zip(ROLES, CATALOG):
            self.assertEqual("%s · %s" % (spec.name, spec.priority), entry["name_priority"])
            self.assertIn(spec.priority, ("P0", "P1", "P2"))
        self.assertEqual(role("A27").name, "Evidence Verification Agent")
        self.assertEqual(role("A16").priority, "P2")

    def test_docs_copy_of_the_catalog_matches_the_packaged_one(self):
        docs = Path(__file__).resolve().parents[1] / "docs" / "agent-catalog.json"
        self.assertEqual(json.loads(docs.read_text(encoding="utf-8")), CATALOG)

    def test_kind_and_layer_follow_the_binding_table(self):
        self.assertEqual(KINDS, ("control", "rule", "llm", "hybrid"))
        self.assertEqual(LAYERS, tuple(name for name, _, _ in LAYER_RANGES))
        for spec in ROLES:
            number = int(spec.agent_id[1:])
            layer = next(name for name, low, high in LAYER_RANGES if low <= number <= high)
            with self.subTest(spec.agent_id):
                self.assertEqual(spec.kind, EXPECTED_KIND[spec.agent_id])
                self.assertEqual(spec.layer, layer)

    def test_tools_are_bounded_and_model_access_matches_kind(self):
        for spec in ROLES:
            with self.subTest(spec.agent_id):
                self.assertIs(type(spec.allowed_tools), tuple)
                self.assertTrue(set(spec.allowed_tools) <= TOOLS)
                self.assertEqual(len(set(spec.allowed_tools)), len(spec.allowed_tools))
                self.assertEqual("local_llm" in spec.allowed_tools, spec.kind in ("llm", "hybrid"))
        # Roles whose inputs are never connected here get no tools at all.
        for agent_id in ("A12", "A16", "A32"):
            self.assertEqual(role(agent_id).allowed_tools, ())
        self.assertEqual(role("A13").allowed_tools, ("query_lineage",))
        self.assertEqual(role("A22").allowed_tools, ("knowledge_retrieve", "local_llm"))

    def test_executor_refs_are_well_formed_and_not_resolved_yet(self):
        # Executors land in the next batch; this checks only the "module:function" format and the layer module.
        functions = set()
        for spec in ROLES:
            with self.subTest(spec.agent_id):
                match = EXECUTOR_REF.fullmatch(spec.executor_ref)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), spec.layer)
                functions.add(match.group(2))
        self.assertEqual(len(functions), 36)

    def test_trigger_summaries_are_short_and_present(self):
        for spec in ROLES:
            self.assertTrue(0 < len(spec.trigger_summary) <= 120, spec.agent_id)
        self.assertEqual(role("A12").trigger_summary, "only if logs are provided (none are connected)")

    def test_specs_are_frozen(self):
        self.assertTrue(dataclasses.is_dataclass(RoleSpec))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            role("A01").kind = "llm"

    def test_role_lookup_rejects_unknown_ids(self):
        self.assertIs(role("A01"), ROLES[0])
        for value in ("A37", "A00", "a01", "", None, 1):
            with self.subTest(value=value), self.assertRaisesRegex(InputRejected, "^Unknown agent role$"):
                role(value)

    def test_build_rejects_a_catalog_that_disagrees_with_the_table(self):
        entries = [dict(entry) for entry in CATALOG]
        self.assertEqual(registry._build(entries), ROLES)
        broken = [dict(entry) for entry in CATALOG]
        broken[3]["agent_id"] = "A99"
        no_priority = [dict(entry) for entry in CATALOG]
        no_priority[0]["name_priority"] = "Global Supervisor"
        for value in (entries[:-1], broken, no_priority):
            with self.subTest(), self.assertRaisesRegex(InputRejected, "^Agent catalog does not match the role table$"):
                registry._build(value)


if __name__ == "__main__":
    unittest.main()
