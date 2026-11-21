# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from random import Random
import unittest

from aegisflow_dr import schema_registry as sr
from aegisflow_dr.analysis import discover_schema
from aegisflow_dr.pipeline import InputRejected, generate_orders


def cols(*pairs):
    return [{"name": n, "type": t} for n, t in pairs]


BASE = cols(("order_id", "integer"), ("customer_id", "integer"), ("order_total", "decimal"))


class ValidationTests(unittest.TestCase):
    def test_valid_columns_are_copied(self):
        result = sr.clean_columns(BASE)
        self.assertEqual(result, BASE)
        self.assertIsNot(result[0], BASE[0])

    def test_rejections(self):
        bad = [None, [], "x", [1], [{"name": "a"}], [{"name": "a", "type": "integer", "x": 1}],
               cols(("a", "float")), [{"name": "a", "type": 3}], [{"name": 3, "type": "text"}],
               cols(("", "text")), cols((" a", "text")), cols(("a ", "text")), cols(("a\nb", "text")),
               cols(("a\x7f", "text")), cols(("x" * 129, "text")), cols(("a", "text"), ("a", "text")),
               [{"name": "c%d" % i, "type": "text"} for i in range(sr.MAX_COLUMNS + 1)]]
        for value in bad:
            with self.assertRaises(InputRejected, msg=repr(value)[:60]):
                sr.clean_columns(value)

    def test_limits_are_inclusive(self):
        sr.clean_columns([{"name": "c%d" % i, "type": "text"} for i in range(sr.MAX_COLUMNS)])
        sr.clean_columns(cols(("x" * 128, "text")))

    def test_hash_depends_on_names_types_and_order(self):
        base = sr.schema_sha256(BASE)
        self.assertEqual(base, sr.schema_sha256(deepcopy(BASE)))
        self.assertNotEqual(base, sr.schema_sha256(BASE[::-1]))
        self.assertNotEqual(base, sr.schema_sha256(cols(("order_id", "integer"), ("customer_id", "integer"), ("order_total", "text"))))
        self.assertNotEqual(base, sr.schema_sha256(cols(("order_id", "integer"), ("customer_id", "integer"), ("total", "decimal"))))

    def test_discovery_output_becomes_columns(self):
        discovery = discover_schema(generate_orders(seed=1, rows=6, fault="clean"))
        self.assertEqual([c["name"] for c in sr.columns_from_discovery(discovery)], ["order_id", "customer_id", "order_total"])


