# SPDX-License-Identifier: Apache-2.0
import copy
import json
import unittest
from importlib.resources import files

from jsonschema import Draft202012Validator

from aegisflow_dr.agents import contracts
from aegisflow_dr.agents.contracts import STATUSES, TRANSPORTS, validate_result, validate_task
from aegisflow_dr.pipeline import InputRejected

H = "a" * 64
REF = {"id": "ev-profile-1", "sha256": H}


def task(**changes):
    value = {
        "task_id": "task-1", "run_id": "run-1", "tenant_id": "local", "case_id": "case-1", "agent_id": "A10",
        "goal": "profile_payload", "input_refs": [REF], "allowed_tools": ["profile_csv"],
        "budget": {"max_tool_calls": 4, "max_llm_calls": 0, "max_tokens": 0, "deadline_ms": 90000},
        "policy_version": "1",
    }
    value.update(changes)
    return value


def result(**changes):
    value = {
        "task_id": "task-1", "agent_id": "A10",
        "status": "COMPLETED",
        "claims": [{"text_key": "profile.check_count", "params": {"check": "duplicate_rows", "count": 3,
                                                                  "share": 0.25, "ids": ["obs-1", "obs-2"],
                                                                  "flag": True, "column": None},
                    "evidence_refs": [REF]}],
        "evidence_refs": [REF],
        "uncertainty": {"level": "low", "reason": "deterministic_rule"},
        "proposed_actions": [],
        "usage": {"tool_calls": 1, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 12},
        "transport": "in_process",
        "llm": None,
        "retrieval": None,
        "error_code": None,
        "advisory_text": None,
    }
    value.update(changes)
    return value


LLM = {"provider": "ollama", "model": "qwen3:4b", "prompt_sha256": H, "temperature": 0, "seed": 7}


