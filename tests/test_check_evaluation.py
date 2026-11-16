# SPDX-License-Identifier: Apache-2.0
import csv
import io
import json
import re
import unittest
from dataclasses import replace
from pathlib import Path

from aegisflow_dr import check_evaluation as ev


def rows_of(payload):
    return list(csv.reader(io.StringIO(payload.decode(), newline="")))


def mutant(rule):
    """A deliberately wrong detector: rule(header, rows) -> set of (check, column, record)."""
    def run(payload):
        rows = rows_of(payload)
        return rule(rows[0], rows[1:])
    return run


def correct_row_rules(header, rows, *, strip=True, fold=False, blank_duplicates=False, amount=r"[0-9]{1,12}(?:\.[0-9]{1,2})?"):
    found, seen = set(), {}
    index = {name: i for i, name in enumerate(header)}
    for number, row in enumerate(rows, 1):
        for column in ev.COLUMNS:
            if column in index:
                value = row[index[column]]
                if not (value.strip() if strip else value):
                    found.add(("not_null", column, number))
        if "order_id" in index:
            identifier = row[index["order_id"]].strip()
            identifier = identifier.lower() if fold else identifier
            if identifier or blank_duplicates:
                if identifier in seen:
                    found |= {("unique", "order_id", seen[identifier]), ("unique", "order_id", number)}
                else:
                    seen[identifier] = number
        if "order_total" in index:
            raw = row[index["order_total"]].strip()
            if raw and not re.fullmatch(amount, raw):
                found.add(("amount_format", "order_total", number))
    return found


ROW_CHECKS = frozenset({"not_null", "unique", "amount_format"})


def run(rule, split="development"):
    cases = [c for c in ev.build_corpus() if c.split == split]
    return ev.score(cases, mutant(rule), ROW_CHECKS)


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = ev.build_corpus()

    def test_corpus_is_reproducible_and_digest_tracks_every_change(self):
        again = ev.build_corpus()
        self.assertEqual(ev.corpus_digest(self.cases), ev.corpus_digest(again))
        changed = [replace(self.cases[0], truth={("not_null", "order_id", 1): "x"}), *self.cases[1:]]
        self.assertNotEqual(ev.corpus_digest(changed), ev.corpus_digest(self.cases))
        changed = [replace(self.cases[0], payload=self.cases[0].payload + b" "), *self.cases[1:]]
        self.assertNotEqual(ev.corpus_digest(changed), ev.corpus_digest(self.cases))

    def test_every_split_holds_every_injected_pattern(self):
        patterns = {c.variant for c in self.cases}
        self.assertEqual(len(patterns), 28)
        for split in ev.SPLITS:
            self.assertEqual({c.variant for c in self.cases if c.split == split}, patterns, split)

    def test_groups_never_straddle_splits_and_leakage_is_clean(self):
        self.assertTrue(ev.check_leakage(self.cases)["clean"])
        self.assertEqual({c.split for c in self.cases if c.group == 0}, {ev.split_of(0)})

    def test_leakage_checker_detects_planted_leaks(self):
        other = next(s for s in ev.SPLITS if s != self.cases[0].split)
        for planted in (replace(self.cases[0], split=other),
                        replace(self.cases[0], case_id="copy", group=999, split=other)):
            report = ev.check_leakage([*self.cases, planted])
            self.assertFalse(report["clean"])
        report = ev.check_leakage([*self.cases, replace(self.cases[0], case_id="copy", group=999, split=other)])
        self.assertEqual((report["groups_in_several_splits"], report["payloads_in_several_splits"]), (0, 1))
        self.assertGreater(report["records_in_several_splits"], 0)

    def test_truth_is_set_by_construction(self):
        by_variant = {c.variant: c for c in self.cases if c.group == 0}
        self.assertEqual(by_variant["clean"].truth, {})
        self.assertEqual(by_variant["case_differs_not_duplicate"].truth, {})
        self.assertEqual({k[0] for k in by_variant["valid_amount_padded"].truth}, set())
        self.assertEqual({k[0] for k in by_variant["blank_ids_not_duplicates"].truth}, {"not_null"})
        self.assertEqual(len(by_variant["duplicate_triple"].truth), 3)
        self.assertEqual(sorted(k[0] for k in by_variant["multi_fault"].truth),
                         ["amount_format", "not_null", "not_null", "unique", "unique"])
        schema = by_variant["schema_renamed_column"].truth
        self.assertEqual(set(schema), {("missing_column", "order_total", 0), ("unexpected_column", "total_amount", 0)})

    def test_split_proportions_are_roughly_sixty_twenty_twenty(self):
        groups = {s: len({c.group for c in self.cases if c.split == s}) for s in ev.SPLITS}
        self.assertEqual(sum(groups.values()), ev.GROUPS)
        self.assertTrue(all(count >= 4 for count in groups.values()), groups)


