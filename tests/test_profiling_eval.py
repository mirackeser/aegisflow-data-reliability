# SPDX-License-Identifier: Apache-2.0
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import unittest
from unittest import mock

from aegisflow_dr import profiling, profiling_eval as pe


@lru_cache(maxsize=1)
def rendered():
    return pe.main()


def development_counts(kind):
    """Found and extra records of the targeted check over the development groups, for one fault kind."""
    found = extra = 0
    for group in range(pe.GROUPS):
        if pe.split_of(group) != "development":
            continue
        payload, truth = pe.inject(group, kind)
        flagged = pe.flagged_records(profiling.profile_csv(payload))
        for key, records in flagged.items():
            wanted = truth.get(key, set())
            found, extra = found + len(records & wanted), extra + len(records - wanted)
    return found, extra


def cells(payload):
    return [line.split(",") for line in payload.decode().strip().split("\n")][1:]


class SplitTests(unittest.TestCase):
    def test_every_group_is_in_exactly_one_split_and_all_are_used(self):
        counts = {name: sum(pe.split_of(g) == name for g in range(pe.GROUPS)) for name in pe.SPLITS}
        self.assertEqual(sum(counts.values()), pe.GROUPS)
        self.assertTrue(all(counts.values()))
        self.assertEqual(counts, {"development": 31, "validation": 12, "heldout": 17})

    def test_variants_of_one_group_share_one_base_series(self):
        base, _ = pe.base_series(3)
        for kind in ("spike_large", "flatline", "clean"):
            payload, _ = pe.inject(3, kind)
            self.assertEqual(len(cells(payload)[0]), 4)
            self.assertEqual(cells(payload)[0][0], base[0][0])

    def test_generation_is_deterministic(self):
        self.assertEqual(pe.inject(5, "gap"), pe.inject(5, "gap"))
        self.assertNotEqual(pe.inject(5, "gap")[0], pe.inject(6, "gap")[0])


class InjectionTruthTests(unittest.TestCase):
    """The ground truth must describe the data that was actually written."""

    def diff_records(self, group, kind, column):
        clean = cells(pe.inject(group, "clean")[0])
        faulty = cells(pe.inject(group, kind)[0])
        self.assertEqual(len(clean), len(faulty))
        return {i + 1 for i, (a, b) in enumerate(zip(clean, faulty)) if a[column] != b[column]}

    def test_clean_has_no_truth(self):
        self.assertEqual(pe.inject(2, "clean")[1], {})

    def test_spikes_and_type_corruption_change_exactly_the_truth_records(self):
        for group in range(8):
            for kind, column in (("spike_large", 1), ("spike_small", 1), ("type_corruption", 2)):
                _, truth = pe.inject(group, kind)
                (key, records), = truth.items()
                self.assertEqual((key[1], len(records)), (pe.COLUMN[kind], 3))
                self.assertEqual(self.diff_records(group, kind, column), records)

    def test_spike_sizes_match_their_tier(self):
        for group in range(8):
            sd = pe.base_series(group)[1]
            for kind, low, high in (("spike_large", 10, 20), ("spike_small", 4, 6)):
                clean = cells(pe.inject(group, "clean")[0])
                faulty = cells(pe.inject(group, kind)[0])
                for record in pe.inject(group, kind)[1][("outlier", "temp_c")]:
                    size = abs(float(faulty[record - 1][1]) - float(clean[record - 1][1])) / sd
                    self.assertTrue(low - 0.01 <= size <= high + 0.01, (kind, size))

    def test_flatline_run_is_constant_and_twelve_long(self):
        for group in range(8):
            (key, records), = pe.inject(group, "flatline")[1].items()
            rows = cells(pe.inject(group, "flatline")[0])
            self.assertEqual((len(records), max(records) - min(records)), (12, 11))
            self.assertEqual(len({rows[r - 1][2] for r in records}), 1)

    def test_gap_removes_five_rows_at_the_truth_record(self):
        for group in range(8):
            (key, records), = pe.inject(group, "gap")[1].items()
            rows = cells(pe.inject(group, "gap")[0])
            self.assertEqual(len(rows), pe.ROWS - 5)
            record, = records
            step = (datetime.fromisoformat(rows[record - 1][0]) - datetime.fromisoformat(rows[record - 2][0])).total_seconds()
            self.assertEqual(step, 6 * pe.STEP_SECONDS)

    def test_duplicate_and_out_of_order_timestamps_match_the_truth(self):
        for group in range(8):
            rows = cells(pe.inject(group, "duplicate_timestamp")[0])
            for record in pe.inject(group, "duplicate_timestamp")[1][("timestamp_duplicate", "ts")]:
                self.assertEqual(rows[record - 1][0], rows[record - 2][0])
            rows = cells(pe.inject(group, "out_of_order")[0])
            record, = pe.inject(group, "out_of_order")[1][("timestamp_out_of_order", "ts")]
            self.assertLess(datetime.fromisoformat(rows[record - 1][0]), datetime.fromisoformat(rows[record - 2][0]))

    def test_null_burst_is_eighty_empty_cells_over_the_limit(self):
        for group in range(8):
            (key, records), = pe.inject(group, "null_burst")[1].items()
            rows = cells(pe.inject(group, "null_burst")[0])
            self.assertEqual({i + 1 for i, r in enumerate(rows) if r[3] == ""}, records)
            self.assertGreater(len(records) / pe.ROWS, profiling.EMPTY_RATE)


class MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pe.evaluate()

    def test_rates_without_a_denominator_are_none_not_100_percent(self):
        self.assertEqual(pe._rate(0, 0), {"successes": 0, "trials": 0, "rate": None, "wilson95": None})
        self.assertEqual(pe._show(None), "n/a")
        self.assertEqual(pe._show(pe._rate(0, 0)), "n/a")
        clean = self.report["splits"]["heldout"]["kinds"]["clean"]
        self.assertIsNone(clean["case_detection"])
        self.assertEqual(clean["record_recall"]["rate"], None)

    def test_small_rates_are_not_rounded_to_zero(self):
        self.assertIn("0.0019%", pe._show(pe._rate(1, 54000)))
        self.assertEqual(pe._show(pe._rate(2, 4)), "2/4 = 50.0% [15.0–85.0]")

    def test_pinned_heldout_figures(self):
        held = self.report["splits"]["heldout"]
        self.assertEqual(held["groups"], 17)
        for kind in ("spike_large", "flatline", "gap", "duplicate_timestamp", "out_of_order", "type_corruption"):
            row = held["kinds"][kind]
            self.assertEqual(row["found_records"], row["truth_records"], kind)
        self.assertEqual((held["kinds"]["spike_small"]["found_records"], held["kinds"]["spike_small"]["truth_records"]), (17, 51))
        self.assertEqual(held["kinds"]["null_burst"]["detected_cases"], 17)
        self.assertEqual(held["clean_false_alarm_values"]["successes"], 1)
        self.assertEqual(self.report["clean_false_alarm_values"]["trials"], 54000)

    def test_clean_false_alarms_stay_within_ten_times_the_design_target(self):
        rate = self.report["clean_false_alarm_values"]
        self.assertLess(rate["successes"] / rate["trials"], 1e-4)

    def test_every_split_contains_every_kind(self):
        for bucket in self.report["splits"].values():
            self.assertTrue(all(row["cases"] == bucket["groups"] for row in bucket["kinds"].values()))

    def test_flatline_runs_are_expanded_to_records(self):
        payload, truth = pe.inject(4, "flatline")
        found = pe.flagged_records(profiling.profile_csv(payload))
        self.assertEqual(found[("flatline", "pressure_kpa")], truth[("flatline", "pressure_kpa")])


class MutantTests(unittest.TestCase):
    """A deliberately broken detector must show up in the numbers."""

    def test_unbroken_detectors_find_everything_without_extras(self):
        for kind in ("spike_large", "flatline", "gap"):
            self.assertGreater(development_counts(kind)[0], 0, kind)
        self.assertEqual(development_counts("clean"), (0, 0))

    def test_disabled_outlier_check_is_exposed(self):
        with mock.patch.object(profiling, "OUTLIER_K", 1e9):
            self.assertEqual(development_counts("spike_large")[0], 0)

    def test_oversensitive_outlier_check_is_exposed(self):
        with mock.patch.object(profiling, "OUTLIER_K", 1.5):
            self.assertGreater(development_counts("clean")[1], 100)

    def test_blind_flatline_check_is_exposed(self):
        with mock.patch.object(profiling, "FLAT_RUN", 10_000):
            self.assertEqual(development_counts("flatline")[0], 0)

    def test_blind_gap_check_is_exposed(self):
        with mock.patch.object(profiling, "GAP_FACTOR", 1e6):
            self.assertEqual(development_counts("gap")[0], 0)

    def test_sweep_restores_the_threshold(self):
        before = profiling.OUTLIER_K
        sweep = pe.threshold_sweep()
        self.assertEqual(profiling.OUTLIER_K, before)
        self.assertEqual([row["k"] for row in sweep], list(pe.SWEEP))
        self.assertGreaterEqual(sweep[0]["spike_small"]["found"], sweep[-1]["spike_small"]["found"])


class ReportTests(unittest.TestCase):
    def test_committed_report_matches_the_code(self):
        committed = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "profiling.md"
        self.assertEqual(committed.read_text("utf-8"), rendered() + "\n")

    def test_report_states_its_limits(self):
        text = rendered()
        for phrase in ("Not real sensors", "not a language model", "not evidence about real sensors", "was not changed afterwards",
                       "column-level", "n/a"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
