# SPDX-License-Identifier: Apache-2.0
"""Case-level measurement of ``baseline.compare`` on generated series with known changes (work package D05c).

Each *group* is one generated process (``temp_c`` is one seasonal wave plus Gaussian noise; ``pressure_kpa`` and
``flow_lpm`` are i.i.d. Gaussian noise). Its first 1,200 records form three reference batches; the next records form
the current batch, to which one variant is applied. Every variant of a group shares the same reference bytes, and the
whole group stays in one split, chosen by hash buckets of 6/2/2 out of 10 (realized as development 37, validation 14
and held-out 9 of the 60 groups), so nothing leaks across splits. The thresholds in ``baseline`` were written down
before any measurement and are not tuned here.

Scope, stated plainly: synthetic generated series only, change kinds chosen by the authors of the checks, no real
sensors, no root cause, no model, no production connection. PSI is a descriptive index, not a significance test.
Rates carry their counts and a Wilson 95% interval and are ``None`` (shown ``n/a``) when the denominator is zero.
"""
import argparse
import datetime as dt
import hashlib
import math
from random import Random
from statistics import pstdev

from . import baseline
from .check_evaluation import wilson
from .profiling import read_table

VERSION = "1"
SPLITS = ("development", "validation", "heldout")
GROUPS, REFERENCES, BATCH, SPIKE_BATCH, STEP_SECONDS, PERIOD = 60, 3, 400, 1000, 60, 100
START = dt.datetime(2026, 1, 1)
HEADER = ("ts", "temp_c", "pressure_kpa", "flow_lpm")
NUMERIC = HEADER[1:]
VARIANTS = ("clean", "clean_partial_cycle", "clean_jitter", "clean_recent_lag", "mean_shift_large", "mean_shift_small",
            "scale_change", "unit_change", "sampling_slow", "sampling_fast", "volume_drop", "volume_spike", "stale",
            "null_increase")
TRUTH = {"clean": set(), "clean_partial_cycle": set(), "clean_jitter": set(), "clean_recent_lag": set(),
         "mean_shift_large": {("distribution_shift", "temp_c")}, "mean_shift_small": {("distribution_shift", "temp_c")},
         "scale_change": {("distribution_shift", "pressure_kpa")}, "unit_change": {("distribution_shift", "pressure_kpa")},
         "sampling_slow": {("sampling_interval_change", "ts")}, "sampling_fast": {("sampling_interval_change", "ts")},
         "volume_drop": {("volume_change", None)}, "volume_spike": {("volume_change", None)}, "stale": {("freshness", "ts")},
         "null_increase": {("empty_rate_change", "flow_lpm")}}
CHANGE = {"clean": "none", "clean_partial_cycle": "current batch has 350 records",
          "clean_jitter": "every current timestamp moved by an integer U(-10, 10) s, order kept",
          "clean_recent_lag": "as_of = latest + 150 s (inside the 180 s SLA)",
          "mean_shift_large": "temp_c + 1.5 x baseline temp sd", "mean_shift_small": "temp_c + 0.25 x baseline temp sd",
          "scale_change": "pressure_kpa noise sd 1 -> 2.5", "unit_change": "pressure_kpa x 10",
          "sampling_slow": "interval 120 s, 400 records", "sampling_fast": "interval 30 s, 400 records",
          "volume_drop": "160 records", "volume_spike": "1,000 records", "stale": "as_of = latest + 1,800 s",
          "null_increase": "25% of flow_lpm cells emptied"}
SHIFT = {"mean_shift_large": 1.5, "mean_shift_small": 0.25}
KEEP = {"clean_partial_cycle": 350, "volume_drop": 160}
INTERVAL = {"sampling_slow": 120, "sampling_fast": 30}
LAG = {"clean_recent_lag": 150, "stale": 1800}
DEFAULT_LAG, JITTER, NULLS, SCALE_SD = 60, 10, 100, 2.5
SHIFTS = (0.25, 0.5, 0.75, 1.0, 1.5)
CLEAN_PSI_VARIANTS = ("clean", "clean_partial_cycle", "clean_jitter", "clean_recent_lag")
PSI_NOTE = 0.1  # the conventional "minor shift" level of PSI; reported only, never a decision rule here
NULL_SIZES, NULL_BASELINE, NULL_DRAWS, NULL_BINS = (150, 200, 400), 1200, 1000, 10
SCOPE = ("Deterministic baseline comparison against synthetic changes in generated series. Synthetic generated series "
         "only: no real sensors, change kinds chosen by the authors of the checks, no root cause, no model, no production "
         "connection.")


