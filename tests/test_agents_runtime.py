# SPDX-License-Identifier: Apache-2.0
"""The agent runtime: selection, waves, budgets, recovery, the Judge gate, events and the sealed run record.

The local model is the recorded-response fake from agents_support (no Ollama). Unless a test needs the optional
paths, runs use transport="in_process"; tests/test_agents_transport.py covers MCP and A2A, and the "auto" runs here
exercise them through the runtime.
"""
import copy
from datetime import datetime, timezone
import json
import shutil
import threading
import time
import unittest
from unittest import mock

from agents_support import (BASELINE, BIG_ORDERS, DRIFTED, DUPLICATES, ORDERS, TIMED, FakeTransport, envelope, model,
                            timed_csv)
from aegisflow_dr.advisory.context_cache import ContextCache
from aegisflow_dr.agents import runtime, transport as transports
from aegisflow_dr.agents.context import PolicyDenied
from aegisflow_dr.agents.contracts import STATUSES, validate_event, validate_run
from aegisflow_dr.agents.events import EVENT_TYPES, EventLog
from aegisflow_dr.agents.executors import resolve
from aegisflow_dr.agents.executors.orchestration import SPECIALISTS
from aegisflow_dr.agents.executors.reasoning import CLAIM_WORDS, free_text_params, judge
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.agents.runtime import AGENT_IDS, Budget, Case, run_case, trace_digest, verify_record
from aegisflow_dr.pipeline import InputRejected

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
RETRIEVER = lambda query, limit: [{"source": "kb/runbook.md", "revision": "r1", "citation": "kb#1",  # noqa: E731
                                   "passage": "Duplicate deliveries and replays"}]
GAP = timed_csv(gap_at=5, repeat_at=9)
HISTORY = [{"run_id": "r-1", "status": "PASS", "finished_at": "2026-11-01T00:00:00Z"}]


class Clock:
    """A thread-safe manual clock (seconds)."""

    def __init__(self, value=0.0):
        self.value, self._lock = value, threading.Lock()

    def __call__(self):
        with self._lock:
            return self.value

    def advance(self, seconds):
        with self._lock:
            self.value += seconds


def execute(case, **kwargs):
    kwargs.setdefault("transport", "in_process")
    kwargs.setdefault("clock", Clock())
    kwargs.setdefault("now", lambda: NOW)
    kwargs.setdefault("run_id", "run-test")
    return run_case(case, **kwargs)


def row(record, agent):
    return record["agents"][AGENT_IDS.index(agent)]


def result(record, agent):
    return row(record, agent)["result"]


def selection(record):
    return {item["agent_id"]: item for item in record["selection"]}


def events(record, kind, agent=None):
    return [e for e in record["events"] if e["type"] == kind and (agent is None or e["agent_id"] == agent)]


def wrapped(overrides):
    """Patch runtime.resolve so ``overrides[agent](task, ctx, execute)`` replaces chosen executors."""
    def fake(agent):
        execute_agent = resolve(agent)
        if agent not in overrides:
            return execute_agent
        return lambda task, ctx: overrides[agent](task, ctx, execute_agent)
    return mock.patch.object(runtime, "resolve", side_effect=fake)


