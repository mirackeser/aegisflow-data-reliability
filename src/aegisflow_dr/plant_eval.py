# SPDX-License-Identifier: Apache-2.0
"""End-to-end measurement of the simulated plant's incident loop: detection, change onset, evidence, candidate explanation.

For every seed and scenario a fresh simulated plant (``simulation.Plant``) runs a seeded warm-up of 60-599 live seconds.
One fault is then injected, and the plant advances one monitoring check at a time until an incident opens on the fault's
sensor (or on the stream, for stream faults). It keeps advancing until that incident's evidence is frozen. The
deterministic probe loop (``hypotheses.investigate``, the same call the agents' A24 makes) then runs on the frozen
evidence window.

The step-1 behaviour, investigating the window in which the incident was first detected (what step 1 did when an
investigation was started right at detection), is measured side by side
on the same cases.

Splits are fixed by seed, not hashed:

* development: seeds 1-20. The estimator and the evidence rule were designed on these.
* validation: seeds 21-40.
* held-out: seeds 41-60, scored once after review.

No threshold in ``changepoint``, ``simulation`` or ``hypotheses`` was changed in response to these numbers.

Scope, stated plainly: simulated faults in a simulated plant, written by the same authors as the detectors and probes.
High rates measure that the loop recognises the faults it was designed around, not real-world diagnosis. There is no
root cause, no model and no production connection. Rates carry counts and a Wilson 95% interval and are ``n/a`` when
the denominator is zero.
"""
import argparse
from datetime import datetime, timezone
from random import Random
from statistics import median

from . import changepoint, hypotheses, simulation as sim
from .check_evaluation import wilson

VERSION = "1"
SPLITS = ("development", "validation", "heldout")
SEEDS = {"development": range(1, 21), "validation": range(21, 41), "heldout": range(41, 61)}
START = datetime(2026, 11, 28, 8, 0, tzinfo=timezone.utc)
WARMUP = (60, 600)
DETECT_LIMIT, EVIDENCE_LIMIT = 900, 3 * sim.WINDOW_SECONDS
CLEAN_SECONDS = 3600
ONSET_TOLERANCE = 5
EXPECTED = {"calibration_offset": "calibration_offset", "unit_change": "unit_change", "stuck_sensor": "stuck_sensor",
            "noise_increase": "noise_increase", "sampling_slowdown": "sampling_config_change",
            "ingestion_pause": "source_outage", "duplicate_burst": "duplicate_delivery"}
SCENARIOS = tuple((fault, sensor) for fault in sim.SENSOR_FAULTS for sensor in sim.SENSORS) + tuple(
    (fault, None) for fault in sim.STREAM_FAULTS)
RATES = ("detected", "onset_within", "evidence_ready", "sole_supported", "wrong_supported", "step1_sole_supported")
SCOPE = ("Simulated faults injected into a simulated plant and recognised by detectors and probes written by the same "
         "authors. These rates measure internal consistency of the incident loop, not real-world diagnosis. No root cause, "
         "no model, no production connection.")


def scenario_name(fault, sensor):
    return fault if sensor is None else "%s/%s" % (fault, sensor)


def _supported(record):
    return sorted(h["mechanism"] for h in record["hypotheses"] if h["status"] == "supported")


def _verdicts(record, expected):
    supported = _supported(record)
    return supported == [expected], any(m not in (expected, "genuine_change") for m in supported)


def run_case(seed, fault, sensor):
    """One case: the measurements of one injected fault on one seeded plant."""
    rng = Random("aegisflow-plant-eval-v%s:%d:%s" % (VERSION, seed, scenario_name(fault, sensor)))
    plant = sim.Plant(seed=seed, start=START)
    plant.advance(rng.randrange(*WARMUP))
    injected = plant.inject(fault, sensor)
    group = sensor or sim.STREAM
    case = {"detected": False, "delay_s": None, "onset_error_s": None, "evidence": None, "supported": None,
            "sole_supported": False, "wrong_supported": False, "step1_sole_supported": False, "step1_supported": None}
    incident = None
    while incident is None and plant.now - injected["started_t"] < DETECT_LIMIT:
        plant.advance(sim.CHECK_EVERY)
        incident = next((i for i in plant.incidents if i["sensor"] == group and i["opened_t"] >= injected["started_t"]
                         and i["status"] == "open"), None)
    if incident is None:
        return case
    case.update(detected=True, delay_s=incident["opened_t"] - injected["started_t"])
    detection = sim.to_csv(plant.window(incident["opened_t"]))
    step1 = hypotheses.investigate(plant.baseline, detection, as_of=incident["window"]["as_of"])
    case["step1_supported"] = _supported(step1)
    case["step1_sole_supported"] = _verdicts(step1, EXPECTED[fault])[0]
    begin = plant.now
    while plant.incident(incident["id"])["evidence"]["state"] == sim.COLLECTING and plant.now - begin < EVIDENCE_LIMIT:
        plant.advance(sim.CHECK_EVERY)
    evidence = plant.incident(incident["id"])["evidence"]
    case["evidence"] = evidence["state"]
    if evidence["onset_t"] is not None:
        case["onset_error_s"] = evidence["onset_t"] - injected["started_t"]
    if evidence["state"] == sim.READY:
        payload, as_of = plant.evidence(incident["id"])
        record = hypotheses.investigate(plant.baseline, payload, as_of=as_of)
        case["supported"] = _supported(record)
        case["sole_supported"], case["wrong_supported"] = _verdicts(record, EXPECTED[fault])
    return case


