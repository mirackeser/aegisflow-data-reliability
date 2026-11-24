# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the executor tests: tasks, cases and a recorded-response fake of the local model (no Ollama)."""
from datetime import datetime, timedelta, timezone
import json

from aegisflow_dr.agents.context import AgentContext
from aegisflow_dr.agents.contracts import validate_result
from aegisflow_dr.agents.executors import resolve
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.agents.registry import role
from aegisflow_dr.baseline import build_baseline
from aegisflow_dr.pipeline import generate_orders

ORDERS = generate_orders(rows=24)
DUPLICATES = generate_orders(rows=24, fault="duplicate_order")
NULL_TOTAL = generate_orders(rows=24, fault="null_total")
DRIFTED = generate_orders(rows=24, fault="schema_drift")
BIG_ORDERS = generate_orders(rows=80, seed=3)
BASELINE = build_baseline([ORDERS])


def timed_csv(rows=40, *, step=60, gap_at=None, repeat_at=None, marker=None, extra_rows=()):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lines = ["ts,reading,label"]
    moment = start
    for n in range(rows):
        if gap_at is not None and n == gap_at:
            moment += timedelta(seconds=step * 10)
        stamp = moment if repeat_at is None or n != repeat_at else moment - timedelta(seconds=step)
        label = marker if marker is not None and n == rows // 2 else "ok"
        lines.append("%s,%s,%s" % (stamp.isoformat(), 20 + (n % 7) * 0.5, label))
        moment += timedelta(seconds=step)
    lines += list(extra_rows)
    return ("\n".join(lines) + "\n").encode()


TIMED = timed_csv()


def task(agent_id, *, tools=None, calls=8, llm_calls=2, tokens=4000, task_id=None):
    spec = role(agent_id)
    return {"task_id": task_id or "task-" + agent_id.lower(), "run_id": "run-1", "tenant_id": "local",
            "case_id": "case-1", "agent_id": agent_id, "goal": "test_goal", "input_refs": [],
            "allowed_tools": list(spec.allowed_tools if tools is None else tools),
            "budget": {"max_tool_calls": calls, "max_llm_calls": llm_calls, "max_tokens": tokens, "deadline_ms": 90000},
            "policy_version": "1"}


def context(payload=ORDERS, **kwargs):
    return AgentContext(payload, "local", "case-1", **kwargs)


def run(agent_id, ctx, **task_kwargs):
    result = resolve(agent_id)(task(agent_id, **task_kwargs), ctx)
    validate_result(result)
    return result


def envelope(data, prompt=40, output=12):
    content = data if type(data) is str else json.dumps(data)
    return json.dumps({"model": "qwen3:4b", "message": {"role": "assistant", "content": content}, "done": True,
                       "prompt_eval_count": prompt, "eval_count": output}).encode()


def _answer(schema):
    """A schema-valid recorded answer: the first allowed id(s) in each slot."""
    items = next(iter(schema["properties"].values()))
    name = next(iter(schema["properties"]))
    if name == "questions":
        refs = items["items"]["properties"]["refs"]["items"]["enum"][:1]
        return {"questions": [{"goal": g, "refs": refs, "question": "Which records fail %s?" % g}
                              for g in items["items"]["properties"]["goal"]["enum"]]}
    if name == "relevance":
        return {"relevance": [{"citation": c, "sentence": "Covers the same check."}
                              for c in items["items"]["properties"]["citation"]["enum"]]}
    if name == "candidates":
        return {"candidates": [{"mechanism": "duplicate_delivery",
                                "explains": items["items"]["properties"]["explains"]["items"]["enum"][:1]}]}
    if name == "options":
        ids = items["items"]["properties"]["addresses"]["items"]["enum"]
        return {"options": [{"title": "Quarantine affected records", "risk": "medium",
                             "rollback": "Restore the previous extract", "addresses": ids[:2]}]}
    ids = items["properties"]["addresses"]["items"]["enum"]
    return {"proposal": {"kind": "sql", "text": "Keep the first record per order_id in a reviewed staging view.",
                         "addresses": ids[:1]}}


class FakeTransport:
    """Answers each request from its JSON schema, or from queued overrides (bytes, dicts or exceptions)."""

    def __init__(self, *overrides):
        self.overrides, self.calls = list(overrides), []

    def __call__(self, url, body, timeout):
        request = json.loads(body)
        self.calls.append(request)
        if self.overrides:
            override = self.overrides.pop(0)
            if isinstance(override, BaseException):
                raise override
            return override if type(override) is bytes else envelope(override)
        return envelope(_answer(request["format"]))

    def prompts(self):
        return [m["content"] for request in self.calls for m in request["messages"]]


def model(*overrides):
    transport = FakeTransport(*overrides)
    return LocalModel(transport=transport), transport