class Selection(unittest.TestCase):
    def test_every_role_appears_once_with_a_status_and_a_reason(self):
        local, _ = model()
        for case in (Case(ORDERS, "orders"), Case(TIMED, "timed"),
                     Case(DRIFTED, "drift", baseline=BASELINE, history=HISTORY, retriever=RETRIEVER),
                     Case(BIG_ORDERS, "big", baseline=BASELINE, second_payload=ORDERS, history=HISTORY,
                          retriever=RETRIEVER)):
            with self.subTest(case.case_id):
                record = execute(case, model=local)
                self.assertEqual([a["agent_id"] for a in record["agents"]], list(AGENT_IDS))
                self.assertEqual([s["agent_id"] for s in record["selection"]], list(AGENT_IDS))
                for item in record["selection"]:
                    status = result(record, item["agent_id"])["status"]
                    self.assertIn(status, STATUSES)
                    self.assertTrue(item["reason"])
                    if not item["selected"]:
                        self.assertEqual((status, item["error_code"]), ("SKIPPED", "NOT_SELECTED"))
                        self.assertIsNone(row(record, item["agent_id"])["task"])
                finished = {e["agent_id"] for e in events(record, "agent_finished")}
                skipped = {e["agent_id"] for e in events(record, "agent_skipped")}
                self.assertEqual(finished | skipped, set(AGENT_IDS))

    def test_routing_follows_the_trigger_table(self):
        timed = selection(execute(Case(TIMED, "timed")))
        self.assertEqual([a for a in SPECIALISTS if timed[a]["selected"]], ["A10", "A15"])
        self.assertEqual((timed["A12"]["reason"], timed["A16"]["reason"], timed["A08"]["reason"]),
                         ("no_log_source", "no_cdc_source", "no_baseline"))
        self.assertEqual((timed["A28"]["reason"], timed["A30"]["reason"], timed["A06"]["reason"]),
                         ("a24_not_selected", "not_order_extract", "no_failed_agent"))
        self.assertEqual((timed["A29"]["reason"], timed["A33"]["reason"]), ("accepted_findings", "no_proposals"))
        big = execute(Case(BIG_ORDERS, "big", baseline=BASELINE, second_payload=ORDERS, history=HISTORY,
                           retriever=RETRIEVER))
        chosen = selection(big)
        specialists = [a for a in SPECIALISTS if chosen[a]["selected"]]
        self.assertEqual(len(specialists), 8)
        dropped = [a for a in SPECIALISTS if chosen[a]["reason"] == "specialist_limit"]
        self.assertTrue(dropped)
        for agent in dropped:
            self.assertEqual((chosen[agent]["selected"], chosen[agent]["error_code"]), (False, "NOT_SELECTED"))
        self.assertEqual(big["status"], "completed_with_gaps")  # the router limit is selection, not a budget stop
        self.assertEqual(big["budget"]["exceeded"], [])
        self.assertTrue(all(chosen[a]["selected"] for a in ("A24", "A25", "A28", "A23")))

    def test_without_a_model_llm_roles_report_model_unavailable(self):
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE))
        self.assertEqual((result(record, "A23")["status"], result(record, "A23")["error_code"]),
                         ("NEEDS_EVIDENCE", "MODEL_UNAVAILABLE"))
        self.assertEqual(result(record, "A29")["error_code"], "MODEL_UNAVAILABLE")
        for agent, prerequisite in (("A30", "A29"), ("A31", "A30"), ("A32", "A30")):  # gated, not run
            self.assertEqual((result(record, agent)["error_code"], selection(record)[agent]["unmet"]),
                             ("DEPENDENCY_UNMET", [prerequisite]))
        self.assertEqual((result(record, "A02")["status"], result(record, "A02")["llm"]), ("COMPLETED", None))
        self.assertEqual(record["usage"]["totals"]["llm_calls"], 0)

    def test_order_extract_chain_reaches_validators_and_a_pending_approval(self):
        local, _ = model()
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
        self.assertEqual(result(record, "A30")["status"], "COMPLETED")
        self.assertEqual([result(record, a)["error_code"] for a in ("A31", "A32")],
                         ["SANDBOX_WRITES_DISABLED", "NO_BACKFILL_TARGET"])
        self.assertTrue(record["proposals"])
        self.assertTrue(all(p["executed"] is False for p in record["proposals"]))
        self.assertEqual(record["approvals"][0]["decision"], "pending")
        self.assertEqual(len(record["approvals"][0]["items"]), len(record["proposals"]))
        approval = events(record, "approval_requested", "A33")
        self.assertEqual(approval[0]["data"], {"items": len(record["proposals"]), "decision": "pending",
                                               "executed": False})
        timed = execute(Case(TIMED, "timed"), model=local)
        self.assertEqual(selection(timed)["A30"]["reason"], "not_order_extract")

    def test_unreadable_case_ends_the_run_as_input_rejected(self):
        record = execute(Case(b"\xff\xfe\x00broken", "bad"))
        self.assertEqual(record["status"], "input_rejected")
        self.assertEqual((result(record, "A01")["status"], result(record, "A01")["error_code"]),
                         ("FAILED", "INPUT_REJECTED"))
        for agent in AGENT_IDS[1:]:
            self.assertEqual(result(record, agent)["error_code"], "INTAKE_REJECTED")
        self.assertIsNone(record["intake"])
        self.assertEqual(record["judge"]["verdicts"], [])
        self.assertEqual(record["events"][-1]["type"], "run_finished")
        self.assertEqual(events(record, "agent_started", "A01"), [])  # no A01 executor ran
        self.assertTrue(events(record, "agent_finished", "A01")[0]["data"]["runtime"])
        verify_record(record)


class Waves(unittest.TestCase):
    def test_waves_are_bounded_and_follow_dependencies(self):
        local, _ = model()
        record = execute(Case(BIG_ORDERS, "big", baseline=BASELINE, second_payload=ORDERS, history=HISTORY,
                              retriever=RETRIEVER), model=local)
        self.assertTrue(all(1 <= len(w["agents"]) <= 4 for w in record["waves"]))
        self.assertEqual([w["wave"] for w in record["waves"]], list(range(1, len(record["waves"]) + 1)))
        wave = {a: row(record, a)["wave"] for a in AGENT_IDS}
        ran = [a for a in SPECIALISTS if wave[a] is not None]
        self.assertTrue(all(wave["A10"] < wave[a] for a in ran if a != "A10"))
        self.assertTrue(all(wave[a] < wave["A24"] for a in ran))  # A24/A25 after A11/A20 and every specialist
        self.assertLess(wave["A24"], wave["A23"])
        self.assertLess(wave["A25"], wave["A23"])
        self.assertLess(wave["A24"], wave["A28"])
        self.assertLess(wave["A28"], wave["A27"])
        self.assertLess(wave["A27"], wave["A29"])
        self.assertLess(wave["A29"], wave["A30"])
        self.assertEqual(wave["A31"], wave["A32"])
        self.assertLess(wave["A30"], wave["A31"])
        self.assertEqual(wave["A01"], len(record["waves"]))
        finished = {e["agent_id"]: e["seq"] for e in events(record, "agent_finished")}
        for event in events(record, "agent_started"):
            for dependency in event["data"]["depends_on"]:
                self.assertLess(finished[dependency], event["seq"])
        for item in record["waves"]:  # results and events of a wave are published in agent-id order
            seqs = [finished[a] for a in item["agents"]]
            self.assertEqual(seqs, sorted(seqs))

    def test_a_wave_runs_concurrently(self):
        barrier = threading.Barrier(4, timeout=5)

        def together(task, ctx, execute_agent):
            barrier.wait()
            return execute_agent(task, ctx)

        with wrapped({a: together for a in ("A08", "A09", "A11", "A13")}):
            record = execute(Case(DRIFTED, "drift", baseline=BASELINE))
        self.assertIn(["A08", "A09", "A11", "A13"], [w["agents"] for w in record["waves"]])
        self.assertTrue(all(result(record, a)["status"] == "COMPLETED" for a in ("A08", "A09", "A11", "A13")))


