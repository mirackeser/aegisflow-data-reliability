# SPDX-License-Identifier: Apache-2.0
"""Fixed, versioned prompt templates for the model-using roles and the A34 context rule.

Contexts are built by the executors only from whitelisted fields of tool outputs: column names, check names,
counts, rounded statistics, observation ids and mechanism names (docs/superpowers/specs/2026-11-24-agent-runtime-roles.md,
"LLM context rule"). ``safe_context`` is the final guard before any model call. Every string must be an allowed name
(a fixed vocabulary word, a column of the current header, of the baseline or of the order contract) or a run-local id,
except under the few free-text keys that carry knowledge-base passages or earlier model text. Free text is compared
after NFKC normalisation and case folding: it must not equal any cell value, must not contain any cell value of at
least ``MIN_LEAK_CHARS`` characters, and must not contain a shorter non-numeric cell value as a whole word. A cell
value that equals an allowed name counts only as that name. A violation raises InputRejected, which the executors
report as POLICY_DENIED. The guard checks strings; numbers pass, so executors must build contexts only from
whitelisted aggregate fields (counts, shares, rounded statistics), which they do. A cell that happens to look like a
run id (for example ``obs-1``) is indistinguishable from one. Changing any template, schema or vocabulary requires a
new ``PROMPT_VERSION``.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import re
import unicodedata

from ..baseline import CHECKS as BASELINE_CHECKS, ROLES, load_baseline
from ..hypotheses import MECHANISMS, PROBES
from ..pipeline import EXPECTED_COLUMNS, InputRejected
from ..profiling import CHECKS as PROFILE_CHECKS, read_table

PROMPT_VERSION = "2"  # 2: planner goals carry signal/observation ids; a29 forbids stating causes
DIAGNOSE_CHECKS = ("missing_column", "unexpected_column", "not_null", "unique", "amount_format", "nonempty_dataset")
FREE_TEXT_KEYS = frozenset({"passage", "kb_source", "option_title", "option_rollback"})
MIN_LEAK_CHARS, MAX_FREE_TEXT, MAX_CONTEXT_CHARS, MAX_DEPTH = 3, 400, 12_000, 6
REASON_CODES = ("first_specialist", "history_given", "baseline_given", "order_extract", "time_column_present",
                "type_signal", "two_order_extracts", "knowledge_source_given", "observations_exist",
                "baseline_and_observations", "specialist_limit", "no_history", "no_baseline", "not_order_extract",
                "no_log_source", "no_cdc_source", "no_time_column", "no_type_signal", "no_second_order_extract",
                "no_history_or_retriever", "no_observations", "no_baseline_or_observations", "no_as_of",
                "no_sla", "timezone_mismatch", "as_of_before_latest_record", "no_baseline_interval",
                "too_few_intervals", "role_changed", "too_few_values_in_baseline", "constant_in_baseline",
                "too_few_values")
VOCABULARY = frozenset(PROFILE_CHECKS + BASELINE_CHECKS + DIAGNOSE_CHECKS + MECHANISMS + PROBES + ROLES + (
    "drop", "increase", "profile", "baseline", "low", "medium", "high", "sql", "csv_cleaning", "PASS", "FAIL",
    "BLOCKED", "FINDINGS", "NO_FINDINGS", "DRIFT", "NO_DRIFT", "BREAKING", "COMPATIBLE", "IDENTICAL", "order_count",
    "amount_cents", "supported", "open", "refuted", "no_observations", "none_supported", "single_supported",
    "multiple_supported") + REASON_CODES)
_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_RUN_ID = re.compile(r"(?:obs|hyp|prb|sig)-[0-9]{1,4}|(?:g|c|f|opt)[0-9]{1,3}|A(?:0[1-9]|[12][0-9]|3[0-6])"
                     r"|a[0-9]{2}\.[a-z_]{1,40}")
_REJECTED = "LLM context contains a value that is not allowed"
_NUMBER = re.compile(r"[+-]?[0-9.,]+")
_WORD = re.compile(r"\w+")


def case_vocabulary(*payloads, baseline=None):
    """(allowed column names, distinct stripped cell values) of a case.

    Names are the readable payloads' headers, the order-contract columns and, for a valid baseline record, its
    columns (a renamed or missing column is still a column name). Unreadable payloads and an invalid baseline
    contribute nothing.
    """
    header, cells = set(EXPECTED_COLUMNS), set()
    for payload in payloads:
        if payload is None:
            continue
        try:
            names, rows = read_table(payload)
        except InputRejected:
            continue
        header.update(names)
        cells.update(value.strip() for row in rows for value in row if value.strip())
    if baseline is not None:
        try:
            header.update(column["name"] for column in load_baseline(baseline)["columns"])
        except InputRejected:
            pass
    return frozenset(header), frozenset(cells)


def _fold(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


@lru_cache(maxsize=8)
def _leak_patterns(cells, names):
    """(every folded cell, folded cells to find as substrings, short non-numeric folded cells to find as words)."""
    allowed = {_fold(name) for name in names} | {_fold(word) for word in VOCABULARY}
    folded = {_fold(cell) for cell in cells} - allowed - {""}
    long = tuple(sorted(cell for cell in folded if len(cell) >= MIN_LEAK_CHARS))
    short = frozenset(cell for cell in folded if len(cell) < MIN_LEAK_CHARS and not _NUMBER.fullmatch(cell))
    return frozenset(folded), long, short


def free_text_ok(text, cells, names=frozenset()):
    """True when ``text`` may be sent as free text: short enough and no cell value in any normalised form."""
    if len(text) > MAX_FREE_TEXT:
        return False
    every, long, short = _leak_patterns(frozenset(cells), frozenset(names))
    folded = _fold(text)
    if folded in every or any(cell in folded for cell in long):
        return False
    return not set(_WORD.findall(folded)) & short


def _check(value, header, cells, free, depth):
    if depth > MAX_DEPTH:
        return False
    if value is None or type(value) is bool or type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is str:
        if free:
            return free_text_ok(value, cells, header)
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
                    "a check name, a column and the signal or observation ids it rests on. Return one question per "
                    "goal id with the ids it rests on, at most 160 characters, using only the given names. Do not "
                    "state or guess causes.", 256),
    "a22": Template("a22", "You state in one sentence how each knowledge-base passage relates to the listed "
                    "data-quality checks. Return one sentence per citation id, at most 200 characters. Describe only "
                    "what the passage covers; do not state causes.", 256),
    "a23": Template("a23", "You propose up to three candidate mechanisms from the given catalog for the observations. "
                    "Each candidate lists the observation ids it would explain. Candidates are hypotheses for fixed "
                    "probes to test, never a determined cause.", 256),
    "a29": Template("a29", "You draft up to three remediation options for the accepted findings. Each option has a "
                    "short title, a risk level, a rollback note and the finding ids it addresses. Options are "
                    "proposals for human review; nothing is executed. Do not state causes.", 384),
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


def planner_schema(goal_ids, ref_ids):
    item = _strict({"goal": {"enum": list(goal_ids)}, "refs": _ids(ref_ids),
                    "question": {"type": "string", "minLength": 1, "maxLength": 160}})
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
