# SPDX-License-Identifier: Apache-2.0
"""Tests of the synthetic baseline-comparison evaluation; they score development and validation only."""
from datetime import datetime, timedelta
import statistics
import unittest
from unittest import mock

from aegisflow_dr import baseline, baseline_eval as be

LARGE_KINDS = ("mean_shift_large", "unit_change", "sampling_slow", "sampling_fast", "volume_drop", "volume_spike", "stale",
               "null_increase")


def cells(payload):
    return [line.split(",") for line in payload.decode().strip().split("\n")]


def development_group():
    return next(g for g in range(be.GROUPS) if be.split_of(g) == "development")


class SplitTests(unittest.TestCase):
    def test_split_assignment_is_stable_and_complete(self):
        names = [be.split_of(g) for g in range(be.GROUPS)]
        self.assertEqual(names, [be.split_of(g) for g in range(be.GROUPS)])
        self.assertTrue(set(names) <= set(be.SPLITS))
        self.assertTrue(all(names.count(name) for name in be.SPLITS))
        self.assertEqual({name: names.count(name) for name in be.SPLITS}, {"development": 37, "validation": 14, "heldout": 9})
        self.assertEqual([be.split_of(g) for g in (0, 1, 6, 7)], ["validation", "development", "validation", "heldout"])
        self.assertEqual(be.GROUPS, 60)
        self.assertEqual(be.VERSION, "1")
        self.assertEqual(be.SHIFTS, (0.25, 0.5, 0.75, 1.0, 1.5))
        self.assertEqual(be.VARIANTS, ("clean", "clean_partial_cycle", "clean_jitter", "clean_recent_lag", "mean_shift_large",
                                       "mean_shift_small", "scale_change", "unit_change", "sampling_slow", "sampling_fast",
                                       "volume_drop", "volume_spike", "stale", "null_increase"))


