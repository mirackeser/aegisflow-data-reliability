# SPDX-License-Identifier: Apache-2.0
import unittest

from random import Random

from aegisflow_dr.analysis import _parse, analyze_csv, apply_mapping, discover_schema, record_issues
from aegisflow_dr.pipeline import diagnose_csv
from aegisflow_dr.pipeline import InputRejected, generate_orders

BAD = (b"order_id,customer_id,order_total\nA1000,C1,10.00\nA1000,C1,10.00\nA3,C3,abc\n"
       b"A4,C1,\nA5,C2,5.50\nA6,,7.00\nA6,C9,7.50\n")
DRIFT = b"order_id,customer_id,total_amount\nA1,C1,10.00\nA2,C2,5.5\n"


class DiscoveryTests(unittest.TestCase):
    def test_clean_file_is_compatible_with_exact_profiles(self):
        found = discover_schema(generate_orders())
        self.assertEqual(found["status"], "COMPATIBLE")
        self.assertEqual(found["row_count"], 24)
        types = {c["name"]: c["inferred_type"] for c in found["columns"]}
        self.assertEqual(types, {"order_id": "text", "customer_id": "text", "order_total": "decimal"})
        self.assertTrue(all(c["status"] == "matched" for c in found["contract"]))

    def test_candidate_is_suggested_but_never_applied(self):
        found = discover_schema(DRIFT)
        self.assertEqual(found["status"], "MAPPING_NEEDED")
        total = next(c for c in found["contract"] if c["name"] == "order_total")
        self.assertEqual(total["candidate"]["column"], "total_amount")
        self.assertEqual(analyze_csv(DRIFT)["status"], "FAIL")

    def test_mostly_numeric_column_with_a_bad_value_is_still_offered_and_the_bad_value_surfaces_after_mapping(self):
        payload = b"order_id,customer_id,total_amount\nA1,C1,10.00\nA2,C2,5.50\nA3,C3,abc\n"
        found = discover_schema(payload)
        self.assertEqual(found["status"], "MAPPING_NEEDED")
        mapped = analyze_csv(apply_mapping(payload, {"total_amount": "order_total"}))
        self.assertEqual(mapped["heatmap"], [{"column": "order_total", "check": "amount_format", "records": 1}])

    def test_unrelated_or_text_columns_are_not_candidates(self):
        found = discover_schema(b"order_id,customer_id,notes\nA1,C1,hello\n")
        self.assertEqual(found["status"], "INCOMPATIBLE")
        self.assertIsNone(next(c for c in found["contract"] if c["name"] == "order_total")["candidate"])
        self.assertEqual(found["unexpected"], ["notes"])

    def test_extra_columns_are_not_reported_compatible(self):
        found = discover_schema(b"order_id,customer_id,order_total,note\nA1,C1,1.00,x\n")
        self.assertEqual(found["status"], "EXTRA_COLUMNS")

    def test_malformed_input_is_rejected_with_the_diagnostic_errors(self):
        for payload in (b"", b"a,a\n1,2\n", b"\xff\xfe", b"order_id\n1,2\n", b"x" * 1_000_001):
            with self.assertRaises(InputRejected):
                discover_schema(payload)