class Budgets(unittest.TestCase):
    def test_budget_validation(self):
        for bad in ({"specialists": 9}, {"llm_calls": -1}, {"tokens": 40_001}, {"wall_ms": 0},
                    {"agent_deadline_ms": 90_001}, {"specialists": True}):
            with self.subTest(bad), self.assertRaises(InputRejected):
                Budget(**bad)
        self.assertEqual(Budget().limits(), {"specialists": 8, "llm_calls": 12, "tokens": 40_000,
                                             "elapsed_ms": 90_000})

    def assert_stopped(self, record, limit):
        self.assertEqual(record["status"], "budget_exceeded")
        self.assertIn(limit, record["budget"]["exceeded"])
        self.assertEqual(json.loads(json.dumps(result(record, "A05")["claims"][0]["text_key"])), "a05.budget_exceeded")
        reasons = [e["data"]["reason"] for e in events(record, "agent_skipped") if e["data"]["error_code"]
                   == "BUDGET_EXCEEDED"]
        self.assertTrue(reasons)
        return reasons

    def test_llm_call_limit(self):
        local, transport = model()
        record = execute(Case(GAP, "gap", baseline=BASELINE, retriever=RETRIEVER), model=local,
                         budget=Budget(llm_calls=1))
        reasons = self.assert_stopped(record, "llm_calls")
        self.assertEqual(set(reasons), {"llm_calls_limit"})
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(record["budget"]["used"]["llm_calls"], 1)
        for agent in ("A23", "A29"):
            self.assertEqual((result(record, agent)["status"], result(record, agent)["error_code"]),
                             ("SKIPPED", "BUDGET_EXCEEDED"))
            self.assertTrue(selection(record)[agent]["selected"])
        a22 = result(record, "A22")  # a hybrid keeps its rule part without a model call
        budget = row(record, "A22")["task"]["budget"]
        self.assertEqual((a22["status"], a22["usage"]["llm_calls"], budget["max_llm_calls"]), ("COMPLETED", 0, 0))

    def test_token_limit(self):
        local, _ = model()
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local, budget=Budget(tokens=60))
        self.assertEqual(row(record, "A02")["task"]["budget"]["max_tokens"], 60)
        self.assertEqual(result(record, "A23")["error_code"], "TOKEN_BUDGET_EXCEEDED")
        self.assertEqual(set(self.assert_stopped(record, "tokens")), {"tokens_limit"})
        self.assertEqual(result(record, "A29")["error_code"], "BUDGET_EXCEEDED")

    def test_wall_time_limit_and_bounded_model_calls(self):
        clock = Clock()
        inner = FakeTransport()
        timeouts = []

        def hanging(url, body, timeout):  # a model that never answers in time: it honours the call timeout
            timeouts.append(timeout)
            clock.advance(timeout)
            raise TimeoutError("no answer")

        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=LocalModel(transport=hanging), clock=clock,
                         budget=Budget(wall_ms=50_000))
        self.assertEqual(timeouts, [30.0, 20.0])  # A02: the model limit; A23: the 20 s left of the run
        self.assertEqual((result(record, "A02")["status"], result(record, "A02")["llm"]), ("COMPLETED", None))
        self.assertEqual((result(record, "A23")["status"], result(record, "A23")["error_code"]),
                         ("NEEDS_EVIDENCE", "TIMEOUT"))
        self.assertEqual(set(self.assert_stopped(record, "elapsed_ms")), {"time_limit"})
        self.assertEqual(result(record, "A29")["error_code"], "BUDGET_EXCEEDED")
        for agent in ("A27", "A34", "A35", "A36", "A26", "A01"):  # closing controls still close the run
            self.assertEqual(result(record, agent)["status"], "COMPLETED", agent)
        self.assertEqual(record["duration_ms"], 50_000)  # never beyond the wall limit
        self.assertFalse(inner.calls)

    def test_a_hanging_agent_is_cut_at_its_deadline(self):
        release = threading.Event()
        entered = []

        def hanging(query, limit):
            entered.append(query)
            release.wait(10)
            return RETRIEVER(query, limit)

        started = time.perf_counter()
        try:
            record = execute(Case(ORDERS, "orders", retriever=hanging), budget=Budget(agent_deadline_ms=300))
        finally:
            release.set()
        self.assertLess(time.perf_counter() - started, 5)
        a22 = result(record, "A22")
        self.assertEqual((a22["status"], a22["error_code"]), ("FAILED", "DEADLINE_EXCEEDED"))
        self.assertEqual(record["abandoned"], ["A22"])
        self.assertEqual(record["recovery"][0]["decision"], "safe_stop")  # a deadline is never retried
        finished = events(record, "agent_finished", "A22")[0]["data"]
        self.assertEqual((finished["status"], finished["abandoned"]), ("FAILED", True))
        self.assertEqual(len(entered), 1)
        self.assertEqual(result(record, "A01")["status"], "COMPLETED")

    def test_no_model_call_once_the_deadline_is_spent(self):
        clock = Clock()

        def slow(query, limit):
            clock.advance(2)
            return RETRIEVER(query, limit)

        local, transport = model()
        record = execute(Case(GAP, "gap", retriever=slow), model=local, clock=clock,
                         budget=Budget(agent_deadline_ms=1000))
        a22 = result(record, "A22")
        self.assertEqual((a22["status"], a22["error_code"], a22["usage"]["latency_ms"]),
                         ("FAILED", "DEADLINE_EXCEEDED", 2000))
        self.assertEqual(a22["usage"]["tool_calls"], 1)  # the work done before the deadline stays accounted
        self.assertNotIn("relevance", [next(iter(c["format"]["properties"])) for c in transport.calls])
        self.assertEqual(record["abandoned"], [])  # measured on the run clock, not cut in real time

    def test_late_writes_of_an_abandoned_agent_never_reach_the_record(self):
        def run(late):
            wrote, release = threading.Event(), threading.Event()

            def retriever(query, limit):
                (time.sleep if late else release.wait)(0.6)
                return RETRIEVER(query, limit)

            def a22(task, ctx, execute_agent):
                value = execute_agent(task, ctx)  # stores its retrieval evidence after the deadline
                wrote.set()
                return value

            def hold(event):  # the run thread waits for the late write before going on (only in the late run)
                if late and event["type"] == "agent_finished" and event["agent_id"] == "A22":
                    wrote.wait(5)

            try:
                with wrapped({"A22": a22}):
                    return execute(Case(ORDERS, "orders", retriever=retriever), budget=Budget(agent_deadline_ms=300),
                                   on_event=hold)
            finally:
                release.set()
                self.assertTrue(wrote.wait(5) if late else True)

        late, silent = run(True), run(False)
        self.assertEqual(late["abandoned"], ["A22"])
        self.assertNotIn("retrieval", {ref["kind"] for ref in late["evidence"]})
        self.assertEqual(late, silent)
        self.assertEqual(late["trace_sha256"], silent["trace_sha256"])

    def test_closing_agents_respect_the_wall_limit_with_a_fixed_grace(self):
        normal = execute(Case(ORDERS, "orders"))
        self.assertEqual(row(normal, "A27")["task"]["budget"]["deadline_ms"], 60_000)
        clock = Clock()

        def hanging(url, body, timeout):
            clock.advance(timeout)
            raise TimeoutError("no answer")

        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=LocalModel(transport=hanging), clock=clock,
                         budget=Budget(wall_ms=50_000))
        for agent in ("A27", "A34", "A35", "A36", "A26", "A05", "A01"):
            self.assertEqual(row(record, agent)["task"]["budget"]["deadline_ms"], runtime.CLOSING_GRACE_MS, agent)

    def test_model_call_timeout_never_exceeds_the_task_deadline(self):
        local, transport = model()
        execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local, budget=Budget(agent_deadline_ms=1500))
        seen = list(transport.timeouts)
        self.assertTrue(seen)
        self.assertTrue(all(0 < t <= 1.5 for t in seen))

    def test_specialist_limit(self):
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), budget=Budget(specialists=2))
        self.assertEqual(set(self.assert_stopped(record, "specialists")), {"specialist_limit"})
        ran = [a for a in SPECIALISTS if result(record, a)["status"] not in ("SKIPPED",)]
        self.assertEqual(len(ran), 2)
        self.assertEqual(record["budget"]["used"]["specialists"], 2)