def clean_case(seed):
    """Incidents opened by a fault-free plant over ``CLEAN_SECONDS`` live seconds (false alarms)."""
    plant = sim.Plant(seed=seed, start=START)
    plant.advance(CLEAN_SECONDS)
    return plant.incidents_opened


def _rate(successes, trials):
    return {"numerator": successes, "denominator": trials,
            "value": None if trials == 0 else round(successes / trials, 4), "interval_95": wilson(successes, trials)}


def summarise(cases):
    detected = [c for c in cases if c["detected"]]
    ready = [c for c in detected if c["evidence"] == sim.READY]
    errors = [c["onset_error_s"] for c in detected if c["onset_error_s"] is not None]
    delays = [c["delay_s"] for c in detected]
    return {
        "cases": len(cases),
        "rates": {
            "detected": _rate(len(detected), len(cases)),
            "onset_within": _rate(sum(abs(e) <= ONSET_TOLERANCE for e in errors), len(errors)),
            "evidence_ready": _rate(len(ready), len(detected)),
            "sole_supported": _rate(sum(c["sole_supported"] for c in ready), len(ready)),
            "wrong_supported": _rate(sum(c["wrong_supported"] for c in ready), len(ready)),
            "step1_sole_supported": _rate(sum(c["step1_sole_supported"] for c in detected), len(detected)),
        },
        "delay_median_s": median(delays) if delays else None, "delay_max_s": max(delays) if delays else None,
        "onset_error_median_s": median(errors) if errors else None,
        "onset_error_max_abs_s": max(map(abs, errors)) if errors else None,
        "supported": _tally(c["supported"] for c in ready),
    }


def _tally(lists):
    counts = {}
    for supported in lists:
        key = ", ".join(supported) or "none"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def evaluate(splits=SPLITS[:2], scenarios=SCENARIOS):
    report = {}
    for split in splits:
        seeds = SEEDS[split]
        report[split] = {
            "seeds": [seeds[0], seeds[-1]],
            "scenarios": {scenario_name(f, s): summarise([run_case(seed, f, s) for seed in seeds]) for f, s in scenarios},
            "clean_incidents": sum(clean_case(seed) for seed in seeds), "clean_hours": len(seeds) * CLEAN_SECONDS / 3600,
        }
    return {"version": VERSION, "scope": SCOPE, "splits": report}


def _show(rate):
    if rate["value"] is None:
        return "n/a"
    low, high = rate["interval_95"]
    return "%d/%d = %.0f%% [%.0f–%.0f%%]" % (rate["numerator"], rate["denominator"], rate["value"] * 100, low * 100,
                                            high * 100)


def _number(value):
    return "n/a" if value is None else ("%g" % value)


