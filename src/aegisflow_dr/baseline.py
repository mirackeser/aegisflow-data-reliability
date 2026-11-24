# SPDX-License-Identifier: Apache-2.0
"""Digest-protected aggregate baseline built from 1 to 5 reference CSVs (work package D05c).

The record holds column names, roles, counts, shares, means, standard deviations, medians and
decile edges. It holds no record, identifier or text value; decile edges are derived numeric
values and reveal approximate ranges. Thresholds are fixed rules of thumb written down before any measurement,
not guarantees for any real sensor. Nothing here infers a root cause.
"""
from bisect import bisect_right
from datetime import datetime
import hashlib
import json
import math
from statistics import fmean, median, pstdev, quantiles

from .pipeline import InputRejected
from .profiling import MAX_COLUMNS, _column, parse_timestamp, read_table

FORMAT, ENGINE = "1", "deterministic-baseline-v1"
MAX_REFERENCES, MIN_DELTAS = 5, 10
# Fewest numeric values for decile edges (baseline) and for a PSI comparison (current). With no change,
# E[PSI] ~ (B - 1)(1/n_baseline + 1/n_current) for B = 10 bins. Requiring the current-size term
# (B - 1)/n_current <= PSI_SHIFT / 4 gives n_current >= 144, rounded to 150. Set before the held-out split was
# scored, after an independent null simulation showed P(PSI > 0.25) ~ 0.20 at the earlier minimum of 50.
MIN_VALUES = 150
FRESHNESS_INTERVALS, SAMPLING_RATIO, VOLUME_RATIO = 3, 1.5, 1.5
EMPTY_RATE_DELTA, PSI_SHIFT, PSI_SMOOTH = 0.10, 0.25, 0.5
CHECKS = ("column_missing", "column_added", "role_change", "sampling_interval_change", "volume_change", "freshness",
          "empty_rate_change", "distribution_shift")
ROLES = ("numeric", "timestamp", "text", "empty")
MAX_EDGES = 9
MAX_MAGNITUDE = 10 ** 15
_KEYS = {"format_version", "engine", "columns", "time_column", "references", "volume", "sampling", "freshness_sla_seconds",
         "empty_share", "numeric", "digest"}
_HEX = frozenset("0123456789abcdef")