class Dependencies(unittest.TestCase):
    def fail(self, task, ctx, execute_agent):
        raise RuntimeError("bug")

    def test_a_failed_profile_gates_every_dependent(self):
        local, _ = model()
        with wrapped({"A10": self.fail}):
            record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
        self.assertEqual((result(record, "A10")["status"], row(record, "A10")["attempts"]), ("FAILED", 2))
        gated = {a: selection(record)[a]["unmet"] for a in AGENT_IDS
                 if result(record, a)["error_code"] == "DEPENDENCY_UNMET"}
        self.assertEqual(gated, {"A08": ["A10"], "A09": ["A10"], "A11": ["A10"], "A13": ["A10"], "A14": ["A10"],
                                 "A19": ["A10"], "A20": ["A10"], "A24": ["A11", "A20"], "A25": ["A11", "A20"],
                                 "A23": ["A24", "A25"], "A28": ["A24"]})
        for agent, unmet in gated.items():
            event = events(record, "agent_skipped", agent)[-1]["data"]
            self.assertEqual((event["reason"], event["error_code"], event["unmet"]),
                             ("dependency_unmet", "DEPENDENCY_UNMET", unmet))
            self.assertIsNone(row(record, agent)["task"])
            self.assertTrue(selection(record)[agent]["selected"])
        self.assertEqual(record["status"], "failed_agents")

    def test_a_failed_counter_hypothesis_gates_a23_and_a28(self):
        local, _ = model()
        def typed(status, code):
            return lambda task, ctx, execute_agent: runtime._typed("A24", task["task_id"], status, code)

        for name, fake in (("failed", self.fail), ("needs_evidence", typed("NEEDS_EVIDENCE", "NO_BASELINE")),
                           ("policy_denied", typed("POLICY_DENIED", "TOOL_NOT_ALLOWED"))):
            with self.subTest(name), wrapped({"A24": fake}):
                record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
            self.assertEqual({a: result(record, a)["error_code"] for a in ("A23", "A28")},
                             {"A23": "DEPENDENCY_UNMET", "A28": "DEPENDENCY_UNMET"})
            self.assertEqual((selection(record)["A23"]["unmet"], selection(record)["A28"]["unmet"]),
                             (["A24"], ["A24"]))
            self.assertEqual(result(record, "A25")["status"], "COMPLETED")
            self.assertEqual(result(record, "A29")["status"], "COMPLETED")  # specialist findings still feed A29

    def test_a_retry_that_succeeds_releases_the_dependents(self):
        calls = []

        def once(task, ctx, execute_agent):
            calls.append(task["task_id"])
            if len(calls) == 1:
                raise RuntimeError("transient")
            return execute_agent(task, ctx)

        with wrapped({"A10": once}):
            record = execute(Case(DRIFTED, "drift", baseline=BASELINE))
        self.assertEqual((result(record, "A10")["status"], row(record, "A10")["attempts"]), ("COMPLETED", 2))
        self.assertEqual(result(record, "A08")["status"], "COMPLETED")
        investigated = SPECIALISTS + ("A23", "A24", "A25", "A28")  # (no model here, so A29 needs evidence)
        self.assertFalse([a for a in investigated if result(record, a)["error_code"] == "DEPENDENCY_UNMET"])

    def test_a_budget_skipped_prerequisite_is_unmet_and_unselected_ones_do_not_block(self):
        local, _ = model()
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local, budget=Budget(llm_calls=2))
        self.assertEqual(result(record, "A29")["error_code"], "BUDGET_EXCEEDED")
        self.assertEqual((result(record, "A30")["error_code"], selection(record)["A30"]["unmet"]),
                         ("DEPENDENCY_UNMET", ["A29"]))
        gap = execute(Case(GAP, "gap"), model=local)  # A23 without a baseline: A24/A25 not selected
        self.assertEqual(result(gap, "A23")["status"], "COMPLETED")


