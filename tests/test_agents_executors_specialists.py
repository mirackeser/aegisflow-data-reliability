# SPDX-License-Identifier: Apache-2.0
"""Specialists A07-A22: one COMPLETED and one honest NEEDS_EVIDENCE (or denial) path each, results bound to evidence."""
import unittest

from agents_support import (BASELINE, BIG_ORDERS, DRIFTED, DUPLICATES, NULL_TOTAL, ORDERS, TIMED, context, model,
                            run, timed_csv)
from test_agents_executors import assert_bound
from aegisflow_dr.analysis import analyze_csv
from aegisflow_dr.baseline import build_baseline
from aegisflow_dr.agents.executors.specialists import summarise_history


def params(result, key):
    return [c["params"] for c in result["claims"] if c["text_key"] == key]


def numeric_csv(values, column="v"):
    return ("%s\n" % column + "".join("%s\n" % v for v in values)).encode()


class History(unittest.TestCase):
    def test_summary_ignores_free_text_and_picks_the_latest(self):
        history = [{"status": "COMPLETED", "finished_at": "2026-01-02", "meta": {"name": "secret.csv"}},
                   {"status": "free text!", "started_at": "2026-01-03"}, "junk", {"status": "FAILED"}]
        summary = summarise_history(history)
        self.assertEqual(summary, {"runs": 4, "readable": 3, "statuses": {"COMPLETED": 1, "FAILED": 1, "UNKNOWN": 1},
                                   "latest_status": "UNKNOWN"})
        self.assertEqual(summarise_history(["junk"])["latest_status"], None)
        self.assertEqual(summarise_history([{"status": "A"}, {"status": "B"}])["latest_status"], "A")

    def test_a07(self):
        self.assertEqual(run("A07", context())["error_code"], "NO_HISTORY")
        self.assertEqual(run("A07", context(history=[]))["error_code"], "NO_HISTORY")
        ctx = context(history=[{"status": "COMPLETED"}])
        result = run("A07", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a07.history"), [{"runs": 1, "readable": 1, "latest_status": "COMPLETED",
                                                          "statuses": ["COMPLETED"], "counts": [1]}])


