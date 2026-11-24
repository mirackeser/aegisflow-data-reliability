# SPDX-License-Identifier: Apache-2.0
"""Record-level measurement of ``profiling`` against injected sensor-style faults.

Ground truth comes from the injector: every faulty record is known because it was put there.
Each *group* is one generated base series; all of its fault variants stay in one split
(development 60%, validation 20%, held-out 20%), so no variant can leak across a split.
Thresholds in ``profiling`` were set while looking only at the development split.

Scope, stated plainly: this measures whether deterministic checks find synthetic faults of the
kinds below in generated series (one trend + one seasonal wave + Gaussian noise). It says
nothing about real sensors, unseen fault kinds, or any language model. Rates carry their counts
and a Wilson 95% interval, and are ``None`` (never 1.0) when the denominator is zero.
"""
import datetime as dt
import hashlib
import math
from random import Random

from .check_evaluation import wilson
from .profiling import profile_csv

VERSION = "1"
SPLITS = ("development", "validation", "heldout")
GROUPS, ROWS, STEP_SECONDS, NUMERIC_COLUMNS = 60, 300, 60, 3
KINDS = ("spike_large", "spike_small", "flatline", "gap", "duplicate_timestamp", "out_of_order", "null_burst",
         "type_corruption", "clean")
TARGET = {"spike_large": "outlier", "spike_small": "outlier", "flatline": "flatline", "gap": "timestamp_gap",
          "duplicate_timestamp": "timestamp_duplicate", "out_of_order": "timestamp_out_of_order",
          "null_burst": "empty_rate", "type_corruption": "type_mismatch"}
COLUMN = {"spike_large": "temp_c", "spike_small": "temp_c", "flatline": "pressure_kpa", "gap": "ts",
          "duplicate_timestamp": "ts", "out_of_order": "ts", "null_burst": "flow_lpm", "type_corruption": "pressure_kpa"}
# Faults whose truth is "this column is affected", not a list of records; only detection is scored.
COLUMN_LEVEL = frozenset({"null_burst"})
SCOPE = ("Deterministic profiling checks against synthetic injected faults in generated series. Not real sensors, not "
         "unseen fault kinds, and not a language model.")


def split_of(group):
    bucket = int(hashlib.sha256(("aegisflow-profile-eval-v%s:%d" % (VERSION, group)).encode()).hexdigest(), 16) % 10
    return SPLITS[0] if bucket < 6 else SPLITS[1] if bucket < 8 else SPLITS[2]


def base_series(group):
    """Return rows as lists [timestamp, temp, pressure, flow] and the temperature noise level."""
    rng = Random("base:%d" % group)
    sd = rng.choice((0.2, 0.5))
    slope, amplitude, phase = rng.choice((0.0, 0.02)), rng.choice((1.0, 3.0)), rng.random() * 6.28
    start = dt.datetime(2026, 1, 1)
    rows = []
    for i in range(ROWS):
        ts = (start + dt.timedelta(seconds=STEP_SECONDS * i)).isoformat()
        temp = 20 + slope * i + amplitude * math.sin(2 * math.pi * i / 100 + phase) + rng.gauss(0, sd)
        rows.append([ts, "%.3f" % temp, "%.3f" % (100 + rng.gauss(0, 1)), "%.3f" % (5 + rng.gauss(0, 1))])
    return rows, sd


def _spread(rng, count, low, high, gap):
    """Distinct 0-based positions at least ``gap`` apart."""
    chosen = []
    while len(chosen) < count:
        position = rng.randrange(low, high)
        if all(abs(position - other) >= gap for other in chosen):
            chosen.append(position)
    return sorted(chosen)


