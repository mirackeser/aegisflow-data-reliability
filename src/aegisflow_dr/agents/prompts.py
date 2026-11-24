# SPDX-License-Identifier: Apache-2.0
"""Fixed, versioned prompt templates for the model-using roles and the A34 context rule.

Contexts are built by the executors only from whitelisted fields of tool outputs: column names, check names,
counts, rounded statistics, observation ids and mechanism names (docs/superpowers/specs/2026-11-24-agent-runtime-roles.md,
"LLM context rule"). ``safe_context`` is the final guard before any model call: every string must be a known name,
a column name of the case, or a run-local id, except under the few free-text keys that carry knowledge-base passages
or earlier model text; those must not contain any cell value of the case (of at least ``MIN_LEAK_CHARS`` characters)
and must not equal any cell value. A violation raises InputRejected, which the executors report as POLICY_DENIED.
Changing any template, schema or vocabulary requires a new ``PROMPT_VERSION``.
"""
from dataclasses import dataclass
import json
import math
import re

from ..baseline import CHECKS as BASELINE_CHECKS, ROLES
from ..hypotheses import MECHANISMS, PROBES
from ..pipeline import InputRejected
from ..profiling import CHECKS as PROFILE_CHECKS, read_table

PROMPT_VERSION = "1"
DIAGNOSE_CHECKS = ("missing_column", "unexpected_column", "not_null", "unique", "amount_format", "nonempty_dataset")
FREE_TEXT_KEYS = frozenset({"passage", "kb_source", "option_title", "option_rollback"})
MIN_LEAK_CHARS, MAX_FREE_TEXT, MAX_CONTEXT_CHARS, MAX_DEPTH = 4, 400, 12_000, 6
VOCABULARY = frozenset(PROFILE_CHECKS + BASELINE_CHECKS + DIAGNOSE_CHECKS + MECHANISMS + PROBES + ROLES + (
    "drop", "increase", "profile", "baseline", "low", "medium", "high", "sql", "csv_cleaning", "PASS", "FAIL",
    "BLOCKED", "FINDINGS", "NO_FINDINGS", "DRIFT", "NO_DRIFT", "BREAKING", "COMPATIBLE", "IDENTICAL", "order_count",
    "amount_cents", "supported", "open", "refuted", "no_observations", "none_supported", "single_supported",
    "multiple_supported"))
_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_RUN_ID = re.compile(r"(?:obs|hyp|prb)-[0-9]{1,4}|(?:g|c|f|opt)[0-9]{1,3}|A(?:0[1-9]|[12][0-9]|3[0-6])"
                     r"|a[0-9]{2}\.[a-z_]{1,40}")
_REJECTED = "LLM context contains a value that is not allowed"


def case_vocabulary(*payloads):
    """(column names, distinct stripped cell values) of the readable payloads; unreadable ones contribute nothing."""
    header, cells = set(), set()
    for payload in payloads:
        if payload is None:
            continue
        try:
            names, rows = read_table(payload)
        except InputRejected:
            continue
        header.update(names)
        cells.update(value.strip() for row in rows for value in row if value.strip())
    return frozenset(header), frozenset(cells)


def free_text_ok(text, cells):
    if len(text) > MAX_FREE_TEXT or text.strip() in cells:
        return False
    return not any(len(cell) >= MIN_LEAK_CHARS and cell in text for cell in cells)


def _check(value, header, cells, free, depth):
    if depth > MAX_DEPTH:
        return False
    if value is None or type(value) is bool or type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        if free:
            return free_text_ok(value, cells)
        return value in VOCABULARY or value in header or bool(_RUN_ID.fullmatch(value))
    if type(value) is list:
        return all(_check(item, header, cells, free, depth + 1) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _KEY.fullmatch(key) and _check(item, header, cells, key in FREE_TEXT_KEYS,
                                                                        depth + 1)
                   for key, item in value.items())
    return False


def safe_context(obj, *, header=frozenset(), cells=frozenset()):
    """Return ``obj`` unchanged when it may be sent to the model under the A34 rule; else raise InputRejected."""
    if type(obj) is not dict or not _check(obj, header, cells, False, 0):
        raise InputRejected(_REJECTED)
    if len(_canonical(obj)) > MAX_CONTEXT_CHARS:
        raise InputRejected(_REJECTED)
    return obj


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Template:
    name: str
    system: str
    max_tokens: int

    def user(self, context):
        return ("Case context as JSON (aggregates, check names, column names and run ids only):\n"
                + _canonical(context))


TEMPLATES = {
    "a02": Template("a02", "You reword investigation goals as short questions for a data engineer. Each goal has an id, "
                    "a check name and a column. Return one question per goal id, at most 160 characters, using only "
                    "the given names. Do not state or guess causes.", 256),
    "a22": Template("a22", "You state in one sentence how each knowledge-base passage relates to the listed "
                    "data-quality checks. Return one sentence per citation id, at most 200 characters. Describe only "
                    "what the passage covers; do not state causes.", 256),
    "a23": Template("a23", "You propose up to three candidate mechanisms from the given catalog for the observations. "
                    "Each candidate lists the observation ids it would explain. Candidates are hypotheses for fixed "
                    "probes to test, never a determined cause.", 256),
    "a29": Template("a29", "You draft up to three remediation options for the accepted findings. Each option has a "
                    "short title, a risk level, a rollback note and the finding ids it addresses. Options are "
                    "proposals for human review; nothing is executed.", 384),
    "a30": Template("a30", "You draft one patch proposal (SQL or CSV-cleaning steps) for the remediation options of an "
                    "order extract. It is text for human review and is never executed. Refer to columns by name and "
                    "never include data values.", 512),
}


def _strict(properties, required=None):
    return {"type": "object", "additionalProperties": False, "required": list(required or properties),
            "properties": properties}


def _ids(values, *, min_items=1, max_items=16):
    return {"type": "array", "minItems": min_items, "maxItems": max_items, "uniqueItems": True,
            "items": {"enum": list(values)}}


def planner_schema(goal_ids):
    item = _strict({"goal": {"enum": list(goal_ids)}, "question": {"type": "string", "minLength": 1, "maxLength": 160}})
    return _strict({"questions": {"type": "array", "maxItems": len(goal_ids), "items": item}})


def relevance_schema(citation_ids):
    item = _strict({"citation": {"enum": list(citation_ids)},
                    "sentence": {"type": "string", "minLength": 1, "maxLength": 200}})
    return _strict({"relevance": {"type": "array", "maxItems": len(citation_ids), "items": item}})


def hypothesis_schema(observation_ids):
    item = _strict({"mechanism": {"enum": list(MECHANISMS)}, "explains": _ids(observation_ids)})
    return _strict({"candidates": {"type": "array", "maxItems": 3, "items": item}})


def remediation_schema(finding_ids):
    item = _strict({"title": {"type": "string", "minLength": 1, "maxLength": 120},
                    "risk": {"enum": ["low", "medium", "high"]},
                    "rollback": {"type": "string", "minLength": 1, "maxLength": 160},
                    "addresses": _ids(finding_ids)})
    return _strict({"options": {"type": "array", "minItems": 1, "maxItems": 3, "items": item}})


def patch_schema(option_ids):
    proposal = _strict({"kind": {"enum": ["sql", "csv_cleaning"]},
                        "text": {"type": "string", "minLength": 1, "maxLength": 500},
                        "addresses": _ids(option_ids)})
    return _strict({"proposal": proposal})
