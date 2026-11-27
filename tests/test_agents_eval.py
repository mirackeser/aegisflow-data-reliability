# SPDX-License-Identifier: Apache-2.0
"""Tests of the agent runtime evaluation (plan Task 6). They never call Ollama and never run the held-out split.

Unit tests use a small recording made here with the recorded-response fake model (agents_support.FakeTransport) on one
development and one validation group; one test class replays a sample of the committed recording when it is present.
"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError

from agents_support import FakeTransport, envelope
from aegisflow_dr import baseline_eval as be, hypotheses_eval as he
from aegisflow_dr.agents import agents_eval as ae
from aegisflow_dr.agents.executors.orchestration import SPECIALISTS, TRIGGERS, is_order_extract, route
from aegisflow_dr.agents.llm import INVALID_OUTPUT, MODEL_UNAVAILABLE, TIMEOUT, LocalModel, prompt_sha256
from aegisflow_dr.agents.prompts import PROMPT_VERSION
from aegisflow_dr.agents.runtime import AGENT_IDS
from aegisflow_dr.profiling import read_table

DEV, VAL = 120, 122  # the first development and the first validation group
SMALL = ("unit_change", "stuck_sensor", "clean", "unmodelled_sign_flip")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["x"], "properties": {"x": {"type": "integer"}}}


def request_digest(system="s", user="u", schema=SCHEMA):
    return prompt_sha256(system, user, schema, model=ae.MODEL, max_tokens=512)


def entry(case="g120.clean", digest=None, response='{"x": 1}', error=None, latency=250):
    return {"case_id": case, "prompt_sha256": digest or request_digest(), "response_json": response, "error": error,
            "tokens_in": 30, "tokens_out": 5, "latency_ms": latency}


def recording(*calls, runs=()):
    rec = ae.new_recording(created="2026-11-25")
    rec["calls"], rec["runs"] = list(calls), list(runs)
    return rec


def small_recording(seen=None):
    rec = ae.new_recording(created="2026-11-25")
    return ae.record_live(rec, ae.SPLITS[:2], transport=FakeTransport(), scenarios=SMALL, groups=(DEV, VAL),
                          checkpoint=lambda case, wall: (seen if seen is not None else []).append((case, wall)))


# -- constructed run records ---------------------------------------------------------------------------------------------
def result(status="COMPLETED", code=None, claims=()):
    return {"status": status, "error_code": code, "claims": list(claims)}


def constructed(selected, results=None, verdicts=(), events=(), status="completed", exceeded=(), observations=()):
    results = results or {}
    return {"status": status, "budget": {"exceeded": list(exceeded)}, "intake": {"observations": list(observations)},
            "selection": [{"agent_id": a, "selected": a in selected} for a in AGENT_IDS],
            "agents": [{"agent_id": a, "result": results.get(a, result() if a in selected else result("SKIPPED",
                                                                                                    "NOT_SELECTED"))}
                       for a in AGENT_IDS],
            "judge": {"verdicts": list(verdicts)}, "events": list(events)}


def call_event(agent, digest, ok=True, code=None):
    return {"type": "llm_call", "agent_id": agent, "data": {"prompt_sha256": digest, "ok": ok, "error_code": code}}


def suggested(*mechanisms):
    return result(claims=[{"text_key": "a23.suggested", "params": {"mechanisms": list(mechanisms)}}])


def loop(*supported):
    return {"hypotheses": [{"mechanism": m, "status": "supported"} for m in supported]
            + [{"mechanism": "genuine_change", "status": "open"}]}


EXPECTED = set(ae.EXPECTED_SELECTED["unit_change"])
BASE = EXPECTED | {"A01", "A02", "A23", "A27"}


class SplitTests(unittest.TestCase):
    def test_split_assignment_is_stable_and_pinned(self):
        names = [ae.split_of(g) for g in ae.GROUPS]
        self.assertEqual(ae.GROUPS, range(120, 160))
        self.assertEqual(ae.SPLITS, ("development", "validation", "heldout"))
        # Realized counts only; the held-out split is never run here.
        self.assertEqual({name: names.count(name) for name in ae.SPLITS},
                         {"development": 21, "validation": 9, "heldout": 10})
        self.assertEqual(names[:8], ["development", "development", "validation", "development", "development",
                                     "development", "heldout", "validation"])
        self.assertEqual((ae.split_of(DEV), ae.split_of(VAL)), ("development", "validation"))

    def test_groups_are_disjoint_from_earlier_corpora(self):
        self.assertFalse(set(ae.GROUPS) & set(range(be.GROUPS)))
        self.assertFalse(set(ae.GROUPS) & set(he.GROUPS))
        self.assertEqual(len(ae.GROUPS), 40)

    def test_split_salt_differs_from_earlier_evaluations(self):
        ours = [ae.split_of(g) for g in ae.GROUPS]
        self.assertNotEqual(ours, [he.split_of(g) for g in ae.GROUPS])
        self.assertNotEqual(ours, [be.split_of(g) for g in ae.GROUPS])

    def test_no_payload_is_shared_with_earlier_corpora(self):
        ours, theirs = set(), set()
        for group in (DEV, VAL, ae.GROUPS[-1]):  # the payloads only; nothing is run
            for name in ae.SCENARIOS:
                references, current, _, _ = he.scenario(group, name)
                ours.update(references + [current])
        for group in (0, be.GROUPS - 1, he.GROUPS[0], he.GROUPS[-1]):
            for name in he.SCENARIOS:
                references, current, _, _ = he.scenario(group, name)
                theirs.update(references + [current])
        self.assertFalse(ours & theirs)

    def test_scenarios_are_the_hypothesis_evaluation_injections(self):
        self.assertIs(ae.SCENARIOS, he.SCENARIOS)
        self.assertEqual(ae.truth_of("unit_change"), "unit_change")
        self.assertIsNone(ae.truth_of("clean"))
        self.assertEqual(ae.case_id(DEV, "clean"), "g120.clean")


class ExpectationTests(unittest.TestCase):
    def test_expected_sets_follow_the_role_table_triggers(self):
        self.assertEqual(set(ae.EXPECTED_SELECTED), set(ae.SCENARIOS))
        self.assertEqual(set(ae.CASE_FACTS), set(ae.SCENARIOS))
        for name, facts in ae.CASE_FACTS.items():
            intake = {"history": facts["history"], "baseline": facts["baseline"], "retriever": facts["retriever"],
                      "order_extract": facts["order_extract"], "second_order_extract": facts["second_order_extract"],
                      "time_column": "ts" if facts["time_column"] else None, "type_mismatch": facts["type_signal"],
                      "role_change": False, "observations": []}
            routed = {item["agent"] for item in route(intake)["selected"]} & set(SPECIALISTS)
            self.assertEqual(routed, set(ae.EXPECTED_SELECTED[name]), name)
            self.assertLessEqual(len(routed), 8)
            self.assertEqual(set(TRIGGERS) & set(ae.EXPECTED_SELECTED[name]), set(ae.EXPECTED_SELECTED[name]))

    def test_case_facts_match_the_generated_inputs(self):
        for name in ae.SCENARIOS:
            references, current, as_of, _ = he.scenario(DEV, name)
            header = read_table(current)[0]
            self.assertEqual(header, list(be.HEADER), name)
            self.assertFalse(is_order_extract(header))
            self.assertEqual((len(references), bool(as_of)), (be.REFERENCES, True))


class ScoringTests(unittest.TestCase):
    def bucket(self):
        return ae._empty_bucket(("unit_change", "clean", "unmodelled_sign_flip"))

    def test_selection_and_outcome_arithmetic(self):
        bucket = self.bucket()
        record = constructed((BASE | {"A17"}) - {"A15"},
                             results={"A10": result("NEEDS_EVIDENCE", "NO_TIME_COLUMN"), "A23": suggested("unit_change"),
                                      "A27": result("SKIPPED", "DEPENDENCY_UNMET")})
        ae.score_case(bucket, "unit_change", record, [], loop("unit_change"))
        shift = [{"check": "distribution_shift", "direction": None}]
        ae.score_case(bucket, "unit_change", constructed(BASE, results={"A23": suggested("noise_increase",
                                                                                          "unit_change")},
                                                         observations=shift),
                      [], loop("unit_change", "noise_increase"))
        ae.score_case(bucket, "clean", constructed(BASE, results={"A23": suggested("unit_change", "calibration_offset")},
                                                   observations=shift), [], loop())
        ae.score_case(bucket, "clean", constructed(BASE, results={"A23": suggested("unit_change", "unit_change")},
                                                   observations=shift), [], loop())
        ae.score_case(bucket, "clean", constructed(BASE, results={"A23": suggested()}, observations=shift), [], loop())
        self.assertEqual(ae.catalog_order(shift)[:3], ["unit_change", "calibration_offset", "noise_increase"])
        self.assertEqual(ae.catalog_order([]), [])
        clean = bucket["scenarios"]["clean"]
        self.assertEqual((clean["a23_echo"], clean["a23_repeated"], clean["a23_suggested"], clean["a23_lengths"]),
                         (1, 1, 2, {2: 2, 0: 1}))
        row = bucket["scenarios"]["unit_change"]
        self.assertEqual((row["a23_lengths"], row["a23_echo"]), ({1: 1, 2: 1}, 0))
        self.assertEqual({k: row[k] for k in ("cases", "exact", "tp", "fp", "fn")},
                         {"cases": 2, "exact": 1, "tp": 9, "fp": 1, "fn": 1})
        self.assertEqual((row["extra"], row["missed"]), ({"A17": 1}, {"A15": 1}))
        self.assertEqual(bucket["agents"]["A10"], {"NEEDS_EVIDENCE/NO_TIME_COLUMN": 1, "COMPLETED": 4})
        self.assertEqual(bucket["agents"]["A27"], {"SKIPPED/DEPENDENCY_UNMET": 1, "COMPLETED": 4})
        self.assertNotIn("A03", bucket["agents"])
        self.assertEqual({k: row[k] for k in ("a23_selected", "a23_suggested", "a23_top1", "a23_any", "loop_sole",
                                               "loop_any")},
                         {"a23_selected": 2, "a23_suggested": 2, "a23_top1": 1, "a23_any": 2, "loop_sole": 1,
                          "loop_any": 2})
        ae._finalize(bucket)
        rates = bucket["scenarios"]["unit_change"]["rates"]
        self.assertEqual((rates["precision"]["successes"], rates["precision"]["trials"]), (9, 10))
        self.assertEqual((rates["recall"]["successes"], rates["recall"]["trials"]), (9, 10))
        self.assertEqual(rates["exact"]["rate"], 0.5)
        self.assertIsNone(rates["a23_misattributed"])
        self.assertEqual(bucket["selection"]["precision"]["trials"], 25)
        clean = bucket["scenarios"]["clean"]["rates"]
        self.assertIsNone(clean["a23_top1"])
        self.assertEqual(ae._show(clean["a23_misattributed"]), "2/3 = 66.7% [20.8–93.8]")
        self.assertEqual(clean["a23_echo"]["trials"], 2)
        self.assertEqual(bucket["scenarios"]["unit_change"]["rates"]["a23_echo"]["trials"], 2)

    def test_unmodelled_and_failed_suggestions(self):
        bucket = self.bucket()
        advisory = [{"agent": "A23", "verdict": "advisory", "reason": "model_suggestion", "text_key": "a23.suggested"}]
        ae.score_case(bucket, "unmodelled_sign_flip", constructed(BASE, results={"A23": suggested("genuine_change")},
                                                                  verdicts=advisory), [], loop("calibration_offset"))
        ae.score_case(bucket, "unmodelled_sign_flip", constructed(BASE, results={"A23": suggested(
            "genuine_change", "noise_increase")}), [], loop())
        ae.score_case(bucket, "unmodelled_sign_flip", constructed(BASE, results={"A23": result(
            "NEEDS_EVIDENCE", MODEL_UNAVAILABLE)}), [], loop())
        ae.score_case(bucket, "unit_change", constructed(BASE - {"A23"}), [], loop())
        self.assertEqual(bucket["a23_judge"], {"claims": 1, "advisory": 1, "reasons": {}})
        row = bucket["scenarios"]["unmodelled_sign_flip"]
        self.assertEqual((row["a23_suggested"], row["a23_misattributed"], row["loop_misattributed"]), (2, 1, 1))
        self.assertEqual(row["a23_lengths"], {1: 1, 2: 1})
        unit = bucket["scenarios"]["unit_change"]
        self.assertEqual((unit["a23_selected"], unit["a23_suggested"], unit["a23_top1"], unit["a23_any"]), (0, 0, 0, 0))
        ae._finalize(bucket)
        self.assertEqual(bucket["scenarios"]["unmodelled_sign_flip"]["rates"]["a23_misattributed"]["trials"], 3)
        self.assertIsNone(bucket["scenarios"]["unmodelled_sign_flip"]["rates"]["loop_sole"])

    def test_judge_and_model_call_arithmetic(self):
        bucket = self.bucket()
        verdicts = [{"agent": "A10", "verdict": "accepted", "reason": "evidence_verified"},
                    {"agent": "A11", "verdict": "rejected", "reason": "free_text_in_params"},
                    {"agent": "A01", "verdict": "accepted", "reason": "evidence_verified", "text_key": "a01.run_status"},
                    {"agent": "A02", "verdict": "accepted", "reason": "evidence_verified", "text_key": "a02.plan"},
                    {"agent": "A02", "verdict": "advisory", "reason": "model_suggestion", "text_key": "a02.worded"},
                    {"agent": "A23", "verdict": "rejected", "reason": "mechanism_does_not_explain",
                     "text_key": "a23.suggested"},
                    {"agent": "A23", "verdict": "advisory", "reason": "model_suggestion", "text_key": "a23.compared"},
                    {"agent": "A29", "verdict": "advisory", "reason": "model_suggestion", "text_key": "a29.options"}]
        events = [{"type": "agent_started", "agent_id": "A02", "data": {}},
                  call_event("A02", "a" * 64), call_event("A23", "b" * 64, False, INVALID_OUTPUT),
                  call_event("A29", "c" * 64, False, TIMEOUT), call_event("A29", "d" * 64, False, MODEL_UNAVAILABLE)]
        calls = [{"prompt_sha256": "a" * 64, "latency_ms": 1200, "miss": False},
                 {"prompt_sha256": "b" * 64, "latency_ms": 900, "miss": False},
                 {"prompt_sha256": "c" * 64, "latency_ms": 30000, "miss": False},
                 {"prompt_sha256": "d" * 64, "miss": True}]
        record = constructed(BASE, verdicts=verdicts, events=events, status="completed_with_gaps",
                             exceeded=["llm_calls"])
        ae.score_case(bucket, "clean", record, calls, loop(), {"wall_ms": 7000, "outcome_sha256": ae.outcome(record)})
        ae.score_case(bucket, "clean", record, [], loop(), {"wall_ms": 9000, "outcome_sha256": "0" * 64})
        ae.score_case(bucket, "clean", record, [], loop())
        self.assertEqual((bucket["judge"]["claims"], bucket["judge"]["accepted"]), (6, 3))
        self.assertEqual(bucket["judge"]["reasons"], {"free_text_in_params": 3})
        llm = bucket["llm"]
        self.assertEqual({k: llm["A02"][k] for k in ("calls", "valid", "advisory", "rejected")},
                         {"calls": 3, "valid": 3, "advisory": 3, "rejected": 0})
        self.assertEqual((llm["A23"]["invalid"], llm["A23"]["advisory"], llm["A23"]["rejected"]), (3, 3, 3))
        self.assertEqual(llm["A23"]["reasons"], {"mechanism_does_not_explain": 3})
        self.assertEqual((llm["A29"]["timeout"], llm["A29"]["unavailable"], llm["A29"]["calls"]), (3, 3, 6))
        self.assertEqual(bucket["a23_judge"], {"claims": 3, "advisory": 0,
                                               "reasons": {"mechanism_does_not_explain": 3}})
        runs = bucket["runs"]
        self.assertEqual((runs["statuses"], runs["exceeded"], runs["misses"], runs["compared"], runs["matched"]),
                         ({"completed_with_gaps": 3}, {"llm_calls": 3}, 1, 2, 1))
        ae._finalize(bucket)
        self.assertEqual(bucket["judge"]["rate"]["rate"], 0.5)
        self.assertEqual((llm["A02"]["p50"], llm["A02"]["p95"], llm["A02"]["latencies"]), (1200, 1200, 1))
        self.assertEqual(llm["A23"]["rates"]["valid"]["rate"], 0.0)
        self.assertIsNone(llm["A29"]["rates"]["valid"]["rate"])
        self.assertIsNone(llm["A22"]["p50"])
        self.assertEqual((runs["p50"], runs["p95"], runs["walls"]), (7000, 9000, 2))
        self.assertEqual(runs["fidelity"]["rate"], 0.5)
        self.assertEqual(bucket["a23_judge"]["rate"]["rate"], 0.0)

    def test_percentile_is_nearest_rank(self):
        self.assertIsNone(ae.percentile([], 50))
        values = list(range(1, 21))
        self.assertEqual((ae.percentile(values, 50), ae.percentile(values, 95), ae.percentile(values, 100)),
                         (10, 19, 20))
        self.assertEqual(ae.percentile([5], 95), 5)

    def test_render_shows_n_a_for_an_empty_split(self):
        bucket = ae._empty_bucket()
        ae._finalize(bucket)
        report = {"version": ae.VERSION, "scope": ae.SCOPE, "groups": len(ae.GROUPS), "splits": {"heldout": bucket},
                  "recording": {"model": ae.MODEL, "prompt_version": PROMPT_VERSION, "created": "2026-11-25",
                                "calls": 0, "runs": 0}}
        text = ae.render_markdown(report)
        self.assertIn("development, validation and held-out (`--include-heldout`)", text)
        self.assertIn("| unit_change | 0 | n/a | n/a | n/a | none | none |", text)
        self.assertIn("| A23 | 0 | n/a | 0 | 0 | n/a | none | n/a | n/a |", text)
        self.assertIn("| clean | 0/0 | n/a | none | n/a | n/a | n/a | n/a | n/a | n/a | n/a |", text)
        self.assertIn("more than once: n/a.", text)
        self.assertIn("p50 n/a, p95 n/a", text)
        self.assertIn("accepted n/a; not accepted by reason: none", text)


class RecordingTests(unittest.TestCase):
    def test_check_recording(self):
        good = recording(entry(), runs=[{"case_id": "g120.clean", "split": "development", "wall_ms": 7,
                                         "outcome_sha256": "e" * 64}])
        self.assertIs(ae.check_recording(good), good)
        bad = [None, {**good, "version": "0"}, {**good, "model": 1}, {**good, "created": None}, {**good, "calls": {}},
               {**good, "runs": None}, recording(entry(digest="x")), recording(entry(error="OTHER")),
               recording({**entry(), "latency_ms": -1}), recording({**entry(), "response_json": 3}),
               recording(runs=[{"case_id": "c", "split": "test", "wall_ms": 1, "outcome_sha256": "e" * 64}]),
               recording(runs=[{"case_id": "c", "split": "development", "wall_ms": 1, "outcome_sha256": "e"}])]
        for item in bad:
            with self.assertRaisesRegex(ValueError, "Invalid model recording"):
                ae.check_recording(item)
        with self.assertRaisesRegex(ValueError, "prompt version '1'; the code has"):
            ae.check_recording({**good, "prompt_version": "1"})

    def test_new_recording_and_round_trip(self):
        self.assertEqual(len(ae.new_recording()["created"]), 10)
        rec = recording(entry())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rec.json"
            ae.save_recording(rec, path)
            self.assertEqual(ae.load_recording(path), rec)
            self.assertTrue(path.read_text("utf-8").endswith("}\n"))

    def test_replay_serves_exact_recorded_responses(self):
        rec = recording(entry(latency=1500), entry(response='{"x": 2}', latency=700))
        replay, clock, log = ae.ReplayModel(rec), ae.VirtualClock(lambda: 10.0), []
        model = replay.model("g120.clean", clock, log)
        self.assertIs(type(model), LocalModel)
        first = model.complete("s", "u", SCHEMA)
        second = model.complete("s", "u", SCHEMA)
        self.assertEqual((first.ok, first.data, first.tokens_in, first.tokens_out), (True, {"x": 1}, 30, 5))
        self.assertEqual(second.data, {"x": 2})
        self.assertEqual(first.prompt_sha256, request_digest())
        self.assertAlmostEqual(clock(), 12.2)
        self.assertEqual([c["latency_ms"] for c in log], [1500, 700])
        third = model.complete("s", "u", SCHEMA)  # the recorded responses are used up: a miss, not a guess
        self.assertEqual((third.ok, third.error_code), (False, MODEL_UNAVAILABLE))
        self.assertEqual(replay.misses, [("g120.clean", request_digest())])
        # A fresh model for the case starts again from the first recorded response.
        self.assertEqual(replay.model("g120.clean").complete("s", "u", SCHEMA).data, {"x": 1})

    def test_unknown_hash_is_model_unavailable_with_a_clear_error(self):
        replay = ae.ReplayModel(recording(entry()))
        other = replay.model("g120.clean").complete("s", "different", SCHEMA)
        self.assertEqual((other.ok, other.data, other.error_code), (False, None, MODEL_UNAVAILABLE))
        wrong_case = replay.model("g121.clean").complete("s", "u", SCHEMA)
        self.assertEqual(wrong_case.error_code, MODEL_UNAVAILABLE)
        with self.assertRaisesRegex(ae.ReplayMiss, "No recorded response for prompt sha256 [0-9a-f]{64} in case "
                                                   "g120.clean; replay never guesses"):
            replay.transport("g120.clean")("http://127.0.0.1:11434/api/chat", b"{}", 30)
        self.assertEqual(len(replay.misses), 3)

    def test_replay_reproduces_recorded_failures(self):
        rec = recording(entry(error=TIMEOUT, response=None), entry(case="g120.unit_change", error=MODEL_UNAVAILABLE,
                                                                   response=None),
                        entry(case="g120.stuck_sensor", error=INVALID_OUTPUT, response=None),
                        entry(case="g120.partial_load", response='{"x": "no"}'))
        replay = ae.ReplayModel(rec)
        codes = [replay.model(case).complete("s", "u", SCHEMA).error_code
                 for case in ("g120.clean", "g120.unit_change", "g120.stuck_sensor", "g120.partial_load")]
        self.assertEqual(codes, [TIMEOUT, MODEL_UNAVAILABLE, INVALID_OUTPUT, INVALID_OUTPUT])
        self.assertEqual(replay.misses, [])

    def test_recorder_records_live_outcomes(self):
        calls = []
        replies = [envelope({"x": 1}, prompt=12, output=3), TimeoutError(), URLError(TimeoutError()), OSError("down"),
                   b"not json", json.dumps({"message": {"content": 5}}).encode(),
                   json.dumps({"message": {"content": "{}"}, "prompt_eval_count": -1, "eval_count": "9"}).encode()]
        model = LocalModel(transport=ae.recorder(FakeTransport(*replies), "g120.clean", calls))
        codes = [model.complete("s", "u%d" % n, SCHEMA).error_code for n in range(len(replies))]
        self.assertEqual(codes, [None, TIMEOUT, TIMEOUT, MODEL_UNAVAILABLE, INVALID_OUTPUT, INVALID_OUTPUT,
                                 INVALID_OUTPUT])
        self.assertEqual([c["error"] for c in calls], [None, TIMEOUT, TIMEOUT, MODEL_UNAVAILABLE, INVALID_OUTPUT,
                                                       INVALID_OUTPUT, None])
        self.assertEqual((calls[0]["response_json"], calls[0]["tokens_in"], calls[0]["tokens_out"]), ('{"x": 1}', 12, 3))
        self.assertEqual((calls[6]["response_json"], calls[6]["tokens_in"], calls[6]["tokens_out"]), ("{}", 0, 0))
        self.assertEqual(calls[0]["prompt_sha256"], prompt_sha256("s", "u0", SCHEMA, model=ae.MODEL, max_tokens=512))
        self.assertTrue(all(c["case_id"] == "g120.clean" and c["latency_ms"] >= 0 for c in calls))
        ae.check_recording(recording(*calls))
        # Replaying what was recorded gives the same typed outcomes.
        replay = ae.ReplayModel(recording(*calls)).model("g120.clean")
        self.assertEqual([replay.complete("s", "u%d" % n, SCHEMA).error_code for n in range(len(replies))], codes)


class SmallRecordingTests(unittest.TestCase):
    """Record one development and one validation group with the fake model, then replay and score them."""

    @classmethod
    def setUpClass(cls):
        cls.seen = []
        cls.recording = small_recording(cls.seen)
        cls.report = ae.evaluate(cls.recording, scenarios=SMALL, groups=(DEV, VAL))
        cls.text = ae.render_markdown(cls.report)

    def test_recording_covers_the_cases(self):
        self.assertEqual([r["case_id"] for r in self.recording["runs"]],
                         [ae.case_id(g, n) for g in (DEV, VAL) for n in SMALL])
        self.assertEqual({r["split"] for r in self.recording["runs"]}, {"development", "validation"})
        self.assertTrue(self.recording["calls"])
        self.assertEqual([case for case, _ in self.seen], [r["case_id"] for r in self.recording["runs"]])
        self.assertEqual([wall for _, wall in self.seen], [r["wall_ms"] for r in self.recording["runs"]])
        ae.check_recording(self.recording)

    def test_cases_keep_to_the_requested_splits(self):
        # Group 126 is held-out: it is skipped by its hash alone, before any payload is generated or run.
        self.assertEqual(ae.split_of(126), "heldout")
        listed = [(group, split, name) for group, split, name, *_ in ae.cases(("development",), ("clean",),
                                                                               (126, DEV, VAL))]
        self.assertEqual(listed, [(DEV, "development", "clean")])

    def test_replay_reproduces_every_live_outcome(self):
        for split in ("development", "validation"):
            runs = self.report["splits"][split]["runs"]
            self.assertEqual((runs["cases"], runs["compared"], runs["matched"], runs["misses"]), (4, 4, 4, 0))
            self.assertEqual(self.report["splits"][split]["groups"], 1)

    def test_heldout_absent_by_default(self):
        self.assertEqual(set(self.report["splits"]), {"development", "validation"})
        self.assertNotIn("Split: heldout", self.text)
        self.assertIn("development and validation; `--include-heldout` adds the held-out split", self.text)

    def test_report_is_deterministic(self):
        again = ae.render_markdown(ae.evaluate(self.recording, scenarios=SMALL, groups=(DEV, VAL)))
        self.assertEqual(again, self.text)

    def test_report_text(self):
        for phrase in ("## Split: development (1 groups)", "## Split: validation (1 groups)",
                       "groups 120-159", "(D05c, groups 0-59)", "(F04, groups 60-119)",
                       "development 21, validation 9 and held-out 10 groups", "salt `aegisflow-agents-eval-v1`",
                       "Model `qwen3:4b`", "prompt version %s" % PROMPT_VERSION, "never a guess",
                       "not diagnostic accuracy on real data", "advisory", "Judge", "not a calibrated best guess",
                       "constrained decoding", "held-out is scored once", "A17 (no type or role change injected)",
                       "| unit_change | pressure_kpa x 10 | A08, A10, A11, A15, A20 |",
                       "| A29 Remediation Strategy Planner | llm |", "Replay reproduced the live outcome in 4/4"):
            self.assertIn(phrase, self.text)

    def test_missing_recording_is_reported_as_misses(self):
        empty = ae.evaluate(recording(), scenarios=("unit_change",), groups=(DEV,))
        runs = empty["splits"]["development"]["runs"]
        self.assertGreater(runs["misses"], 0)
        self.assertEqual((runs["compared"], runs["walls"]), (0, 0))
        self.assertEqual(empty["splits"]["development"]["llm"]["A23"]["unavailable"], 1)
        self.assertEqual(empty["splits"]["validation"]["groups"], 0)

    def test_record_live_skips_recorded_cases(self):
        rec = json.loads(json.dumps(self.recording))
        transport, seen = FakeTransport(), []
        ae.record_live(rec, ae.SPLITS[:2], transport=transport, scenarios=SMALL, groups=(DEV, VAL),
                       checkpoint=lambda case, wall: seen.append(case))
        self.assertEqual((transport.calls, seen, rec), ([], [], self.recording))
        fresh = ae.record_live(recording(), ("development",), transport=FakeTransport(), scenarios=("clean",),
                               groups=(DEV,))  # no checkpoint
        self.assertEqual([r["case_id"] for r in fresh["runs"]], ["g120.clean"])


    def test_record_live_stops_when_the_model_stops_answering(self):
        def dead(url, body, timeout):
            raise ConnectionRefusedError("connection refused")

        rec, seen = recording(), []
        with self.assertRaises(ae.ModelStopped) as caught:
            ae.record_live(rec, ("development",), transport=dead, scenarios=SMALL, groups=(DEV,),
                           checkpoint=lambda case, wall: seen.append(case))
        self.assertIn("stopped answering", str(caught.exception))
        self.assertEqual((rec["runs"], rec["calls"], seen), ([], [], []))  # the failed case is not marked done


class MainTests(unittest.TestCase):
    def test_default_replays_the_committed_recording_without_heldout(self):
        with mock.patch.object(ae, "load_recording", return_value="rec") as load, \
                mock.patch.object(ae, "evaluate", return_value="report") as evaluate, \
                mock.patch.object(ae, "render_markdown", return_value="text"), \
                mock.patch.object(Path, "exists", return_value=True):
            self.assertEqual(ae.main(), "text")
            load.assert_called_once_with(ae.RECORDING)
            evaluate.assert_called_once_with("rec", ("development", "validation"))
            ae.main(["--include-heldout"])
            evaluate.assert_called_with("rec", ("development", "validation", "heldout"))

    def test_missing_recording_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                ae.main(["--record", str(Path(folder) / "none.json")])

    def test_live_records_then_replays(self):
        def fake_live(rec, splits, transport, checkpoint):
            rec["runs"].append({"case_id": "g120.clean", "split": "development", "wall_ms": 5,
                                "outcome_sha256": "e" * 64})
            checkpoint("g120.clean", 5)

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(ae, "record_live", side_effect=fake_live) as live, \
                mock.patch.object(ae, "evaluate", return_value="report") as evaluate, \
                mock.patch.object(ae, "render_markdown", return_value="text"):
            path = Path(folder) / "rec.json"
            self.assertEqual(ae.main(["--live", "--record", str(path)], transport="t", err=err), "text")
            self.assertEqual(live.call_args.args[1], ("development", "validation"))
            self.assertEqual(live.call_args.kwargs["transport"], "t")
            saved = ae.load_recording(path)
            self.assertEqual(len(saved["runs"]), 1)
            self.assertEqual(evaluate.call_args.args, (saved, ("development", "validation")))
            ae.main(["--live", "--record", str(path)], err=err)  # extends the existing recording
            self.assertEqual(len(ae.load_recording(path)["runs"]), 2)
        self.assertEqual(err.getvalue(), "g120.clean 5 ms\ng120.clean 5 ms\n")

    def test_live_saves_and_exits_when_the_model_stops(self):
        def stopped_live(rec, splits, transport, checkpoint):
            rec["runs"].append({"case_id": "g120.clean", "split": "development", "wall_ms": 5,
                                "outcome_sha256": "e" * 64})
            raise ae.ModelStopped("The local model stopped answering during g120.unit_change")

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, mock.patch("sys.stderr", err), \
                mock.patch.object(ae, "record_live", side_effect=stopped_live):
            path = Path(folder) / "rec.json"
            with self.assertRaises(SystemExit) as caught:
                ae.main(["--live", "--record", str(path)])
            self.assertEqual(caught.exception.code, 1)
            self.assertEqual([r["case_id"] for r in ae.load_recording(path)["runs"]], ["g120.clean"])
        self.assertIn("stopped answering", err.getvalue())


@unittest.skipUnless(ae.RECORDING.exists(), "no committed recording")
class CommittedRecordingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recording = ae.load_recording(ae.RECORDING)

    def test_recording_metadata(self):
        self.assertEqual((self.recording["model"], self.recording["prompt_version"]), (ae.MODEL, PROMPT_VERSION))
        cases = {r["case_id"] for r in self.recording["runs"]}
        self.assertEqual(len(cases), len(self.recording["runs"]))
        self.assertTrue({c["case_id"] for c in self.recording["calls"]} <= cases)
        for run in self.recording["runs"]:
            group, name = run["case_id"][1:].split(".", 1)
            self.assertIn(name, ae.SCENARIOS)
            self.assertEqual(run["split"], ae.split_of(int(group)))
        recorded = {r["split"] for r in self.recording["runs"]}
        self.assertTrue({"development", "validation"} <= recorded)

    def test_recording_contains_no_cell_value(self):
        """Model outputs over aggregate contexts only: no cell value of any generated payload appears in them."""
        texts = {}
        for call in self.recording["calls"]:
            texts.setdefault(call["case_id"], []).append(call["response_json"] or "")
        def cells(payloads):
            return {value.strip() for payload in payloads for row in read_table(payload)[1] for value in row
                    if value.strip()}

        reference_cells = {}
        for identifier, outputs in texts.items():
            group, name = identifier[1:].split(".", 1)
            references, current, _, _ = he.scenario(int(group), name)
            if group not in reference_cells:  # every scenario of a group shares its reference batches
                reference_cells[group] = cells(references)
            text = "\n".join(outputs)
            self.assertEqual([c for c in reference_cells[group] | cells([current]) if c in text], [], identifier)

    def test_replay_of_a_sample_reproduces_the_live_runs(self):
        report = ae.evaluate(self.recording, groups=(DEV, VAL))
        for split in ("development", "validation"):
            runs = report["splits"][split]["runs"]
            self.assertEqual((runs["cases"], runs["compared"], runs["matched"], runs["misses"]),
                             (len(ae.SCENARIOS),) * 3 + (0,), split)


if __name__ == "__main__":
    unittest.main()
