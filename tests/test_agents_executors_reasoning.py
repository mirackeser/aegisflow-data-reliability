# SPDX-License-Identifier: Apache-2.0
"""Reasoning A23-A28, remediation A29-A32, model paths with a fake transport, the no-raw-value property and determinism."""
import copy
from random import Random
import unittest
from urllib.error import URLError

from agents_support import (BASELINE, BIG_ORDERS, ORDERS, TIMED, context, envelope, model, run, timed_csv)
from test_agents_executors import assert_bound, completed
from aegisflow_dr.agents.executors.reasoning import judge
from aegisflow_dr.baseline import build_baseline
from aegisflow_dr.hypotheses import trace_digest
from aegisflow_dr.pipeline import InputRejected

NAMES = frozenset({"order_id", "created_at", "total"})


def params(result, key):
    return [c["params"] for c in result["claims"] if c["text_key"] == key]


def chain(ctx, agents, **task_kwargs):
    for agent in agents:
        ctx.prior[agent] = run(agent, ctx, **task_kwargs)
    return ctx.prior


def observed(**kwargs):
    return context(BIG_ORDERS, baseline=BASELINE, **kwargs)


class Hypotheses(unittest.TestCase):
    def test_a23_needs_observations_and_a_model(self):
        self.assertEqual(run("A23", context())["error_code"], "NO_OBSERVATIONS")
        missing = run("A23", observed())
        self.assertEqual((missing["status"], missing["error_code"], missing["llm"], missing["usage"]["llm_calls"]),
                         ("NEEDS_EVIDENCE", "MODEL_UNAVAILABLE", None, 0))

    def test_a23_suggestion_is_stored_as_advisory_evidence(self):
        local, transport = model()
        ctx = observed(model=local)
        result = run("A23", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a23.suggested"), [{"mechanisms": ["duplicate_delivery"], "explains": ["obs-1"]}])
        suggestion = result["claims"][0]["evidence_refs"][0]
        self.assertEqual(ctx.evidence.kind(suggestion), "llm_suggestion")
        stored = ctx.evidence.get(suggestion)
        self.assertEqual((stored["agent"], stored["observations"], stored["prompt_version"]), ("A23", ["obs-1"], "3"))
        self.assertEqual(result["llm"], {"provider": "ollama", "model": "qwen3:4b",
                                         "prompt_sha256": stored["prompt_sha256"], "temperature": 0, "seed": 7})
        self.assertEqual((result["usage"]["tokens_in"], result["usage"]["tokens_out"]), (40, 12))
        self.assertEqual(result["uncertainty"], {"level": "high", "reason": "model_advisory"})
        self.assertIn("not a cause", result["advisory_text"])
        request = transport.calls[0]
        self.assertEqual(request["options"], {"temperature": 0, "seed": 7, "num_predict": 256})
        enum = request["format"]["properties"]["candidates"]["items"]["properties"]["mechanism"]["enum"]
        self.assertEqual(len(enum), 12)

    def test_a23_prompt_versions_send_different_contexts(self):
        """Version 3 sends each observation with its reading and no catalog; version 2 is unchanged (catalog list)."""
        sent = {}
        for version in ("2", "3"):
            local, transport = model()
            ctx = observed(model=local, prompt_version=version)
            run("A23", ctx)
            stored = ctx.evidence.get(next(r for r in ctx.evidence.refs() if ctx.evidence.kind(r) == "llm_context"))
            sent[version] = (stored["prompt_version"], stored["context"], transport.calls[0]["messages"][0]["content"])
        self.assertEqual(sent["2"][0], "2")
        self.assertIn("catalog", sent["2"][1])
        self.assertTrue(all("reading" not in o for o in sent["2"][1]["observations"]))
        self.assertEqual(sent["3"][0], "3")
        self.assertNotIn("catalog", sent["3"][1])
        self.assertEqual(sent["3"][1]["observations"][0]["reading"], {"rows": "increase"})
        self.assertIn("Signatures:", sent["3"][2])
        self.assertNotIn("Signatures:", sent["2"][2])

    def test_a23_v3_keeps_a_repeated_mechanism_once(self):
        answer = {"candidates": [{"mechanism": "duplicate_delivery", "explains": ["obs-1"]},
                                 {"mechanism": "duplicate_delivery", "explains": ["obs-1"]}]}
        for version, expected in (("3", ["duplicate_delivery"]), ("2", ["duplicate_delivery", "duplicate_delivery"])):
            local, _ = model(answer)
            result = run("A23", observed(model=local, prompt_version=version))
            with self.subTest(version=version):
                self.assertEqual(params(result, "a23.suggested")[0]["mechanisms"], expected)

    def test_an_unknown_prompt_version_is_refused(self):
        with self.assertRaises(InputRejected):
            observed(prompt_version="9")

    def test_a23_model_failures_are_needs_evidence_with_the_model_record(self):
        for override, code in ((envelope({"candidates": [{"mechanism": "root_cause", "explains": ["obs-1"]}]}),
                                "INVALID_OUTPUT"),
                               (envelope({"candidates": [{"mechanism": "partial_load", "explains": ["obs-7"]}]}),
                                "INVALID_OUTPUT"),
                               (URLError("refused"), "MODEL_UNAVAILABLE"), (TimeoutError(), "TIMEOUT")):
            local, _ = model(override)
            result = run("A23", observed(model=local))
            with self.subTest(code=code):
                self.assertEqual((result["status"], result["error_code"], result["claims"]),
                                 ("NEEDS_EVIDENCE", code, []))
                self.assertIsNotNone(result["llm"])
                self.assertEqual(result["usage"]["llm_calls"], 1)

    def test_a23_empty_suggestion_and_comparison_with_a24(self):
        local, _ = model({"candidates": []})
        result = run("A23", observed(model=local))
        self.assertEqual(params(result, "a23.suggested"), [{"mechanisms": [], "explains": []}])
        self.assertTrue(result["advisory_text"].endswith("none"))
        local, _ = model()
        ctx = observed(model=local)
        chain(ctx, ["A24", "A23"])
        compared = params(ctx.prior["A23"], "a23.compared")[0]
        self.assertEqual(set(compared), {"agreed", "model_only", "rule_supported"})
        assert_bound(self, ctx.prior["A23"], ctx)

    def test_a24_a25(self):
        for agent in ("A24", "A25"):
            self.assertEqual(run(agent, context())["error_code"], "NO_BASELINE")
            quiet = run(agent, context(ORDERS, baseline=BASELINE))
            self.assertEqual((quiet["error_code"], len(quiet["evidence_refs"])), ("NO_OBSERVATIONS", 1))
        ctx = observed()
        competitors = run("A24", ctx)
        assert_bound(self, competitors, ctx)
        summary = params(competitors, "a24.summary")[0]
        self.assertEqual(summary["hypotheses"], len(params(competitors, "a24.hypothesis")))
        self.assertEqual(competitors["uncertainty"]["reason"], "candidate_mechanisms_only")
        probes = run("A25", ctx)
        assert_bound(self, probes, ctx)
        self.assertEqual(len(params(probes, "a25.probe")), params(probes, "a25.stop")[0]["used"])
        self.assertEqual(probes["evidence_refs"], competitors["evidence_refs"])

    def test_a28_ranks_only_after_a24(self):
        self.assertEqual(run("A28", observed())["error_code"], "A24_NOT_RUN")
        ctx = observed()
        chain(ctx, ["A24"])
        ranked = run("A28", ctx)
        assert_bound(self, ranked, ctx)
        record = ctx.evidence.get(ranked["evidence_refs"][0])
        self.assertEqual(params(ranked, "a28.ranking")[0]["ranking"], record["ranking"][:16])
        self.assertEqual(ranked["uncertainty"]["level"], "high")
        single = dict(record, verdict="single_supported")
        single["trace_sha256"] = trace_digest(single)
        ref = ctx.evidence.put("investigation", single)
        ctx.prior["A24"] = completed("A24", evidence_refs=[ref])
        self.assertEqual(run("A28", ctx)["uncertainty"], {"level": "medium", "reason": "single_candidate_consistent"})
        tampered = dict(record, verdict="single_supported")
        ctx.prior["A24"] = completed("A24", evidence_refs=[ctx.evidence.put("investigation", tampered)])
        self.assertEqual(run("A28", ctx)["error_code"], "INPUT_REJECTED")


class Collector(unittest.TestCase):
    def test_a26_stores_valid_results_and_input_digests(self):
        ctx = context(baseline=BASELINE, second_payload=TIMED, history=[{}], as_of="2026-01-01")
        ctx.prior.update({"A10": run("A10", ctx), "A11": completed("A12"), "A99": completed("A10"), "A13": "junk"})
        result = run("A26", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a26.stored"), [{"results": 1, "rejected": 3, "inputs": 7}])
        index = ctx.evidence.get(result["evidence_refs"][1])
        self.assertEqual(index["rejected"], ["A11", "A13", "invalid"])
        self.assertEqual(ctx.evidence.get(index["results"]["A10"]), ctx.prior["A10"])
        inputs = ctx.evidence.get(result["evidence_refs"][0])
        self.assertEqual((inputs["baseline_digest"], inputs["as_of_given"], inputs["history_runs"]),
                         (BASELINE["digest"], True, 1))
        bare = context(baseline={"digest": "nope"})
        inputs = bare.evidence.get(run("A26", bare)["evidence_refs"][0])
        self.assertEqual((inputs["baseline_digest"], inputs["second_payload_sha256"]), (None, None))


class Judge(unittest.TestCase):
    def test_accepts_verified_claims_and_labels_model_claims_advisory(self):
        local, _ = model()
        ctx = observed(model=local)
        chain(ctx, ["A10", "A23", "A12"])
        result = run("A27", ctx)
        assert_bound(self, result, ctx)
        verdicts = ctx.evidence.get(result["evidence_refs"][0])["verdicts"]
        self.assertEqual({v["agent"]: v["verdict"] for v in verdicts}, {"A10": "accepted", "A23": "advisory"})
        self.assertEqual(params(result, "a27.verdict")[0]["rejected"], 0)

    def test_rejects_unbound_altered_unknown_and_inconsistent_claims(self):
        local, _ = model({"candidates": [{"mechanism": "unit_change", "explains": ["obs-1"]}]})
        ctx = observed(model=local)
        chain(ctx, ["A10", "A23"])
        observations = [{"id": "obs-1", "source": "baseline", "check": "volume_change", "column": None,
                         "direction": "increase"}]
        self.assertEqual([v["reason"] for v in judge({"A23": ctx.prior["A23"]}, ctx.evidence, observations,
                                                     names=NAMES)],
                         ["mechanism_does_not_explain"])
        a10 = ctx.prior["A10"]
        stray = ctx.evidence.put("profile", {"other": 1})
        unbound = copy.deepcopy(a10)
        unbound["claims"][0]["evidence_refs"] = [stray]
        missing = copy.deepcopy(a10)
        ghost = {"id": "profile:" + "0" * 32, "sha256": "0" * 64}
        missing["claims"][0]["evidence_refs"] = [ghost]
        missing["evidence_refs"] = [ghost]
        unknown = copy.deepcopy(ctx.prior["A23"])
        unknown["claims"][0]["params"]["explains"] = ["obs-9"]
        not_list = copy.deepcopy(ctx.prior["A23"])
        not_list["claims"][0]["params"]["explains"] = "obs-1"
        results = {"A10": unbound, "A23": unknown,
                   "A12": completed("A12", "NEEDS_EVIDENCE"), "A13": {"status": "COMPLETED"},
                   "A14": completed("A15"), "A99": {"status": "COMPLETED"}}
        reasons = {v["agent"]: v["reason"] for v in judge(results, ctx.evidence, observations, names=NAMES)}
        self.assertEqual(reasons, {"A10": "ref_not_in_result", "A23": "unknown_observation",
                                   "A13": "invalid_result", "A14": "invalid_result", "invalid": "invalid_result"})
        self.assertEqual([v["reason"] for v in judge({"A10": missing}, ctx.evidence, observations, names=NAMES)][:1],
                         ["evidence_missing_or_altered"])
        self.assertEqual([v["reason"] for v in judge({"A23": not_list}, ctx.evidence, observations, names=NAMES)],
                         ["unknown_observation"])

    def test_a02_wording_is_advisory_only_when_every_goal_maps(self):
        local, _ = model()
        ctx = observed(model=local)
        chain(ctx, ["A02"])
        signals = [{"id": "sig-1", "check": "volume_change", "column": None}]
        observations = [{"id": "obs-1", "source": "baseline", "check": "volume_change", "column": None,
                         "direction": "increase"}]
        self.assertEqual([v["verdict"] for v in judge({"A02": ctx.prior["A02"]}, ctx.evidence, observations,
                                                      signals, names=NAMES)], ["accepted", "advisory"])
        self.assertEqual(params(run("A27", ctx), "a27.verdict")[0]["advisory"], 1)
        good = ctx.evidence.get(ctx.prior["A02"]["claims"][1]["evidence_refs"][0])
        question = good["data"]["questions"][0]
        broken = [dict(good, goals=[dict(good["goals"][0], refs=["sig-9"])]),
                  dict(good, goals="junk"), dict(good, goals=["junk"]),
                  dict(good, data={"questions": [dict(question, refs=["obs-7"])]}),
                  dict(good, data={"questions": [dict(question, goal="g8")]})]
        for suggestion in broken:
            forged = copy.deepcopy(ctx.prior["A02"])
            ref = ctx.evidence.put("llm_suggestion", suggestion)
            forged["claims"][1]["evidence_refs"] = [ref]
            forged["evidence_refs"].append(ref)
            with self.subTest(suggestion=suggestion["goals"]):
                self.assertEqual([v["reason"] for v in judge({"A02": forged}, ctx.evidence, observations, signals,
                                                             names=NAMES)],
                                 ["evidence_verified", "goal_not_mapped"])

    def test_every_citation_must_be_in_the_results_own_retrieval_evidence(self):
        passage = {"source": "kb", "revision": "1", "citation": "kb#1", "passage": "About duplicates."}
        ctx = context(retriever=lambda q, n: [passage])
        a22 = run("A22", ctx)
        self.assertEqual([v["verdict"] for v in judge({"A22": a22}, ctx.evidence, [], names=NAMES)], ["accepted"])
        forged = copy.deepcopy(a22)
        forged["retrieval"]["citations"].append({"source": "kb", "revision": "2", "citation": "kb#9"})
        self.assertEqual([v["reason"] for v in judge({"A22": forged}, ctx.evidence, [], names=NAMES)],
                         ["evidence_verified", "unverified_citation"])
        ctx.prior["A22"] = forged
        self.assertEqual(params(run("A27", ctx), "a27.verdict")[0]["rejected_agents"], ["A22"])


class Remediation(unittest.TestCase):
    def accepted_case(self, *overrides, payload=BIG_ORDERS):
        local, transport = model(*overrides)
        ctx = context(payload, baseline=BASELINE, model=local)
        chain(ctx, ["A03", "A10", "A11", "A24", "A27"])
        return ctx, transport

    def test_a29_needs_accepted_findings_and_a_model(self):
        self.assertEqual(run("A29", context())["error_code"], "NO_ACCEPTED_FINDINGS")
        ctx = context()
        chain(ctx, ["A03", "A27"])
        self.assertEqual(run("A29", ctx)["error_code"], "NO_ACCEPTED_FINDINGS")
        ctx, _ = self.accepted_case()
        ctx = context(BIG_ORDERS, baseline=BASELINE, evidence=ctx.evidence, prior=ctx.prior)
        self.assertEqual(run("A29", ctx)["error_code"], "MODEL_UNAVAILABLE")

    def test_a29_drafts_proposals_from_accepted_findings_only(self):
        ctx, transport = self.accepted_case()
        result = run("A29", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(params(result, "a29.options"), [{"options": 1, "risks": ["medium"], "addresses": ["f1", "f2"]}])
        self.assertEqual(result["proposed_actions"], [{"text_key": "a29.option", "executed": False,
                                                       "params": {"option": "opt1", "risk": "medium",
                                                                  "addresses": ["f1", "f2"]}}])
        context_sent = transport.prompts()[-1]
        self.assertNotIn("A03", context_sent)
        self.assertNotIn("A24", context_sent)
        self.assertNotIn("transform_sha256", context_sent)
        findings = ctx.evidence.get(result["claims"][0]["evidence_refs"][0])["findings"]
        self.assertEqual(findings[0]["agent"], "A10")
        self.assertTrue(all("A07" <= f["agent"] <= "A22" for f in findings))

    def test_a29_never_receives_policy_or_governance_claims(self):
        ctx, transport = self.accepted_case()
        chain(ctx, ["A34", "A35", "A27", "A29"])
        findings = ctx.evidence.get(ctx.prior["A29"]["claims"][0]["evidence_refs"][0])["findings"]
        self.assertTrue(findings)
        self.assertTrue(all("A07" <= f["agent"] <= "A22" for f in findings))
        self.assertNotIn("a34.reviewed", transport.prompts()[-1])

    def test_a29_skips_verdicts_whose_result_is_gone(self):
        ctx, _ = self.accepted_case()
        ctx.prior["A10"] = completed("A10")  # its accepted claim indexes are now out of range
        result = run("A29", ctx)
        findings = ctx.evidence.get(result["claims"][0]["evidence_refs"][0])["findings"]
        self.assertEqual({f["agent"] for f in findings}, {"A11"})
        del ctx.prior["A11"]
        self.assertEqual(run("A29", ctx)["error_code"], "NO_ACCEPTED_FINDINGS")

    def test_a30_and_validators(self):
        ctx, _ = self.accepted_case()
        self.assertEqual(run("A30", ctx)["error_code"], "NO_REMEDIATION_OPTIONS")
        for agent in ("A31", "A32"):
            self.assertEqual(run(agent, ctx)["error_code"], "NO_PROPOSAL")
        chain(ctx, ["A29"])
        result = run("A30", ctx)
        assert_bound(self, result, ctx)
        self.assertEqual(params(result, "a30.proposal"), [{"kind": "sql", "addresses": ["opt1"], "executed": False}])
        self.assertEqual(result["proposed_actions"][0]["executed"], False)
        self.assertTrue(result["advisory_text"].startswith("Proposal for human review, not applied: "))
        ctx.prior["A30"] = result
        sandbox = run("A31", ctx)
        self.assertEqual((sandbox["status"], sandbox["error_code"], sandbox["usage"]["tool_calls"]),
                         ("NEEDS_EVIDENCE", "SANDBOX_WRITES_DISABLED", 2))
        self.assertEqual(ctx.evidence.get(sandbox["evidence_refs"][0])["applied"], False)
        backfill = run("A32", ctx)
        self.assertEqual((backfill["status"], backfill["error_code"]), ("NEEDS_EVIDENCE", "NO_BACKFILL_TARGET"))

    def test_a30_requires_an_order_extract_and_clean_option_text(self):
        local, _ = model()
        timed = context(timed_csv(gap_at=20), baseline=build_baseline([TIMED]), model=local)
        timed.prior["A29"] = completed("A29", evidence_refs=[timed.evidence.put("llm_suggestion", {"data": {}})])
        self.assertEqual(run("A30", timed)["error_code"], "NOT_ORDER_EXTRACT")
        leak = {"options": [{"title": "Fix ORD-00001", "risk": "low", "rollback": "Restore", "addresses": ["f1"]}]}
        ctx, transport = self.accepted_case(leak)
        chain(ctx, ["A29"])
        denied = run("A30", ctx)
        self.assertEqual((denied["status"], denied["error_code"]), ("POLICY_DENIED", "RAW_VALUE_IN_CONTEXT"))
        self.assertEqual(len(transport.calls), 1)


def order_payload(rng, marker):
    rows = rng.randint(6, 30)
    lines = ["order_id,customer_id,order_total"]
    for n in range(rows):
        lines.append("ORD-%05d,CUS-%03d,%d.%02d" % (n + 1, rng.randint(1, 9), rng.randint(1, 999), rng.randint(0, 99)))
    if rng.random() < 0.5:
        lines.append(lines[-1])  # an exact repeat (duplicate_rows observation)
    row = rng.randint(1, len(lines) - 1)
    cells = lines[row].split(",")
    cells[rng.randint(0, 2)] = marker
    lines[row] = ",".join(cells)
    return ("\n".join(lines) + "\n").encode()


MODEL_CHAIN = ["A34", "A02", "A03", "A10", "A11", "A22", "A24", "A23", "A27", "A29", "A30", "A34"]


class NoRawValues(unittest.TestCase):
    def test_a_payload_cell_value_never_appears_in_any_prompt(self):
        rng = Random(2026)
        for case in range(25):
            marker = "ZQX%dMARK%04d" % (case, rng.randint(0, 9999))
            payload = order_payload(rng, marker)
            local, transport = model()
            passages = [{"source": "kb", "revision": "1", "citation": "kb#1", "passage": "Duplicates inflate totals."},
                        {"source": "kb", "revision": "1", "citation": "kb#2", "passage": "Seen: %s twice." % marker},
                        {"source": marker, "revision": "1", "citation": "kb#3", "passage": "Clean text."}]
            ctx = context(payload, baseline=BASELINE, second_payload=ORDERS, model=local,
                          retriever=lambda q, n, p=passages: p)
            chain(ctx, MODEL_CHAIN)
            with self.subTest(case=case):
                self.assertTrue(transport.calls)
                self.assertNotIn(marker, "".join(transport.prompts()))
                self.assertEqual(ctx.prior["A34"]["status"], "COMPLETED")
        drifted = order_payload(Random(5), "ZQXDRIFTMARK").replace(b"order_total", b"total_amount", 1)
        local, transport = model()
        ctx = context(drifted, baseline=BASELINE, model=local, retriever=lambda q, n: [])
        chain(ctx, MODEL_CHAIN)
        self.assertNotIn("ZQXDRIFTMARK", "".join(transport.prompts()))
        self.assertNotIn("POLICY_DENIED", [r["status"] for r in ctx.prior.values()])
        timed = timed_csv(marker="ZQXTIMEDMARK")
        local, transport = model()
        chain(context(timed, baseline=build_baseline([TIMED]), model=local), MODEL_CHAIN)
        self.assertNotIn("ZQXTIMEDMARK", "".join(transport.prompts()))


def stable(result):
    value = copy.deepcopy(result)
    value["usage"]["latency_ms"] = 0
    return value


class Determinism(unittest.TestCase):
    def test_same_case_same_results_and_evidence(self):
        runs = []
        for _ in range(2):
            local, _ = model()
            ctx = context(BIG_ORDERS, baseline=BASELINE, second_payload=ORDERS, model=local, history=[{}],
                          retriever=lambda q, n: [{"source": "kb", "revision": "1", "citation": "kb#1",
                                                   "passage": "About volume."}])
            order = ["A34", "A01", "A02", "A03", "A04", "A05", "A10", "A07", "A08", "A09", "A11", "A13", "A14", "A18",
                     "A19", "A20", "A21", "A22", "A24", "A25", "A23", "A26", "A27", "A28", "A29", "A30", "A31", "A32",
                     "A33", "A35", "A36", "A06", "A12", "A15", "A16", "A17"]
            chain(ctx, order)
            # A05 (elapsed time), A35 (latency roll-up) and A26 (stores results with their latency) depend on the clock.
            clocked = ("A05", "A26", "A35")
            kinds = ("budget_check", "usage_rollup", "agent_result", "evidence_index")
            runs.append(({a: stable(r) for a, r in ctx.prior.items() if a not in clocked},
                         [ref for ref in ctx.evidence.refs() if ctx.evidence.kind(ref) not in kinds]))
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(len(runs[0][0]), 33)


if __name__ == "__main__":
    unittest.main()