class Schema(unittest.TestCase):
    def test_a08(self):
        self.assertEqual(run("A08", context(DRIFTED))["error_code"], "NO_BASELINE")
        ctx = context(DRIFTED, baseline=BASELINE)
        result = run("A08", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a08.schema_diff"), [{
            "status": "BREAKING", "removed": ["order_total"], "added": ["total_amount"], "widened": [], "narrowed": [],
            "reordered": False, "possible_renames": 1}])
        tampered = dict(BASELINE, digest="0" * 64)
        self.assertEqual(run("A08", context(ORDERS, baseline=tampered))["error_code"], "INPUT_REJECTED")

    def test_a08_widened_and_narrowed(self):
        base = build_baseline([("a,b\n" + "".join("%d,x%d\n" % (n, n) for n in range(12))).encode()])
        current = ("a,b\n" + "".join("t%d,%d\n" % (n, n) for n in range(12))).encode()
        result = run("A08", context(current, baseline=base))
        self.assertEqual(params(result, "a08.schema_diff")[0]["widened"], ["a"])
        self.assertEqual(params(result, "a08.schema_diff")[0]["narrowed"], ["b"])

    def test_a09(self):
        self.assertEqual(run("A09", context(TIMED))["error_code"], "NOT_ORDER_EXTRACT")
        ctx = context(NULL_TOTAL)
        result = run("A09", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a09.contract")[0]["status"], "FAIL")
        self.assertEqual(params(result, "a09.check"), [{"check": "not_null", "column": "order_total", "findings": 1}])
        clean = run("A09", context(ORDERS))
        self.assertEqual((params(clean, "a09.contract")[0]["status"], params(clean, "a09.check")), ("PASS", []))
        drifted = run("A09", context(DRIFTED))
        self.assertIn({"check": "missing_column", "column": "order_total", "findings": 1}, params(drifted, "a09.check"))

    def test_a10(self):
        ctx = context(timed_csv(repeat_at=5))
        result = run("A10", ctx)
        assert_bound(self, result, ctx)
        profile = params(result, "a10.profile")[0]
        self.assertEqual((profile["records"], profile["time_column"], profile["status"]), (40, "ts", "FINDINGS"))
        self.assertIn("timestamp_duplicate", [p["check"] for p in params(result, "a10.finding")])
        self.assertEqual(run("A10", context(), tools=[])["status"], "POLICY_DENIED")


class BaselineRoles(unittest.TestCase):
    def test_a11_volume_and_freshness(self):
        self.assertEqual(run("A11", context())["error_code"], "NO_BASELINE")
        ctx = context(BIG_ORDERS, baseline=BASELINE)
        result = run("A11", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a11.volume"), [{"baseline_min": 24, "baseline_max": 24, "current": 80,
                                                         "changed": True, "direction": "increase"}])
        self.assertEqual(params(result, "a11.freshness")[0]["reason"], "no_as_of")
        timed_base = build_baseline([TIMED])
        stale = run("A11", context(TIMED, baseline=timed_base, as_of="2026-01-02T00:00:00+00:00"))
        fresh = params(stale, "a11.freshness")[0]
        self.assertEqual((fresh["evaluated"], fresh["stale"], fresh["reason"]), (True, True, None))
        self.assertEqual(params(stale, "a11.volume")[0]["changed"], False)

    def test_a20_psi(self):
        self.assertEqual(run("A20", context())["error_code"], "NO_BASELINE")
        base = build_baseline([numeric_csv(range(200))])
        ctx = context(numeric_csv(range(500, 700)), baseline=base)
        result = run("A20", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a20.summary"), [{"measured": 1, "shifted": 1, "not_evaluated": 0,
                                                          "threshold": 0.25}])
        self.assertEqual(params(result, "a20.psi")[0]["shifted"], True)
        same = run("A20", context(numeric_csv(range(200)), baseline=base))
        self.assertEqual(params(same, "a20.psi")[0]["shifted"], False)
        small = run("A20", context(ORDERS, baseline=BASELINE))
        self.assertEqual(params(small, "a20.not_evaluated"), [{"column": "order_total",
                                                               "reason": "too_few_values_in_baseline"}])

    def test_a17_type_signals(self):
        self.assertEqual(run("A17", context())["error_code"], "NO_TYPE_SIGNAL")
        self.assertEqual(run("A17", context(ORDERS, baseline=BASELINE))["error_code"], "NO_TYPE_SIGNAL")
        mismatch = numeric_csv([1] * 19 + ["oops"])
        ctx = context(mismatch)
        result = run("A17", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a17.type_mismatch"), [{"column": "v", "count": 1, "expected": "numeric"}])
        texts = ORDERS.decode().splitlines()
        changed = ("\n".join([texts[0]] + [",".join(line.split(",")[:2] + ["n/a"]) for line in texts[1:]]) + "\n")
        result = run("A17", context(changed.encode(), baseline=BASELINE))
        self.assertEqual(params(result, "a17.role_change"), [{"column": "order_total", "baseline": "numeric",
                                                              "current": "text"}])


class Absent(unittest.TestCase):
    def test_a12_and_a16_have_no_source(self):
        for agent, code in (("A12", "NO_LOG_SOURCE"), ("A16", "NO_CDC_SOURCE")):
            result = run(agent, context(history=[{}], baseline=BASELINE))
            self.assertEqual((result["status"], result["error_code"], result["claims"], result["evidence_refs"]),
                             ("NEEDS_EVIDENCE", code, [], []))


class Orders(unittest.TestCase):
    def test_a13(self):
        self.assertEqual(run("A13", context(TIMED))["error_code"], "NOT_ORDER_EXTRACT")
        ctx = context()
        result = run("A13", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a13.downstream")[0]["potential"],
                         ["staging_orders", "customer_sales", "sales_dashboard"])

    def test_a14_and_a19(self):
        for agent in ("A14", "A19"):
            self.assertEqual(run(agent, context(TIMED))["error_code"], "NOT_ORDER_EXTRACT")
        ctx = context()
        transform = run("A14", ctx)
        assert_bound(self, transform, ctx)
        self.assertEqual(params(transform, "a14.transform")[0]["status"], "PASS")
        self.assertEqual(len(params(transform, "a14.artifact")), 3)
        reconciled = run("A19", ctx)
        self.assertEqual([p["check"] for p in params(reconciled, "a19.reconciliation")], ["order_count", "amount_cents"])
        self.assertTrue(all(p["passed"] for p in params(reconciled, "a19.reconciliation")))
        blocked = run("A19", context(NULL_TOTAL))
        self.assertEqual(params(blocked, "a19.blocked"), [{"status": "BLOCKED", "source_findings": 1}])
        self.assertEqual(params(run("A14", context(NULL_TOTAL)), "a14.transform")[0]["status"], "BLOCKED")

    def test_a15(self):
        self.assertEqual(run("A15", context())["error_code"], "NO_TIME_COLUMN")
        ctx = context(timed_csv(gap_at=20, repeat_at=30))
        result = run("A15", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a15.watermark"), [{"time_column": "ts", "gaps": 1, "duplicates": 1,
                                                            "out_of_order": 0, "mixed_timezone": 0}])

    def test_a18_and_a21(self):
        for agent in ("A18", "A21"):
            self.assertEqual(run(agent, context())["error_code"], "NO_SECOND_SOURCE")
            self.assertEqual(run(agent, context(second_payload=TIMED))["error_code"], "NOT_ORDER_EXTRACT")
            self.assertEqual(run(agent, context(TIMED, second_payload=ORDERS))["error_code"], "NOT_ORDER_EXTRACT")
        ctx = context(DUPLICATES, second_payload=ORDERS)
        join = run("A18", ctx)
        assert_bound(self, join, ctx)
        self.assertEqual(params(join, "a18.join")[0]["fan_out"], True)
        self.assertEqual([p["side"] for p in params(join, "a18.keys")], ["first", "second"])
        consistency = run("A21", ctx)
        assert_bound(self, consistency, ctx)
        summary = params(consistency, "a21.consistency")[0]
        self.assertEqual((summary["ambiguous_first"], summary["compared_columns"]),
                         (2, ["customer_id", "order_total"]))
        self.assertEqual([p["column"] for p in params(consistency, "a21.column")], ["customer_id", "order_total"])