def split_of(group):
    bucket = int(hashlib.sha256(("aegisflow-baseline-eval-v%s:%d" % (VERSION, group)).encode()).hexdigest(), 16) % 10
    return SPLITS[0] if bucket < 6 else SPLITS[1] if bucket < 8 else SPLITS[2]


def _process(group):
    """Return a function giving record ``i`` of the group's process as [datetime, temp, pressure, flow] cells."""
    rng = Random("baseline-eval:%d" % group)
    amplitude, sigma, phase = rng.choice((1.0, 3.0)), rng.choice((0.2, 0.5)), rng.random() * 6.28
    noise_rng = Random("baseline-eval:%d:noise" % group)
    noise = [(noise_rng.gauss(0, sigma), noise_rng.gauss(0, 1), noise_rng.gauss(0, 1))
             for _ in range(REFERENCES * BATCH + SPIKE_BATCH)]

    def record(i):
        t, p, f = noise[i]
        return [START + dt.timedelta(seconds=STEP_SECONDS * i),
                "%.3f" % (20 + amplitude * math.sin(2 * math.pi * i / PERIOD + phase) + t), "%.3f" % (100 + p),
                "%.3f" % (5 + f)]

    return record


def _csv(rows):
    lines = [",".join(HEADER)] + [",".join([r[0].isoformat()] + r[1:]) for r in rows]
    return ("\n".join(lines) + "\n").encode()


def _generate(group, variant, shift):
    record = _process(group)
    references = [[record(k * BATCH + j) for j in range(BATCH)] for k in range(REFERENCES)]
    first = REFERENCES * BATCH
    current = [record(first + j) for j in range(SPIKE_BATCH if variant == "volume_spike" else BATCH)]
    current = current[:KEEP.get(variant, len(current))]
    if variant in INTERVAL:
        begin = current[0][0]
        for j, row in enumerate(current):
            row[0] = begin + dt.timedelta(seconds=INTERVAL[variant] * j)
    elif variant == "clean_jitter":
        rng = Random("baseline-eval:%d:jitter" % group)
        for row in current:
            row[0] += dt.timedelta(seconds=rng.randint(-JITTER, JITTER))
    elif variant == "null_increase":
        for j in Random("baseline-eval:%d:nulls" % group).sample(range(BATCH), NULLS):
            current[j][3] = ""
    elif variant == "scale_change":
        rng = Random("baseline-eval:%d:scale" % group)
        for row in current:
            row[2] = "%.3f" % (100 + rng.gauss(0, SCALE_SD))
    elif variant == "unit_change":
        for row in current:
            row[2] = "%.3f" % (float(row[2]) * 10)
    if shift:
        size = shift * pstdev([float(row[1]) for rows in references for row in rows])
        for row in current:
            row[1] = "%.3f" % (float(row[1]) + size)
    as_of = (max(row[0] for row in current) + dt.timedelta(seconds=LAG.get(variant, DEFAULT_LAG))).isoformat()
    return [_csv(rows) for rows in references], _csv(current), as_of


def generate(group, variant):
    """Return (reference payloads, current payload, as_of, truth keys) for one case."""
    if variant not in TRUTH:
        raise ValueError("unknown variant %r" % variant)
    references, current, as_of = _generate(group, variant, SHIFT.get(variant, 0.0))
    return references, current, as_of, set(TRUTH[variant])


def _rate(successes, trials):
    return {"successes": successes, "trials": trials, "rate": round(successes / trials, 8) if trials else None,
            "wilson95": [round(x, 8) for x in wilson(successes, trials)] if trials else None}


def _empty_bucket():
    return {"groups": 0, "variants": {v: {"cases": 0, "detected_cases": 0, "cases_with_unexpected": 0} for v in VARIANTS},
            "checks": {}, "clean_psi": {v: {c: {"cases": 0, "max": 0.0, "above": 0} for c in NUMERIC} for v in CLEAN_PSI_VARIANTS},
            "not_evaluated": {}}


