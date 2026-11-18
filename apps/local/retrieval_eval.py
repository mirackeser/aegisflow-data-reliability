# SPDX-License-Identifier: Apache-2.0
"""Measure the lexical retrieval of the built-in reference documents on labelled queries.

The queries were written by the author with the six documents in view, so this is a regression guard and an
honest picture of lexical matching, not an independent benchmark. Three groups: ``keyword`` queries reuse
document wording, ``paraphrase`` queries say the same thing in other words, ``out_of_scope`` queries have no
relevant document and should return nothing. Intervals are 95% Wilson intervals on very small samples.
"""
from __future__ import annotations

import json

from aegisflow_dr.check_evaluation import wilson
from knowledge import Knowledge
from reference_documents import REFERENCE_DOCUMENTS

QUALITY, RECON, SCHEMA, MISSING, DUPLICATE, AMOUNT = (d.source for d in REFERENCE_DOCUMENTS)

QUERIES = (
    ("keyword", "source quality failure checks", {QUALITY}),
    ("keyword", "never repair source data automatically", {QUALITY}),
    ("keyword", "a finding is an observation not a causal explanation", {QUALITY}),
    ("keyword", "transformation reconciliation expected observed order count", {RECON}),
    ("keyword", "amount cents mismatch loss", {RECON}),
    ("keyword", "inconsistent transformation evidence", {RECON}),
    ("keyword", "required columns order_id customer_id order_total no other column", {SCHEMA}),
    ("keyword", "renamed or reordered export field", {SCHEMA}),
    ("keyword", "map columns only after confirmation", {SCHEMA}),
    ("keyword", "blank order_total understates revenue", {MISSING}),
    ("keyword", "blank identifier prevents matching", {MISSING}),
    ("keyword", "fix the value at its source system and inspect a new export", {MISSING}),
    ("keyword", "repeated load or export identical repeated records", {DUPLICATE}),
    ("keyword", "key collision conflicting updates", {DUPLICATE}),
    ("keyword", "repeats counted twice overstate revenue", {DUPLICATE}),
    ("keyword", "nonnegative decimal two decimal places", {AMOUNT}),
    ("keyword", "currency symbol thousands separator exponent", {AMOUNT}),
    ("keyword", "locale decimal comma cannot be summed", {AMOUNT}),
    ("paraphrase", "price column contains a euro sign", {AMOUNT}),
    ("paraphrase", "the same purchase appears twice", {DUPLICATE}),
    ("paraphrase", "header names changed upstream", {SCHEMA}),
    ("paraphrase", "total revenue does not match between systems", {RECON}),
    ("paraphrase", "empty cells in the total field", {MISSING}),
    ("paraphrase", "should the tool fix the data for me", {QUALITY}),
    ("paraphrase", "rows lost during the transform step", {RECON}),
    ("paraphrase", "numbers written with a comma as decimal separator", {AMOUNT}),
    ("out_of_scope", "what is the weather in Istanbul tomorrow", set()),
    ("out_of_scope", "how do I train a neural network", set()),
    ("out_of_scope", "who won the football match", set()),
    ("out_of_scope", "recipe for lentil soup", set()),
    ("out_of_scope", "the and of to a", set()),
    ("out_of_scope", "reset my password", set()),
)
GROUPS = ("keyword", "paraphrase", "out_of_scope")


def _rate(successes: int, trials: int) -> dict:
    return {"value": round(successes / trials, 4), "numerator": successes, "denominator": trials, "wilson95": wilson(successes, trials)}


def evaluate(knowledge: Knowledge | None = None) -> dict:
    if knowledge is None:
        knowledge = Knowledge()
        knowledge.replace(REFERENCE_DOCUMENTS)
    allowed = frozenset(d.source for d in REFERENCE_DOCUMENTS)
    groups = {}
    for group in GROUPS:
        rows = [(query, gold) for g, query, gold in QUERIES if g == group]
        hits1 = hits3 = empty = 0
        reciprocal = 0.0
        for query, gold in rows:
            found = [r["source"] for r in knowledge.retrieve("local", query, allowed_sources=allowed, limit=3)]
            empty += not found
            if gold:
                hits1 += bool(found) and found[0] in gold
                hits3 += any(source in gold for source in found)
                reciprocal += next((1 / (i + 1) for i, source in enumerate(found) if source in gold), 0.0)
        n = len(rows)
        if group == "out_of_scope":
            groups[group] = {"queries": n, "correctly_empty": _rate(empty, n), "false_retrieval": _rate(n - empty, n)}
        else:
            groups[group] = {"queries": n, "recall_at_1": _rate(hits1, n), "recall_at_3": _rate(hits3, n), "mrr": round(reciprocal / n, 4)}
    return {"documents": len(REFERENCE_DOCUMENTS), "queries": len(QUERIES), "method": "lexical term overlap",
            "authored_with_corpus_in_view": True, "groups": groups}


def _pct(rate: dict) -> str:
    low, high = rate["wilson95"]
    return f"{rate['numerator']}/{rate['denominator']} ({rate['value']:.0%}, 95% interval {low:.0%}–{high:.0%})"


def render_markdown(report: dict) -> str:
    keyword, paraphrase, scope = (report["groups"][g] for g in GROUPS)
    lines = ["# Reference retrieval evaluation", "",
             f"Method: {report['method']} over {report['documents']} built-in reference documents and {report['queries']} labelled queries. "
             "The queries were written with the documents in view, so this is a regression guard and a picture of lexical matching, not an independent benchmark. "
             "It measures retrieval only; no model is involved and nothing here says anything about generated answers.", "",
             "| Group | Queries | Right document first | Right document in top 3 | Mean reciprocal rank |", "|---|---|---|---|---|"]
    for name, group in (("keyword", keyword), ("paraphrase", paraphrase)):
        lines.append(f"| {name} | {group['queries']} | {_pct(group['recall_at_1'])} | {_pct(group['recall_at_3'])} | {group['mrr']:.4f} |")
    lines += ["", f"Out of scope ({scope['queries']} queries with no relevant document): nothing returned for {_pct(scope['correctly_empty'])}; "
              f"a result was wrongly returned for {_pct(scope['false_retrieval'])}.", "",
              "Reading the numbers: keyword queries reuse document wording, so matching is easy. Paraphrase queries are the realistic case and show the limit of "
              "matching on shared words. Intervals are wide because the samples are small.", "",
              "History: the first measurement returned a result for 67% of out-of-scope queries because function words such as `the` and `is` counted as evidence. "
              "Removing them brought that to 0% and moved paraphrase right-first from 25% to 38%.", ""]
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - thin CLI
    import sys
    print(render_markdown(evaluate()) if "--markdown" in sys.argv else json.dumps(evaluate(), indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
