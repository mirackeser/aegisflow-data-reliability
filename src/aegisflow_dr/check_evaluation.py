# SPDX-License-Identifier: Apache-2.0
"""Record-level evaluation of the deterministic order-contract checks against injected faults.

Ground truth comes from the fault injector, never from the checks under test: every expected
(check, column, record) is known because the injector put it there, or deliberately did not.
Cases are generated per base table (a *group*); a group is assigned to exactly one of the
development, validation and held-out splits, so variants of one table can never straddle a split.

Scope, stated plainly: this measures whether deterministic checks find synthetic faults of the
kinds listed below. It says nothing about real data, unseen fault kinds, or any language model.
Precision and recall are reported with explicit counts, and are ``None`` (never 1.0) when the
denominator is zero.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter
from dataclasses import dataclass
from random import Random
from typing import Callable

from .analysis import _parse, record_issues
from .pipeline import diagnose_csv

VERSION = "1"
SPLITS = ("development", "validation", "heldout")
GROUPS = 40
ROWS = 20
COLUMNS = ("order_id", "customer_id", "order_total")
SCOPE = ("Deterministic order-contract checks against synthetic injected faults. Not real data, not unseen fault "
         "kinds, and not a language model.")
# Contract used to define truth: values are trimmed; identifiers match exactly (case-sensitive) after trimming;
# an amount is 1-12 digits with at most two decimals; empty identifiers are missing, never duplicates.

Truth = dict[tuple[str, str, int], str]
Detector = Callable[[bytes], set[tuple[str, str, int]]]


@dataclass(frozen=True)
class Case:
    case_id: str
    group: int
    split: str
    variant: str
    payload: bytes
    truth: Truth


def split_of(group: int) -> str:
    bucket = int(hashlib.sha256(f"aegisflow-eval-v{VERSION}:{group}".encode()).hexdigest(), 16) % 10
    return SPLITS[0] if bucket < 6 else SPLITS[1] if bucket < 8 else SPLITS[2]


def _base(group: int) -> list[list[str]]:
    rng = Random(group)
    return [[f"G{group:03}-{i + 1:04}", f"CUS-{rng.randrange(1, 11):03}", f"{rng.randrange(100, 100001) / 100:.2f}"]
            for i in range(ROWS)]


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


BAD_AMOUNTS = {"comma_decimal": "12,50", "text": "abc", "exponent": "1e3", "currency": "$12.50",
               "negative": "-5.00", "three_decimals": "1.234", "thirteen_digits": "1234567890123"}
VALID_AMOUNTS = {"zero": "0", "integer": "100", "max_digits": "999999999999.99", "leading_zeros": "007.10",
                 "padded": " 12.50 "}


def _variants(group: int) -> list[tuple[str, list[str], list[list[str]], Truth]]:
    """Return (variant, header, rows, truth) for every injected pattern of one base table."""
    rng = Random(group * 7919)
    out = []

    def make(name, edit=None, header=None):
        rows = [row[:] for row in _base(group)]
        truth: Truth = {}
        if edit:
            edit(rows, truth)
        out.append((name, list(header or COLUMNS), rows, truth))

    def pick(n):
        return rng.sample(range(ROWS), n)

    make("clean")
    for column in range(3):
        for kind, value in (("empty", ""), ("spaces", "   ")):
            def edit(rows, truth, column=column, value=value, kind=kind):
                at = pick(1)[0]
                rows[at][column] = value
                truth[("not_null", COLUMNS[column], at + 1)] = f"null_{COLUMNS[column]}_{kind}"
            make(f"null_{COLUMNS[column]}_{kind}", edit)

    def pair(rows, truth):
        a, b = sorted(pick(2))
        rows[b][0] = rows[a][0]
        for at in (a, b):
            truth[("unique", "order_id", at + 1)] = "duplicate_pair"
    make("duplicate_pair", pair)

    def triple(rows, truth):
        a, b, c = sorted(pick(3))
        rows[b][0] = rows[c][0] = rows[a][0]
        for at in (a, b, c):
            truth[("unique", "order_id", at + 1)] = "duplicate_triple"
    make("duplicate_triple", triple)

    def padded(rows, truth):
        a, b = sorted(pick(2))
        rows[b][0] = " " + rows[a][0] + " "
        for at in (a, b):
            truth[("unique", "order_id", at + 1)] = "duplicate_whitespace"
    make("duplicate_whitespace", padded)

    def case_differs(rows, truth):  # hard negative: matching is exact, so no finding is expected
        a, b = sorted(pick(2))
        rows[b][0] = rows[a][0].lower()
    make("case_differs_not_duplicate", case_differs)

    def blank_ids(rows, truth):  # hard negative for uniqueness: two blanks are missing values, not duplicates
        a, b = sorted(pick(2))
        rows[a][0] = rows[b][0] = ""
        for at in (a, b):
            truth[("not_null", "order_id", at + 1)] = "blank_ids"
    make("blank_ids_not_duplicates", blank_ids)

    for name, bad in BAD_AMOUNTS.items():
        def edit(rows, truth, bad=bad, name=name):
            at = pick(1)[0]
            rows[at][2] = bad
            truth[("amount_format", "order_total", at + 1)] = f"amount_{name}"
        make(f"amount_{name}", edit)
    for name, good in VALID_AMOUNTS.items():
        def edit(rows, truth, good=good):
            rows[pick(1)[0]][2] = good
        make(f"valid_amount_{name}", edit)

    def multi(rows, truth):
        a, b, c, d = sorted(pick(4))
        rows[a][2] = ""
        truth[("not_null", "order_total", a + 1)] = "multi_fault"
        rows[c][0] = rows[b][0]
        for at in (b, c):
            truth[("unique", "order_id", at + 1)] = "multi_fault"
        rows[d][1] = ""
        rows[d][2] = "x"
        truth[("not_null", "customer_id", d + 1)] = "multi_fault"
        truth[("amount_format", "order_total", d + 1)] = "multi_fault"
    make("multi_fault", multi)

    out.append(("schema_missing_column", ["order_id", "order_total"],
                [[r[0], r[2]] for r in _base(group)], {("missing_column", "customer_id", 0): "schema_missing_column"}))
    out.append(("schema_renamed_column", ["order_id", "customer_id", "total_amount"], _base(group),
                {("missing_column", "order_total", 0): "schema_renamed_column",
                 ("unexpected_column", "total_amount", 0): "schema_renamed_column"}))
    out.append(("schema_extra_column", [*COLUMNS, "channel"], [[*r, "web"] for r in _base(group)],
                {("unexpected_column", "channel", 0): "schema_extra_column"}))
    return out


def build_corpus(groups: int = GROUPS) -> list[Case]:
    cases = []
    for group in range(groups):
        for variant, header, rows, truth in _variants(group):
            cases.append(Case(f"g{group:03}-{variant}", group, split_of(group), variant, _csv(header, rows), truth))
    return cases


def corpus_digest(cases: list[Case]) -> str:
    """Hash of every payload and its truth; changes if any case or label changes."""
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda c: c.case_id):
        digest.update(case.case_id.encode() + hashlib.sha256(case.payload).digest())
        digest.update(json.dumps(sorted((list(k), v) for k, v in case.truth.items())).encode())
    return digest.hexdigest()


def check_leakage(cases: list[Case]) -> dict:
    """Report anything shared across splits; ``clean`` is true only when nothing is."""
    where_group: dict[int, set[str]] = {}
    where_payload: dict[str, set[str]] = {}
    where_record: dict[str, set[str]] = {}
    for case in cases:
        where_group.setdefault(case.group, set()).add(case.split)
        where_payload.setdefault(hashlib.sha256(case.payload).hexdigest(), set()).add(case.split)
        header, rows = _parse(case.payload)
        for row in rows:
            where_record.setdefault(hashlib.sha256("\x1f".join(row).encode()).hexdigest(), set()).add(case.split)
    shared = lambda index: sum(1 for splits in index.values() if len(splits) > 1)  # noqa: E731
    result = {"groups_in_several_splits": shared(where_group), "payloads_in_several_splits": shared(where_payload),
              "records_in_several_splits": shared(where_record)}
    return {**result, "clean": not any(result.values())}


def diagnose_detector(payload: bytes) -> set[tuple[str, str, int]]:
    found = set()
    for finding in diagnose_csv(payload).findings:
        for number in finding.record_numbers or (0,):
            found.add((finding.check, finding.column, number))
    return found


def record_detector(payload: bytes) -> set[tuple[str, str, int]]:
    header, rows = _parse(payload)
    return {(check, column, number) for (column, check), numbers in record_issues(header, rows)[1].items()
            for number in numbers}


DETECTORS = {
    "diagnose_csv": (diagnose_detector, frozenset({"missing_column", "unexpected_column", "not_null", "unique", "amount_format"})),
    "record_issues": (record_detector, frozenset({"not_null", "unique", "amount_format"})),
}


def wilson(successes: int, trials: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson score interval, or None when there are no trials."""
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def _rate(successes: int, trials: int) -> dict:
    return {"value": None if trials == 0 else round(successes / trials, 4), "numerator": successes,
            "denominator": trials, "interval_95": wilson(successes, trials)}