class CandidateAndMaskingTests(unittest.TestCase):
    def test_column_profiles_cover_empty_integer_and_text_columns(self):
        found = discover_schema(b"order_id,customer_id,order_total,blank,count\nA1,C1,1.00,,3\nA2,C2,2.00, ,4\n")
        types = {c["name"]: c["inferred_type"] for c in found["columns"]}
        self.assertEqual((types["blank"], types["count"], types["order_id"]), ("empty", "integer", "text"))

    def test_a_blank_column_is_never_a_candidate_for_the_amount(self):
        found = discover_schema(b"order_id,customer_id,amount\nA1,C1,\n")
        self.assertEqual(found["status"], "INCOMPATIBLE")

    def test_one_column_cannot_fill_two_contract_slots(self):
        found = discover_schema(b"order_id,customer,total\nA1,C1,5.00\n")
        by_name = {c["name"]: c for c in found["contract"]}
        self.assertEqual(by_name["customer_id"]["candidate"]["column"], "customer")
        self.assertEqual(by_name["order_total"]["candidate"]["column"], "total")

    def test_similar_names_are_candidates_but_dissimilar_ones_and_weaker_ones_are_not(self):
        found = discover_schema(b"order_id,customer_id,amount,order_totals,zzz\nA1,C1,1.00,2.00,3.00\n")
        total = next(c for c in found["contract"] if c["name"] == "order_total")["candidate"]
        self.assertEqual((total["column"], total["basis"]), ("amount", "alias"))
        similar = discover_schema(b"order_id,customer_id,order_totals,zzz\nA1,C1,2.00,3.00\n")
        match = next(c for c in similar["contract"] if c["name"] == "order_total")["candidate"]
        self.assertEqual((match["column"], match["basis"]), ("order_totals", "similar"))
        self.assertIn("zzz", similar["unexpected"])

    def test_identifiers_are_masked_by_length_and_blanks_stay_blank(self):
        result = analyze_csv(b"order_id,customer_id,order_total\nAB,,1.00\nABCDE,,2.00\nORDER-12345,,3.00\n,C1,4.00\n")
        masked = {r["record"]: r["order_id_masked"] for r in result["affected_records"]}
        self.assertEqual(masked, {1: "A•••", 2: "A•••E", 3: "OR•••45", 4: ""})
        self.assertNotIn("ORDER-12345", str(result))


