# SPDX-License-Identifier: Apache-2.0
from random import Random
import unittest

from jsonschema import Draft202012Validator

from aegisflow_dr.agents import prompts
from aegisflow_dr.agents.prompts import (FREE_TEXT_KEYS, PROMPT_VERSION, TEMPLATES, VOCABULARY, case_vocabulary,
                                         free_text_ok, safe_context)
from aegisflow_dr.hypotheses import MECHANISMS
from aegisflow_dr.pipeline import InputRejected

HEADER = frozenset({"order_id", "customer_id", "order_total"})
CELLS = frozenset({"ORD-00001", "CUS-007", "12.50", "x"})


class Vocabulary(unittest.TestCase):
    def test_case_vocabulary_reads_header_and_stripped_cells_and_skips_unreadable_payloads(self):
        header, cells = case_vocabulary(b"a,b\n 1 ,x\n,y\n", None, b"\xff", b"c\n2\n")
        self.assertEqual(header, {"a", "b", "c", "order_id", "customer_id", "order_total"})
        self.assertEqual(cells, {"1", "x", "y", "2"})

    def test_vocabulary_has_checks_mechanisms_and_no_free_text(self):
        self.assertTrue(set(MECHANISMS) <= VOCABULARY)
        self.assertTrue({"duplicate_rows", "volume_change", "not_null", "flatline"} <= VOCABULARY)
        self.assertEqual(PROMPT_VERSION, "2")
        self.assertEqual(set(TEMPLATES), {"a02", "a22", "a23", "a29", "a30"})
        self.assertEqual(FREE_TEXT_KEYS, {"passage", "kb_source", "option_title", "option_rollback"})


class SafeContext(unittest.TestCase):
    def ok(self, obj):
        self.assertIs(safe_context(obj, header=HEADER, cells=CELLS), obj)

    def bad(self, obj, **kwargs):
        options = {"header": HEADER, "cells": CELLS, **kwargs}
        with self.assertRaisesRegex(InputRejected, "^LLM context contains a value that is not allowed$"):
            safe_context(obj, **options)

    def test_accepts_names_ids_numbers_and_clean_free_text(self):
        self.ok({"goals": [{"id": "g1", "check": "not_null", "column": "order_total", "count": 3, "share": 0.25,
                            "flag": True, "none": None}],
                 "observations": [{"id": "obs-12", "agent": "A10", "text_key": "a10.finding"}],
                 "ids": ["hyp-1", "prb-2", "c3", "f4", "opt1"],
                 "citations": [{"id": "c1", "kb_source": "runbook", "passage": "Duplicates inflate totals."}]})
        empty = {}
        self.assertIs(safe_context(empty), empty)

    def test_rejects_cell_values_unknown_text_and_bad_shapes(self):
        for obj in ({"column": "ORD-00001"}, {"column": "free text"}, {"note": "12.50"},
                    {"values": [1, "CUS-007"]}, {"Bad": 1}, {1: "x"}, {"n": float("nan")}, {"n": float("inf")},
                    {"n": object()}, {"n": (1, 2)}, {"nested": {"deep": {"deeper": {"a": {"b": {"c": {"d": 1}}}}}}}):
            with self.subTest(obj=obj):
                self.bad(obj)
        for obj in (None, [], "text"):
            with self.subTest(obj=obj):
                self.bad(obj)

    def test_free_text_may_not_contain_or_equal_a_cell(self):
        self.bad({"passage": "Order ORD-00001 was late."})
        self.bad({"kb_source": "x"})
        self.bad({"passage": "a" * 401})
        self.bad({"passage": "A short x note about tax."})  # a short non-numeric cell matches as a whole token
        self.ok({"passage": "A short note about tax."})
        self.assertTrue(free_text_ok("fine", frozenset()))
        self.assertFalse(free_text_ok(" CUS-007 ", CELLS))

    def test_free_text_check_normalises_case_and_unicode_and_catches_short_cells(self):
        cells = frozenset({"M\u00fcller", "abc", "Q", "7"})
        self.assertFalse(free_text_ok("Customer M\u00dcLLER", cells))
        self.assertFalse(free_text_ok("Customer Mu\u0308ller", cells))
        self.assertFalse(free_text_ok("Customer \uff2d\u00fcller", cells))
        self.assertFalse(free_text_ok("seen ABC twice", cells))
        self.assertFalse(free_text_ok("grade q here", cells))
        self.assertTrue(free_text_ok("Quality of 7 records", cells))  # short cells match whole tokens; numbers < 3 chars skip
        self.assertTrue(free_text_ok("Quality matters", frozenset({"Q"})))
        self.assertFalse(free_text_ok(" 7 ", cells))

    def test_allowed_names_stay_allowed_as_names_even_when_they_are_cells(self):
        names = frozenset({"order_total"})
        self.assertIs(safe_context(ctx := {"column": "order_total"}, header=names, cells=frozenset({"order_total"})), ctx)
        self.assertTrue(free_text_ok("Check order_total first", frozenset({"order_total"}), names))
        self.assertFalse(free_text_ok("Check order_total first", frozenset({"order_total"})))

    def test_case_vocabulary_adds_baseline_and_contract_names(self):
        from agents_support import BASELINE
        names, _ = case_vocabulary(b"x\n1\n", baseline=BASELINE)
        self.assertTrue({"x", "order_id", "customer_id", "order_total"} <= names)
        names, _ = case_vocabulary(b"x\n1\n", baseline={"columns": "junk"})
        self.assertEqual(names, {"x", "order_id", "customer_id", "order_total"})

    def test_signal_ids_are_run_ids(self):
        self.ok({"refs": ["sig-1", "obs-2"]})

    def test_size_limit(self):
        self.bad({"counts": list(range(5000))})

    def test_random_payload_cells_never_pass_outside_free_text(self):
        rng = Random(11)
        for _ in range(200):
            value = "".join(rng.choice("ABCDEFXYZ0123456789-._ ") for _ in range(rng.randint(4, 12))).strip()
            if not value or value in VOCABULARY or prompts._RUN_ID.fullmatch(value):
                continue
            with self.subTest(value=value):
                self.bad({"column": value}, header=HEADER, cells=frozenset({value}))
                self.bad({"passage": "see " + value}, header=HEADER, cells=frozenset({value}))


