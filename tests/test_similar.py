# SPDX-License-Identifier: Apache-2.0
import unittest

from aegisflow_dr import similar
from aegisflow_dr.analysis import analyze_csv
from aegisflow_dr.pipeline import generate_orders


def run(run_id, payload, meta=None, finished="t"):
    return {"run_id": run_id, "scenario": "upload", "meta": meta, "started_at": f"s{run_id}", "finished_at": finished,
            "result": {"cases": [{"analysis": analyze_csv(payload)}]}}


def sample(run_id, fault, rows=24, **extra):
    return run(run_id, generate_orders(fault=fault, rows=rows), {"kind": "synthetic_sample", "name": "synthetic-" + fault}, **extra)


class SignatureTests(unittest.TestCase):
    def test_signature_lists_failing_checks_and_schema_issues(self):
        self.assertEqual(similar.signature(sample("1", "clean")), frozenset())
        self.assertIn("check:not_null:order_total", similar.signature(sample("2", "null_total")))
        broken = run("3", b"id,customer_id,order_total\nA,C,1.00\n")
        self.assertTrue(any(item.startswith("schema:") for item in similar.signature(broken)))

    def test_run_without_analysis_has_no_signature(self):
        self.assertIsNone(similar.signature({"run_id": "x", "result": None}))
        self.assertIsNone(similar.signature({"run_id": "y", "result": {"cases": []}}))


class MatchTests(unittest.TestCase):
    def test_same_fault_matches_and_other_fault_does_not(self):
        target = sample("t", "null_total")
        runs = [sample("a", "null_total", rows=30, finished="2"), sample("b", "duplicate_order"), sample("c", "clean"),
                {"run_id": "bare", "result": None}, target]
        matches = similar.similar_runs(target, runs)
        self.assertEqual([m["run_id"] for m in matches], ["a"])
        self.assertEqual(matches[0]["score"], 1.0)
        self.assertEqual((matches[0]["only_here"], matches[0]["only_there"]), ([], []))
        self.assertEqual(matches[0]["row_count"], 30)
        self.assertEqual(matches[0]["source"], "synthetic-null_total")

    def test_partial_overlap_reports_what_differs(self):
        left = run("l", b"order_id,customer_id,order_total\nA,C,\nB,C,x\nC,C,1.00\n")
        right = run("r", b"order_id,customer_id,order_total\nA,C,\nB,C,2.00\nC,C,1.00\n")
        found = similar.similar_runs(left, [right])
        self.assertEqual(len(found), 1)
        self.assertTrue(0.5 <= found[0]["score"] < 1)
        self.assertTrue(found[0]["only_here"])
        self.assertTrue(found[0]["shared"])

    def test_below_threshold_is_not_reported(self):
        left = run("l", b"order_id,customer_id,order_total\nA,C,\nA,C,x\nB,,1.00\n")
        right = run("r", b"order_id,customer_id,order_total\nA,C,\nB,C,2.00\n")
        self.assertEqual(similar.similar_runs(left, [right]), [])

    def test_clean_target_and_unanalysed_target_match_nothing(self):
        self.assertEqual(similar.similar_runs(sample("c", "clean"), [sample("d", "clean")]), [])
        self.assertEqual(similar.similar_runs({"run_id": "n", "result": None}, [sample("a", "null_total")]), [])

    def test_ordering_limit_and_duplicates(self):
        target = sample("t", "null_total")
        runs = [sample(str(i), "null_total", finished=f"{i}") for i in range(5)]
        runs.append(sample("0", "null_total"))  # duplicate id is ignored
        matches = similar.similar_runs(target, runs)
        self.assertEqual(len(matches), similar.LIMIT)
        self.assertEqual([m["run_id"] for m in matches], ["0", "1", "2"])

    def test_source_and_time_fall_back(self):
        target = sample("t", "null_total")
        other = sample("o", "null_total")
        other["finished_at"] = None
        other["meta"] = {"kind": "file"}
        self.assertEqual(similar.similar_runs(target, [other])[0]["source"], "file")
        other["meta"] = None
        self.assertEqual(similar.similar_runs(target, [other])[0]["source"], "upload")
        self.assertEqual(similar.similar_runs(target, [other])[0]["at"], "so")


class IndexTests(unittest.TestCase):
    def test_index_has_only_runs_with_matches(self):
        runs = [sample("1", "null_total"), sample("2", "null_total"), sample("3", "clean"), sample("4", "duplicate_order")]
        index = similar.similar_index(runs)
        self.assertEqual(set(index["matches"]), {"1", "2"})
        self.assertEqual((index["version"], index["min_score"]), (similar.VERSION, similar.MIN_SCORE))


if __name__ == "__main__":
    unittest.main()