class ShippedChecksTests(unittest.TestCase):
    def test_shipped_detectors_match_injected_truth_on_every_split(self):
        report = ev.evaluate(include_heldout=True)
        for name, splits in report["results"].items():
            for split, result in splits.items():
                with self.subTest(detector=name, split=split):
                    self.assertEqual(result["exact_match_cases"]["value"], 1.0)
                    self.assertEqual((result["overall"]["false_positives"], result["overall"]["false_negatives"]), (0, 0))
                    self.assertEqual(result["missed_by_category"], {})
                    self.assertGreater(result["overall"]["true_positives"], 0)

    def test_heldout_is_scored_only_on_request(self):
        default = ev.evaluate()
        self.assertFalse(default["heldout_evaluated"])
        self.assertEqual(set(default["results"]["diagnose_csv"]), {"development", "validation"})
        self.assertEqual(set(ev.evaluate(include_heldout=True)["results"]["diagnose_csv"]), set(ev.SPLITS))

    def test_record_detector_does_not_claim_schema_checks(self):
        self.assertEqual(set(ev.evaluate()["results"]["record_issues"]["validation"]["per_check"]), ROW_CHECKS)


class SensitivityTests(unittest.TestCase):
    """The corpus must catch each deliberately broken detector, or a perfect score means nothing."""

    def test_reference_rules_are_perfect(self):
        result = run(lambda h, r: correct_row_rules(h, r))
        self.assertEqual((result["overall"]["false_positives"], result["overall"]["false_negatives"]), (0, 0))

    def test_missing_whitespace_trim_is_caught(self):
        result = run(lambda h, r: correct_row_rules(h, r, strip=False))
        self.assertGreater(result["per_check"]["not_null"]["false_negatives"], 0)
        self.assertTrue(any(k.endswith("_spaces") for k in result["missed_by_category"]))
        self.assertLess(result["per_check"]["not_null"]["recall"]["value"], 1.0)

    def test_case_insensitive_identifiers_are_caught(self):
        result = run(lambda h, r: correct_row_rules(h, r, fold=True))
        self.assertGreater(result["per_check"]["unique"]["false_positives"], 0)
        self.assertIn("case_differs_not_duplicate", result["spurious_by_variant"])

    def test_blank_identifiers_treated_as_duplicates_are_caught(self):
        result = run(lambda h, r: correct_row_rules(h, r, blank_duplicates=True))
        self.assertIn("blank_ids_not_duplicates", result["spurious_by_variant"])

    def test_accepting_negative_amounts_is_caught(self):
        result = run(lambda h, r: correct_row_rules(h, r, amount=r"-?[0-9]{1,12}(?:\.[0-9]{1,2})?"))
        self.assertEqual(result["missed_by_category"], {"amount_negative": result["per_check"]["amount_format"]["false_negatives"]})

    def test_rejecting_valid_edge_amounts_is_caught(self):
        result = run(lambda h, r: correct_row_rules(h, r, amount=r"[1-9][0-9]{0,11}\.[0-9]{2}"))
        self.assertTrue({"valid_amount_zero", "valid_amount_integer"} <= set(result["spurious_by_variant"]))

    def test_detector_that_finds_nothing_has_zero_recall_and_undefined_precision(self):
        result = run(lambda h, r: set())
        self.assertEqual(result["overall"]["recall"]["value"], 0.0)
        self.assertIsNone(result["overall"]["precision"]["value"])
        self.assertIsNone(result["overall"]["precision"]["interval_95"])
        self.assertEqual(result["exact_match_cases"]["numerator"] > 0, True)  # clean cases still match
        self.assertEqual(len(result["error_examples"]), 20)


class StatisticsAndReportTests(unittest.TestCase):
    def test_wilson_interval(self):
        self.assertIsNone(ev.wilson(0, 0))
        low, high = ev.wilson(10, 10)
        self.assertAlmostEqual(low, 0.7225, places=3)
        self.assertEqual(high, 1.0)
        low, high = ev.wilson(0, 10)
        self.assertEqual(low, 0.0)
        self.assertAlmostEqual(high, 0.2775, places=3)

    def test_report_is_json_serialisable_and_markdown_is_labelled(self):
        report = json.loads(ev.main([]))
        self.assertEqual(report["corpus"]["per_split"]["heldout"]["cases"] > 0, True)
        markdown = ev.main(["--markdown"])
        self.assertIn("Held-out split scored: no", markdown)
        self.assertIn("Not real data", markdown)
        self.assertIn("Held-out split scored: yes", ev.main(["--markdown", "--include-heldout"]))

    def test_committed_report_matches_the_code(self):
        committed = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "latest.md"
        self.assertEqual(committed.read_text("utf-8"), ev.main(["--markdown", "--include-heldout"]) + "\n")

    def test_markdown_shows_undefined_rates_and_leaks(self):
        cases = ev.build_corpus(groups=6)
        report = ev.evaluate(cases=[*cases, replace(cases[0], case_id="dup", split="validation" if cases[0].split != "validation" else "development")],
                             detectors={"nothing": (mutant(lambda h, r: set()), ROW_CHECKS)})
        markdown = ev.render_markdown(report)
        self.assertIn("n/a", markdown)
        self.assertIn("FOUND", markdown)
        self.assertIn("Missed by category: {", markdown)


if __name__ == "__main__":
    unittest.main()