def canonical_digest(record):
    """SHA-256 of the canonical JSON of ``record`` without its ``digest`` field."""
    body = {k: v for k, v in record.items() if k != "digest"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def bin_counts(edges, values):
    """Count ``values`` per bin; a value goes to bin ``bisect_right(edges, value)``."""
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    return counts


def interval_median(timestamps):
    """Median positive gap in seconds between sorted distinct timestamps; None below MIN_DELTAS gaps."""
    ordered = sorted(set(timestamps))
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    return median(gaps) if len(gaps) >= MIN_DELTAS else None


def _numeric_entry(values):
    entry = {"count": len(values), "mean": round(fmean(values), 6), "sd": round(pstdev(values), 6),
             "median": round(median(values), 6), "edges": None, "counts": None}
    if len(values) >= MIN_VALUES:
        constant = min(values) == max(values)
        entry["edges"] = [] if constant else sorted({round(e, 6) for e in quantiles(values, n=10, method="inclusive")})
        entry["counts"] = bin_counts(entry["edges"], values)
    return entry


def build_baseline(payloads, *, freshness_sla_seconds=None):
    if type(payloads) is not list or not 1 <= len(payloads) <= MAX_REFERENCES:
        raise InputRejected("A baseline needs 1 to %d reference CSV files" % MAX_REFERENCES)
    if freshness_sla_seconds is not None and (type(freshness_sla_seconds) is not int or freshness_sla_seconds < 1):
        raise InputRejected("freshness_sla_seconds must be a positive integer")
    tables = [read_table(payload) for payload in payloads]
    header = tables[0][0]
    if any(other != header for other, _ in tables):
        raise InputRejected("Reference files must share the same header, in the same order")
    pooled = {name: [row[i] for _, rows in tables for row in rows] for i, name in enumerate(header)}
    profiles, kinds = {}, {}
    for name in header:
        profiles[name], kinds[name] = _column(name, pooled[name])
    clock = next((n for n in header if profiles[n]["role"] == "timestamp"), None)
    index = header.index(clock) if clock is not None else None
    parsed = [[] if clock is None else [ts for ts in (parse_timestamp(r[index].strip()) for r in rows) if ts is not None]
              for _, rows in tables]
    if len({ts.tzinfo is not None for stamps in parsed for ts in stamps}) > 1:
        raise InputRejected("Reference timestamps have mixed timezone awareness")
    references = []
    for payload, (_, rows), stamps in zip(payloads, tables, parsed):
        references.append({"sha256": hashlib.sha256(payload).hexdigest(), "records": len(rows),
                           "first": min(stamps).isoformat() if stamps else None, "last": max(stamps).isoformat() if stamps else None,
                           "median_interval_seconds": interval_median(stamps)})
    medians = [r["median_interval_seconds"] for r in references if r["median_interval_seconds"] is not None]
    counts = [r["records"] for r in references]
    sampling = median(medians) if medians else None
    if freshness_sla_seconds is None and sampling is not None:
        freshness_sla_seconds = max(1, round(FRESHNESS_INTERVALS * sampling))
    total = sum(counts)
    record = {"format_version": FORMAT, "engine": ENGINE,
              "columns": [{"name": n, "role": profiles[n]["role"]} for n in header], "time_column": clock,
              "references": references,
              "volume": {"min_records": min(counts), "max_records": max(counts), "median_records": median(counts)},
              "sampling": {"median_interval_seconds": sampling}, "freshness_sla_seconds": freshness_sla_seconds,
              "empty_share": {n: round(profiles[n]["empty"] / total, 6) for n in header},
              "numeric": {n: _numeric_entry([float(v) for v, k in zip(pooled[n], kinds[n]) if k in ("integer", "decimal")])
                          for n in header if profiles[n]["role"] == "numeric"}}
    record["digest"] = canonical_digest(record)
    return record


def _number(x):
    """A finite int or float; ints beyond MAX_MAGNITUDE are rejected before any float conversion."""
    return (type(x) is int and abs(x) <= MAX_MAGNITUDE) or (type(x) is float and math.isfinite(x))


def _count(x, minimum=0):
    return type(x) is int and x >= minimum


def _shaped(x, keys):
    return type(x) is dict and set(x) == set(keys)


def _timestamp(x):
    return type(x) is str and parse_timestamp(x) is not None


def _column_ok(column):
    return _shaped(column, ("name", "role")) and type(column["name"]) is str and column["name"] != "" and column["role"] in ROLES


def _reference_ok(ref, timed):
    if not _shaped(ref, ("sha256", "records", "first", "last", "median_interval_seconds")):
        return False
    step = ref["median_interval_seconds"]
    return (type(ref["sha256"]) is str and len(ref["sha256"]) == 64 and set(ref["sha256"]) <= _HEX and _count(ref["records"], 1)
            and (ref["first"] is None) == (ref["last"] is None) and (ref["first"] is None or (timed and _timestamp(ref["first"])
                                                                                               and _timestamp(ref["last"])))
            and (step is None or (timed and _number(step) and step > 0)))


def _numeric_ok(entry):
    if not _shaped(entry, ("count", "mean", "sd", "median", "edges", "counts")) or not _count(entry["count"], 1):
        return False
    edges, counts = entry["edges"], entry["counts"]
    if not (_number(entry["mean"]) and _number(entry["sd"]) and entry["sd"] >= 0 and _number(entry["median"])):
        return False
    if edges is None or counts is None:
        return edges is None and counts is None and entry["count"] < MIN_VALUES
    return (entry["count"] >= MIN_VALUES and type(edges) is list and len(edges) <= MAX_EDGES and all(_number(e) for e in edges)
            and all(a < b for a, b in zip(edges, edges[1:])) and type(counts) is list and len(counts) == len(edges) + 1
            and all(_count(c) for c in counts) and sum(counts) == entry["count"])


def _valid(obj):
    if not _shaped(obj, _KEYS) or obj["format_version"] != FORMAT or obj["engine"] != ENGINE:
        return False
    columns, refs, volume, sampling = obj["columns"], obj["references"], obj["volume"], obj["sampling"]
    if not (type(columns) is list and 1 <= len(columns) <= MAX_COLUMNS and all(_column_ok(c) for c in columns)):
        return False
    names = [c["name"] for c in columns]
    clock = next((c["name"] for c in columns if c["role"] == "timestamp"), None)
    if len(set(names)) != len(names) or obj["time_column"] != clock:
        return False
    if not (type(refs) is list and 1 <= len(refs) <= MAX_REFERENCES and all(_reference_ok(r, clock is not None) for r in refs)):
        return False
    if not (_shaped(volume, ("min_records", "max_records", "median_records")) and _count(volume["min_records"], 1)
            and _count(volume["max_records"], 1) and _number(volume["median_records"])
            and volume["min_records"] <= volume["median_records"] <= volume["max_records"]):
        return False
    step, sla = sampling["median_interval_seconds"] if _shaped(sampling, ("median_interval_seconds",)) else 0, obj["freshness_sla_seconds"]
    if not (step is None or (_number(step) and step > 0)) or not (sla is None or _count(sla, 1)):
        return False
    share, numeric = obj["empty_share"], obj["numeric"]
    if not (_shaped(share, names) and all(_number(s) and 0 <= s <= 1 for s in share.values())):
        return False
    wanted = [c["name"] for c in columns if c["role"] == "numeric"]
    return _shaped(numeric, wanted) and all(_numeric_ok(e) for e in numeric.values())


def load_baseline(obj):
    """Return ``obj`` unchanged when it is a well-formed, untampered baseline record; else raise InputRejected."""
    if not _valid(obj):
        raise InputRejected("Baseline record is malformed")
    if obj["digest"] != canonical_digest(obj):
        raise InputRejected("Baseline digest does not match its content")
    return obj


def psi(baseline_counts, current_counts):
    """Population stability index of two bin-count lists, each share smoothed with ``PSI_SMOOTH`` per bin.

    A descriptive index, not a significance test. Rounded to 6 places for reporting.
    """
    return round(_psi_raw(baseline_counts, current_counts), 6)


def _psi_raw(baseline_counts, current_counts):
    bins = len(baseline_counts)
    b_total, c_total = sum(baseline_counts) + PSI_SMOOTH * bins, sum(current_counts) + PSI_SMOOTH * bins
    total = 0.0
    for b_count, c_count in zip(baseline_counts, current_counts):
        b, c = (b_count + PSI_SMOOTH) / b_total, (c_count + PSI_SMOOTH) / c_total
        total += (c - b) * math.log(c / b)
    return total


def _sort_key(item):
    column = item["column"]
    return CHECKS.index(item["check"]), column is not None, column or ""


def _sampling(base, stamps, usable, measured):
    reference = base["sampling"]["median_interval_seconds"]
    current = interval_median(stamps) if usable else None
    measured["sampling_interval"] = {"baseline_seconds": reference, "current_seconds": current}
    if reference is None:
        return None, "no_baseline_interval"
    if not usable:
        return None, "no_time_column"
    if current is None:
        return None, "too_few_intervals"
    ratio = current / reference
    if ratio > SAMPLING_RATIO or ratio < 1 / SAMPLING_RATIO:
        return {"baseline_seconds": reference, "current_seconds": current, "ratio": round(ratio, 4)}, None
    return None, None


def _freshness(base, stamps, usable, aware, as_of_time, measured):
    sla = base["freshness_sla_seconds"]
    latest = max(stamps) if stamps else None
    lag, reason = None, None
    if as_of_time is None:
        reason = "no_as_of"
    elif not usable:
        reason = "no_time_column"
    elif sla is None:
        reason = "no_sla"
    elif latest is None or (as_of_time.tzinfo is not None) != aware:
        reason = "timezone_mismatch"
    else:
        lag = (as_of_time - latest).total_seconds()
        if lag < 0:
            reason = "as_of_before_latest_record"
    measured["freshness"] = {"sla_seconds": sla, "latest": latest.isoformat() if latest else None,
                             "lag_seconds": lag if reason is None else None}
    if reason is None and lag > sla:
        return {"lag_seconds": lag, "sla_seconds": sla, "latest": latest.isoformat()}, None
    return None, reason


def _shares(counts):
    total = sum(counts)
    return [round(c / total, 6) for c in counts]


def _distribution(entry, values):
    """Return (detail or None, not-evaluated reason or None, measured PSI and bin shares or None).

    The decision uses the unrounded index, so a value just above the threshold is never rounded down to it.
    """
    if entry["edges"] is None:
        return None, "too_few_values_in_baseline", None
    if not entry["edges"]:
        return None, "constant_in_baseline", None
    if len(values) < MIN_VALUES:
        return None, "too_few_values", None
    counts = bin_counts(entry["edges"], values)
    raw = _psi_raw(entry["counts"], counts)
    shares = {"psi": round(raw, 6), "edges": list(entry["edges"]), "baseline": _shares(entry["counts"]),
              "current": _shares(counts)}
    if raw <= PSI_SHIFT:
        return None, None, shares
    return {"psi": shares["psi"], "threshold": PSI_SHIFT, "baseline_mean": entry["mean"], "current_mean": round(fmean(values), 6),
            "baseline_sd": entry["sd"], "current_sd": round(pstdev(values), 6),
            "baseline_proportions": shares["baseline"], "current_proportions": shares["current"],
            "edges": shares["edges"]}, None, shares


def compare(baseline, payload, *, as_of=None):
    """Compare one CSV payload with a stored baseline; findings are fixed-rule differences, not causes."""
    base = load_baseline(baseline)
    if as_of is not None and type(as_of) is not str:
        raise InputRejected("as_of must be a timestamp string")
    as_of_time = None if as_of is None else parse_timestamp(as_of.strip())
    if as_of is not None and as_of_time is None:
        raise InputRejected("as_of is not a recognised timestamp")
    header, rows = read_table(payload)
    records = len(rows)
    profiles = {name: _column(name, [row[i] for row in rows]) for i, name in enumerate(header)}
    base_roles = {c["name"]: c["role"] for c in base["columns"]}
    findings, skipped = [], []
    measured = {"psi": {}, "bin_shares": {}}

    def found(check, column, **detail):
        findings.append({"check": check, "column": column, "detail": detail})

    def not_evaluated(check, column, reason):
        skipped.append({"check": check, "column": column, "reason": reason})

    for name in base_roles:
        if name not in profiles:
            found("column_missing", name)
    for name in header:
        if name not in base_roles:
            found("column_added", name)
    shared = [name for name in header if name in base_roles]
    for name in shared:
        role = profiles[name][0]["role"]
        if role != base_roles[name]:
            found("role_change", name, baseline=base_roles[name], current=role)
            if "numeric" in (role, base_roles[name]):
                not_evaluated("distribution_shift", name, "role_changed")

    clock = base["time_column"]
    usable = clock in profiles and profiles[clock][0]["role"] == "timestamp"
    aware = any(r["first"] is not None and datetime.fromisoformat(r["first"]).tzinfo is not None for r in base["references"])
    stamps = []
    if usable:
        index = header.index(clock)
        parsed = (parse_timestamp(row[index].strip()) for row in rows)
        stamps = [ts for ts in parsed if ts is not None and (ts.tzinfo is not None) == aware]
    detail, reason = _sampling(base, stamps, usable, measured)
    if detail:
        found("sampling_interval_change", clock, **detail)
    if reason:
        not_evaluated("sampling_interval_change", clock, reason)

    volume = base["volume"]
    measured["volume"] = {"baseline_min": volume["min_records"], "baseline_max": volume["max_records"], "current": records}
    if records < volume["min_records"] / VOLUME_RATIO:
        found("volume_change", None, baseline_min=volume["min_records"], baseline_max=volume["max_records"], current=records,
              direction="drop")
    elif records > volume["max_records"] * VOLUME_RATIO:
        found("volume_change", None, baseline_min=volume["min_records"], baseline_max=volume["max_records"], current=records,
              direction="increase")

    detail, reason = _freshness(base, stamps, usable, aware, as_of_time, measured)
    if detail:
        found("freshness", clock, **detail)
    if reason:
        not_evaluated("freshness", clock, reason)

    for name in shared:
        profile, kinds = profiles[name]
        current_share = profile["empty"] / records
        if current_share - base["empty_share"][name] > EMPTY_RATE_DELTA:
            found("empty_rate_change", name, baseline=round(base["empty_share"][name], 4), current=round(current_share, 4))
        if profile["role"] == "numeric" and base_roles[name] == "numeric":
            values = [float(row[header.index(name)]) for row, kind in zip(rows, kinds) if kind in ("integer", "decimal")]
            detail, reason, shares = _distribution(base["numeric"][name], values)
            if shares is not None:
                measured["psi"][name] = shares["psi"]
                measured["bin_shares"][name] = shares
            if detail:
                found("distribution_shift", name, **detail)
            if reason:
                not_evaluated("distribution_shift", name, reason)

    findings.sort(key=_sort_key)
    skipped.sort(key=_sort_key)
    return {"format_version": FORMAT, "engine": ENGINE, "baseline_digest": base["digest"],
            "source_sha256": hashlib.sha256(payload).hexdigest(), "records": records, "as_of": as_of,
            "measurements": measured, "findings": findings, "not_evaluated": skipped, "status": "DRIFT" if findings else "NO_DRIFT"}