class Schemas(unittest.TestCase):
    def test_schemas_are_draft_2020_12_closed_and_offline(self):
        for name in ("agent-task-v1.json", "agent-result-v1.json"):
            text = files("aegisflow_dr").joinpath("data", name).read_text(encoding="utf-8")
            schema = json.loads(text)
            Draft202012Validator.check_schema(schema)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIs(schema["additionalProperties"], False)
            self.assertNotIn("http://", text.replace(schema["$schema"], ""))
            self.assertNotIn("https://", text.replace(schema["$schema"], ""))

    def test_enums_match_the_spec(self):
        self.assertEqual(STATUSES, ("COMPLETED", "NEEDS_EVIDENCE", "POLICY_DENIED", "SKIPPED", "FAILED"))
        self.assertEqual(TRANSPORTS, ("in_process", "mcp_local", "a2a_mtls"))
        schema = json.loads(files("aegisflow_dr").joinpath("data", "agent-result-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(schema["properties"]["status"]["enum"]), STATUSES)
        self.assertEqual(tuple(schema["properties"]["transport"]["enum"]), TRANSPORTS)


class Task(unittest.TestCase):
    def test_accepts_a_valid_task_and_returns_it(self):
        value = task()
        self.assertIs(validate_task(value), value)
        validate_task(task(input_refs=[], allowed_tools=[], agent_id="A36"))
        validate_task(task(agent_id="A23", allowed_tools=["local_llm"]))
        validate_task(task(agent_id="A17", allowed_tools=["baseline_compare"]))

    def test_rejects_invalid_tasks(self):
        bad = [
            task(extra=1),
            task(agent_id="A37"), task(agent_id="A00"), task(agent_id="A1"), task(agent_id="A10\n"),
            task(task_id=""), task(run_id="x" * 65), task(tenant_id="Has Space"), task(case_id=7),
            task(goal=""), task(goal="g" * 301),
            task(input_refs=[{"id": "ev-1"}]), task(input_refs=[{"id": "ev-1", "sha256": "A" * 64}]),
            task(input_refs=[REF, REF]),
            task(allowed_tools=["profile_csv", "profile_csv"]), task(allowed_tools=["Bad-Tool"]),
            task(budget={"max_tool_calls": 1, "max_llm_calls": 13, "max_tokens": 0, "deadline_ms": 1}),
            task(budget={"max_tool_calls": 1, "max_llm_calls": 0, "max_tokens": 40001, "deadline_ms": 1}),
            task(budget={"max_tool_calls": 1, "max_llm_calls": 0, "max_tokens": 0, "deadline_ms": 90001}),
            task(budget={"max_tool_calls": 1, "max_llm_calls": 0, "max_tokens": 0, "deadline_ms": 0}),
            task(budget={"max_tool_calls": True, "max_llm_calls": 0, "max_tokens": 0, "deadline_ms": 1}),
            task(budget={"max_tool_calls": 1, "max_llm_calls": 0, "max_tokens": 0}),
            task(policy_version=""),
            task(agent_id="A01"), task(allowed_tools=["local_llm"]), task(agent_id="A12"),
            task(allowed_tools=["profile_csv", "diagnose_csv"]),
            [], None, "task",
        ]
        missing = task()
        del missing["goal"]
        bad.append(missing)
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(InputRejected, "^Agent task contract rejected$"):
                validate_task(value)


class Result(unittest.TestCase):
    def test_accepts_valid_results_and_returns_them(self):
        value = result()
        self.assertIs(validate_result(value), value)
        validate_result(result(llm=LLM, transport="mcp_local", advisory_text="x" * 600,
                               retrieval={"citations": [{"source": "kb", "revision": "r1", "citation": "kb#1"}],
                                          "cache": "hit"}))
        validate_result(result(retrieval={"citations": [], "cache": "none"}, transport="a2a_mtls"))
        validate_result(result(proposed_actions=[{"text_key": "remediation.option", "params": {"rank": 1},
                                                  "executed": False}]))
        for status in STATUSES[1:]:
            validate_result(result(status=status, claims=[], evidence_refs=[], error_code="MODEL_UNAVAILABLE"))

    def test_rejects_invalid_results(self):
        claim = result()["claims"][0]

        def with_claim(**changes):
            changed = copy.deepcopy(claim)
            changed.update(changes)
            return result(claims=[changed])

        bad = [
            result(extra=1), result(status="DONE"), result(transport="http"),
            with_claim(text="the model says the root cause is X"),
            with_claim(text_key="Free text with spaces"),
            with_claim(evidence_refs=[]),
            with_claim(params={"nested": {"a": 1}}),
            with_claim(params={"long": "x" * 129}),
            with_claim(params={"Bad Key": 1}),
            with_claim(params={"many": list(range(17))}),
            with_claim(params={"list": [{"a": 1}]}),
            with_claim(params={"share": float("nan")}),
            with_claim(params={"share": float("inf")}),
            result(uncertainty={"level": "certain", "reason": "x"}),
            result(uncertainty={"level": "low", "reason": "free text reason"}),
            result(proposed_actions=[{"text_key": "a", "params": {}, "executed": True}]),
            result(usage={"tool_calls": -1, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0}),
            result(llm={**LLM, "temperature": 0.7}), result(llm={**LLM, "seed": 8}),
            result(llm={**LLM, "prompt_sha256": "x"}), result(llm={**LLM, "extra": 1}),
            result(retrieval={"citations": [], "cache": "warm"}),
            result(retrieval={"citations": [{"source": "kb", "revision": "r1", "citation": "c", "passage": "p"}],
                              "cache": "miss"}),
            result(advisory_text="x" * 601), result(advisory_text=""),
            result(error_code="MODEL_UNAVAILABLE"),
            result(error_code="lowercase"),
            result(status="FAILED", claims=[], evidence_refs=[], error_code=None),
            result(status="NEEDS_EVIDENCE", error_code="NO_BASELINE"),
            result(status="SKIPPED", claims=[], evidence_refs=[], error_code="NOT_SELECTED",
                   proposed_actions=[{"text_key": "a", "params": {}, "executed": False}]),
            [], None,
        ]
        for field in ("advisory_text", "task_id", "agent_id"):
            missing = result()
            del missing[field]
            bad.append(missing)
        bad += [result(task_id=""), result(agent_id="A37"), result(agent_id="a10"),
                with_claim(params={1: "x"}), with_claim(params={("tuple",): "x"}),
                result(proposed_actions=[{"text_key": "a", "params": {2: 1}, "executed": False}])]
        for value in bad:
            with self.subTest(value=value), self.assertRaisesRegex(InputRejected, "^Agent result contract rejected$"):
                validate_result(value)

    def test_validators_are_cached_and_offline(self):
        self.assertIs(contracts._validator("agent-task-v1"), contracts._validator("agent-task-v1"))
        with self.assertRaises(Exception):
            contracts._offline("https://example.invalid/schema")


if __name__ == "__main__":
    unittest.main()