class MappingTests(unittest.TestCase):
    def test_explicit_mapping_renames_only_the_header(self):
        mapped = apply_mapping(DRIFT, {"total_amount": "order_total"})
        self.assertEqual(mapped.splitlines()[0], b"order_id,customer_id,order_total")
        self.assertEqual(mapped.splitlines()[1:], DRIFT.splitlines()[1:])
        self.assertEqual(analyze_csv(mapped)["status"], "PASS")

    def test_invalid_mappings_are_rejected(self):
        for mapping in ({}, {"total_amount": "nonsense"}, {"missing": "order_total"},
                        {"order_id": "order_total"}, {"total_amount": "order_total", "x": "order_total"},
                        {"total_amount": 3}, [("a", "b")]):
            with self.assertRaises(InputRejected, msg=str(mapping)):
                apply_mapping(DRIFT, mapping)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.result = analyze_csv(BAD)

    def test_dimensions_use_exact_numerators_and_denominators(self):
        d = self.result["dimensions"]
        self.assertEqual((d["completeness"]["passed"], d["completeness"]["total"]), (19, 21))
        self.assertEqual((d["uniqueness"]["passed"], d["uniqueness"]["total"]), (5, 7))
        self.assertEqual((d["validity"]["passed"], d["validity"]["total"]), (5, 6))
        self.assertEqual((d["record_health"]["passed"], d["record_health"]["total"]), (1, 7))

    def test_money_is_exact_decimal_and_double_count_exposure_is_repeats_only(self):
        impact = self.result["impact"]
        self.assertEqual(impact["valid_amount_total"], "40.00")
        self.assertEqual(impact["valid_amount_in_affected_records"], "34.50")
        self.assertEqual(impact["double_count_exposure"], "17.50")
        self.assertEqual((impact["repeat_records"], impact["records_without_amount"]), (2, 1))

    def test_duplicate_patterns_are_observed_not_causal_and_ids_are_masked(self):
        identical, conflicting = self.result["duplicate_groups"]
        self.assertEqual(identical["pattern"], "IDENTICAL_REPEAT")
        self.assertEqual(conflicting["pattern"], "CONFLICTING_VALUES")
        self.assertEqual(conflicting["differing_columns"], ["customer_id", "order_total"])
        self.assertNotIn("A1000", str(self.result))
        self.assertNotIn("C9", str(self.result))

    def test_listed_records_name_the_failed_check_and_column(self):
        listed = {r["record"]: r for r in self.result["affected_records"]}
        self.assertEqual(listed[3]["issues"], ["amount_format:order_total"])
        self.assertEqual(listed[3]["amount_state"], "invalid")
        self.assertEqual(listed[4]["issues"], ["not_null:order_total"])
        self.assertEqual(listed[6]["issues"], ["not_null:customer_id", "unique:order_id"])
        self.assertEqual([r["record"] for r in self.result["affected_records"]], [1, 2, 3, 4, 6, 7])

    def test_clean_file_has_no_findings_actions_or_blocked_lineage(self):
        clean = analyze_csv(generate_orders())
        self.assertEqual(clean["status"], "PASS")
        self.assertEqual(clean["actions"], [])
        self.assertEqual(clean["impact"]["affected_records"], 0)
        self.assertFalse(clean["downstream"]["blocked_by_source"])
        self.assertEqual(sum(b["count"] for b in clean["amount_histogram"]), 24)

    def test_missing_amount_column_is_reported_without_inventing_amounts(self):
        result = analyze_csv(b"order_id,customer_id\nA1,\nA2,C2\n")
        self.assertEqual(result["affected_records"][0]["amount_state"], "not_available")
        self.assertEqual(result["dimensions"]["validity"]["total"], 0)
        self.assertIsNone(result["dimensions"]["validity"]["ratio"])
        self.assertEqual(result["amount_histogram"], [])
        self.assertEqual(result["actions"][0]["code"], "restore_column")

    def test_unexpected_column_alone_proposes_a_schema_review(self):
        result = analyze_csv(b"order_id,customer_id,order_total,note\nA1,C1,1.00,x\n")
        self.assertEqual([a["code"] for a in result["actions"]], ["review_extra_columns", "reinspect"])

    def test_records_without_identifier_are_not_grouped_as_duplicates(self):
        result = analyze_csv(b"order_id,customer_id,order_total\n,C1,1.00\n,C2,2.00\n")
        self.assertEqual(result["duplicate_groups"], [])
        self.assertEqual(result["impact"]["repeat_records"], 0)
        self.assertEqual(result["dimensions"]["uniqueness"]["total"], 0)

    def test_failed_source_blocks_declared_downstream(self):
        down = self.result["downstream"]
        self.assertTrue(down["blocked_by_source"])
        self.assertEqual(down["potential"], ["staging_orders", "customer_sales", "sales_dashboard"])
        self.assertEqual(down["lineage_kind"], "declared_dataset_dag")

    def test_actions_are_read_only_and_ordered_schema_first(self):
        drift = analyze_csv(DRIFT)["actions"]
        self.assertEqual(drift[0]["code"], "map_column")
        self.assertEqual(drift[0]["candidate"], "total_amount")
        for action in drift + self.result["actions"]:
            self.assertFalse(action["applies_changes"])
            self.assertEqual(action["status"], "proposed")
        self.assertEqual(len({a["id"] for a in self.result["actions"]}), len(self.result["actions"]))

    def test_listing_is_bounded_but_impact_is_not_capped_by_the_finding_limit(self):
        rows = "".join(f"O{i},C1,\n" for i in range(300))
        big = analyze_csv(("order_id,customer_id,order_total\n" + rows).encode())
        self.assertEqual(len(big["affected_records"]), 200)
        self.assertTrue(big["affected_records_truncated"])
        self.assertTrue(big["findings_truncated"])
        self.assertEqual(big["impact"]["affected_records"], 300)
        self.assertEqual(big["impact"]["records_without_amount"], 300)

    def test_record_rules_match_the_diagnostic_engine_on_random_inputs(self):
        rng = Random(7)
        cells = ["", "1.00", "abc", "12.345", "7", " ", "9.5"]
        ids = ["A", "B", "C", "", "A"]
        for _ in range(60):
            lines = ["order_id,customer_id,order_total"]
            for _ in range(rng.randrange(1, 12)):
                lines.append(f"{rng.choice(ids)},{rng.choice(['C1', ''])},{rng.choice(cells)}")
            payload = "\n".join(lines).encode()
            header, rows = _parse(payload)
            issues, _ = record_issues(header, rows)
            expected = {}
            for finding in diagnose_csv(payload).findings:
                for number in finding.record_numbers:
                    expected.setdefault(number, set()).add(finding.check)
            self.assertEqual(issues, expected, payload)


if __name__ == "__main__":
    unittest.main()