def retained(run_id, payload, **extra):
    return {"run_id": run_id, "status": "COMPLETED", "finished_at": "2026-01-0%s" % run_id[-1],
            "result": {"cases": [{"analysis": analyze_csv(payload)}]}, **extra}


PASSAGE = {"source": "runbook", "revision": "r1", "citation": "runbook#duplicates",
           "passage": "Repeated order identifiers double count totals downstream."}


class Knowledge(unittest.TestCase):
    def test_a22_needs_a_source(self):
        self.assertEqual(run("A22", context())["error_code"], "NO_HISTORY_OR_RETRIEVER")
        self.assertEqual(run("A22", context(history=[]))["error_code"], "NO_HISTORY_OR_RETRIEVER")

    def test_a22_retriever_filters_malformed_items_and_records_citations(self):
        queries = []

        def retriever(query, limit):
            queries.append((query, limit))
            return [PASSAGE, {"source": "x"}, "junk", dict(PASSAGE, revision="r" * 65)]
        ctx = context(DUPLICATES, retriever=retriever)
        result = run("A22", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(queries, [("unique order_id", 5)])
        self.assertEqual(params(result, "a22.retrieved"), [{"citations": 1, "rejected": 3}])
        self.assertEqual(result["retrieval"], {"citations": [{k: PASSAGE[k] for k in ("source", "revision",
                                                                                         "citation")}],
                                               "cache": "none"})
        self.assertIsNone(result["llm"])
        odd = run("A22", context(b"a\n1\n", retriever=lambda q, n: {"not": "a list"}))
        self.assertEqual((params(odd, "a22.retrieved"), odd["retrieval"]["citations"]),
                         ([{"citations": 0, "rejected": 0}], []))

    def test_a22_history_similarity(self):
        history = [retained("run-1", DUPLICATES), retained("run-2", ORDERS), "junk", {"run_id": 5},
                   retained("run-3", DUPLICATES, meta="x"), retained("run-4", DUPLICATES, finished_at=5),
                   {"run_id": "run-5", "result": {"cases": [{"analysis": {"row_count": 1}}]}},
                   retained("run-6", DUPLICATES, meta={"name": "orders.csv"})]
        ctx = context(DUPLICATES, history=history)
        result = run("A22", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a22.similar_runs"), [{"matches": 2, "scores": [1.0, 1.0]}])
        self.assertEqual([c["revision"] for c in result["retrieval"]["citations"]], ["run-1", "run-6"])

    def test_a22_model_relevance_is_advisory_and_withholds_passages_with_cell_values(self):
        local, transport = model()
        leaking = dict(PASSAGE, citation="leak", passage="Order ORD-00001 was repeated.")
        ctx = context(DUPLICATES, model=local, retriever=lambda q, n: [PASSAGE, leaking])
        result = run("A22", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a22.relevance"), [{"citations": ["c1"]}])
        self.assertTrue(result["advisory_text"].startswith("c1: "))
        self.assertNotIn("ORD-00001", "".join(transport.prompts()))
        self.assertEqual(len(result["retrieval"]["citations"]), 2)
        self.assertEqual(result["uncertainty"]["reason"], "model_advisory")

    def test_a22_without_offerable_passages_or_model_stays_retrieval_only(self):
        local, transport = model()
        leaking = dict(PASSAGE, passage="Order ORD-00001 was repeated.")
        result = run("A22", context(DUPLICATES, model=local, retriever=lambda q, n: [leaking]))
        self.assertEqual((result["status"], result["llm"], transport.calls), ("COMPLETED", None, []))
        denied = run("A22", context(DUPLICATES, model=local, retriever=lambda q, n: [PASSAGE]),
                     tools=["knowledge_retrieve"])
        self.assertEqual((denied["status"], denied["llm"]), ("COMPLETED", None))
        empty = run("A22", context(DUPLICATES, model=local, retriever=lambda q, n: []))
        self.assertIsNone(empty["llm"])
        for override in (b"garbage", {"relevance": []}):
            failing, _ = model(override)
            result = run("A22", context(DUPLICATES, model=failing, retriever=lambda q, n: [PASSAGE]))
            with self.subTest(override=override):
                self.assertEqual((result["status"], [c["text_key"] for c in result["claims"]]),
                                 ("COMPLETED", ["a22.retrieved"]))
                self.assertIsNotNone(result["llm"])
                self.assertEqual(result["retrieval"]["cache"], "none")


if __name__ == "__main__":
    unittest.main()