def render_markdown(report):
    scored = ("development, validation and held-out (`--include-heldout`)" if "heldout" in report["splits"]
              else "development and validation; `--include-heldout` adds the held-out split")
    out = ["# Simulated plant incident loop evaluation", "",
           "Generated by `python -m aegisflow_dr.plant_eval` (%s)." % scored, "",
           "**Scope.** " + report["scope"], "",
           "## Method", "",
           "- **Cases.** For every seed and scenario a fresh simulated plant runs a seeded warm-up of %d-%d live "
           "seconds, then one fault is injected. The plant advances one monitoring check (%d s) at a time until an "
           "incident opens on the fault's sensor, or on the stream for stream faults, within %d s."
           % (WARMUP[0], WARMUP[1] - 1, sim.CHECK_EVERY, DETECT_LIMIT),
           "- **Evidence.** The plant keeps advancing until the incident's evidence is frozen, within %d s. The evidence "
           "is the first full %d s window after the change onset estimated from the readings (`changepoint`)." % (
               EVIDENCE_LIMIT, sim.WINDOW_SECONDS),
           "- **Probes.** `hypotheses.investigate`, the call the agents' A24 makes, runs on the frozen evidence.",
           "- **Step-1 comparison.** The same probe loop also runs on the window in which the incident was first "
           "detected: what step 1 investigated when an investigation was started right at detection. Step 1 kept "
           "the latest window with findings, so a later start saw more post-change readings; this column is its "
           "earliest case, not its average.",
           "- **Splits** are fixed by seed: development 1-20, on which the estimator and the evidence rule were "
           "designed; validation 21-40; held-out 41-60, scored once after review.",
           "- **Changes after validation.** The first validation run showed two weaknesses, and two changes followed "
           "before held-out was scored. The onset of a stuck seasonal sensor was misplaced, because one common harmonic "
           "was removed before splitting, so each segment now has its own harmonic. Noise faults closed before their "
           "evidence was complete, so collection now continues after an incident closes. Validation is therefore not "
           "independent for these two changes; held-out is.",
           "- **Thresholds.** Every threshold (change point: minimum segment %d, clear at a statistic of %g; seasonal "
           "R² %g; the probe thresholds of F04) was fixed before validation and held-out were scored. None was changed "
           "in response to these numbers." % (changepoint.MIN_SEGMENT, changepoint.CLEAR_STATISTIC,
                                              changepoint.SEASONAL_R2), "",
           "| Fault | Expected candidate |", "|---|---|"]
    out += ["| %s | %s |" % (fault, EXPECTED[fault]) for fault in EXPECTED]
    out += ["",
            "Columns:", "",
            "- *Detected* — an incident opened on the right sensor or stream.",
            "- *Onset ±%ds* — the estimated onset is within %d s of the injection." % (ONSET_TOLERANCE, ONSET_TOLERANCE),
            "- *Evidence ready* — the evidence froze before the limit.",
            "- *Sole supported* — the expected mechanism is the only supported candidate on the frozen evidence.",
            "- *Wrong supported* — any other mechanism, except `genuine_change`, is supported.",
            "- *Step 1* — the sole-supported rate on the first detection window. Its denominator is the detected "
            "cases, while *Sole supported* counts cases whose evidence froze.",
            "",
            "Rates are `count/cases = percent [Wilson 95%]`, and `n/a` means nothing to measure."]
    for split, bucket in report["splits"].items():
        out += ["", "## Split: %s (seeds %d-%d)" % (split, *bucket["seeds"]), "",
                "| Scenario | Detected | Onset ±%ds | Evidence ready | Sole supported | Wrong supported | Step 1 sole "
                "supported |" % ONSET_TOLERANCE, "|---|---|---|---|---|---|---|"]
        for name, row in bucket["scenarios"].items():
            out.append("| %s | " % name + " | ".join(_show(row["rates"][metric]) for metric in RATES) + " |")
        out += ["", "| Scenario | Detection delay median / max (s) | Onset error median / max abs (s) | Supported on "
                "frozen evidence |", "|---|---|---|---|"]
        for name, row in bucket["scenarios"].items():
            supported = "; ".join("%s: %d" % item for item in row["supported"].items()) or "n/a"
            out.append("| %s | %s / %s | %s / %s | %s |" % (
                name, _number(row["delay_median_s"]), _number(row["delay_max_s"]), _number(row["onset_error_median_s"]),
                _number(row["onset_error_max_abs_s"]), supported))
        out += ["", "False alarms: %d incident(s) opened in %g simulated hours of fault-free plant (one plant per seed, "
                "%d s each)."
                % (bucket["clean_incidents"], bucket["clean_hours"], CLEAN_SECONDS)]
    out += ["", "## Reading these numbers", "",
            "- Simulated faults only, with fixed magnitudes, and detectors and probes written by the same authors. High "
            "rates show that the loop recognises these faults, not how it would do on real sensors.",
            "- **Noise on `temp_c`.** The F04 spread probe compares marginal spreads, and on a seasonal sensor the "
            "seasonal swing dominates them. A threefold noise increase raises the spread by only about 20%, so the "
            "probe refutes the noise mechanism. This is a limit of the fixed probe, not tuned away here.",
            "- **Duplicate burst.** The burst repeats %d readings, about 13%% of a %d s window, which is below the fixed "
            "20%% support threshold of `duplicate_share`, so the candidate stays open. Its onset is the start of the "
            "repeated range, %d s before the injection, by construction." % (
                sim.DUPLICATE_BURST, sim.WINDOW_SECONDS, sim.DUPLICATE_BURST - 1),
            "- **Stuck sensor.** Its onset is one second before the injection: the stuck value is the previous reading.",
            "- **Ingestion pause.** Its onset is the second after the last reading (`data_stopped`), not a change point.",
            "- \"Supported\" means consistent with fixed probes and inconsistent with none. It never means the cause.",
            "- Seeds are independent plants. Scenarios of one seed share the plant's noise stream up to the warm-up, so "
            "rates across scenarios are not fully independent."]
    return "\n".join(out)


def main(argv=()):
    parser = argparse.ArgumentParser(prog="python -m aegisflow_dr.plant_eval")
    parser.add_argument("--include-heldout", action="store_true", help="also score the held-out split")
    args = parser.parse_args(list(argv))
    return render_markdown(evaluate(splits=SPLITS if args.include_heldout else SPLITS[:2]))


if __name__ == "__main__":  # pragma: no cover
    import sys

    print(main(sys.argv[1:]))
