# SPDX-License-Identifier: Apache-2.0
"""Key cardinality of one extract and the fan-out a join between two extracts would cause.

Keys are trimmed order identifiers; blank keys are counted separately and never joined. The join figures
are exact: an inner join on the key emits ``count_first * count_second`` rows per shared key, and a
repeated key on the other side repeats that side's valid amount, which is how a join silently inflates a
total. Nothing is written and no value is guessed.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

from .analysis import _AMOUNT, _parse
from .pipeline import InputRejected

KEY = "order_id"
AMOUNT = "order_total"


def _keys(payload: bytes, side: str):
    header, rows = _parse(payload)
    if KEY not in header:
        raise InputRejected(f"The {side} source has no {KEY} column")
    key_at = header.index(KEY)
    amount_at = header.index(AMOUNT) if AMOUNT in header else None
    counts: Counter[str] = Counter()
    amounts: dict[str, Decimal] = {}
    blank = 0
    for row in rows:
        key = row[key_at].strip()
        if not key:
            blank += 1
            continue
        counts[key] += 1
        value = row[amount_at].strip() if amount_at is not None else ""
        if _AMOUNT.fullmatch(value):
            amounts[key] = amounts.get(key, Decimal(0)) + Decimal(value)
    return len(rows), blank, counts, amounts


def profile_keys(payload: bytes) -> dict:
    rows, blank, counts, _ = _keys(payload, "this")
    multiplicity = Counter(counts.values())
    keyed = rows - blank
    return {"rows": rows, "blank_keys": blank, "distinct_keys": len(counts),
            "repeated_keys": sum(1 for n in counts.values() if n > 1),
            "max_multiplicity": max(counts.values(), default=0),
            "extra_rows": keyed - len(counts),
            "multiplicity": {str(n): multiplicity[n] for n in sorted(multiplicity)}}


def join_cardinality(payload_first: bytes, payload_second: bytes) -> dict:
    """Relationship of the shared keys and the exact result of an inner join on ``order_id``."""
    _, _, first, first_amounts = _keys(payload_first, "first")
    _, _, second, second_amounts = _keys(payload_second, "second")
    shared = sorted(set(first) & set(second))
    relationship = Counter()
    for key in shared:
        left, right = first[key] > 1, second[key] > 1
        relationship["many_to_many" if left and right else "one_to_many" if right else "many_to_one" if left else "one_to_one"] += 1
    join_rows = sum(first[key] * second[key] for key in shared)
    first_before = sum((first_amounts.get(key, Decimal(0)) for key in shared), Decimal(0))
    first_after = sum((first_amounts.get(key, Decimal(0)) * second[key] for key in shared), Decimal(0))
    second_before = sum((second_amounts.get(key, Decimal(0)) for key in shared), Decimal(0))
    second_after = sum((second_amounts.get(key, Decimal(0)) * first[key] for key in shared), Decimal(0))
    return {
        "shared_keys": len(shared),
        "relationship": {name: relationship[name] for name in ("one_to_one", "one_to_many", "many_to_one", "many_to_many")},
        "join_rows": join_rows,
        "extra_rows_from_join": join_rows - len(shared),
        "fan_out": bool(join_rows - len(shared)),
        "amount_inflation": {"first": {"before": f"{first_before:.2f}", "after_join": f"{first_after:.2f}", "inflation": f"{first_after - first_before:.2f}"},
                             "second": {"before": f"{second_before:.2f}", "after_join": f"{second_after:.2f}", "inflation": f"{second_after - second_before:.2f}"}},
        "first": profile_keys(payload_first), "second": profile_keys(payload_second),
    }
