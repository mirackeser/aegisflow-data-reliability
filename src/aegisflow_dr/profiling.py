# SPDX-License-Identifier: Apache-2.0
"""Generic table profiling and deterministic time-series checks for any CSV (work package D05).

Every finding names exact 1-based data records (header excluded) and the numbers behind it.
Thresholds are module constants, set on the development split of ``profiling_eval`` and then
measured once on the held-out split; they are rules of thumb for the synthetic fault kinds
listed there, not guarantees for any real sensor. Nothing here infers a root cause.
"""
import csv
from datetime import datetime
import hashlib
import io
import math
from statistics import median
import re

from .pipeline import InputRejected

MAX_BYTES, MAX_ROWS, MAX_COLUMNS, MAX_RECORDS_LISTED = 1_000_000, 20_000, 40, 20
EMPTY_RATE = 0.2
OUTLIER_K, MIN_NUMERIC, EDGE_PARTNER, STEP_PARTNER = 4.5, 20, 0.4, 0.5
FLAT_RUN, FLAT_DISTINCT = 8, 0.3
GAP_FACTOR, MIN_DELTAS = 3.0, 10
ROLE_SHARE = 0.9
CHECKS = ("empty_rate", "type_mismatch", "duplicate_rows", "constant_column", "outlier", "level_shift", "flatline",
          "timestamp_duplicate", "timestamp_out_of_order", "timestamp_gap", "timestamp_mixed_timezone")

_INTEGER = re.compile(r"[+-]?\d{1,15}")
_DECIMAL = re.compile(r"[+-]?\d{1,15}\.\d{1,15}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?(?:Z|[+-]\d{2}:\d{2})?")