def inject(group, kind):
    """Return (csv bytes, truth) where truth maps (check, column) to the exact faulty 1-based records."""
    rows, sd = base_series(group)
    rows = [list(r) for r in rows]
    rng = Random("inject:%d:%s" % (group, kind))
    truth = {}
    if kind in ("spike_large", "spike_small"):
        low, high = (10, 20) if kind == "spike_large" else (4, 6)
        spots = _spread(rng, 3, 10, ROWS - 10, 15)
        for position in spots:
            rows[position][1] = "%.3f" % (float(rows[position][1]) + rng.choice((-1, 1)) * rng.uniform(low, high) * sd)
        truth[(TARGET[kind], "temp_c")] = {p + 1 for p in spots}
    elif kind == "flatline":
        start = rng.randrange(20, ROWS - 40)
        for position in range(start, start + 12):
            rows[position][2] = rows[start][2]
        truth[("flatline", "pressure_kpa")] = {p + 1 for p in range(start, start + 12)}
    elif kind == "gap":
        start = rng.randrange(20, ROWS - 40)
        del rows[start:start + 5]
        truth[("timestamp_gap", "ts")] = {start + 1}
    elif kind == "duplicate_timestamp":
        spots = _spread(rng, 3, 20, ROWS - 10, 15)
        for position in spots:
            rows[position][0] = rows[position - 1][0]
        truth[("timestamp_duplicate", "ts")] = {p + 1 for p in spots}
    elif kind == "out_of_order":
        position = rng.randrange(30, ROWS - 10)
        earlier = dt.datetime.fromisoformat(rows[position - 5][0]) + dt.timedelta(seconds=7)
        rows[position][0] = earlier.isoformat()
        truth[("timestamp_out_of_order", "ts")] = {position + 1}
    elif kind == "null_burst":
        start = rng.randrange(10, ROWS - 90)
        for position in range(start, start + 80):
            rows[position][3] = ""
        truth[("empty_rate", "flow_lpm")] = {p + 1 for p in range(start, start + 80)}
    elif kind == "type_corruption":
        spots = _spread(rng, 3, 10, ROWS - 10, 15)
        for position, text in zip(spots, ("ERR", "N/A", "--")):
            rows[position][2] = text
        truth[("type_mismatch", "pressure_kpa")] = {p + 1 for p in spots}
    payload = "\n".join(",".join(r) for r in [["ts", "temp_c", "pressure_kpa", "flow_lpm"]] + rows) + "\n"
    return payload.encode(), truth


def flagged_records(profile):
    found = {}
    for finding in profile["findings"]:
        records = set(finding["records"])
        if finding["check"] == "flatline":
            records = {n for run in finding["detail"]["runs"] for n in range(run["first"], run["last"] + 1)}
        found[(finding["check"], finding["column"])] = records
    return found


def _rate(successes, trials):
    return {"successes": successes, "trials": trials, "rate": round(successes / trials, 8) if trials else None,
            "wilson95": [round(x, 8) for x in wilson(successes, trials)] if trials else None}


def evaluate():
    splits = {name: {"groups": 0, "kinds": {k: {"cases": 0, "detected_cases": 0, "truth_records": 0, "found_records": 0,
                                                 "extra_records": 0, "unexpected_findings": 0, "cases_with_unexpected": 0} for k in KINDS},
                     "checks": {}} for name in SPLITS}
    for group in range(GROUPS):
        bucket = splits[split_of(group)]
        bucket["groups"] += 1
        for kind in KINDS:
            payload, truth = inject(group, kind)
            found = flagged_records(profile_csv(payload))
            row = bucket["kinds"][kind]
            row["cases"] += 1
            for key, records in truth.items():
                if kind in COLUMN_LEVEL:
                    row["detected_cases"] += key in found
                    continue
                hit = found.get(key, set()) & records
                row["truth_records"] += len(records)
                row["found_records"] += len(hit)
                row["detected_cases"] += bool(hit)
            row["cases_with_unexpected"] += any(key not in truth for key in found)
            for key, records in found.items():
                extra = 0 if kind in COLUMN_LEVEL and key in truth else len(records - truth.get(key, set()))
                row["extra_records"] += extra
                row["unexpected_findings"] += key not in truth
                check = bucket["checks"].setdefault(key[0], {"true_records": 0, "false_records": 0})
                check["true_records"] += len(records) - extra
                check["false_records"] += extra
    for bucket in splits.values():
        for kind, row in bucket["kinds"].items():
            row["record_recall"] = _rate(row["found_records"], row["truth_records"])
            row["case_detection"] = _rate(row["detected_cases"], row["cases"]) if kind != "clean" else None
            row["false_alarm_cases"] = _rate(row["cases_with_unexpected"], row["cases"])
        clean = bucket["kinds"]["clean"]
        bucket["clean_false_alarm_values"] = _rate(clean["extra_records"], clean["cases"] * ROWS * NUMERIC_COLUMNS)
        for check, row in bucket["checks"].items():
            row["precision"] = _rate(row["true_records"], row["true_records"] + row["false_records"])
    clean = [splits[name]["kinds"]["clean"] for name in SPLITS]
    overall = _rate(sum(c["extra_records"] for c in clean), sum(c["cases"] for c in clean) * ROWS * NUMERIC_COLUMNS)
    return {"version": VERSION, "scope": SCOPE, "groups": GROUPS, "rows_per_table": ROWS, "splits": splits,
            "clean_false_alarm_values": overall}


SWEEP = (3.5, 4.0, 4.5, 5.0, 6.0)


