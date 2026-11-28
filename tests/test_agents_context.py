# SPDX-License-Identifier: Apache-2.0
from hashlib import sha256
import json
import unittest

from aegisflow_dr.advisory.context_cache import ContextCache
from aegisflow_dr.agents.context import (AgentContext, EvidenceStore, reference, PolicyDenied, ToolBudgetExceeded, ToolError,
                                         Usage)
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.pipeline import InputRejected, generate_orders

PAYLOAD = generate_orders(rows=12)


def bound_task(agent_id="A10", tools=("profile_csv",), calls=2):
    return {"agent_id": agent_id, "allowed_tools": list(tools),
            "budget": {"max_tool_calls": calls, "max_llm_calls": 0, "max_tokens": 0, "deadline_ms": 1000}}


class Evidence(unittest.TestCase):
    def test_put_is_digest_addressed_and_get_returns_a_copy(self):
        store = EvidenceStore()
        obj = {"b": [1, 2.5, None, True], "a": "x"}
        ref = store.put("profile", obj)
        digest = sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(ref, {"id": "profile:" + digest[:32], "sha256": digest})
        self.assertEqual(store.put("profile", dict(reversed(list(obj.items())))), ref)
        copy = store.get(ref)
        copy["a"] = "changed"
        self.assertEqual(store.get(ref), obj)
        self.assertTrue(store.has(ref))
        self.assertEqual(store.kind(ref), "profile")
        other = store.put("triage", obj)
        self.assertNotEqual(other["id"], ref["id"])
        self.assertEqual(store.refs(), [ref, other])
        self.assertEqual(store.refs("triage"), [other])

    def test_unknown_or_mismatched_references_do_not_resolve(self):
        store = EvidenceStore()
        ref = store.put("profile", {"a": 1})
        for bad in ({"id": ref["id"], "sha256": "0" * 64}, {"id": "profile:nope", "sha256": ref["sha256"]},
                    {"id": ref["id"]}, {"id": 1, "sha256": ref["sha256"]}, {"id": ref["id"], "sha256": None},
                    None, [ref["id"]]):
            with self.subTest(bad=bad):
                self.assertFalse(store.has(bad))
                self.assertIsNone(store.kind(bad) if type(bad) is dict and "id" in bad else None)
                with self.assertRaisesRegex(InputRejected, "^Unknown or altered evidence reference$"):
                    store.get(bad)

    def test_altered_bytes_are_detected(self):
        store = EvidenceStore()
        ref = store.put("profile", {"a": 1})
        body, digest = store._items[ref["id"]]
        store._items[ref["id"]] = (body.replace(b"1", b"2"), digest)
        self.assertFalse(store.has(ref))
        self.assertIsNone(store.kind(ref))

    def test_rejects_bad_kind_non_json_collision_and_overflow(self):
        store = EvidenceStore(max_items=1, max_bytes=100)
        for kind in ("", "Profile", "1x", "a" * 32, None):
            with self.subTest(kind=kind), self.assertRaisesRegex(InputRejected, "^Invalid evidence kind$"):
                store.put(kind, {})
        for obj in (float("nan"), {1: object()}, {"a": object()}):
            with self.subTest(obj=obj), self.assertRaisesRegex(InputRejected, "^Evidence must be finite JSON$"):
                store.put("x", obj)
        ref = store.put("x", {"a": 1})
        with self.assertRaisesRegex(InputRejected, "^Evidence store is full$"):
            store.put("x", {"a": 2})
        roomy = EvidenceStore(max_bytes=10)
        with self.assertRaisesRegex(InputRejected, "^Evidence store is full$"):
            roomy.put("x", {"long": "value"})
        store._items[ref["id"]] = (store._items[ref["id"]][0], "f" * 64)
        with self.assertRaisesRegex(InputRejected, "^Evidence identifier collision$"):
            store.put("x", {"a": 1})


class Staged(unittest.TestCase):
    def test_an_agents_writes_stay_private_until_committed(self):
        store = EvidenceStore()
        shared = store.put("profile", {"rows": 3})
        view = store.stage()
        self.assertIsInstance(view, EvidenceStore)
        self.assertEqual(view.put("profile", {"rows": 3}), shared)  # already in the store: nothing staged
        own = view.put("lineage", {"to": ["customer_sales"]})
        self.assertEqual(view.put("lineage", {"to": ["customer_sales"]}), own)
        self.assertTrue(view.has(own) and view.has(shared))
        self.assertFalse(store.has(own))
        self.assertEqual((view.kind(own), view.kind(shared), view.get(own)), ("lineage", "profile",
                                                                              {"to": ["customer_sales"]}))
        self.assertEqual(view.refs(), [shared, own])
        self.assertEqual(view.refs("lineage"), [own])
        view.commit()
        self.assertTrue(store.has(own))
        self.assertEqual(store.refs(), [shared, own])

    def test_a_dropped_view_leaves_no_trace_and_bounds_count_the_store(self):
        store = EvidenceStore(max_items=2)
        store.put("a", {"n": 1})
        view = store.stage()
        view.put("a", {"n": 2})
        with self.assertRaisesRegex(InputRejected, "^Evidence store is full$"):
            view.put("a", {"n": 3})
        self.assertEqual(len(store.refs()), 1)  # never committed: as if the agent never wrote
        collided = EvidenceStore()
        ref = collided.put("x", {"a": 1})
        collided._items[ref["id"]] = (collided._items[ref["id"]][0], "f" * 64)
        with self.assertRaisesRegex(InputRejected, "^Evidence identifier collision$"):
            collided.stage().put("x", {"a": 1})