def score(cases: list[Case], detector: Detector, checks: frozenset[str]) -> dict:
    """Micro-averaged record-level scores per check, with explicit counts and error categories."""
    counts: dict[str, Counter] = {}
    missed: Counter = Counter()
    spurious: Counter = Counter()
    examples = []
    exact = 0
    for case in cases:
        expected = {key for key in case.truth if key[0] in checks}
        observed = {key for key in detector(case.payload) if key[0] in checks}
        for key in expected | observed:
            tally = counts.setdefault(key[0], Counter())
            if key in expected and key in observed:
                tally["tp"] += 1
            elif key in expected:
                tally["fn"] += 1
                missed[case.truth[key]] += 1
                examples.append({"kind": "missed", "case": case.case_id, "check": key[0], "column": key[1], "record": key[2]})
            else:
                tally["fp"] += 1
                spurious[case.variant] += 1
                examples.append({"kind": "spurious", "case": case.case_id, "check": key[0], "column": key[1], "record": key[2]})
        exact += expected == observed
    per_check = {}
    for check in sorted(checks):
        tally = counts.get(check, Counter())
        per_check[check] = {"true_positives": tally["tp"], "false_positives": tally["fp"], "false_negatives": tally["fn"],
                            "precision": _rate(tally["tp"], tally["tp"] + tally["fp"]),
                            "recall": _rate(tally["tp"], tally["tp"] + tally["fn"])}
    tp, fp, fn = (sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn"))
    return {"cases": len(cases), "exact_match_cases": _rate(exact, len(cases)),
            "overall": {"true_positives": tp, "false_positives": fp, "false_negatives": fn,
                        "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn)},
            "per_check": per_check, "missed_by_category": dict(sorted(missed.items())),
            "spurious_by_variant": dict(sorted(spurious.items())), "error_examples": examples[:20]}


def evaluate(*, include_heldout: bool = False, detectors: dict | None = None, cases: list[Case] | None = None) -> dict:
    """Score every detector per split. Held-out cases are scored only on explicit request."""
    cases = build_corpus() if cases is None else cases
    wanted = SPLITS if include_heldout else SPLITS[:2]
    by_split = {split: [c for c in cases if c.split == split] for split in SPLITS}
    chosen = DETECTORS if detectors is None else detectors
    return {"version": VERSION, "scope": SCOPE, "heldout_evaluated": include_heldout,
            "corpus": {"cases": len(cases), "groups": len({c.group for c in cases}),
                       "variants": len({c.variant for c in cases}), "sha256": corpus_digest(cases),
                       "per_split": {s: {"cases": len(by_split[s]), "groups": len({c.group for c in by_split[s]}),
                                         "sha256": corpus_digest(by_split[s])} for s in SPLITS}},
            "leakage": check_leakage(cases),
            "results": {name: {split: score(by_split[split], fn, checks) for split in wanted}
                        for name, (fn, checks) in chosen.items()}}


def _pct(rate: dict) -> str:
    return "n/a" if rate["value"] is None else f"{rate['value'] * 100:.2f}% ({rate['numerator']}/{rate['denominator']})"


def render_markdown(report: dict) -> str:
    lines = ["# Deterministic check evaluation", "", f"Scope: {report['scope']}", "",
             f"- Corpus: {report['corpus']['cases']} cases, {report['corpus']['groups']} base tables, "
             f"{report['corpus']['variants']} injected patterns; sha256 `{report['corpus']['sha256']}`",
             f"- Leakage across splits: {'none found' if report['leakage']['clean'] else 'FOUND'} "
             f"({report['leakage']})",
             f"- Held-out split scored: {'yes' if report['heldout_evaluated'] else 'no'}", ""]
    for name, splits in report["results"].items():
        lines += [f"## {name}", ""]
        for split, result in splits.items():
            lines += [f"### {split} ({result['cases']} cases)", "",
                      f"Exact-match cases: {_pct(result['exact_match_cases'])}", "",
                      "| check | precision | recall | TP | FP | FN |", "|---|---|---|---|---|---|"]
            for check, row in {**result["per_check"], "overall": result["overall"]}.items():
                lines.append(f"| {check} | {_pct(row['precision'])} | {_pct(row['recall'])} | "
                             f"{row['true_positives']} | {row['false_positives']} | {row['false_negatives']} |")
            lines += ["", f"Missed by category: {result['missed_by_category'] or 'none'}",
                      f"Spurious by variant: {result['spurious_by_variant'] or 'none'}", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> str:
    result = evaluate(include_heldout="--include-heldout" in argv)
    return render_markdown(result) if "--markdown" in argv else json.dumps(result, indent=2, sort_keys=True)


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(main(sys.argv[1:]))
