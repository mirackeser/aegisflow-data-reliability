# SPDX-License-Identifier: Apache-2.0
"""Compare two order extracts by identifier and report where they agree, differ or are one-sided.

Both inputs go through the same bounded validation as an upload. Values are trimmed before comparing;
identifiers and customer ids match exactly (case-sensitive); amounts that are valid decimals compare
numerically, anything else compares as text. An identifier that is blank or repeated inside one source
cannot be matched reliably, so it is reported as ambiguous and left out of both the value comparison and the one-sided counts.
Nothing is written; samples are masked and bounded.
"""
from __future__ import annotations

from decimal import Decimal

from .analysis import _AMOUNT, _mask, _parse
from .pipeline import InputRejected

KEY = "order_id"
COMPARED = ("customer_id", "order_total")
SAMPLE_LIMIT = 20


def _index(header: list[str], rows: list[list[str]], side: str):
    if KEY not in header:
        raise InputRejected(f"The {side} source has no {KEY} column to match on")
    position = {name: header.index(name) for name in header}
    seen: dict[str, list[int]] = {}
    for number, row in enumerate(rows, 1):
        seen.setdefault(row[position[KEY]].strip(), []).append(number)
    ambiguous = {key for key, numbers in seen.items() if key == "" or len(numbers) > 1}
    records = {key: rows[numbers[0] - 1] for key, numbers in seen.items() if key not in ambiguous}
    return position, records, ambiguous, sum(len(seen[key]) for key in ambiguous)


def _same(column: str, left: str, right: str) -> bool:
    left, right = left.strip(), right.strip()
    if column == "order_total" and _AMOUNT.fullmatch(left) and _AMOUNT.fullmatch(right):
        return Decimal(left) == Decimal(right)
    return left == right


def compare(payload_a: bytes, payload_b: bytes) -> dict:
    header_a, rows_a = _parse(payload_a)
    header_b, rows_b = _parse(payload_b)
    position_a, records_a, keys_a, ambiguous_a = _index(header_a, rows_a, "first")
    position_b, records_b, keys_b, ambiguous_b = _index(header_b, rows_b, "second")
    columns = [c for c in COMPARED if c in position_a and c in position_b]
    only_a = sorted(set(records_a) - set(records_b) - keys_b)
    only_b = sorted(set(records_b) - set(records_a) - keys_a)
    differing, by_column = [], {c: 0 for c in columns}
    matched = sorted(set(records_a) & set(records_b))
    for key in matched:
        diffs = [c for c in columns if not _same(c, records_a[key][position_a[c]], records_b[key][position_b[c]])]
        for column in diffs:
            by_column[column] += 1
        if diffs:
            differing.append({"id": _mask(key), "columns": diffs,
                              "first": {c: records_a[key][position_a[c]].strip() for c in diffs},
                              "second": {c: records_b[key][position_b[c]].strip() for c in diffs}})
    return {
        "key": KEY,
        "compared_columns": columns,
        "not_compared": [c for c in COMPARED if c not in columns],
        "first": {"rows": len(rows_a), "ambiguous_rows": ambiguous_a},
        "second": {"rows": len(rows_b), "ambiguous_rows": ambiguous_b},
        "matched": len(matched),
        "identical": len(matched) - len(differing),
        "differing": len(differing),
        "differing_by_column": by_column,
        "only_in_first": len(only_a),
        "only_in_second": len(only_b),
        "samples": {"differing": differing[:SAMPLE_LIMIT],
                    "only_in_first": [_mask(k) for k in only_a[:SAMPLE_LIMIT]],
                    "only_in_second": [_mask(k) for k in only_b[:SAMPLE_LIMIT]]},
    }