class DiffTests(unittest.TestCase):
    def test_identical(self):
        d = sr.diff_columns(BASE, BASE)
        self.assertEqual(d["status"], "IDENTICAL")
        self.assertFalse(d["reordered"])

    def test_added_is_compatible(self):
        d = sr.diff_columns(BASE, BASE + cols(("note", "text")))
        self.assertEqual((d["status"], d["added"], d["removed"]), ("COMPATIBLE", ["note"], []))

    def test_removed_is_breaking(self):
        d = sr.diff_columns(BASE, BASE[:2])
        self.assertEqual((d["status"], d["removed"]), ("BREAKING", ["order_total"]))

    def test_widening_is_breaking_and_narrowing_is_compatible(self):
        wide = cols(("order_id", "text"), ("customer_id", "decimal"), ("order_total", "decimal"))
        d = sr.diff_columns(BASE, wide)
        self.assertEqual(d["status"], "BREAKING")
        self.assertEqual([(w["name"], w["from"], w["to"]) for w in d["widened"]],
                         [("order_id", "integer", "text"), ("customer_id", "integer", "decimal")])
        back = sr.diff_columns(wide, BASE)
        self.assertEqual(back["status"], "COMPATIBLE")
        self.assertEqual([n["name"] for n in back["narrowed"]], ["order_id", "customer_id"])

    def test_empty_type_is_not_evidence(self):
        d = sr.diff_columns(cols(("a", "empty")), cols(("a", "text")))
        self.assertEqual((d["status"], len(d["uninformative"]), d["widened"]), ("COMPATIBLE", 1, []))
        self.assertEqual(sr.diff_columns(cols(("a", "text")), cols(("a", "empty")))["status"], "COMPATIBLE")

    def test_reorder_is_compatible_but_reported(self):
        d = sr.diff_columns(BASE, [BASE[2], BASE[0], BASE[1]])
        self.assertEqual((d["status"], d["reordered"]), ("COMPATIBLE", True))

    def test_insertion_alone_is_not_a_reorder(self):
        d = sr.diff_columns(BASE, [BASE[0], {"name": "x", "type": "text"}, BASE[1], BASE[2]])
        self.assertFalse(d["reordered"])

    def test_possible_rename_is_a_hint_only(self):
        renamed = cols(("order_id", "integer"), ("customer_id", "integer"), ("total", "decimal"))
        d = sr.diff_columns(BASE, renamed)
        self.assertEqual(d["status"], "BREAKING")
        self.assertEqual(d["possible_renames"], [{"from": "order_total", "to": "total", "basis": "same position and type"}])
        different_type = cols(("order_id", "integer"), ("customer_id", "integer"), ("total", "text"))
        self.assertEqual(sr.diff_columns(BASE, different_type)["possible_renames"], [])
        empties = sr.diff_columns(cols(("a", "empty")), cols(("b", "empty")))
        self.assertEqual(empties["possible_renames"], [])

    def test_properties_over_random_schemas(self):
        rng = Random(7)
        names = ["a", "b", "c", "d", "e", "f"]

        def make():
            picked = rng.sample(names, rng.randint(1, 6))
            return [{"name": n, "type": rng.choice(sr.TYPES)} for n in picked]
        for _ in range(400):
            a, b = make(), make()
            forward, backward = sr.diff_columns(a, b), sr.diff_columns(b, a)
            self.assertEqual(forward["removed"], [n for n in (c["name"] for c in a) if n not in {c["name"] for c in b}])
            self.assertEqual(sorted(forward["added"]), sorted(backward["removed"]))
            self.assertEqual(sorted(w["name"] for w in forward["widened"]), sorted(n["name"] for n in backward["narrowed"]))
            self.assertEqual(forward["reordered"], backward["reordered"])
            self.assertEqual(sr.diff_columns(a, a)["status"], "IDENTICAL")
            self.assertEqual(forward["status"] == "IDENTICAL", a == b)
            if forward["status"] == "BREAKING":
                self.assertTrue(forward["removed"] or forward["widened"])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = sr.SchemaRegistry()

    def test_versions_increase_and_identical_is_idempotent(self):
        first = self.registry.register("orders", BASE)
        again = self.registry.register("orders", deepcopy(BASE))
        self.assertEqual((first["version"], first["created"], first["diff"]), (1, True, None))
        self.assertEqual((again["version"], again["created"]), (1, False))
        changed = self.registry.register("orders", BASE + cols(("note", "text")))
        self.assertEqual((changed["version"], changed["diff"]["status"]), (2, "COMPATIBLE"))
        reverted = self.registry.register("orders", BASE)
        self.assertEqual((reverted["version"], reverted["created"]), (3, True))
        self.assertEqual([v["version"] for v in self.registry.versions("orders")], [1, 2, 3])

    def test_subject_validation_and_limits(self):
        for bad in ("", "-x", "a b", "x" * 65, None, 3, "a/b"):
            with self.assertRaises(InputRejected):
                self.registry.register(bad, BASE)
        self.registry.register("x" * 64, BASE)
        for i in range(sr.MAX_SUBJECTS - 1):
            self.registry.register("s%d" % i, BASE)
        with self.assertRaises(InputRejected):
            self.registry.register("one-too-many", BASE)
        self.registry.register("s0", BASE + cols(("n", "text")))

    def test_version_limit(self):
        for i in range(sr.MAX_VERSIONS):
            self.registry.register("v", cols(("c", "text"), ("n%d" % i, "text")))
        with self.assertRaises(InputRejected):
            self.registry.register("v", cols(("c", "text"), ("other", "text")))

    def test_lookup_errors_and_copies(self):
        with self.assertRaises(InputRejected):
            self.registry.versions("missing")
        self.registry.register("orders", BASE)
        for bad in (0, 2, True, "1", 1.0):
            with self.assertRaises(InputRejected):
                self.registry.get("orders", bad)
        record = self.registry.get("orders")
        record["columns"][0]["name"] = "hacked"
        self.assertEqual(self.registry.get("orders", 1)["columns"][0]["name"], "order_id")
        self.assertEqual(self.registry.subjects(), [{"subject": "orders", "versions": 1, "contract": None}])

    def test_diff_between_versions(self):
        self.registry.register("orders", BASE)
        self.registry.register("orders", BASE[:2])
        self.assertEqual(self.registry.diff("orders", 1, 2)["status"], "BREAKING")
        self.assertEqual(self.registry.diff("orders", 2, 1)["status"], "COMPATIBLE")

    def test_contract_and_drift(self):
        self.registry.register("orders", BASE)
        self.assertEqual(self.registry.drift("orders", BASE)["status"], "NO_CONTRACT")
        self.assertEqual(self.registry.set_contract("orders", 1), 1)
        self.assertEqual(self.registry.drift("orders", BASE)["status"], "CONFORMS")
        extra = self.registry.drift("orders", BASE + cols(("note", "text")))
        self.assertEqual((extra["status"], extra["contract_version"]), ("DRIFT_COMPATIBLE", 1))
        self.assertEqual(self.registry.drift("orders", BASE[:1])["status"], "DRIFT_BREAKING")
        with self.assertRaises(InputRejected):
            self.registry.set_contract("orders", 5)
        with self.assertRaises(InputRejected):
            self.registry.drift("nope", BASE)

    def test_set_contract_without_version_pins_latest(self):
        self.registry.register("orders", BASE)
        self.registry.register("orders", BASE[:2])
        self.assertEqual(self.registry.set_contract("orders"), 2)