class Recovery(unittest.TestCase):
    def test_a_failed_agent_is_retried_once_with_the_same_task(self):
        calls = []

        def flaky(query, limit):
            calls.append(query)
            if len(calls) == 1:
                raise OSError("index offline")
            return RETRIEVER(query, limit)

        record = execute(Case(ORDERS, "orders", retriever=flaky))
        a22 = result(record, "A22")
        self.assertEqual((a22["status"], row(record, "A22")["attempts"]), ("COMPLETED", 2))
        self.assertEqual(a22["usage"]["tool_calls"], 2)  # both attempts are accounted
        self.assertEqual(record["recovery"], [{"agent": "A22", "error_code": "TOOL_ERROR",
                                               "decision": "retry_once_same_input", "retried": True}])
        self.assertEqual(result(record, "A06")["status"], "COMPLETED")
        self.assertEqual(selection(record)["A06"]["reason"], "failed_agent")
        starts = events(record, "agent_started", "A22")
        self.assertEqual([e["data"]["attempt"] for e in starts], [1, 2])
        self.assertEqual(starts[0]["data"]["budget"], starts[1]["data"]["budget"])
        self.assertEqual(calls[0], calls[1])

    def test_a_retry_happens_only_once(self):
        def broken(query, limit):
            raise OSError("index offline")

        record = execute(Case(ORDERS, "orders", retriever=broken))
        self.assertEqual((result(record, "A22")["status"], row(record, "A22")["attempts"]), ("FAILED", 2))
        self.assertEqual(record["status"], "failed_agents")
        self.assertEqual(len(record["recovery"]), 1)

    def test_no_retry_codes_and_executor_errors(self):
        def rejected(task, ctx, execute_agent):
            return runtime._typed("A13", task["task_id"], "FAILED", "INPUT_REJECTED")

        def crash(task, ctx, execute_agent):
            raise RuntimeError("bug")

        with wrapped({"A13": rejected, "A14": crash, "A33": crash}):
            record = execute(Case(ORDERS, "orders"), model=model()[0])
        self.assertEqual([(i["agent"], i["decision"], i["retried"]) for i in record["recovery"]],
                         [("A13", "safe_stop", False), ("A14", "retry_once_same_input", True),  # specialists' wave
                          ("A33", "retry_once_same_input", True)])  # a second recovery, later in the run
        self.assertEqual(record["recovery"][1]["error_code"], "EXECUTOR_ERROR")
        self.assertEqual((row(record, "A13")["attempts"], row(record, "A14")["attempts"]), (1, 2))
        self.assertEqual(len(events(record, "agent_selected", "A06")), 1)
        self.assertEqual(row(record, "A06")["attempts"], 2)
        self.assertEqual((record["approvals"], events(record, "approval_requested")), ([], []))

    def test_tool_outcomes_are_labelled_in_events(self):
        def rejecting(query, limit):
            raise InputRejected("bad query")

        with mock.patch.object(transports.McpTools, "invoke", side_effect=PolicyDenied("TOOL_NOT_ALLOWED")):
            record = execute(Case(ORDERS, "orders", retriever=rejecting), transport="mcp")
        outcomes = {e["data"]["tool"]: e["data"]["outcome"] for e in events(record, "tool_call")
                    if e["data"]["phase"] == "agent"}
        self.assertEqual((outcomes["knowledge_retrieve"], outcomes["diagnose_csv"], outcomes["profile_csv"]),
                         ("input_rejected", "denied", "ok"))
        self.assertEqual(result(record, "A09")["status"], "POLICY_DENIED")
        self.assertEqual(result(record, "A22")["error_code"], "INPUT_REJECTED")

    def test_no_retry_when_the_budget_is_spent(self):
        clock = Clock()

        def slow_failure(query, limit):
            clock.advance(90)
            raise OSError("index offline")

        record = execute(Case(ORDERS, "orders", retriever=slow_failure), clock=clock,
                         budget=Budget(agent_deadline_ms=90_000))
        self.assertEqual(record["recovery"], [{"agent": "A22", "error_code": "TOOL_ERROR",
                                               "decision": "retry_once_same_input", "retried": False}])
        self.assertEqual(row(record, "A22")["attempts"], 1)

    def test_router_and_scheduler_failures_skip_the_routed_roles(self):
        def fail(task, ctx, execute_agent):
            return runtime._typed(task["agent_id"], task["task_id"], "FAILED", "INPUT_REJECTED")

        for agent, reason in (("A03", "router_unavailable"), ("A04", "dependency_unmet")):
            with self.subTest(agent), wrapped({agent: fail}):
                record = execute(Case(ORDERS, "orders"))
            self.assertEqual(selection(record)["A10"]["reason"] if agent == "A03" else
                             events(record, "agent_skipped", "A10")[0]["data"]["reason"], reason)
            self.assertEqual(result(record, "A10")["status"], "SKIPPED")
            self.assertEqual(selection(record)["A10" if agent == "A04" else "A04"]["unmet"], [agent])
            self.assertEqual(record["status"], "failed_agents")