class Schemas(unittest.TestCase):
    def test_output_schemas_are_valid_and_restrict_ids(self):
        cases = [
            (prompts.planner_schema(["g1"], ["sig-1"]), {"questions": [{"goal": "g1", "refs": ["sig-1"], "question": "q"}]},
             {"questions": [{"goal": "g1", "refs": ["sig-2"], "question": "q"}]}),
            (prompts.relevance_schema(["c1"]), {"relevance": [{"citation": "c1", "sentence": "s"}]},
             {"relevance": [{"citation": "c1", "sentence": "s", "extra": 1}]}),
            (prompts.hypothesis_schema(["obs-1"]), {"candidates": [{"mechanism": "partial_load", "explains": ["obs-1"]}]},
             {"candidates": [{"mechanism": "root_cause", "explains": ["obs-1"]}]}),
            (prompts.remediation_schema(["f1"]),
             {"options": [{"title": "t", "risk": "low", "rollback": "r", "addresses": ["f1"]}]}, {"options": []}),
            (prompts.patch_schema(["opt1"]), {"proposal": {"kind": "sql", "text": "t", "addresses": ["opt1"]}},
             {"proposal": {"kind": "shell", "text": "t", "addresses": ["opt1"]}}),
        ]
        for schema, good, bad in cases:
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            self.assertTrue(validator.is_valid(good))
            self.assertFalse(validator.is_valid(bad))
        too_many = {"candidates": [{"mechanism": "partial_load", "explains": ["obs-1"]}] * 4}
        self.assertFalse(Draft202012Validator(prompts.hypothesis_schema(["obs-1"])).is_valid(too_many))

    def test_templates_render_the_canonical_context(self):
        user = TEMPLATES["a23"].user({"b": 1, "a": ["x"]})
        self.assertTrue(user.endswith('{"a":["x"],"b":1}'))
        for name, template in TEMPLATES.items():
            self.assertEqual(template.name, name)
            self.assertTrue(1 <= template.max_tokens <= 512)
            self.assertRegex(template.system, "(?i)never|not a cause|do not state|nothing is executed")


if __name__ == "__main__":
    unittest.main()