def score_case(bucket, variant, truth, result):
    """Add one comparison result to ``bucket``; keys are (check, column) pairs."""
    found = {(f["check"], f["column"]) for f in result["findings"]}
    row = bucket["variants"][variant]
    row["cases"] += 1
    # An empty truth is trivially "detected" here; such variants report case_detection None (n/a), so it never shows.
    row["detected_cases"] += truth <= found
    row["cases_with_unexpected"] += bool(found - truth)
    for key in found | truth:
        check = bucket["checks"].setdefault(key[0], {"true_keys": 0, "false_keys": 0, "missed_keys": 0})
        check["true_keys" if key in found and key in truth else "false_keys" if key in found else "missed_keys"] += 1
    for item in result["not_evaluated"]:
        bucket["not_evaluated"][item["reason"]] = bucket["not_evaluated"].get(item["reason"], 0) + 1


def _psi_values(record, payload):
    """PSI of every numeric column of ``payload`` against the baseline bins, whether or not it crosses the threshold."""
    header, rows = read_table(payload)
    out = {}
    for name in NUMERIC:
        entry, index = record["numeric"][name], header.index(name)
        values = [float(row[index]) for row in rows if row[index] != ""]
        out[name] = baseline.psi(entry["counts"], baseline.bin_counts(entry["edges"], values))
    return out


def evaluate(splits=("development", "validation")):
    report = {name: _empty_bucket() for name in splits}
    for group in range(GROUPS):
        if split_of(group) not in report:
            continue
        bucket = report[split_of(group)]
        bucket["groups"] += 1
        record = None
        for variant in VARIANTS:
            references, current, as_of, truth = generate(group, variant)
            record = record or baseline.build_baseline(references)
            score_case(bucket, variant, truth, baseline.compare(record, current, as_of=as_of))
            if variant in CLEAN_PSI_VARIANTS:
                for name, value in _psi_values(record, current).items():
                    cell = bucket["clean_psi"][variant][name]
                    cell["cases"] += 1
                    cell["max"] = max(cell["max"], value)
                    cell["above"] += value > PSI_NOTE
    for bucket in report.values():
        for variant, row in bucket["variants"].items():
            row["case_detection"] = _rate(row["detected_cases"], row["cases"]) if TRUTH[variant] else None
            row["unexpected_cases"] = _rate(row["cases_with_unexpected"], row["cases"])
        for row in bucket["checks"].values():
            row["precision"] = _rate(row["true_keys"], row["true_keys"] + row["false_keys"])
            row["recall"] = _rate(row["true_keys"], row["true_keys"] + row["missed_keys"])
    return {"version": VERSION, "scope": SCOPE, "groups": GROUPS, "splits": report}


def sensitivity():
    """Detection of a temp_c mean shift of d baseline sd at the fixed threshold, development split only.

    It shows sensitivity; it is not used to change the threshold.
    """
    rows = []
    for d in SHIFTS:
        detected = cases = unexpected = 0
        for group in range(GROUPS):
            if split_of(group) != "development":
                continue
            references, current, as_of = _generate(group, "clean", d)  # the clean current batch, temp_c shifted by d sd
            result = baseline.compare(baseline.build_baseline(references), current, as_of=as_of)
            found = {(f["check"], f["column"]) for f in result["findings"]}
            cases += 1
            detected += ("distribution_shift", "temp_c") in found
            unexpected += bool(found - {("distribution_shift", "temp_c")})
        rows.append({"shift_sd": d, "detection": _rate(detected, cases), "cases_with_unexpected": unexpected})
    return rows


def null_psi(draws=NULL_DRAWS):
    """PSI when nothing changed: i.i.d. N(0, 1) current batches against i.i.d. N(0, 1) baselines of 1,200 values.

    Seeded and independent of the corpus (no group is generated or split). Each draw builds a fresh baseline with
    ``baseline``'s own decile bins, then bins one current batch per size and applies the module's PSI rule. It shows the
    sampling noise of PSI at small current sizes, which ``MIN_VALUES`` bounds; it is not used to change any threshold.
    """
    rng = Random("baseline-eval-null")
    totals = {n: [0.0, 0] for n in NULL_SIZES}
    for _ in range(draws):
        entry = baseline._numeric_entry([rng.gauss(0, 1) for _ in range(NULL_BASELINE)])
        for n in NULL_SIZES:
            value = baseline._psi_raw(entry["counts"], baseline.bin_counts(entry["edges"], [rng.gauss(0, 1) for _ in range(n)]))
            totals[n][0] += value
            totals[n][1] += value > baseline.PSI_SHIFT
    return [{"n_current": n, "n_baseline": NULL_BASELINE, "draws": draws, "mean_psi": round(total / draws, 6), "above": above,
             "expected": round((NULL_BINS - 1) * (1 / NULL_BASELINE + 1 / n), 6)} for n, (total, above) in totals.items()]


