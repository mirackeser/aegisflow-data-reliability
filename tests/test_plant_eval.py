# SPDX-License-Identifier: Apache-2.0
import io
import json
from pathlib import Path
import tempfile
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


class SavedCasesTests(unittest.TestCase):
    def test_save_and_render_saved_cases(self):
        seeds = {"development": range(1, 2), "validation": range(21, 22), "heldout": range(41, 42)}
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(pe, "SEEDS", seeds), \
                mock.patch.object(pe, "CLEAN_SECONDS", 30), mock.patch.object(pe, "SCENARIOS", (("unit_change", "flow_lpm"),)):
            path = Path(folder) / "cases.json"
            text = pe.main(["--save-cases", str(path)])
            self.assertEqual(pe.main(["--from-cases", str(path)]), text)
            saved = json.loads(path.read_text("utf-8"))
            self.assertEqual(set(saved["splits"]), {"development", "validation"})
            saved["version"] = "0"
            path.write_text(json.dumps(saved), "utf-8")
            with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                pe.main(["--from-cases", str(path)])


class CommittedReportTests(unittest.TestCase):
    """The committed report and case measurements were generated once, with held-out, after implementation and review.

    Running every plant again takes minutes, and over an hour under line tracing on Python 3.11/3.12. So the report is
    checked against the saved measurements, and the first seed of every split is recomputed from scratch.
    """

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.report = (root / "docs" / "evaluation" / "plant.md").read_text("utf-8")
        cls.cases_path = root / "fixtures" / "evaluations" / "plant-cases-v1.json"
        cls.saved = json.loads(cls.cases_path.read_text("utf-8"))

    def test_committed_report_renders_from_the_saved_cases(self):
        self.assertEqual(self.report, pe.main(["--include-heldout", "--from-cases", str(self.cases_path)]) + "\n")

    def test_saved_cases_cover_every_split_seed_and_scenario(self):
        self.assertEqual(list(self.saved["splits"]), list(pe.SPLITS))
        for split, bucket in self.saved["splits"].items():
            seeds = pe.SEEDS[split]
            self.assertEqual((bucket["seeds"], len(bucket["clean"])), ([seeds[0], seeds[-1]], len(seeds)))
            self.assertEqual(list(bucket["cases"]), [pe.scenario_name(f, s) for f, s in pe.SCENARIOS])
            self.assertTrue(all(len(cases) == len(seeds) for cases in bucket["cases"].values()))

    def test_first_seed_of_every_split_is_reproduced(self):
        for split, bucket in self.saved["splits"].items():
            seed = pe.SEEDS[split][0]
            for fault, sensor in pe.SCENARIOS:
                self.assertEqual(pe.run_case(seed, fault, sensor), bucket["cases"][pe.scenario_name(fault, sensor)][0],
                                 (split, seed, fault, sensor))
            self.assertEqual(pe.clean_case(seed), bucket["clean"][0], (split, seed))


if __name__ == "__main__":
    unittest.main()