class GenerationTests(unittest.TestCase):
    def test_generation_is_deterministic_and_variants_share_references(self):
        group = development_group()
        self.assertEqual(be.generate(group, "clean_jitter"), be.generate(group, "clean_jitter"))
        references = be.generate(group, "clean")[0]
        self.assertEqual(len(references), 3)
        for variant in be.VARIANTS:
            self.assertEqual(be.generate(group, variant)[0], references, variant)
        self.assertNotEqual(be.generate(group + 1, "clean")[0], references)

    def test_unknown_variant_is_refused(self):
        with self.assertRaises(ValueError):
            be.generate(0, "nonsense")

    def test_variant_mechanics(self):
        group = development_group()

        def table(variant):
            references, current, as_of, truth = be.generate(group, variant)
            rows = cells(current)
            self.assertEqual(rows[0], ["ts", "temp_c", "pressure_kpa", "flow_lpm"])
            return rows[1:], datetime.fromisoformat(as_of), truth

        references = [cells(r)[1:] for r in be.generate(group, "clean")[0]]
        self.assertEqual([len(r) for r in references], [400, 400, 400])
        self.assertEqual(references[0][0][0], "2026-01-01T00:00:00")
        self.assertEqual(references[2][-1][0], (datetime(2026, 1, 1) + timedelta(seconds=60 * 1199)).isoformat())
        clean, clean_as_of, truth = table("clean")
        self.assertEqual(truth, set())
        self.assertEqual(clean[0][0], (datetime(2026, 1, 1) + timedelta(seconds=60 * 1200)).isoformat())
        self.assertEqual(len(clean), 400)
        latest = datetime.fromisoformat(clean[-1][0])
        self.assertEqual(clean_as_of - latest, timedelta(seconds=60))

        rows, _, truth = table("clean_partial_cycle")
        self.assertEqual((rows, truth), (clean[:350], set()))
        rows, _, truth = table("volume_drop")
        self.assertEqual((rows, truth), (clean[:160], {("volume_change", None)}))
        rows, _, truth = table("volume_spike")
        self.assertEqual((len(rows), rows[:400], truth), (1000, clean, {("volume_change", None)}))

        for variant, step in (("sampling_slow", 120), ("sampling_fast", 30)):
            rows, as_of, truth = table(variant)
            stamps = [datetime.fromisoformat(r[0]) for r in rows]
            self.assertEqual(len(rows), 400)
            self.assertEqual(stamps[0], datetime.fromisoformat(clean[0][0]))
            self.assertEqual({(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])}, {step})
            self.assertEqual([r[1:] for r in rows], [r[1:] for r in clean])
            self.assertEqual(as_of - stamps[-1], timedelta(seconds=60))
            self.assertEqual(truth, {("sampling_interval_change", "ts")})

        rows, as_of, truth = table("clean_jitter")
        moves = [(datetime.fromisoformat(r[0]) - datetime.fromisoformat(c[0])).total_seconds() for r, c in zip(rows, clean)]
        self.assertTrue(all(-10 <= m <= 10 and m == int(m) for m in moves))
        self.assertGreater(len(set(moves)), 5)
        stamps = [datetime.fromisoformat(r[0]) for r in rows]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual([r[1:] for r in rows], [r[1:] for r in clean])
        self.assertEqual((as_of - max(stamps), truth), (timedelta(seconds=60), set()))

        for variant, lag, wanted in (("clean_recent_lag", 150, set()), ("stale", 1800, {("freshness", "ts")})):
            rows, as_of, truth = table(variant)
            self.assertEqual(rows, clean)
            self.assertEqual((as_of - latest, truth), (timedelta(seconds=lag), wanted))

        rows, _, truth = table("null_increase")
        empty = [i for i, r in enumerate(rows) if r[3] == ""]
        self.assertEqual(len(empty), 100)
        self.assertEqual([r for i, r in enumerate(rows) if i not in empty], [c for i, c in enumerate(clean) if i not in empty])
        self.assertEqual(truth, {("empty_rate_change", "flow_lpm")})

        reference_temps = [float(r[1]) for ref in references for r in ref]
        sd = statistics.pstdev(reference_temps)
        for variant, d in (("mean_shift_large", 1.5), ("mean_shift_small", 0.25)):
            rows, _, truth = table(variant)
            offsets = [float(r[1]) - float(c[1]) for r, c in zip(rows, clean)]
            self.assertTrue(all(abs(o - d * sd) < 0.0011 for o in offsets), variant)
            self.assertEqual([[r[0]] + r[2:] for r in rows], [[c[0]] + c[2:] for c in clean])
            self.assertEqual(truth, {("distribution_shift", "temp_c")})

        rows, _, truth = table("unit_change")
        self.assertTrue(all(abs(float(r[2]) - 10 * float(c[2])) < 1e-6 for r, c in zip(rows, clean)))
        self.assertTrue(all(r[2] == "%.3f" % float(r[2]) for r in rows))
        self.assertEqual(truth, {("distribution_shift", "pressure_kpa")})

        rows, _, truth = table("scale_change")
        pressures = [float(r[2]) for r in rows]
        self.assertNotEqual(pressures, [float(c[2]) for c in clean])
        self.assertTrue(1.8 < statistics.pstdev(pressures) < 3.2)
        self.assertLess(abs(statistics.fmean(pressures) - 100), 0.5)
        self.assertEqual([[r[0], r[1], r[3]] for r in rows], [[c[0], c[1], c[3]] for c in clean])
        self.assertEqual(truth, {("distribution_shift", "pressure_kpa")})