class JudgeGate(unittest.TestCase):
    def test_forged_missing_free_text_and_model_support_are_rejected(self):
        ghost = {"id": "profile:" + "0" * 32, "sha256": "0" * 64}

        def tamper(task, ctx, execute_agent):
            value = execute_agent(task, ctx)
            ref = value["claims"][0]["evidence_refs"][0]
            forged = {"id": ref["id"], "sha256": "f" * 64}
            suggestion = ctx.evidence.put("llm_suggestion", {"agent": "A23", "data": {"candidates": []}})
            value = copy.deepcopy(value)
            value["evidence_refs"] += [forged, ghost, suggestion]
            value["claims"] = [
                {"text_key": "a10.profile", "params": {"records": 1}, "evidence_refs": [forged]},
                {"text_key": "a10.profile", "params": {"records": 1}, "evidence_refs": [ghost]},
                {"text_key": "a10.finding", "params": {"check": "the model thinks it is a duplicate"},
                 "evidence_refs": [ref]},
                {"text_key": "a10.profile", "params": {"records": 24}, "evidence_refs": [suggestion]},
                {"text_key": "a10.profile", "params": {"records": 24}, "evidence_refs": [ref]}]
            return value

        local, transport = model()
        with wrapped({"A10": tamper}):
            record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
        reasons = [(v["claim"], v["verdict"], v["reason"]) for v in record["judge"]["verdicts"] if v["agent"] == "A10"]
        self.assertEqual(reasons, [(0, "rejected", "evidence_missing_or_altered"),
                                   (1, "rejected", "evidence_missing_or_altered"),
                                   (2, "rejected", "free_text_in_params"),
                                   (3, "rejected", "model_suggestion_as_support"),
                                   (4, "accepted", "evidence_verified")])
        self.assertIn({"agent": "A10", "claim": 4}, record["judge"]["accepted_findings"])
        self.assertNotIn({"agent": "A10", "claim": 2}, record["judge"]["accepted_findings"])
        a29 = next(r for r in transport.calls if "options" in r["format"]["properties"])
        self.assertNotIn("the model thinks", a29["messages"][1]["content"])
        verdict_events = [e for e in events(record, "judge_verdict", "A27") if e["data"]["subject"] == "A10"]
        self.assertEqual((verdict_events[0]["data"]["rejected"], verdict_events[0]["data"]["accepted"]), (4, 1))

    def test_model_claims_are_advisory_and_later_claims_get_a_closing_pass(self):
        local, _ = model()
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
        verdicts = record["judge"]["verdicts"]
        a29 = [v for v in verdicts if v["agent"] == "A29"]
        self.assertEqual([(v["verdict"], v["pass"]) for v in a29], [("advisory", "closing")])
        self.assertTrue({v["agent"] for v in verdicts if v["pass"] == "closing"} >= {"A01", "A26", "A33", "A36"})
        self.assertFalse([v for v in verdicts if v["reason"] == "free_text_in_params"])
        self.assertTrue(all(f["agent"] in SPECIALISTS for f in record["judge"]["accepted_findings"]))
        self.assertEqual(record["judge"]["accepted"] + record["judge"]["advisory"] + record["judge"]["rejected"],
                         len(verdicts))

    def test_free_text_rule(self):
        names = frozenset({"order_id"})
        self.assertFalse(free_text_params({"column": "order_id", "agents": ["A10", "obs-1"], "count": 3,
                                           "status": "PASS", "digest": "a" * 64, "flag": None}, names))
        self.assertTrue(free_text_params({"column": "Order Id"}, names))
        self.assertTrue(free_text_params({"items": ["duplicate_delivery", "some words"]}, names))
        self.assertIn("declared_dataset_dag", CLAIM_WORDS)
        self.assertFalse(free_text_params({"error_code": "TOOL_ERROR", "status": "COMPLETED", "latest": "UNKNOWN"},
                                          names))
        self.assertTrue(free_text_params({"error_code": "THE_MODEL_SAYS_DROP_IT"}, names))  # not a declared code
        self.assertEqual(judge({}, None, [], names=names), [])
        with self.assertRaises(TypeError):  # the case's column names are required, never silently empty
            judge({}, None, [])


class Record(unittest.TestCase):
    def test_determinism_with_a_fake_model(self):
        records = []
        for _ in range(2):
            local, _ = model()
            records.append(execute(Case(DRIFTED, "drift", baseline=BASELINE, history=HISTORY, retriever=RETRIEVER),
                                   model=local))
        self.assertEqual(records[0], records[1])
        self.assertEqual(records[0]["trace_sha256"], trace_digest(records[0]))
        local, _ = model()
        over_mcp = execute(Case(DRIFTED, "drift", baseline=BASELINE, history=HISTORY, retriever=RETRIEVER),
                           model=local, transport="mcp")
        def tool_evidence(record):  # stored results carry their transport label; tool evidence must not differ
            return [ref for ref in record["evidence"] if ref["kind"] not in ("agent_result", "evidence_index")]

        self.assertEqual(tool_evidence(over_mcp), tool_evidence(records[0]))
        self.assertEqual(over_mcp["transports"]["agents"]["A09"], "mcp_local")
        self.assertEqual(over_mcp["judge"]["verdicts"], records[0]["judge"]["verdicts"])

    def test_record_validates_and_the_digest_detects_edits(self):
        record = execute(Case(ORDERS, "orders"))
        self.assertIs(verify_record(record), record)
        validate_run(record)
        self.assertEqual((record["started_at"], record["finished_at"]), ("2026-11-24T12:00:00.000Z",) * 2)
        for edit in (lambda r: r.update(status="completed" if r["status"] != "completed" else "failed_agents"),
                     lambda r: r["agents"][9]["result"]["claims"][0]["params"].update(records=999),
                     lambda r: r["events"].pop()):
            changed = copy.deepcopy(record)
            edit(changed)
            with self.assertRaisesRegex(InputRejected, "trace digest"):
                verify_record(changed)
        broken = copy.deepcopy(record)
        broken["status"] = "fine"
        with self.assertRaisesRegex(InputRejected, "contract"):
            verify_record(broken)

    def test_usage_rollup_counts_intake_calls(self):
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE))
        intake = record["usage"]["intake"]
        self.assertEqual([(c["agent"], c["tool"]) for c in intake["calls"]],
                         [("A10", "profile_csv"), ("A01", "baseline_compare"), ("A01", "diagnose_csv")])
        tool_events = [e for e in events(record, "tool_call") if e["data"]["phase"] == "intake"]
        self.assertEqual([(e["agent_id"], e["data"]["tool"], e["data"]["outcome"]) for e in tool_events],
                         [("A10", "profile_csv", "ok"), ("A01", "baseline_compare", "ok"),
                          ("A01", "diagnose_csv", "ok")])
        agents_total = sum(u["tool_calls"] for u in record["usage"]["agents"].values())
        self.assertEqual(record["usage"]["totals"]["tool_calls"], agents_total + 3)
        self.assertEqual(record["usage"]["external_spend_usd"], 0)
        per_agent = [e for e in events(record, "tool_call") if e["data"]["phase"] == "agent"]
        self.assertEqual(len(per_agent), agents_total)

    def test_invalid_requests(self):
        case = Case(ORDERS, "orders")
        for kwargs in ({"budget": {}}, {"clock": 1}, {"now": 1}, {"on_event": 1}, {"model": object()},
                       {"cache": object()}, {"run_id": "Bad Id"}, {"transport": "carrier-pigeon"}):
            with self.subTest(kwargs), self.assertRaises(InputRejected):
                run_case(case, **kwargs)
        with self.assertRaises(InputRejected):
            run_case("not a case")
        with self.assertRaisesRegex(InputRejected, "aware datetime"):
            run_case(case, now=lambda: datetime(2026, 1, 1), transport="in_process")
        record = run_case(case, transport="in_process")
        self.assertRegex(record["run_id"], r"^run-[0-9a-f]{24}$")


