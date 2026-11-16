# SPDX-License-Identifier: Apache-2.0
import copy
import unittest

from aegisflow_dr import monitoring as mon
from aegisflow_dr.analysis import analyze_csv
from aegisflow_dr.pipeline import generate_orders

HEADER = "order_id,customer_id,order_total\n"


def run(run_id, payload, meta=None, scenario="upload"):
    return {"run_id": run_id, "scenario": scenario, "meta": meta, "started_at": f"t{run_id}",
            "finished_at": None if run_id.endswith("x") else f"t{run_id}.", "result": {"cases": [{"analysis": analyze_csv(payload)}]}}


def sample(run_id, fault, rows=24):
    return run(run_id, generate_orders(fault=fault, rows=rows), {"kind": "synthetic_sample", "name": "synthetic-" + fault})


def csv(*rows):
    return (HEADER + "".join(r + "\n" for r in rows)).encode()


def one(report):
    return report["streams"][0]


def codes(point):
    return {c["code"] for c in point["changes"]}


class StreamTests(unittest.TestCase):
    def test_key_grouping(self):
        self.assertEqual(mon.stream_key({"kind": "synthetic_sample", "name": "synthetic-clean"}, "upload"), ("synthetic-sample", "synthetic-sample"))
        self.assertEqual(mon.stream_key({"kind": "file", "name": "a.csv"}, None), ("file:a.csv", "a.csv"))
        self.assertEqual(mon.stream_key({"kind": "connected"}, None), ("connected:connected", "connected"))
        self.assertEqual(mon.stream_key(None, "suite"), ("suite:suite", "suite"))
        self.assertEqual(mon.stream_key(None, None), ("unknown:unknown", "unknown"))

    def test_runs_without_analysis_or_duplicates_are_ignored(self):
        bare = {"run_id": "b", "result": None}
        no_cases = {"run_id": "c", "result": {"cases": []}}
        first = sample("1", "clean")
        report = mon.monitor([bare, no_cases, first, copy.deepcopy(first)])
        self.assertEqual(len(one(report)["runs"]), 1)
        self.assertEqual(one(report)["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(mon.monitor([])["streams"], [])

    def test_streams_are_separate_and_sorted(self):
        report = mon.monitor([run("1", csv("A,C,1.00"), {"kind": "file", "name": "b.csv"}),
                              run("2", csv("A,C,1.00"), {"kind": "file", "name": "a.csv"})])
        self.assertEqual([s["label"] for s in report["streams"]], ["a.csv", "b.csv"])

    def test_history_is_bounded(self):
        runs = [sample(str(i), "clean") for i in range(mon.MAX_RUNS + 5)]
        self.assertEqual(len(one(mon.monitor(runs))["runs"]), mon.MAX_RUNS)

    def test_point_uses_exact_values_from_the_analysis(self):
        point = one(mon.monitor([sample("1", "null_total")]))["runs"][0]
        self.assertEqual((point["row_count"], point["affected_records"], point["affected_rate"]), (24, 1, round(1 / 24, 4)))
        self.assertEqual(point["failing_checks"], ["not_null:order_total"])
        self.assertEqual(point["at"], "t1.")
        self.assertIsNotNone(point["mean_valid_amount"])
        self.assertEqual(one(mon.monitor([run("2x", csv("A,C,1.00")), ]))["runs"][0]["at"], "t2x")


class DriftTests(unittest.TestCase):
    def test_degradation_then_recovery_on_labelled_samples(self):
        report = mon.monitor([sample("1", "clean"), sample("2", "duplicate_order"), sample("3", "clean")])
        stream = one(report)
        self.assertEqual([codes(p) for p in stream["runs"]],
                         [set(), {"NEW_CHECK_FAILURE", "QUALITY_DEGRADED"}, {"RECOVERED"}])
        self.assertEqual(stream["status"], "RECOVERED")
        self.assertEqual(stream["latest_changes"][0]["detail"], {"before": 2, "after": 0})

    def test_degraded_when_rate_rises_by_five_points(self):
        good = csv(*(f"A{i},C,1.00" for i in range(20)))
        bad = csv(*(f"A{i},C,1.00" for i in range(18)), "A18,C,", "A19,C,")
        report = mon.monitor([run("1", good), run("2", bad)])
        self.assertEqual(one(report)["status"], "DEGRADED")
        self.assertIn("QUALITY_DEGRADED", codes(one(report)["runs"][1]))
        big_good = csv(*(f"A{i},C,1.00" for i in range(40)))
        small = csv(*(f"A{i},C,1.00" for i in range(39)), "A39,C,")  # 2.5 points: below the 5-point rule
        self.assertNotIn("QUALITY_DEGRADED", codes(one(mon.monitor([run("1", big_good), run("2", small)]))["runs"][1]))

    def test_schema_change(self):
        renamed = (b"order_id,customer_id,total_amount\nA1,C,1.00\n")
        report = mon.monitor([run("1", csv("A1,C,1.00")), run("2", renamed)])
        self.assertIn("SCHEMA_CHANGED", codes(one(report)["runs"][1]))
        self.assertEqual(one(report)["status"], "DEGRADED")
        back = one(mon.monitor([run("1", renamed), run("2", csv("A1,C,1.00"))]))
        self.assertEqual((codes(back["runs"][1]), back["status"]), ({"SCHEMA_RESTORED"}, "RECOVERED"))

    def test_recovery_requires_no_schema_issues(self):
        bad = csv("A1,C,", "A2,C,1.00")
        renamed = b"order_id,customer_id,total_amount\nA1,C,1.00\n"
        self.assertNotIn("RECOVERED", codes(one(mon.monitor([run("1", bad), run("2", renamed)]))["runs"][1]))

    def test_row_count_and_amount_level_shift(self):
        small = csv(*(f"A{i},C,10.00" for i in range(10)))
        big = csv(*(f"B{i},C,30.00" for i in range(20)))
        latest = one(mon.monitor([run("1", small), run("2", big)]))["runs"][1]
        self.assertTrue({"ROW_COUNT_SHIFT", "AMOUNT_LEVEL_SHIFT"} <= codes(latest))
        steady = csv(*(f"B{i},C,11.00" for i in range(11)))
        self.assertEqual(codes(one(mon.monitor([run("1", small), run("2", steady)]))["runs"][1]), set())

    def test_undefined_comparisons_raise_no_alerts(self):
        empty = HEADER.encode()
        no_amounts = csv("A1,C,")
        zero_level = csv("A1,C,0")
        full = csv("A1,C,5.00")
        for before, after in ((empty, full), (full, empty), (no_amounts, full), (zero_level, full)):
            changes = codes(one(mon.monitor([run("1", before), run("2", after)]))["runs"][1])
            self.assertFalse(changes & {"QUALITY_DEGRADED", "ROW_COUNT_SHIFT", "AMOUNT_LEVEL_SHIFT"}, (before, after, changes))
        self.assertEqual(codes(one(mon.monitor([run("1", full), run("2", no_amounts)]))["runs"][1]), {"QUALITY_DEGRADED", "NEW_CHECK_FAILURE"})
        self.assertIsNone(one(mon.monitor([run("1", empty)]))["runs"][0]["affected_rate"])
        self.assertIsNone(one(mon.monitor([run("1", no_amounts)]))["runs"][0]["mean_valid_amount"])

    def test_stable_status_and_rules_are_exposed(self):
        report = mon.monitor([sample("1", "clean"), sample("2", "clean")])
        self.assertEqual(one(report)["status"], "STABLE")
        self.assertEqual(report["rules"], mon.RULES)


if __name__ == "__main__":
    unittest.main()