class ScoringTests(unittest.TestCase):
    def test_rates_without_denominator_are_none(self):
        self.assertEqual(be._rate(0, 0), {"successes": 0, "trials": 0, "rate": None, "wilson95": None})
        self.assertEqual(be._show(be._rate(0, 0)), "n/a")
        self.assertEqual(be._show(None), "n/a")
        self.assertEqual(be._show(be._rate(2, 4)), "2/4 = 50.0% [15.0–85.0]")

    def test_score_case_counts_keys_and_not_evaluated_reasons(self):
        bucket = be._empty_bucket()
        result = {"findings": [{"check": "volume_change", "column": None, "detail": {}},
                               {"check": "distribution_shift", "column": "temp_c", "detail": {}}],
                  "not_evaluated": [{"check": "freshness", "column": "ts", "reason": "no_as_of"},
                                    {"check": "distribution_shift", "column": "flow_lpm", "reason": "too_few_values"},
                                    {"check": "freshness", "column": "ts", "reason": "no_as_of"}]}
        be.score_case(bucket, "volume_drop", {("volume_change", None), ("freshness", "ts")}, result)
        row = bucket["variants"]["volume_drop"]
        self.assertEqual((row["cases"], row["detected_cases"], row["cases_with_unexpected"]), (1, 0, 1))
        self.assertEqual(bucket["checks"]["volume_change"], {"true_keys": 1, "false_keys": 0, "missed_keys": 0})
        self.assertEqual(bucket["checks"]["distribution_shift"], {"true_keys": 0, "false_keys": 1, "missed_keys": 0})
        self.assertEqual(bucket["checks"]["freshness"], {"true_keys": 0, "false_keys": 0, "missed_keys": 1})
        self.assertEqual(bucket["not_evaluated"], {"no_as_of": 2, "too_few_values": 1})
        be.score_case(bucket, "clean", set(), {"findings": [], "not_evaluated": []})
        self.assertEqual(bucket["variants"]["clean"], {"cases": 1, "detected_cases": 1, "cases_with_unexpected": 0})


class MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = be.evaluate()
        cls.development = cls.report["splits"]["development"]

    def test_heldout_not_scored_by_default(self):
        self.assertEqual(set(self.report["splits"]), {"development", "validation"})
        self.assertNotIn("heldout", self.report["splits"])

    def test_every_case_is_counted(self):
        for name, bucket in self.report["splits"].items():
            groups = sum(be.split_of(g) == name for g in range(be.GROUPS))
            self.assertEqual(bucket["groups"], groups)
            self.assertTrue(all(row["cases"] == groups for row in bucket["variants"].values()))
            self.assertIsNone(bucket["variants"]["clean"]["case_detection"])
            self.assertEqual(bucket["variants"]["stale"]["case_detection"]["trials"], groups)
            for variant in be.CLEAN_PSI_VARIANTS:
                self.assertEqual(set(bucket["clean_psi"][variant]), {"temp_c", "pressure_kpa", "flow_lpm"})
                for column in bucket["clean_psi"][variant].values():
                    self.assertEqual(column["cases"], groups)
                    self.assertTrue(0 <= column["above"] <= groups and column["max"] >= 0)

    def test_unbroken_corpus_finds_large_kinds(self):
        for kind in LARGE_KINDS:
            row = self.development["variants"][kind]
            self.assertEqual(row["detected_cases"], row["cases"], kind)

    def test_precision_and_recall_per_check(self):
        checks = self.development["checks"]
        for check, row in checks.items():
            self.assertEqual(row["precision"]["trials"], row["true_keys"] + row["false_keys"], check)
            self.assertEqual(row["recall"]["trials"], row["true_keys"] + row["missed_keys"], check)
        self.assertEqual(checks["freshness"]["recall"]["rate"], 1.0)