class Events(unittest.TestCase):
    def test_agent_finished_is_published_when_the_agent_completes(self):
        received = []

        def slow(task, ctx, execute_agent):
            time.sleep(0.3)
            return execute_agent(task, ctx)

        with wrapped({"A08": slow}):  # A08 and A09 share a wave; the lower id is the slower one
            record = execute(Case(DRIFTED, "drift", baseline=BASELINE), on_event=received.append,
                             clock=time.monotonic)
        live = [e["agent_id"] for e in received if e["type"] == "agent_finished" and e["agent_id"] in ("A08", "A09")]
        self.assertEqual(live, ["A09", "A08"])
        sealed = [e for e in record["events"] if e["type"] == "agent_finished" and e["agent_id"] in ("A08", "A09")]
        self.assertEqual([e["agent_id"] for e in sealed], ["A08", "A09"])  # the record keeps agent-id order
        self.assertGreater(sealed[0]["t_ms"], sealed[1]["t_ms"])  # each stamped at its real completion
        self.assertEqual([e["seq"] for e in record["events"]], list(range(1, len(record["events"]) + 1)))

    def test_on_event_receives_exactly_the_recorded_events(self):
        received = []

        def subscriber(event):
            received.append(copy.deepcopy(event))
            event["data"]["tampered"] = True

        local, _ = model()
        cache = ContextCache()
        record = execute(Case(GAP, "gap", baseline=BASELINE, retriever=RETRIEVER), model=local, cache=cache,
                         on_event=subscriber)
        self.assertEqual([e["seq"] for e in received], list(range(1, len(received) + 1)))  # arrival order
        self.assertEqual(sorted(json.dumps({k: v for k, v in e.items() if k != "seq"}, sort_keys=True)
                                for e in received),
                         sorted(json.dumps({k: v for k, v in e.items() if k != "seq"}, sort_keys=True)
                                for e in record["events"]))  # the same events; the record seals a canonical order
        self.assertEqual([e["seq"] for e in record["events"]], list(range(1, len(record["events"]) + 1)))
        self.assertTrue({e["type"] for e in record["events"]} == set(EVENT_TYPES))
        self.assertEqual(record["events"][0]["type"], "run_started")
        self.assertEqual(record["events"][-1]["type"], "run_finished")
        self.assertEqual(events(record, "cache")[0]["data"]["result"], "miss")
        llm = events(record, "llm_call", "A23")[0]["data"]
        self.assertEqual((llm["template"], llm["ok"], llm["model"]), ("a23", True, "qwen3:4b"))
        self.assertEqual(events(record, "retrieval", "A22")[0]["data"], {"citations": 1, "sources": ["kb/runbook.md"]})

    def test_event_transports_are_the_transports_actually_used(self):
        local, _ = model()
        record = run_case(Case(DRIFTED, "drift", baseline=BASELINE), model=local, transport="auto")
        for event in events(record, "agent_started"):
            self.assertNotIn("transport", event["data"])
        for event in events(record, "agent_finished"):
            self.assertEqual(event["data"]["transport"], result(record, event["agent_id"])["transport"])
        for agent in ("A23", "A29", "A30", "A10", "A02"):  # model-only or never MCP-eligible
            self.assertEqual(result(record, agent)["transport"], "in_process")
        self.assertEqual(events(record, "run_started")[0]["data"]["transport_plan"]["requested"], "auto")

    def test_event_data_is_typed_per_event(self):
        log = EventLog(Clock(), 0.0)
        for kind, data in (("agent_selected", {}), ("agent_selected", {"reason": "always", "extra": 1}),
                           ("tool_call", {"tool": "x"}), ("run_finished", {"status": "fine", "duration_ms": 0,
                                                                          "budget_exceeded": []})):
            with self.subTest(kind=kind, data=data), self.assertRaisesRegex(ValueError, "Invalid event"):
                log.stamp("A01", kind, data)
        record = execute(Case(ORDERS, "orders"))
        for event in record["events"]:
            validate_event(event)
        changed = copy.deepcopy(record["events"][0])
        changed["data"]["limits"] = "none"
        with self.assertRaises(InputRejected):
            validate_event(changed)

    def test_a_failing_subscriber_never_breaks_the_run(self):
        def broken(event):
            raise RuntimeError("subscriber down")

        record = execute(Case(ORDERS, "orders"), on_event=broken)
        self.assertEqual(record["event_log"]["callback_errors"], len(record["events"]))
        self.assertNotEqual(record["status"], "input_rejected")

    def test_event_log_bounds_and_validation(self):
        clock = Clock()
        delivered = []
        log = EventLog(clock, 0.0, delivered.append, max_events=3)
        clock.advance(0.25)
        selected = {"reason": "always"}
        self.assertEqual(log.emit("A01", "agent_selected", selected)["t_ms"], 250)
        log.emit("A10", "agent_selected", selected)
        self.assertIsNone(log.emit("A10", "agent_selected", selected))  # the last slot is kept for run_finished
        finished = {"status": "completed", "duration_ms": 250, "budget_exceeded": []}
        self.assertEqual(log.emit("A01", "run_finished", finished)["seq"], 3)
        self.assertIsNone(log.emit("A01", "run_finished", finished))
        self.assertEqual((log.dropped, len(log.events()), len(delivered)), (2, 3, 3))
        for bad in (("A99", "tool_call", {}), ("A10", "gossip", {}), ("A10", "tool_call", [])):
            with self.subTest(bad), self.assertRaises(ValueError):
                log.stamp(*bad)
        for settings in ((1, 0.0), (clock, 0.0, 5), (clock, 0.0, None, 1)):
            with self.subTest(settings), self.assertRaises(ValueError):
                EventLog(*settings[:3], **({"max_events": settings[3]} if len(settings) > 3 else {}))