def _show(rate):
    if rate is None or rate["rate"] is None:
        return "n/a"
    low, high = rate["wilson95"]
    return "%d/%d = %.1f%% [%.1f–%.1f]" % (rate["successes"], rate["trials"], rate["rate"] * 100, low * 100, high * 100)


def render_markdown(report, sweep, null):
    sizes = [sum(split_of(g) == name for g in range(report["groups"])) for name in SPLITS]
    out = ["# Baseline comparison evaluation", "",
           "Generated by `python -m aegisflow_dr.baseline_eval` (development and validation; `--include-heldout` adds the "
           "held-out split).", "",
           "**Scope.** " + report["scope"], "",
           "## Corpus", "",
           "%d generated groups, split by a hash of the group number into development, validation and held-out; all variants of "
           "a group stay in one split. Each group is one process: `ts` every %d s from %s, `temp_c` = 20 + A sin(2π i/%d + φ) + "
           "N(0, σ) with A in {1, 3} and σ in {0.2, 0.5}, `pressure_kpa` = N(100, 1), `flow_lpm` = N(5, 1), three decimals. "
           "The baseline is built from %d consecutive reference batches of %d records; the current batch is the next %d records "
           "with one variant applied. `as_of` is the latest current timestamp + %d s unless the variant says otherwise."
           % (report["groups"], STEP_SECONDS, START.isoformat(), PERIOD, REFERENCES, BATCH, BATCH, DEFAULT_LAG), "",
           "The hash buckets are 6/2/2 out of 10, realized as development %d, validation %d and held-out %d groups. "
           "Held-out is small, so its intervals are wide: a perfect %d/%d has a Wilson 95%% lower bound of %.1f%%."
           % (sizes[0], sizes[1], sizes[2], sizes[2], sizes[2], wilson(sizes[2], sizes[2])[0] * 100), "",
           "| Variant | Change | Truth (keys that must be found) |", "|---|---|---|"]
    for variant in VARIANTS:
        truth = ", ".join("%s/%s" % k for k in sorted(TRUTH[variant], key=str)) or "none"
        out.append("| %s | %s | %s |" % (variant, CHANGE[variant], truth))
    out += ["", "A case is *detected* when every truth key is found, and has an *unexpected finding* when any found key is "
            "not in its truth. Rates are `found/total = percent [95% Wilson interval]`; `n/a` means there was nothing to measure.",
            "", "## Thresholds and where they came from", "",
            "- `PSI_SHIFT = %s`: the conventional \"significant population shift\" rule of thumb in credit-risk practice, chosen "
            "before any measurement. PSI uses the baseline decile bins with %s added to every bin count on both sides."
            % (baseline.PSI_SHIFT, baseline.PSI_SMOOTH),
            "- `SAMPLING_RATIO = %s` and `VOLUME_RATIO = %s`, a freshness SLA of `FRESHNESS_INTERVALS = %d` baseline sampling "
            "intervals, and `EMPTY_RATE_DELTA = %s`: design choices written in the design document, not fitted."
            % (baseline.SAMPLING_RATIO, baseline.VOLUME_RATIO, baseline.FRESHNESS_INTERVALS, baseline.EMPTY_RATE_DELTA),
            "- `MIN_VALUES = %d`: the fewest numeric values for baseline decile edges and for a PSI comparison. With no "
            "change, E[PSI] ≈ (B − 1)(1/n_baseline + 1/n_current) with B = %d bins; requiring the current-size term "
            "(B − 1)/n_current ≤ PSI_SHIFT / 4 gives n_current ≥ 144, rounded to 150. It was set before the held-out split "
            "was scored, after an independent reviewer's null simulation showed P(PSI > 0.25) ≈ 0.20 at the earlier "
            "minimum of 50 values." % (baseline.MIN_VALUES, NULL_BINS),
            "- No threshold was changed in response to these numbers.", "",
            "No-change PSI (seeded, uses no corpus group): i.i.d. N(0, 1) current batches against a fresh %s-value i.i.d. "
            "N(0, 1) baseline per draw, binned on the baseline deciles exactly as `compare` does." % format(NULL_BASELINE, ","),
            "", "| Current values | Mean PSI | (B − 1)(1/n_baseline + 1/n_current) | Draws with PSI > %s |" % baseline.PSI_SHIFT,
            "|---|---|---|---|"]
    out += ["| %d | %.4f | %.4f | %d/%d |" % (row["n_current"], row["mean_psi"], row["expected"], row["above"], row["draws"])
            for row in null]
    out += ["",
            "## Sensitivity to a temp_c mean shift (development split only)", "",
            "A diagnostic at the fixed threshold; it is not used to change the threshold.", "",
            "| Shift (baseline sd) | Cases detected | Cases with another finding |", "|---|---|---|"]
    for row in sweep:
        out.append("| %s | %s | %d |" % (row["shift_sd"], _show(row["detection"]), row["cases_with_unexpected"]))
    for name, bucket in report["splits"].items():
        out += ["", "## Split: %s (%d groups)" % (name, bucket["groups"]), "",
                "| Variant | Cases detected | Cases with an unexpected finding |", "|---|---|---|"]
        for variant in VARIANTS:
            row = bucket["variants"][variant]
            out.append("| %s | %s | %s |" % (variant, _show(row["case_detection"]), _show(row["unexpected_cases"])))
        out += ["", "| Check | Precision (keys) | Recall (keys) |", "|---|---|---|"]
        out += ["| %s | %s | %s |" % (check, _show(bucket["checks"][check]["precision"]), _show(bucket["checks"][check]["recall"]))
                for check in sorted(bucket["checks"])]
        out += ["", "PSI on unchanged columns of the clean variants (largest value, and cases above %s):" % PSI_NOTE, "",
                "| Variant | " + " | ".join(NUMERIC) + " |", "|---|" + "---|" * len(NUMERIC)]
        for variant in CLEAN_PSI_VARIANTS:
            cells = bucket["clean_psi"][variant]
            out.append("| %s | " % variant + " | ".join("%.4f (%d/%d above)" % (cells[c]["max"], cells[c]["above"], cells[c]["cases"])
                                                       for c in NUMERIC) + " |")
        skipped = ", ".join("%s: %d" % item for item in sorted(bucket["not_evaluated"].items()))
        out += ["", "Not-evaluated entries by reason: %s." % (skipped or "none")]
    out += ["", "## Reading these numbers", "",
            "- Synthetic generated series only; no real sensors. Every change kind was chosen by the authors of the checks, and "
            "the large kinds were sized to be found. High scores mean the checks do what they were written to do on this one "
            "family of series; they are not evidence about real sensors, heavier-tailed noise or other change kinds.",
            "- PSI is a descriptive index, not a significance test. On autocorrelated series it has no p-value, and a batch that "
            "covers a different part of a seasonal cycle can move it without any change in the process.",
            "- Fewer records raise PSI sampling noise on every column, the i.i.d. ones included (see the "
            "no-change PSI table above). Partial seasonal cycles add a further shift on `temp_c`: `clean_partial_cycle` (%d "
            "records, %.1f cycles) and `volume_drop` (%d records, %.1f cycles) deliver less than whole seasonal cycles, while "
            "the baseline holds whole ones. A resulting `distribution_shift` is counted as an unexpected finding."
            % (KEEP["clean_partial_cycle"], KEEP["clean_partial_cycle"] / PERIOD, KEEP["volume_drop"], KEEP["volume_drop"] / PERIOD),
            "- Per-variant case rates count one case per group, and groups are generated independently. Per-check key rates "
            "pool keys across the %d variants of a group: keys from the same group are correlated (they share one generated "
            "process and one baseline), so the per-check Wilson intervals, which treat them as independent, are optimistic; "
            "case-level rates are the more conservative reading." % len(VARIANTS),
            "- Small mean shifts (%s baseline sd, `mean_shift_small`) are only partly detected by design: the PSI threshold is "
            "fixed and was not lowered to catch them. The development sensitivity table above shows how detection grows with "
            "the size of the shift." % SHIFT["mean_shift_small"],
            "- Findings are fixed-rule differences from a stored baseline: no root cause, no model, no production connection.",
            "- Thresholds are not changed after the held-out split is scored; anything held-out reveals is reported as a weakness."]
    return "\n".join(out)


def main(argv=()):
    parser = argparse.ArgumentParser(prog="python -m aegisflow_dr.baseline_eval")
    parser.add_argument("--include-heldout", action="store_true", help="also score the held-out split")
    args = parser.parse_args(list(argv))
    return render_markdown(evaluate(splits=SPLITS if args.include_heldout else SPLITS[:2]), sensitivity(), null_psi())


if __name__ == "__main__":  # pragma: no cover
    import sys

    print(main(sys.argv[1:]))
