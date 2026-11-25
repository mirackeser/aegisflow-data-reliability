# SPDX-License-Identifier: Apache-2.0
"""Executor scaffolding, resolvability, the control roles A01-A06 and the governance roles A33-A36."""
from hashlib import sha256
import json
import unittest
from unittest import mock

from agents_support import (BASELINE, BIG_ORDERS, DRIFTED, DUPLICATES, ORDERS, TIMED, context, model, run, task)
from aegisflow_dr.advisory.context_cache import ContextCache
from aegisflow_dr.agents import executors
from aegisflow_dr.agents.context import PolicyDenied
from aegisflow_dr.agents.contracts import validate_result
from aegisflow_dr.agents.executors import _base, orchestration, resolve
from aegisflow_dr.agents.executors._base import MAX_CLAIMS, ModelFailure, Run, bounded
from aegisflow_dr.agents.executors.orchestration import (LIMITS, budget_usage, is_order_extract, plan_waves, route,
                                                          triage)
from aegisflow_dr.agents.registry import ROLES
from aegisflow_dr.pipeline import InputRejected


def assert_bound(test, result, ctx):
    """Every claim reference is in the result, resolves in the run's store and matches the stored bytes' digest."""
    for claim in result["claims"]:
        test.assertTrue(claim["evidence_refs"])
        for ref in claim["evidence_refs"]:
            test.assertIn(ref, result["evidence_refs"])
    for ref in result["evidence_refs"]:
        test.assertTrue(ctx.evidence.has(ref), ref)
        body = json.dumps(ctx.evidence.get(ref), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        test.assertEqual(sha256(body).hexdigest(), ref["sha256"])


def completed(agent_id, status="COMPLETED", **result):
    value = {"task_id": "task-" + agent_id.lower(), "agent_id": agent_id, "status": status, "claims": [],
             "evidence_refs": [], "uncertainty": {"level": "low", "reason": "deterministic_rule"},
             "proposed_actions": [],
             "usage": {"tool_calls": 1, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 3},
             "transport": "in_process", "llm": None, "retrieval": None,
             "error_code": None if status == "COMPLETED" else "SOME_CODE", "advisory_text": None}
    value.update(result)
    return validate_result(value)


class Resolution(unittest.TestCase):
    def test_every_registry_executor_ref_imports_and_is_callable(self):
        for spec in ROLES:
            with self.subTest(spec.agent_id):
                module, function = spec.executor_ref.split(":")
                execute = resolve(spec.agent_id)
                self.assertTrue(callable(execute))
                self.assertEqual((execute.__module__, execute.__name__, execute.agent_id),
                                 (module, function, spec.agent_id))

    def test_resolve_rejects_a_function_bound_to_another_role(self):
        with mock.patch.object(orchestration, "global_supervisor", orchestration.investigation_planner):
            with self.assertRaisesRegex(InputRejected, "^Executor does not belong to its role$"):
                resolve("A01")
        with mock.patch.object(orchestration, "global_supervisor", None):
            with self.assertRaisesRegex(InputRejected, "^Executor does not belong to its role$"):
                executors.resolve("A01")


class Scaffolding(unittest.TestCase):
    def test_task_is_validated_and_must_match_the_role(self):
        ctx = context()
        with self.assertRaisesRegex(InputRejected, "^Agent task contract rejected$"):
            resolve("A10")({"agent_id": "A10"}, ctx)
        with self.assertRaisesRegex(InputRejected, "^Agent task contract rejected$"):
            resolve("A10")(task("A10", tools=["profile_csv", "run_batch"]), ctx)
        with self.assertRaisesRegex(InputRejected, "^Task is for another agent$"):
            resolve("A10")(task("A09"), ctx)

    def test_typed_outcomes_map_to_statuses(self):
        ctx = context()
        denied = run("A10", ctx, tools=[])
        self.assertEqual((denied["status"], denied["error_code"], denied["uncertainty"]["reason"]),
                         ("POLICY_DENIED", "TOOL_NOT_ALLOWED", "policy_denied"))
        self.assertEqual(denied["usage"]["tool_calls"], 0)
        over = run("A10", ctx, calls=0)
        self.assertEqual((over["status"], over["error_code"]), ("FAILED", "TOOL_BUDGET_EXCEEDED"))
        rejected = run("A10", context(b"a,a\n1,2\n"))
        self.assertEqual((rejected["status"], rejected["error_code"]), ("FAILED", "INPUT_REJECTED"))
        self.assertEqual(rejected["usage"]["tool_calls"], 1)
        long_name = ("%s\n" % ("c" * 130) + "same\n" * 10).encode()
        too_long = run("A10", context(long_name))
        self.assertEqual((too_long["status"], too_long["error_code"], too_long["claims"]),
                         ("FAILED", "RESULT_REJECTED", []))
        broken = run("A22", context(retriever=lambda q, n: 1 / 0))
        self.assertEqual((broken["status"], broken["error_code"]), ("FAILED", "TOOL_ERROR"))
        skipped = run("A06", ctx)
        self.assertEqual((skipped["status"], skipped["error_code"], skipped["uncertainty"]),
                         ("SKIPPED", "NO_FAILED_AGENT", {"level": "low", "reason": "not_applicable"}))
        needs = run("A12", ctx)
        self.assertEqual((needs["status"], needs["uncertainty"]["level"]), ("NEEDS_EVIDENCE", "high"))

    def test_run_helpers(self):
        ctx = context()
        bound = ctx.for_task(task("A10"))
        r = Run(task("A10"), bound)
        ref = r.put("x", {"a": 1})
        self.assertEqual(r.put("x", {"a": 1}), ref)
        self.assertEqual(r.refs, [ref])
        for n in range(MAX_CLAIMS + 3):
            r.claim("a10.finding", {"n": n}, ref)
        self.assertEqual(len(r.claims), MAX_CLAIMS)
        with self.assertRaisesRegex(InputRejected, "^Unknown or altered evidence reference$"):
            r.cite({"id": "x:0", "sha256": "0" * 64})
        r.advise("  \n ")
        self.assertIsNone(r.advisory)
        r.advise("a  b\n" + "c" * 700)
        self.assertEqual(len(r.advisory), 600)
        self.assertEqual(r.prior_evidence("A03", "routing"), (None, None))
        self.assertEqual(bounded(range(40)), list(range(16)))
        other = ctx.evidence.put("y", {"b": 2})
        ctx.prior["A03"] = completed("A03", evidence_refs=[other])
        self.assertEqual(r.prior_evidence("A03", "routing"), (None, None))
        self.assertIsNone(r.prior("A03", "FAILED"))
        ctx.prior["A03"] = "junk"
        self.assertIsNone(r.prior("A03"))

    def test_model_guard_order_budget_and_failures(self):
        schema = {"type": "object"}
        local, transport = model()
        ctx = context(model=local)
        r = Run(task("A23"), ctx.for_task(task("A23", tools=[])))
        with self.assertRaises(PolicyDenied) as denied:
            r.ask("a23", {"ok": 1}, schema)
        self.assertEqual(denied.exception.code, "TOOL_NOT_ALLOWED")
        r = Run(task("A23"), ctx.for_task(task("A23")))
        with self.assertRaises(PolicyDenied) as raw:
            r.ask("a23", {"column": "ORD-00001"}, schema)
        self.assertEqual(raw.exception.code, "RAW_VALUE_IN_CONTEXT")
        for kwargs, code in (({"llm_calls": 0}, "LLM_BUDGET_EXHAUSTED"), ({"tokens": 0}, "LLM_BUDGET_EXHAUSTED")):
            r = Run(task("A23", **kwargs), ctx.for_task(task("A23", **kwargs)))
            with self.assertRaises(ModelFailure) as failure:
                r.ask("a23", {"ok": 1}, schema)
            self.assertEqual(failure.exception.code, code)
        self.assertEqual(transport.calls, [])
        no_model = Run(task("A23"), context().for_task(task("A23")))
        with self.assertRaises(ModelFailure) as failure:
            no_model.ask("a23", {"ok": 1}, schema)
        self.assertEqual((failure.exception.code, no_model.llm), ("MODEL_UNAVAILABLE", None))
        local, _ = model({"x": 1})
        r = Run(task("A23", tokens=30), context(model=local).for_task(task("A23", tokens=30)))
        with self.assertRaises(ModelFailure) as failure:
            r.ask("a23", {"ok": 1}, schema)
        self.assertEqual(failure.exception.code, "TOKEN_BUDGET_EXCEEDED")
        self.assertEqual((r.tokens_in, r.tokens_out, r.ctx.usage.llm_calls), (40, 12, 1))
        self.assertEqual(r.llm["temperature"], 0)

    def test_cache_hit_reports_hit_and_makes_no_call(self):
        local, transport = model()
        cache = ContextCache()
        for expected in ("miss", "hit"):
            ctx = context(BIG_ORDERS, baseline=BASELINE, model=local, cache=cache)
            result = run("A23", ctx)
            self.assertEqual((result["status"], result["retrieval"]["cache"]), ("COMPLETED", expected))
            self.assertEqual(result["usage"]["llm_calls"], 1 if expected == "miss" else 0)
        self.assertEqual(len(transport.calls), 1)


class Triage(unittest.TestCase):
    def test_order_extract_rule(self):
        self.assertTrue(is_order_extract(["order_id", "customer_id", "total_amount"]))
        self.assertFalse(is_order_extract(["order_id", "amount"]))
        self.assertFalse(is_order_extract(["customer_id", "order_total"]))

    def test_intake_keeps_names_counts_and_ids_only(self):
        ctx = context(BIG_ORDERS, baseline=BASELINE, second_payload=b"\xff", history=[{}])
        t = triage(ctx)
        self.assertIs(triage(ctx), t)
        self.assertEqual((t["records"], t["order_extract"], t["baseline"], t["second_payload"],
                          t["second_order_extract"], t["history"], t["retriever"]),
                         (80, True, True, True, False, True, False))
        self.assertEqual([o["id"] for o in t["observations"]], ["obs-1"])
        self.assertEqual(t["observations"][0]["check"], "volume_change")
        self.assertEqual(t["signals"], [{"id": "sig-1", "check": "volume_change", "column": None}])
        self.assertNotIn("ORD-00001", json.dumps(t))
        drifted = triage(context(DRIFTED, second_payload=ORDERS))
        self.assertTrue(drifted["order_extract"] and drifted["second_order_extract"])
        self.assertIn(("missing_column", "order_total"), [(s["check"], s["column"]) for s in drifted["signals"]])
        generic = triage(context(TIMED))
        self.assertEqual((generic["order_extract"], generic["time_column"], generic["observations"]), (False, "ts", []))

    def test_intake_rejects_overlong_column_names(self):
        ctx = context(("%s\n1\n" % ("c" * 129)).encode())
        with self.assertRaisesRegex(InputRejected, "^Column names longer than 128 characters are not supported$"):
            triage(ctx)
        self.assertEqual(run("A03", ctx)["error_code"], "INPUT_REJECTED")


class Routing(unittest.TestCase):
    def test_route_selects_by_trigger_with_a10_first_and_a_limit_of_eight(self):
        t = triage(context(BIG_ORDERS, baseline=BASELINE, second_payload=ORDERS, history=[{}],
                           retriever=lambda q, n: []))
        routing = route(t)
        agents = [s["agent"] for s in routing["selected"]]
        self.assertEqual(agents[0], "A10")
        specialists = [a for a in agents if a <= "A22"]
        self.assertEqual(len(specialists), 8)
        self.assertEqual(agents[-3:], ["A23", "A24", "A25"])
        reasons = {s["agent"]: s["reason"] for s in routing["skipped"]}
        self.assertEqual((reasons["A12"], reasons["A16"]), ("no_log_source", "no_cdc_source"))
        self.assertTrue(routing["dropped"])
        self.assertTrue(all(reasons[a] == "specialist_limit" for a in routing["dropped"]))
        self.assertEqual(set(agents) | set(reasons), {"A%02d" % n for n in range(7, 26)})

    def test_router_and_planner_executors(self):
        ctx = context(TIMED)
        routed = run("A03", ctx)
        assert_bound(self, routed, ctx)
        self.assertEqual(routed["claims"][0]["params"]["selected"], ["A10", "A15"])
        ctx.prior["A03"] = routed
        planned = run("A04", ctx)
        assert_bound(self, planned, ctx)
        waves = [c["params"] for c in planned["claims"] if c["text_key"] == "a04.wave"]
        self.assertEqual(waves, [{"wave": 1, "stage": "specialists", "agents": ["A10"]},
                                 {"wave": 2, "stage": "specialists", "agents": ["A15"]}])
        self.assertIn(routed["evidence_refs"][0], planned["claims"][0]["evidence_refs"])
        fresh = run("A04", context(BIG_ORDERS, baseline=BASELINE))
        stages = [c["params"]["stage"] for c in fresh["claims"] if c["text_key"] == "a04.wave"]
        self.assertEqual(stages[-1], "reasoning")
        self.assertTrue(all(len(c["params"].get("agents", [])) <= 4 for c in fresh["claims"]))

    def test_plan_waves_without_a10_and_empty(self):
        self.assertEqual(plan_waves([], "case-1"), [])
        self.assertEqual(plan_waves(["A13", "A14", "A19", "A09", "A08"], "case-1"),
                         [("specialists", ["A08", "A09", "A13", "A14"]), ("specialists", ["A19"])])


class Control(unittest.TestCase):
    def test_supervisor_counts_statuses(self):
        ctx = context()
        result = run("A01", ctx)
        self.assertEqual(result["claims"][0]["params"]["final"], "completed")
        ctx.prior.update({"A10": completed("A10"), "A12": completed("A12", "NEEDS_EVIDENCE"), "A99": {}, "A11": "x"})
        params = run("A01", ctx)["claims"][0]["params"]
        self.assertEqual((params["agents"], params["completed"], params["needs_evidence"], params["final"]),
                         (2, 1, 1, "completed_with_gaps"))
        ctx.prior["A14"] = completed("A14", "FAILED")
        self.assertEqual(run("A01", ctx)["claims"][0]["params"]["final"], "failed_agents")
        ctx.prior["A14"] = completed("A14", "POLICY_DENIED")
        del ctx.prior["A12"]
        self.assertEqual(run("A01", ctx)["claims"][0]["params"]["final"], "completed_with_gaps")

    def test_planner_rule_plan_with_and_without_model(self):
        ctx = context(DUPLICATES)
        plain = run("A02", ctx)
        assert_bound(self, plain, ctx)
        self.assertEqual((plain["status"], plain["llm"], plain["claims"][0]["text_key"]),
                         ("COMPLETED", None, "a02.plan"))
        self.assertEqual(plain["uncertainty"]["reason"], "rule_plan_only")
        local, transport = model()
        ctx = context(DUPLICATES, model=local)
        worded = run("A02", ctx)
        assert_bound(self, worded, ctx)
        self.assertEqual([c["text_key"] for c in worded["claims"]], ["a02.plan", "a02.worded"])
        self.assertEqual(worded["llm"]["provider"], "ollama")
        self.assertIn("g1: Which records fail g1?", worded["advisory_text"])
        self.assertEqual(worded["usage"]["llm_calls"], 1)
        silent, _ = model({"questions": []})
        quiet = run("A02", context(DUPLICATES, model=silent))
        self.assertEqual(([c["text_key"] for c in quiet["claims"]], quiet["advisory_text"]), (["a02.plan"], None))
        no_tool = run("A02", context(DUPLICATES, model=local), tools=[])
        self.assertIsNone(no_tool["llm"])
        nothing = run("A02", context(b"a\nx\ny\n", model=local))
        self.assertEqual((nothing["claims"][0]["params"]["goals"], nothing["llm"]), (0, None))

    def test_planner_falls_back_on_model_failures(self):
        for override, code in ((b"not json", "INVALID_OUTPUT"), (TimeoutError(), "TIMEOUT"), (OSError(), None)):
            local, _ = model(override)
            result = run("A02", context(DUPLICATES, model=local))
            with self.subTest(code=code):
                self.assertEqual((result["status"], result["error_code"]), ("COMPLETED", None))
                self.assertEqual([c["text_key"] for c in result["claims"]], ["a02.plan"])
                self.assertEqual((result["llm"], result["retrieval"], result["usage"]["llm_calls"]), (None, None, 1))
                self.assertEqual(result["uncertainty"]["reason"], "rule_plan_only")

    def test_budget_controller(self):
        ticks = iter([0.0, 0.5, 0.5])  # context start, task start, the elapsed reading
        ctx = context(clock=lambda: next(ticks))
        result = run("A05", ctx)
        self.assertEqual(result["claims"][0]["text_key"], "a05.within_budget")
        self.assertEqual(result["claims"][0]["params"]["used_elapsed_ms"], 500)
        prior = {"A%02d" % n: completed("A%02d" % n) for n in range(7, 17)}
        prior["A23"] = completed("A23", usage={"tool_calls": 0, "llm_calls": 13, "tokens_in": 30000,
                                               "tokens_out": 10001, "latency_ms": 1})
        prior["A12"] = completed("A12", "SKIPPED")
        prior["A99"] = {"usage": {"llm_calls": 50}}
        prior["A24"] = {"agent_id": "A24", "status": "COMPLETED", "usage": [1]}
        used, exceeded = budget_usage(prior, 90_001)
        self.assertEqual(used, {"specialists": 9, "llm_calls": 13, "tokens": 40001, "elapsed_ms": 90001})
        self.assertEqual(exceeded, list(LIMITS))
        ctx = context()
        ctx.prior.update(prior)
        over = run("A05", ctx)
        self.assertEqual((over["status"], over["claims"][0]["text_key"]), ("COMPLETED", "a05.budget_exceeded"))

    def test_recovery_coordinator(self):
        ctx = context()
        ctx.prior.update({"A10": completed("A10", "FAILED", error_code="TOOL_ERROR"),
                          "A11": completed("A11", "FAILED", error_code="INPUT_REJECTED"),
                          "A13": completed("A13", "POLICY_DENIED", error_code="TOOL_NOT_ALLOWED"),
                          "A14": {"status": "FAILED", "error_code": 5}})
        result = run("A06", ctx)
        assert_bound(self, result, ctx)
        decisions = [c["params"] for c in result["claims"] if c["text_key"] == "a06.decision"]
        self.assertEqual(decisions, [
            {"agent": "A10", "decision": "retry_once_same_input", "error_code": "TOOL_ERROR"},
            {"agent": "A11", "decision": "safe_stop", "error_code": "INPUT_REJECTED"},
            {"agent": "A14", "decision": "retry_once_same_input", "error_code": None}])
        self.assertEqual(result["claims"][-1]["params"], {"agents": ["A13"], "reason": "policy_denied"})
        del ctx.prior["A13"]
        self.assertEqual(run("A06", ctx)["claims"][-1]["text_key"], "a06.decision")


class Governance(unittest.TestCase):
    def test_approval_only_records_a_pending_item(self):
        ctx = context()
        self.assertEqual(run("A33", ctx)["error_code"], "NO_PROPOSALS")
        action = {"text_key": "a30.patch", "params": {"kind": "sql"}, "executed": False}
        ctx.prior.update({"A30": completed("A30", proposed_actions=[action]), "A29": completed("A29", "NEEDS_EVIDENCE")})
        result = run("A33", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(result["claims"][0]["params"], {"proposals": 1, "agents": ["A30"], "decision": "pending"})
        record = ctx.evidence.get(result["evidence_refs"][0])
        self.assertEqual((record["decision"], record["executed"]), ("pending", False))
        self.assertEqual(result["proposed_actions"], [])

    def test_policy_review_passes_clean_contexts(self):
        local, _ = model()
        ctx = context(DUPLICATES, model=local)
        ctx.prior["A02"] = run("A02", ctx)
        result = run("A34", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(result["claims"][0]["params"], {"contexts": 2, "results": 1, "denied": 0})

    def test_policy_review_denies_raw_values_and_tool_misuse(self):
        ctx = context()
        ctx.evidence.put("llm_context", {"context": {"column": "ORD-00001"}})
        self.assertEqual((run("A34", ctx)["status"], run("A34", ctx)["error_code"]),
                         ("POLICY_DENIED", "RAW_VALUE_IN_CONTEXT"))
        llm = {"provider": "ollama", "model": "qwen3:4b", "prompt_sha256": "a" * 64, "temperature": 0, "seed": 7}
        for prior in ({"A10": completed("A10", llm=llm)},
                      {"A12": completed("A12", "NEEDS_EVIDENCE")},
                      {"A33": completed("A33")}):
            ctx = context()
            ctx.prior.update(prior)
            result = run("A34", ctx)
            with self.subTest(prior=list(prior)):
                expected = ("COMPLETED", None) if "A12" in prior else ("POLICY_DENIED", "TOOL_NOT_ALLOWED")
                if "A12" in prior:
                    ctx.prior["A12"]["usage"]["tool_calls"] = 1
                    expected = ("POLICY_DENIED", "TOOL_NOT_ALLOWED")
                    result = run("A34", ctx)
                self.assertEqual((result["status"], result["error_code"]), expected)
        ctx = context()
        ctx.prior["A10"] = {"agent_id": "A10", "status": "COMPLETED", "usage": None, "llm": None}
        self.assertEqual(run("A34", ctx)["status"], "COMPLETED")

    def test_usage_rollup(self):
        ctx = context()
        ctx.prior.update({"A10": completed("A10"), "A23": completed("A23", usage={
            "tool_calls": 0, "llm_calls": 1, "tokens_in": 40, "tokens_out": 12, "latency_ms": 9}),
            "A11": {"status": "COMPLETED", "usage": {"tool_calls": -1, "latency_ms": "x"}}})
        result = run("A35", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(result["claims"][0]["params"], {"agents": 3, "tool_calls": 1, "llm_calls": 1,
                                                         "tokens_in": 40, "tokens_out": 12, "latency_ms": 12})
        self.assertEqual(len(result["claims"]), 4)
        self.assertEqual(ctx.evidence.get(result["evidence_refs"][0])["external_spend_usd"], 0)

    def test_evaluation_record(self):
        ctx = context()
        ctx.prior.update({"A10": completed("A10"), "A12": completed("A12", "SKIPPED")})
        plain = run("A36", ctx)
        self.assertEqual(plain["claims"][0]["params"], {"agents": 2, "selected": 1, "judge_accepted": None,
                                                        "judge_advisory": None, "judge_rejected": None})
        ctx.prior["A10"] = run("A10", ctx)
        ctx.prior["A27"] = run("A27", ctx)
        judged = run("A36", ctx)
        assert_bound(self, judged, ctx)
        params = judged["claims"][0]["params"]
        self.assertEqual((params["judge_accepted"], params["judge_rejected"]), (len(ctx.prior["A10"]["claims"]), 0))
        self.assertEqual(len(judged["claims"][0]["evidence_refs"]), 2)


PASSAGE = {"source": "kb", "revision": "1", "citation": "kb#1", "passage": "Renamed amount columns break readers."}
ALL_AGENTS = ["A34", "A01", "A02", "A03", "A04", "A05", "A10", "A07", "A08", "A09", "A11", "A12", "A13", "A14", "A15",
              "A16", "A17", "A18", "A19", "A20", "A21", "A22", "A24", "A25", "A23", "A26", "A27", "A28", "A29", "A30",
              "A31", "A32", "A33", "A35", "A36", "A06", "A34"]


class Drift(unittest.TestCase):
    """A renamed contract column (the flagship schema-drift case) is a column name, never a raw value."""

    def test_drifted_case_without_baseline_or_model(self):
        ctx = context(DRIFTED)
        planned = run("A02", ctx)
        self.assertEqual((planned["status"], planned["llm"]), ("COMPLETED", None))
        self.assertIn("missing_column", planned["claims"][0]["params"]["checks"])
        self.assertEqual(run("A34", ctx)["status"], "COMPLETED")

    def test_drifted_case_with_baseline_and_model(self):
        local, transport = model()
        ctx = context(DRIFTED, baseline=BASELINE, model=local, retriever=lambda q, n: [PASSAGE])
        for agent in ("A02", "A22", "A23", "A34"):
            ctx.prior[agent] = run(agent, ctx)
            self.assertNotEqual(ctx.prior[agent]["status"], "POLICY_DENIED", agent)
        self.assertEqual(ctx.prior["A02"]["status"], "COMPLETED")
        self.assertEqual([c["text_key"] for c in ctx.prior["A02"]["claims"]], ["a02.plan", "a02.worded"])
        self.assertEqual(ctx.prior["A23"]["status"], "COMPLETED")
        self.assertEqual(ctx.prior["A34"]["status"], "COMPLETED")
        self.assertIn("order_total", "".join(transport.prompts()))

    def test_no_policy_denial_across_fixtures_with_and_without_model(self):
        fixtures = {"orders": {"payload": ORDERS}, "duplicates": {"payload": DUPLICATES},
                    "drifted": {"payload": DRIFTED}, "drifted_baseline": {"payload": DRIFTED, "baseline": BASELINE},
                    "volume": {"payload": BIG_ORDERS, "baseline": BASELINE},
                    "second": {"payload": DUPLICATES, "second_payload": DRIFTED},
                    "timed": {"payload": TIMED}, "history": {"payload": DUPLICATES, "history": [{"status": "FAILED"}]}}
        for name, inputs in fixtures.items():
            for with_model in (False, True):
                local = model()[0] if with_model else None
                ctx = context(**inputs, model=local, retriever=lambda q, n: [PASSAGE])
                for agent in ALL_AGENTS:
                    ctx.prior[agent] = run(agent, ctx)
                with self.subTest(fixture=name, model=with_model):
                    denied = [a for a, r in ctx.prior.items() if r["status"] == "POLICY_DENIED"]
                    self.assertEqual(denied, [])
                    self.assertEqual(ctx.prior["A02"]["status"], "COMPLETED")

    def test_genuinely_unsafe_inputs_are_still_denied(self):
        local, _ = model()
        ctx = context(DRIFTED, baseline=BASELINE, model=local)
        ctx.evidence.put("llm_context", {"context": {"column": "ORD-00001"}})
        self.assertEqual(run("A34", ctx)["error_code"], "RAW_VALUE_IN_CONTEXT")


class PlannerMapping(unittest.TestCase):
    def test_every_goal_references_existing_signal_or_observation_ids(self):
        ctx = context(BIG_ORDERS, baseline=BASELINE)
        t = triage(ctx)
        self.assertTrue(all(s["id"].startswith("sig-") for s in t["signals"]))
        known = {s["id"] for s in t["signals"]} | {o["id"] for o in t["observations"]}
        planned = run("A02", ctx)
        plan = ctx.evidence.get(planned["claims"][0]["evidence_refs"][0])
        self.assertTrue(plan["goals"])
        for goal in plan["goals"]:
            self.assertTrue(goal["refs"])
            self.assertTrue(set(goal["refs"]) <= known)
        volume = next(g for g in plan["goals"] if g["check"] == "volume_change")
        self.assertIn("obs-1", volume["refs"])

    def test_the_wording_schema_restricts_ids(self):
        local, transport = model()
        run("A02", context(BIG_ORDERS, baseline=BASELINE, model=local))
        item = transport.calls[0]["format"]["properties"]["questions"]["items"]["properties"]
        self.assertIn("obs-1", item["refs"]["items"]["enum"])
        self.assertTrue(all(i.startswith(("sig-", "obs-")) for i in item["refs"]["items"]["enum"]))

    def test_wording_with_an_unknown_id_is_rejected_and_the_rule_plan_kept(self):
        loose = {"type": "object", "required": ["questions"], "properties": {"questions": {"type": "array"}}}
        for question in ({"goal": "g1", "refs": ["sig-99"], "question": "q"},
                         {"goal": "g9", "refs": ["sig-1"], "question": "q"},
                         {"goal": "g1", "refs": [], "question": "q"}):
            local, _ = model({"questions": [question]})
            with mock.patch.object(orchestration, "planner_schema", lambda *a: loose):
                result = run("A02", context(DUPLICATES, model=local))
            with self.subTest(question=question):
                self.assertEqual((result["status"], result["llm"], result["usage"]["llm_calls"]),
                                 ("COMPLETED", None, 1))
                self.assertEqual([c["text_key"] for c in result["claims"]], ["a02.plan"])
                self.assertEqual(result["uncertainty"]["reason"], "rule_plan_only")

    def test_an_unmapped_rule_goal_fails_instead_of_completing(self):
        with mock.patch.object(orchestration, "_goal_refs", lambda signal, observations: ["sig-404"]):
            result = run("A02", context(DUPLICATES))
        self.assertEqual((result["status"], result["error_code"]), ("FAILED", "INPUT_REJECTED"))


class Contract(unittest.TestCase):
    def test_base_module_constants(self):
        self.assertEqual((_base.MAX_CLAIMS, _base.MAX_LIST), (32, 16))


if __name__ == "__main__":
    unittest.main()
