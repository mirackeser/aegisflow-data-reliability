# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import unittest
from unittest import mock

from aegisflow_dr import plant_eval as pe, simulation as sim


class CaseTests(unittest.TestCase):
    def test_unit_change_is_detected_and_solely_supported_on_frozen_evidence(self):
        case = pe.run_case(1, "unit_change", "pressure_kpa")
        self.assertEqual((case["detected"], case["evidence"], case["onset_error_s"]), (True, sim.READY, 0))
        self.assertEqual((case["supported"], case["sole_supported"], case["wrong_supported"]), (["unit_change"], True, False))
        self.assertFalse(case["step1_sole_supported"])  # the mixed detection window supports nothing
        self.assertLessEqual(case["delay_s"], sim.CHECK_EVERY)

    def test_undetected_and_unfinished_evidence(self):
        with mock.patch.object(pe, "DETECT_LIMIT", 0):
            case = pe.run_case(2, "unit_change", "flow_lpm")
        self.assertEqual((case["detected"], case["delay_s"], case["evidence"]), (False, None, None))
        with mock.patch.object(pe, "EVIDENCE_LIMIT", 0):
            case = pe.run_case(2, "unit_change", "flow_lpm")
        self.assertEqual((case["detected"], case["evidence"], case["supported"]), (True, sim.COLLECTING, None))
        with mock.patch.object(sim.changepoint, "change_point", return_value=None), mock.patch.object(pe, "EVIDENCE_LIMIT", 0):
            case = pe.run_case(2, "unit_change", "flow_lpm")
        self.assertIsNone(case["onset_error_s"])

    def test_wrong_support_ignores_genuine_change(self):
        record = {"hypotheses": [{"mechanism": "genuine_change", "status": "supported"},
                                 {"mechanism": "unit_change", "status": "supported"},
                                 {"mechanism": "noise_increase", "status": "refuted"}]}
        self.assertEqual(pe._verdicts(record, "unit_change"), (False, False))
        record["hypotheses"][2]["status"] = "supported"
        self.assertEqual(pe._verdicts(record, "unit_change"), (False, True))

    def test_clean_plant_counts_incidents(self):
        with mock.patch.object(pe, "CLEAN_SECONDS", 60):
            self.assertEqual(pe.clean_case(1), 0)


class ReportTests(unittest.TestCase):
    def test_summary_of_no_cases_is_not_applicable(self):
        row = pe.summarise([])
        self.assertEqual((row["cases"], row["delay_median_s"], row["onset_error_median_s"], row["supported"]), (0, None, None, {}))
        self.assertTrue(all(rate["value"] is None for rate in row["rates"].values()))
        self.assertEqual(pe._show(row["rates"]["detected"]), "n/a")
        self.assertEqual(pe._tally([[], ["a"], ["a"]]), {"a": 2, "none": 1})

    def test_small_report_and_main(self):
        seeds = {"development": range(1, 2), "validation": range(21, 22), "heldout": range(41, 42)}
        with mock.patch.object(pe, "SEEDS", seeds), mock.patch.object(pe, "CLEAN_SECONDS", 30), \
                mock.patch.object(pe, "SCENARIOS", (("unit_change", "pressure_kpa"), ("duplicate_burst", None))):
            text = pe.main()
            full = pe.main(["--include-heldout"])
        self.assertIn("development and validation; `--include-heldout` adds the held-out split", text)
        self.assertNotIn("## Split: heldout", text)
        self.assertIn("## Split: heldout (seeds 41-41)", full)
        self.assertIn("| unit_change/pressure_kpa | 1/1 = 100% [", full)
        self.assertIn("| duplicate_burst | ", full)
        self.assertIn("False alarms: 0 incident(s) opened", full)


class CommittedReportTests(unittest.TestCase):
    """The committed report was generated once, with held-out, after implementation and review."""

    def test_committed_report_matches_the_code(self):
        committed = Path(__file__).resolve().parents[1] / "docs" / "evaluation" / "plant.md"
        self.assertEqual(committed.read_text("utf-8"), pe.main(["--include-heldout"]) + "\n")


if __name__ == "__main__":
    unittest.main()