class PersistenceTests(unittest.TestCase):
    def make(self):
        registry = sr.SchemaRegistry()
        registry.register("orders", BASE)
        registry.register("orders", BASE + cols(("note", "text")))
        registry.register("other", BASE[:1])
        registry.set_contract("orders", 1)
        return registry

    def test_round_trip(self):
        registry = self.make()
        data = registry.dump()
        self.assertEqual(sr.SchemaRegistry.load(deepcopy(data)).dump(), data)
        data["subjects"]["orders"]["versions"].clear()
        self.assertEqual(len(registry.dump()["subjects"]["orders"]["versions"]), 2)

    def test_every_single_field_edit_is_rejected(self):
        data = self.make().dump()
        paths = []
        for name, entry in data["subjects"].items():
            for index, version in enumerate(entry["versions"]):
                for field in ("schema_sha256", "parent_sha256", "record_sha256"):
                    paths.append((name, index, field))
        for name, index, field in paths:
            forged = deepcopy(data)
            value = forged["subjects"][name]["versions"][index][field]
            forged["subjects"][name]["versions"][index][field] = "0" * 64 if value != "0" * 64 else "1" * 64
            with self.assertRaises(InputRejected, msg=(name, index, field)):
                sr.SchemaRegistry.load(forged)
        edited = deepcopy(data)
        edited["subjects"]["orders"]["versions"][0]["columns"][0]["type"] = "text"
        with self.assertRaises(InputRejected):
            sr.SchemaRegistry.load(edited)

    def test_structural_tampering_is_rejected(self):
        good = self.make().dump()

        def mutate(change):
            data = deepcopy(good)
            change(data)
            return data
        cases = [
            lambda d: d.update(format_version="2"), lambda d: d.update(extra=1), lambda d: d.update(subjects=[]),
            lambda d: d["subjects"].update({"bad name": d["subjects"]["other"]}),
            lambda d: d["subjects"]["orders"].update(extra=1), lambda d: d["subjects"]["orders"].update(versions={}),
            lambda d: d["subjects"]["orders"].update(versions=[]),
            lambda d: d["subjects"]["orders"]["versions"].append(deepcopy(d["subjects"]["orders"]["versions"][0])),
            lambda d: d["subjects"]["orders"]["versions"][0].update(extra=1),
            lambda d: d["subjects"]["orders"]["versions"][0].update(version=True),
            lambda d: d["subjects"]["orders"]["versions"][1].update(version=1),
            lambda d: d["subjects"]["orders"]["versions"].reverse(),
            lambda d: d["subjects"]["orders"].update(contract=0), lambda d: d["subjects"]["orders"].update(contract=3),
            lambda d: d["subjects"]["orders"].update(contract="1"), lambda d: d["subjects"]["orders"].update(contract=True),
            lambda d: d["subjects"]["orders"]["versions"][0].update(columns=[]),
        ]
        for index, change in enumerate(cases):
            with self.assertRaises(InputRejected, msg="case %d" % index):
                sr.SchemaRegistry.load(mutate(change))
        with self.assertRaises(InputRejected):
            sr.SchemaRegistry.load(None)

    def test_repeated_adjacent_version_and_limits_are_rejected(self):
        registry = sr.SchemaRegistry()
        registry.register("s", BASE)
        data = registry.dump()
        record = data["subjects"]["s"]["versions"][0]
        second = {**deepcopy(record), "version": 2, "parent_sha256": record["record_sha256"]}
        second["record_sha256"] = sr._record_sha("s", 2, second["schema_sha256"], record["record_sha256"])
        data["subjects"]["s"]["versions"].append(second)
        with self.assertRaises(InputRejected):
            sr.SchemaRegistry.load(data)
        many = {"format_version": "1", "subjects": {"s%d" % i: {} for i in range(sr.MAX_SUBJECTS + 1)}}
        with self.assertRaises(InputRejected):
            sr.SchemaRegistry.load(many)
        long = sr.SchemaRegistry()
        for i in range(sr.MAX_VERSIONS):
            long.register("v", cols(("c", "text"), ("n%d" % i, "text")))
        dumped = long.dump()
        self.assertEqual(len(sr.SchemaRegistry.load(dumped).versions("v")), sr.MAX_VERSIONS)
        dumped["subjects"]["v"]["versions"].append(dumped["subjects"]["v"]["versions"][0])
        with self.assertRaises(InputRejected):
            sr.SchemaRegistry.load(dumped)


if __name__ == "__main__":
    unittest.main()