class MutantTests(unittest.TestCase):
    """A deliberately broken check must show up in the development numbers."""

    @classmethod
    def setUpClass(cls):
        cls.unbroken = be.evaluate(splits=("development",))["splits"]["development"]["variants"]

    def broken(self, target, name, value):
        with mock.patch.object(target, name, value):
            return be.evaluate(splits=("development",))["splits"]["development"]["variants"]

    def assertDetectionDrops(self, variants, kind):
        self.assertLess(variants[kind]["detected_cases"], self.unbroken[kind]["detected_cases"], kind)

    def test_disabled_psi_is_exposed(self):
        variants = self.broken(baseline, "PSI_SHIFT", float("inf"))
        for kind in ("mean_shift_large", "unit_change"):
            self.assertEqual(variants[kind]["detected_cases"], 0)
            self.assertDetectionDrops(variants, kind)

    def test_psi_threshold_times_ten_is_exposed(self):
        self.assertDetectionDrops(self.broken(baseline, "PSI_SHIFT", baseline.PSI_SHIFT * 10), "scale_change")

    def test_disabled_sampling_is_exposed(self):
        variants = self.broken(baseline, "SAMPLING_RATIO", float("inf"))
        for kind in ("sampling_slow", "sampling_fast"):
            self.assertEqual(variants[kind]["detected_cases"], 0)

    def test_inverted_volume_band_is_exposed(self):
        variants = self.broken(baseline, "VOLUME_RATIO", 1 / baseline.VOLUME_RATIO)
        self.assertGreater(variants["clean"]["cases_with_unexpected"], self.unbroken["clean"]["cases_with_unexpected"])
        self.assertEqual(variants["clean"]["cases_with_unexpected"], variants["clean"]["cases"])

    def test_freshness_ignoring_as_of_is_exposed(self):
        original = baseline._freshness

        def ignores_as_of(base, stamps, usable, aware, as_of_time, measured):
            return original(base, stamps, usable, aware, max(stamps), measured)

        variants = self.broken(baseline, "_freshness", ignores_as_of)
        self.assertEqual(variants["stale"]["detected_cases"], 0)
        self.assertDetectionDrops(variants, "stale")

    def test_disabled_empty_rate_is_exposed(self):
        variants = self.broken(baseline, "EMPTY_RATE_DELTA", float("inf"))
        self.assertEqual(variants["null_increase"]["detected_cases"], 0)
        self.assertDetectionDrops(variants, "null_increase")


class SensitivityAndReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = be.main()

    def test_sensitivity_is_development_only_and_monotone_in_cases(self):
        sweep = be.sensitivity()
        development = sum(be.split_of(g) == "development" for g in range(be.GROUPS))
        self.assertEqual([row["shift_sd"] for row in sweep], list(be.SHIFTS))
        self.assertTrue(all(row["detection"]["trials"] == development for row in sweep))
        self.assertGreaterEqual(sweep[-1]["detection"]["successes"], sweep[0]["detection"]["successes"])
        self.assertEqual(sweep[-1]["detection"]["successes"], development)

    def test_main_prints_development_and_validation_only(self):
        self.assertIn("## Split: development", self.text)
        self.assertIn("## Split: validation", self.text)
        self.assertNotIn("Split: heldout", self.text)

    def test_report_states_its_limits(self):
        for phrase in ("Synthetic generated series only", "no real sensors", "not a significance test", "no p-value",
                       "no root cause", "chosen by the authors of the checks", "not fitted", "n/a", "PSI_SHIFT = 0.25",
                       "only partly detected by design", "development sensitivity table", "less than whole seasonal cycles",
                       "Partial cycles can raise PSI", "`clean_partial_cycle` (350 records, 3.5 cycles)",
                       "`volume_drop` (160 records, 1.6 cycles)"):
            self.assertIn(phrase, self.text)

    def test_include_heldout_flag_requests_the_heldout_split(self):
        with mock.patch.object(be, "evaluate", return_value="report") as evaluate, \
                mock.patch.object(be, "sensitivity", return_value="sweep"), \
                mock.patch.object(be, "render_markdown", return_value="text") as render:
            self.assertEqual(be.main(["--include-heldout"]), "text")
            evaluate.assert_called_once_with(splits=("development", "validation", "heldout"))
            render.assert_called_once_with("report", "sweep")
            be.main([])
            evaluate.assert_called_with(splits=("development", "validation"))


if __name__ == "__main__":
    unittest.main()
