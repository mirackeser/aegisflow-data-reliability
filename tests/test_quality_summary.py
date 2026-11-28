# SPDX-License-Identifier: Apache-2.0
"""The quality summary reads every number from an evaluation's own report and normalises rates without changing them."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from aegisflow_dr import baseline_eval, check_evaluation, hypotheses_eval, plant_eval, profiling_eval, quality as q
from aegisflow_dr.agents import agents_eval


def metric(card, key):
    return next(m for m in card["metrics"] if m["key"] == key)


class RateTests(unittest.TestCase):
    def test_rate_shapes_and_n_a(self):
        self.assertEqual(q.rate(3, 4), {"numerator": 3, "denominator": 4, "value": 0.75, "low": 0.3006, "high": 0.9544})
        self.assertEqual(q.rate(0, 0), {"numerator": 0, "denominator": 0, "value": None, "low": None, "high": None})
        self.assertEqual(q.from_report({"successes": 3, "trials": 4, "rate": 0.75, "wilson95": [0, 1]}), q.rate(3, 4))
        self.assertEqual(q.from_report({"numerator": 1, "denominator": 2}), q.rate(1, 2))
        self.assertIsNone(q.from_report(None))

    def test_pool_adds_cases_and_skips_what_does_not_apply(self):
        self.assertEqual(q.pool([q.rate(1, 2), None, q.rate(3, 4)]), q.rate(4, 6))
        self.assertEqual(q.pool([]), q.rate(0, 0))


class CardTests(unittest.TestCase):
    def test_plant_card_from_saved_cases(self):
        report = plant_eval.summarise_collected(json.loads(q.PLANT_CASES.read_text("utf-8")))
        card = q.plant_card(report)
        held = report["splits"]["heldout"]
        detected = [s["rates"]["detected"] for s in held["scenarios"].values()]
        self.assertEqual(metric(card, "detected")["splits"]["heldout"],
                         q.rate(sum(r["numerator"] for r in detected), sum(r["denominator"] for r in detected)))
        self.assertEqual(metric(card, "false_alarms")["splits"]["heldout"],
                         {"count": held["clean_incidents"], "hours": held["clean_hours"]})
        self.assertEqual(card["units"]["heldout"], {"seeds": 20})
        self.assertEqual([r["name"] for r in card["scenarios"]["rows"]], list(held["scenarios"]))
        self.assertEqual(metric(card, "wrong_supported")["better"], q.LOWER)
        self.assertEqual(q.plant_card({"splits": {}})["scenarios"]["rows"], [])

    def test_agents_card_pools_modelled_and_out_of_catalog_scenarios(self):
        bucket = agents_eval._empty_bucket()
        bucket["groups"] = 1
        for name in agents_eval.SCENARIOS:
            row = bucket["scenarios"][name]
            row.update(cases=1, exact=1, a23_suggested=1, a23_any=1, a23_misattributed=1)
        agents_eval._finalize(bucket)
        report = {"recording": {"model": "m", "prompt_version": "2"}, "splits": {"heldout": bucket}}
        card = q.agents_card(report)
        modelled = sum(agents_eval.truth_of(n) is not None for n in agents_eval.SCENARIOS)
        self.assertEqual(metric(card, "a23_any")["splits"]["heldout"], q.rate(modelled, modelled))
        self.assertEqual(metric(card, "a23_misattributed")["splits"]["heldout"], q.rate(2, 2))  # sign flip, amplitude
        self.assertEqual(metric(card, "model_json_valid")["splits"]["heldout"], q.rate(0, 0))
        self.assertIsNone(metric(card, "run_p50_ms")["splits"]["heldout"])
        self.assertEqual((card["model"], card["units"]["heldout"]), ("m", {"groups": 1, "cases": 0}))
        self.assertEqual(len(card["scenarios"]["rows"]), len(agents_eval.SCENARIOS))

    @unittest.skipUnless(q.AGENTS_CASES.exists(), "no saved agent case facts")
    def test_agents_card_from_saved_facts(self):
        report = agents_eval.summarise_collected(json.loads(q.AGENTS_CASES.read_text("utf-8")))
        card, held = q.agents_card(report), report["splits"]["heldout"]
        self.assertEqual(card["units"]["heldout"], {"groups": held["groups"], "cases": held["runs"]["cases"]})
        self.assertEqual(metric(card, "selection_exact")["splits"]["heldout"], q.from_report(held["selection"]["exact"]))
        self.assertEqual(metric(card, "run_p50_ms")["splits"]["heldout"], held["runs"]["p50"])

    def test_hypotheses_card(self):
        names = ("unit_change", "clean", "unmodelled_sign_flip")
        report = hypotheses_eval.evaluate(splits=("heldout",), scenarios=names)
        with mock.patch.object(hypotheses_eval, "UNMODELLED", ("unmodelled_sign_flip",)):  # the scenarios evaluated here
            card = q.hypotheses_card(report)
        held = report["splits"]["heldout"]["scenarios"]
        self.assertEqual(metric(card, "truth_sole_supported")["splits"]["heldout"],
                         q.from_report(held["unit_change"]["rates"]["truth_sole_supported"]))
        self.assertEqual(metric(card, "misattributed")["splits"]["heldout"],
                         q.from_report(held["unmodelled_sign_flip"]["rates"]["misattributed"]))

    def test_baseline_card(self):
        report = baseline_eval.evaluate(splits=("heldout",))
        card = q.baseline_card(report)
        variants = report["splits"]["heldout"]["variants"]
        clean = [v for v in baseline_eval.VARIANTS if not baseline_eval.TRUTH[v]]
        self.assertEqual(metric(card, "clean_with_finding")["splits"]["heldout"],
                         q.pool(q.from_report(variants[v]["unexpected_cases"]) for v in clean))
        self.assertEqual(metric(card, "case_detection")["splits"]["heldout"]["denominator"],
                         sum(variants[v]["cases"] for v in baseline_eval.VARIANTS if v not in clean))

    def test_profiling_and_checks_cards(self):
        report = profiling_eval.evaluate()
        card = q.profiling_card(report)
        self.assertEqual(metric(card, "clean_with_finding")["splits"]["heldout"],
                         q.from_report(report["splits"]["heldout"]["kinds"]["clean"]["false_alarm_cases"]))
        checks = check_evaluation.evaluate(include_heldout=True)
        card = q.checks_card(checks)
        self.assertEqual([m["key"] for m in card["metrics"]], ["diagnose_csv.precision", "diagnose_csv.recall",
                                                               "record_issues.precision", "record_issues.recall"])
        self.assertEqual(metric(card, "record_issues.recall")["splits"]["heldout"],
                         q.from_report(checks["results"]["record_issues"]["heldout"]["overall"]["recall"]))


class SummaryTests(unittest.TestCase):
    def test_summary_orders_the_cards_and_marks_missing_saved_cases(self):
        cards = {name: mock.Mock(return_value={"id": name}) for name in
                 ("plant_card", "agents_card", "hypotheses_card", "baseline_card", "profiling_card", "checks_card")}
        with tempfile.TemporaryDirectory() as folder, mock.patch.multiple(q, **cards), \
                mock.patch.object(q, "AGENTS_CASES", Path(folder) / "none.json"), \
                mock.patch.object(plant_eval, "summarise_collected", return_value="plant report"), \
                mock.patch.object(hypotheses_eval, "evaluate", return_value="h") as hypotheses, \
                mock.patch.object(baseline_eval, "evaluate", return_value="b") as baseline, \
                mock.patch.object(profiling_eval, "evaluate", return_value="p"), \
                mock.patch.object(check_evaluation, "evaluate", return_value="c") as checks:
            result = q.summary()
        self.assertEqual([c["id"] for c in result["evaluations"]],
                         ["plant_card", "agents", "hypotheses_card", "baseline_card", "profiling_card", "checks_card"])
        self.assertEqual(result["evaluations"][1], {"id": "agents", "available": False})
        cards["plant_card"].assert_called_once_with("plant report")
        hypotheses.assert_called_once_with(splits=q.SPLITS)
        baseline.assert_called_once_with(splits=q.SPLITS)
        checks.assert_called_once_with(include_heldout=True)


if __name__ == "__main__":
    unittest.main()