def parse_timestamp(text):
    if not _TIMESTAMP.fullmatch(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def kind_of(value):
    text = value.strip()
    if not text:
        return "empty"
    if _INTEGER.fullmatch(text):
        return "integer"
    if _DECIMAL.fullmatch(text):
        return "decimal"
    return "timestamp" if parse_timestamp(text) is not None else "text"


def read_table(payload):
    """Bounded strict parse. Returns (header, rows)."""
    if type(payload) is not bytes or len(payload) > MAX_BYTES:
        raise InputRejected("CSV exceeds the %d-byte input budget" % MAX_BYTES)
    try:
        source = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputRejected("CSV must be UTF-8") from exc
    if "\x00" in source:
        raise InputRejected("NUL characters are not supported")
    try:
        rows = []
        for row in csv.reader(io.StringIO(source, newline=""), strict=True):
            rows.append(row)
            if len(rows) > MAX_ROWS + 1:
                raise InputRejected("CSV exceeds %d data records" % MAX_ROWS)
    except csv.Error as exc:
        raise InputRejected("Malformed CSV") from exc
    if not rows:
        raise InputRejected("CSV is empty")
    header, body = [name.strip() for name in rows[0]], rows[1:]
    if not 1 <= len(header) <= MAX_COLUMNS or any(not name for name in header) or len(set(header)) != len(header):
        raise InputRejected("Header needs 1 to %d unique, non-empty column names" % MAX_COLUMNS)
    for number, row in enumerate(body, 1):
        if len(row) != len(header):
            raise InputRejected("Record %d has %d fields, expected %d" % (number, len(row), len(header)))
    if not body:
        raise InputRejected("CSV has no data records")
    return header, body


def _finding(check, column, records, **detail):
    return {"check": check, "column": column, "count": len(records), "records": records[:MAX_RECORDS_LISTED], "detail": detail}


def _column(name, values):
    kinds = [kind_of(v) for v in values]
    filled = [k for k in kinds if k != "empty"]
    numeric = sum(k in ("integer", "decimal") for k in filled)
    if not filled:
        role = "empty"
    elif numeric / len(filled) >= ROLE_SHARE:
        role = "numeric"
    elif filled.count("timestamp") / len(filled) >= ROLE_SHARE:
        role = "timestamp"
    else:
        role = "text"
    profile = {"name": name, "role": role, "filled": len(filled), "empty": len(values) - len(filled),
               "distinct": len({v.strip() for v, k in zip(values, kinds) if k != "empty"})}
    if role == "numeric":
        numbers = [float(v) for v, k in zip(values, kinds) if k in ("integer", "decimal")]
        profile.update(min=min(numbers), max=max(numbers), mean=round(math.fsum(numbers) / len(numbers), 6), median=median(numbers))
    return profile, kinds


def _outliers(numbers, ordered):
    """Indices (into ``numbers``) of isolated jumps.

    Ordered series use second differences, which cancel a linear trend and nearly all slow
    curvature; the first and last value have no second difference and are never flagged.
    Unordered columns are compared with the column median. Both scale by 1.4826 x the median
    absolute deviation, so the spikes being looked for do not inflate their own yardstick.
    """
    if len(numbers) < MIN_NUMERIC:
        return []
    if ordered:
        score = [0.0] + [numbers[i - 1] - 2 * numbers[i] + numbers[i + 1] for i in range(1, len(numbers) - 1)] + [0.0]
    else:
        level = median(numbers)
        score = [x - level for x in numbers]
    core = score[1:-1] if ordered else score
    scale = 1.4826 * median(abs(v) for v in core)
    if scale == 0:
        return []
    hits = [i for i, v in enumerate(score) if abs(v) > OUTLIER_K * scale]
    if ordered:
        hits = [i for i in hits if abs(score[i]) > abs(score[i - 1]) and abs(score[i]) >= abs(score[i + 1])]
        last = len(numbers) - 1
        # A jump in the very first or last value also lights up its neighbour (d2 = +s, no partner).
        # Only accept the neighbour when it shows the full spike signature: an opposite-signed partner.
        hits = [i for i in hits if i not in (1, last - 1) or _has_partner(score, i, 2 if i == 1 else last - 2)]
    return hits


def _steps(numbers):
    """Indices (into ``numbers``) of the first value after a persistent jump in level.

    A one-off spike shows up in the first differences as a large step followed at once by an
    opposite one; a level shift is a single large first difference with no such partner.
    """
    if len(numbers) < MIN_NUMERIC:
        return []
    diffs = [b - a for a, b in zip(numbers, numbers[1:])]
    scale = 1.4826 * median(abs(d) for d in diffs)
    if scale == 0:
        return []
    found = []
    for j, d in enumerate(diffs):
        if abs(d) > OUTLIER_K * scale:
            partners = [diffs[k] for k in (j - 1, j + 1) if 0 <= k < len(diffs)]
            if not any(p * d < 0 and abs(p) >= STEP_PARTNER * abs(d) for p in partners):
                found.append(j + 1)
    return found


def _has_partner(score, i, other):
    return score[i] * score[other] < 0 and abs(score[other]) >= EDGE_PARTNER * abs(score[i])


def _runs(numbers, records):
    start = 0
    for i in range(1, len(numbers) + 1):
        if i == len(numbers) or numbers[i] != numbers[start] or records[i] != records[i - 1] + 1:
            if i - start >= FLAT_RUN:
                yield start, i - 1
            start = i


def _timestamp_findings(column, values):
    parsed = [(number, parse_timestamp(v.strip())) for number, v in enumerate(values, 1)]
    parsed = [(n, ts) for n, ts in parsed if ts is not None]
    aware = {ts.tzinfo is not None for _, ts in parsed}
    if len(aware) > 1:
        return [_finding("timestamp_mixed_timezone", column, [n for n, ts in parsed if ts.tzinfo is None])]
    findings, seen, accepted, ahead, behind = [], set(), [], [], []
    top = None
    for number, ts in parsed:
        if ts in seen:
            ahead.append(number)
        elif top is not None and ts < top:
            behind.append(number)
        else:
            top = ts
            accepted.append((number, ts))
        seen.add(ts)
    if ahead:
        findings.append(_finding("timestamp_duplicate", column, ahead))
    if behind:
        findings.append(_finding("timestamp_out_of_order", column, behind))
    deltas = [(b[0], (b[1] - a[1]).total_seconds()) for a, b in zip(accepted, accepted[1:])]
    if len(deltas) >= MIN_DELTAS:
        step = median(d for _, d in deltas)
        gaps = [(n, d) for n, d in deltas if d > GAP_FACTOR * step]
        if gaps:
            findings.append(_finding("timestamp_gap", column, [n for n, _ in gaps], typical_seconds=step,
                                     missing_intervals=[round(d / step) - 1 for _, d in gaps][:MAX_RECORDS_LISTED]))
    return findings


def profile_csv(payload):
    header, rows = read_table(payload)
    columns = {name: [row[i] for row in rows] for i, name in enumerate(header)}
    profiles, kinds, findings = [], {}, []
    for name in header:
        profile, kinds[name] = _column(name, columns[name])
        profiles.append(profile)
    clock = next((p["name"] for p in profiles if p["role"] == "timestamp"), None)
    for profile in profiles:
        name, values, kind = profile["name"], columns[profile["name"]], kinds[profile["name"]]
        if profile["empty"] / len(rows) > EMPTY_RATE:
            findings.append(_finding("empty_rate", name, [n for n, k in enumerate(kind, 1) if k == "empty"],
                                     share=round(profile["empty"] / len(rows), 4)))
        expected = {"numeric": ("integer", "decimal"), "timestamp": ("timestamp",)}.get(profile["role"])
        if expected:
            bad = [n for n, k in enumerate(kind, 1) if k not in expected + ("empty",)]
            if bad:
                findings.append(_finding("type_mismatch", name, bad, expected=profile["role"]))
        if profile["filled"] >= FLAT_RUN and profile["distinct"] == 1:
            findings.append(_finding("constant_column", name, [], value=next(v.strip() for v, k in zip(values, kind) if k != "empty")))
        if profile["role"] == "numeric":
            records = [n for n, k in enumerate(kind, 1) if k in ("integer", "decimal")]
            numbers = [float(values[n - 1]) for n in records]
            steps = _steps(numbers) if clock is not None else []
            # A level shift leaves an equal and opposite pair in the second differences; it is not a spike.
            hits = [i for i in _outliers(numbers, clock is not None) if not {i, i + 1} & set(steps)]
            if steps:
                findings.append(_finding("level_shift", name, [records[i] for i in steps], method="first_difference",
                                         shifts=[round(numbers[i] - numbers[i - 1], 6) for i in steps][:MAX_RECORDS_LISTED]))
            if hits:
                findings.append(_finding("outlier", name, [records[i] for i in hits], method="second_difference" if clock else "median",
                                         k=OUTLIER_K))
            if clock is not None and len(numbers) >= MIN_NUMERIC and profile["distinct"] / len(numbers) >= FLAT_DISTINCT:
                spans = list(_runs(numbers, records))
                if spans:
                    findings.append(_finding("flatline", name, [r for a, b in spans for r in records[a:b + 1]], runs=[
                        {"first": records[a], "last": records[b], "value": numbers[a]} for a, b in spans][:MAX_RECORDS_LISTED]))
    seen, repeats = {}, []
    for number, row in enumerate(rows, 1):
        key = tuple(row)
        if key in seen:
            repeats.append(number)
        seen.setdefault(key, number)
    if repeats:
        findings.append(_finding("duplicate_rows", None, repeats))
    if clock is not None:
        findings.extend(_timestamp_findings(clock, columns[clock]))
    findings.sort(key=lambda f: (CHECKS.index(f["check"]), f["column"] or ""))
    return {"format_version": "1", "engine": "deterministic-profile-v1", "source_sha256": hashlib.sha256(payload).hexdigest(),
            "records": len(rows), "time_column": clock, "columns": profiles, "findings": findings,
            "status": "FINDINGS" if findings else "NO_FINDINGS"}