def threshold_sweep():
    """Outlier threshold trade-off on the development split only (how K was chosen, shown in the report)."""
    from . import profiling
    saved, rows = profiling.OUTLIER_K, []
    try:
        for k in SWEEP:
            profiling.OUTLIER_K = k
            row = {"k": k}
            for kind in ("spike_large", "spike_small", "clean"):
                found = truth_count = extra = 0
                for group in range(GROUPS):
                    if split_of(group) != "development":
                        continue
                    payload, truth = inject(group, kind)
                    flagged = flagged_records(profile_csv(payload)).get(("outlier", "temp_c"), set())
                    wanted = truth.get(("outlier", "temp_c"), set())
                    found, truth_count, extra = found + len(flagged & wanted), truth_count + len(wanted), extra + len(flagged - wanted)
                row[kind] = {"found": found, "truth": truth_count, "extra": extra}
            rows.append(row)
    finally:
        profiling.OUTLIER_K = saved
    return rows


def _show(rate):
    if rate is None or rate["rate"] is None:
        return "n/a"
    low, high = rate["wilson95"]
    if rate["trials"] >= 1000 and (high < 0.01 or rate["rate"] < 0.01):
        return "%d/%d = %.2g%% [%.2g–%.2g]" % (rate["successes"], rate["trials"], rate["rate"] * 100, low * 100, high * 100)
    return "%d/%d = %.1f%% [%.1f–%.1f]" % (rate["successes"], rate["trials"], rate["rate"] * 100, low * 100, high * 100)


def render_markdown(report, sweep):
    from . import profiling
    out = ["# Profiling evaluation", "", "Generated by `python -m aegisflow_dr.profiling_eval`; a test fails if this file drifts from the code.", "",
           "**Scope.** " + report["scope"], "",
           "Corpus: %d base series x %d variants, %d records each. Outlier threshold K = %s (second differences, median-absolute-deviation scale)."
           % (report["groups"], len(KINDS), report["rows_per_table"], profiling.OUTLIER_K), "",
           "Rates are `found/total = percent [95% Wilson interval]`; `n/a` means there was nothing to measure.", "",
           "## How the threshold was chosen (development split only)", "",
           "K was fixed before the held-out split was scored, from a design target of about 1e-5 false flags per clean Gaussian value (P(|z|>K), so K of 4.5 or more), "
           "and was not changed afterwards. Lower K finds more small spikes and eventually raises false alarms; higher K does the opposite. "
           "The measured false-alarm rate is reported below and is higher than that target.", "",
           "**Measured false alarms on clean series (all splits):** %s (percent of scanned numeric values flagged). "
           "Expect roughly that many false outlier flags on noise-only data; real sensor noise is usually heavier-tailed, so expect more." % _show(report["clean_false_alarm_values"]), "",
           "| K | large spikes found | small spikes found | extra flagged records on large / small / clean tables |", "|---|---|---|---|"]
    for row in sweep:
        out.append("| %s | %d/%d | %d/%d | %d / %d / %d |" % (row["k"], row["spike_large"]["found"], row["spike_large"]["truth"],
                   row["spike_small"]["found"], row["spike_small"]["truth"], row["spike_large"]["extra"], row["spike_small"]["extra"], row["clean"]["extra"]))
    for name in SPLITS:
        bucket = report["splits"][name]
        out += ["", "## Split: %s (%d groups)" % (name, bucket["groups"]), "",
                "| Fault kind | Record recall | Cases detected | Cases with an unexpected finding |", "|---|---|---|---|"]
        for kind in KINDS:
            row = bucket["kinds"][kind]
            recall = "column-level" if kind in COLUMN_LEVEL else _show(row["record_recall"]) if row["truth_records"] else "n/a"
            out.append("| %s | %s | %s | %s |" % (kind, recall, _show(row["case_detection"]), _show(row["false_alarm_cases"])))
        out += ["", "Clean-series false alarms in this split: %s." % _show(bucket["clean_false_alarm_values"]),
                "", "| Check | Precision (record level) |", "|---|---|"]
        out += ["| %s | %s |" % (check, _show(bucket["checks"][check]["precision"])) for check in sorted(bucket["checks"])]
    out += ["", "## Reading these numbers", "",
            "- Small spikes (4 to 6 noise units) are only partly found by design; the first and last value of a series are never flagged as outliers.",
            "- `null_burst` is scored per column, not per record, because the finding lists at most %d records." % profiling.MAX_RECORDS_LISTED,
            "- Every fault was injected by the same authors who wrote the checks, into one family of generated series (trend, one seasonal wave, Gaussian noise). "
            "High scores here mean the checks do what they were written to do on that family. They are not evidence about real sensors, heavier-tailed noise, "
            "other fault kinds, or any language model."]
    return "\n".join(out)


def main(argv=()):
    return render_markdown(evaluate(), threshold_sweep())


if __name__ == "__main__":  # pragma: no cover
    print(main())