class Transports(unittest.TestCase):
    def test_auto_uses_mcp_for_tools_and_a2a_for_the_judge(self):
        local, _ = model()
        created = []
        real = transports.ephemeral_pki

        def tracking():
            context = real()
            created.append(context)
            return context

        with mock.patch.object(transports, "ephemeral_pki", side_effect=tracking):
            record = run_case(Case(DRIFTED, "drift", baseline=BASELINE), model=local, transport="auto")
        judge_transport = record["transports"]["judge"]
        self.assertEqual((judge_transport["mode"], judge_transport["tls"]), ("a2a_mtls", "TLSv1.3"))
        self.assertTrue(all(len(judge_transport[k]) == 64 for k in ("ca_sha256", "server_sha256", "client_sha256")))
        self.assertEqual(result(record, "A27")["transport"], "a2a_mtls")
        self.assertEqual(events(record, "agent_finished", "A27")[0]["data"]["certificates"]["ca_sha256"],
                         judge_transport["ca_sha256"])
        self.assertEqual(record["transports"]["agents"]["A09"], "mcp_local")
        self.assertEqual(record["transports"]["agents"]["A10"], "in_process")
        calls = {e["data"]["tool"]: e["data"] for e in events(record, "tool_call") if e["data"]["phase"] == "agent"}
        self.assertEqual((calls["diagnose_csv"]["transport"], calls["diagnose_csv"]["reason"]), ("mcp_local", None))
        self.assertEqual((calls["profile_csv"]["transport"], calls["profile_csv"]["reason"]),
                         ("in_process", "tool_not_in_mcp_profile"))
        self.assertEqual(len(created), 1)

    def test_certificate_directory_is_removed_after_the_run(self):
        roots = []
        real = transports.a2a_review

        def spy(task, review, *, pki, timeout=transports.A2A_TIMEOUT_S):
            roots.append(pki.root)
            self.assertTrue(pki.root.is_dir())
            return real(task, review, pki=pki, timeout=timeout)

        with mock.patch.object(transports, "a2a_review", side_effect=spy):
            execute(Case(ORDERS, "orders"), transport="a2a")
        self.assertEqual(len(roots), 1)
        self.assertFalse(roots[0].exists())
        record = execute(Case(ORDERS, "orders"), transport="a2a")
        self.assertIs(record["transports"]["judge"]["certificates_removed"], True)
        leftovers = []
        with mock.patch.object(transports.shutil, "rmtree", side_effect=lambda path, **kw: leftovers.append(path)):
            kept = execute(Case(ORDERS, "orders"), transport="a2a")
        self.assertIs(kept["transports"]["judge"]["certificates_removed"], False)  # reported, never hidden
        for leftover in leftovers:
            shutil.rmtree(leftover)

    def test_judge_falls_back_in_process_when_the_exchange_fails(self):
        def refuse(task, review, *, pki, timeout=None):
            raise OSError("handshake failed")

        def mismatch(task, review, *, pki, timeout=None):
            return {**review(task), "task_id": "other.a27"}

        def crash(task, review, *, pki, timeout=None):
            raise RuntimeError("judge bug")

        with mock.patch.object(transports, "a2a_review", side_effect=crash):
            record = execute(Case(ORDERS, "orders"), transport="a2a")
        self.assertEqual(result(record, "A27")["error_code"], "EXECUTOR_ERROR")  # a bug is not a transport failure
        self.assertEqual(record["transports"]["judge"]["mode"], "a2a_mtls")
        for fake in (refuse, mismatch):
            with self.subTest(fake.__name__), mock.patch.object(transports, "a2a_review", side_effect=fake):
                record = execute(Case(ORDERS, "orders"), transport="a2a")
            self.assertEqual({k: record["transports"]["judge"][k] for k in ("mode", "reason")},
                             {"mode": "in_process", "reason": "a2a_exchange_failed"})
            self.assertEqual((result(record, "A27")["status"], result(record, "A27")["transport"]),
                             ("COMPLETED", "in_process"))

    def test_unavailable_extras_fall_back_with_a_reason(self):
        with mock.patch.object(transports, "mcp_available", return_value=False), \
                mock.patch.object(transports, "a2a_available", return_value=False):
            record = execute(Case(ORDERS, "orders"), transport="auto")
        self.assertEqual(record["transports"]["tools"], {"mode": "in_process", "reason": "mcp_extra_unavailable"})
        self.assertEqual(record["transports"]["judge"], {"mode": "in_process", "reason": "a2a_extra_unavailable"})
        calls = [e["data"] for e in events(record, "tool_call") if e["data"]["phase"] == "agent"]
        self.assertTrue(calls and all(c == {**c, "transport": "in_process", "reason": "mcp_extra_unavailable"}
                                      for c in calls))
        self.assertEqual(set(record["transports"]["agents"].values()), {"in_process"})


class Recorded(unittest.TestCase):
    def test_model_failure_envelopes_are_typed_not_simulated(self):
        local, _ = model(envelope("not json"), envelope("not json"), envelope("not json"))
        record = execute(Case(DRIFTED, "drift", baseline=BASELINE), model=local)
        self.assertEqual(result(record, "A02")["llm"], None)  # A02 keeps the rule plan
        self.assertIn(result(record, "A23")["error_code"], ("INVALID_OUTPUT",))
        self.assertTrue(all(e["data"]["ok"] is False for e in events(record, "llm_call")[:3]))
        self.assertEqual(result(record, "A33")["status"], "SKIPPED")
        self.assertTrue(all(r in STATUSES for r in (result(record, a)["status"] for a in AGENT_IDS)))


if __name__ == "__main__":
    unittest.main()