class Context(unittest.TestCase):
    def test_defaults_and_validation(self):
        ctx = AgentContext(PAYLOAD, "local", "case-1")
        self.assertIsInstance(ctx.evidence, EvidenceStore)
        self.assertEqual((ctx.prior, ctx.agent_id, ctx.allowed_tools, ctx.usage), ({}, None, (), Usage()))
        AgentContext(PAYLOAD, "local", "case-1", baseline={}, as_of="2026-01-01", second_payload=PAYLOAD,
                     retriever=lambda q, n: [], history=[], model=LocalModel(transport=lambda *a: b""),
                     cache=ContextCache(), prior={"A10": {}})
        bad = [{"payload": b""}, {"payload": "text"}, {"second_payload": b""}, {"tenant_id": "Local"},
               {"case_id": "-x"}, {"case_id": 5}, {"baseline": []}, {"as_of": 1}, {"retriever": "r"},
               {"history": {}}, {"evidence": {}}, {"model": object()}, {"cache": {}}, {"prior": []},
               {"clock": 1}, {"tenant_id": None}]
        for change in bad:
            kwargs = {"payload": PAYLOAD, "tenant_id": "local", "case_id": "case-1", **change}
            with self.subTest(change=list(change)), self.assertRaisesRegex(InputRejected, "^Invalid agent context$"):
                AgentContext(**kwargs)

    def test_elapsed_uses_the_injected_clock(self):
        ticks = iter([10.0, 10.25])
        ctx = AgentContext(PAYLOAD, "local", "case-1", clock=lambda: next(ticks))
        self.assertEqual((ctx.started, ctx.elapsed_ms()), (10.0, 250))
        self.assertEqual(AgentContext(PAYLOAD, "local", "c", clock=lambda: 1.0, started=2.0).elapsed_ms(), 0)

    def test_tool_enforces_allowlist_and_budget_and_counts(self):
        ctx = AgentContext(PAYLOAD, "local", "case-1")
        with self.assertRaisesRegex(InputRejected, "^Agent context is not bound to a task$"):
            ctx.tool("profile_csv", len, b"x")
        bound = ctx.for_task(bound_task(calls=2))
        self.assertEqual((bound.agent_id, bound.allowed_tools, bound.max_tool_calls), ("A10", ("profile_csv",), 2))
        self.assertIs(bound.evidence, ctx.evidence)
        self.assertIs(bound.memo, ctx.memo)
        with self.assertRaises(PolicyDenied) as denied:
            bound.tool("diagnose_csv", len, b"x")
        self.assertEqual(denied.exception.code, "TOOL_NOT_ALLOWED")
        self.assertEqual(bound.tool("profile_csv", len, b"abc"), 3)
        with self.assertRaisesRegex(InputRejected, "^boom$"):
            bound.tool("profile_csv", self._reject)
        with self.assertRaises(ToolBudgetExceeded):
            bound.tool("profile_csv", len, b"x")
        self.assertEqual(bound.usage.tool_calls, 2)
        self.assertEqual(ctx.usage.tool_calls, 0)

    def test_tool_errors_are_typed_and_carry_no_detail(self):
        bound = AgentContext(PAYLOAD, "local", "case-1").for_task(bound_task())

        def broken():
            raise KeyError("secret value")
        with self.assertRaises(ToolError) as caught:
            bound.tool("profile_csv", broken)
        self.assertEqual(str(caught.exception), "")
        self.assertIsNone(caught.exception.__cause__)

    def test_remember_builds_once_per_case(self):
        ctx = AgentContext(PAYLOAD, "local", "case-1")
        calls = []
        self.assertEqual(ctx.remember("k", lambda: calls.append(1) or 7), 7)
        self.assertEqual(ctx.for_task(bound_task()).remember("k", lambda: calls.append(1) or 8), 7)
        self.assertEqual(calls, [1])

    @staticmethod
    def _reject():
        raise InputRejected("boom")



class ReferenceTests(unittest.TestCase):
    def test_reference_matches_what_a_store_returns(self):
        value = {"b": 1, "a": [1.5, "x"]}
        self.assertEqual(reference("investigation", value), EvidenceStore().put("investigation", value))
        with self.assertRaises(InputRejected):
            reference("bad kind!", value)

if __name__ == "__main__":
    unittest.main()
