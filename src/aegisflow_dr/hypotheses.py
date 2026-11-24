# SPDX-License-Identifier: Apache-2.0
"""Observation, hypothesis and probe contracts over a fixed catalog of simulated mechanisms (work package F04).

This is bookkeeping of candidate explanations, not root-cause inference. A "supported" hypothesis means fixed,
deterministic probes found the measurements consistent with it and inconsistent with none, nothing more.
``genuine_change`` (a real change in the measured process) cannot be tested from these data, so it always stays open.
Probe thresholds are written down in the design before any measurement and are not tuned on evaluation output.
"""
from datetime import datetime
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import math
from statistics import fmean, median, pstdev

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

from .baseline import compare
from .pipeline import InputRejected
from .profiling import kind_of, parse_timestamp, profile_csv, read_table

FORMAT, ENGINE, CATALOG_VERSION = "1", "deterministic-hypotheses-v1", "1"
MAX_PROBES_DEFAULT, MAX_PROBES_LIMIT = 6, 20
STATEMENT = "Candidate mechanisms consistent with fixed probes on these measurements. Not a root-cause determination."
MECHANISMS = ("unit_change", "calibration_offset", "noise_increase", "stuck_sensor", "genuine_change", "sampling_config_change",
              "partial_load", "duplicate_delivery", "delivery_delay", "source_outage", "field_outage", "intermittent_loss")
PROBES = ("scale_ratio", "spread_ratio", "flat_share", "interval_regularity", "span_ratio", "freshness_lag", "duplicate_share",
          "empty_runs")
KINDS = ("observation", "hypothesis", "probe_result", "investigation")
PROFILE_CHECKS = ("flatline", "duplicate_rows", "timestamp_duplicate")
# Mechanism -> (column scoped?, observations it explains as (check, direction or None for any)).
CATALOG = {
    "unit_change": (True, (("distribution_shift", None),)),
    "calibration_offset": (True, (("distribution_shift", None),)),
    "noise_increase": (True, (("distribution_shift", None),)),
    "stuck_sensor": (True, (("distribution_shift", None), ("flatline", None))),
    "genuine_change": (True, (("distribution_shift", None),)),
    "sampling_config_change": (False, (("sampling_interval_change", None), ("volume_change", None))),
    "partial_load": (False, (("volume_change", "drop"),)),
    "duplicate_delivery": (False, (("volume_change", "increase"), ("duplicate_rows", None), ("timestamp_duplicate", None))),
    "delivery_delay": (False, (("freshness", None),)),
    "source_outage": (False, (("freshness", None), ("volume_change", "drop"))),
    "field_outage": (True, (("empty_rate_change", None),)),
    "intermittent_loss": (True, (("empty_rate_change", None),)),
}


def _offline(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=1)
def _schema():
    schema = json.loads(files("aegisflow_dr").joinpath("data", "hypothesis-contracts-v1.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=len(KINDS))
def _validator(kind):
    schema = _schema()
    wrapper = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/" + kind}
    return Draft202012Validator(wrapper, registry=Registry(retrieve=_offline))


def validate(kind, value):
    """Return ``value`` unchanged when it satisfies the ``kind`` contract; else raise InputRejected."""
    if type(kind) is not str or kind not in KINDS:
        raise InputRejected("Unknown hypothesis contract")
    try:
        _validator(kind).validate(value)
    except ValidationError:
        raise InputRejected("Hypothesis %s contract rejected" % kind.replace("_", " ")) from None
    return value


def trace_digest(record):
    """SHA-256 of the canonical JSON of ``record`` without its ``trace_sha256`` field."""
    body = {k: v for k, v in record.items() if k != "trace_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def verify_investigation(record):
    """Return ``record`` unchanged when it is schema-valid and its trace digest matches; else raise InputRejected."""
    validate("investigation", record)
    if record["trace_sha256"] != trace_digest(record):
        raise InputRejected("Investigation trace digest does not match its content")
    return record


def observations_from(comparison, profile):
    """Observations from every baseline finding, then from the profile's flatline and duplicate findings, in their order."""
    evidence = comparison["source_sha256"]
    picked = [("baseline", f) for f in comparison["findings"]]
    picked += [("profile", f) for f in profile["findings"] if f["check"] in PROFILE_CHECKS]
    return [{"id": "obs-%d" % number, "source": source, "check": f["check"], "column": f["column"],
             "direction": f["detail"].get("direction") if f["check"] == "volume_change" else None, "evidence_sha256": evidence}
            for number, (source, f) in enumerate(picked, 1)]


def _explains(mechanism, observation):
    return any(check == observation["check"] and direction in (None, observation["direction"])
               for check, direction in CATALOG[mechanism][1])


def generate(observations):
    """One open hypothesis per (mechanism, column) explaining at least one observation, with its competitors."""
    hypotheses, index = [], {}
    for obs in observations:
        for mechanism in MECHANISMS:
            if not _explains(mechanism, obs):
                continue
            key = (mechanism, obs["column"] if CATALOG[mechanism][0] else None)
            if key not in index:
                index[key] = {"id": "hyp-%d" % (len(hypotheses) + 1), "mechanism": mechanism, "column": key[1], "explains": [],
                              "competitors": [], "status": "open", "supporting": [], "refuting": []}
                hypotheses.append(index[key])
            index[key]["explains"].append(obs["id"])
    for hyp in hypotheses:
        hyp["competitors"] = [other["id"] for other in hypotheses
                              if other is not hyp and set(other["explains"]) & set(hyp["explains"])]
    return hypotheses


# ---------------------------------------------------------------------------------------------------------------------
# Probes. Thresholds are the design's fixed values; measured values are rounded to 6 places for the record only.

PROBE_MECHANISMS = {
    "scale_ratio": ("unit_change",),
    "spread_ratio": ("calibration_offset", "noise_increase"),
    "flat_share": ("stuck_sensor",),
    "interval_regularity": ("sampling_config_change", "partial_load"),
    "span_ratio": ("partial_load", "source_outage", "delivery_delay", "sampling_config_change"),
    "freshness_lag": ("source_outage", "partial_load"),
    "duplicate_share": ("duplicate_delivery",),
    "empty_runs": ("field_outage", "intermittent_loss"),
}
COLUMN_PROBES = frozenset({"scale_ratio", "spread_ratio", "flat_share", "empty_runs"})
FLAT_RUN, MIN_GAPS = 8, 10
SUPPORTS, REFUTES, NEUTRAL = "supports", "refutes", "neutral"


class _Current:
    """What the probes read: the stored baseline record, the comparison measurements and the current table.

    ``stamps`` holds, per record, the parsed timestamp of the baseline's time column when its timezone awareness matches
    the baseline, else None; ``timed`` says whether that column is usable at all.
    """

    def __init__(self, base, measurements, header, rows, stamps, timed):
        self.base, self.measurements, self.header, self.rows = base, measurements, header, rows
        self.stamps, self.timed = stamps, timed

    def cells(self, column):
        if column not in self.header:
            return None
        index = self.header.index(column)
        return [row[index] for row in self.rows]

    def numbers(self, column):
        """Numeric current values of ``column`` with their record positions (0-based)."""
        cells = self.cells(column) or []
        return [(i, float(c)) for i, c in enumerate(cells) if kind_of(c) in ("integer", "decimal")]


def _ratio(numerator, denominator):
    return None if numerator is None or denominator is None or denominator == 0 else numerator / denominator


def _rounded(measured):
    return {k: None if v is None else round(v, 6) for k, v in measured.items()}


def _scale_ratio_rules(m):
    r, sd_ratio = m["r"], m["sd_ratio"]
    if r is None:
        return {"unit_change": NEUTRAL}
    if r <= 0 or 0.5 <= abs(r) <= 2:
        return {"unit_change": REFUTES}
    log_r = math.log10(r)
    if (abs(log_r) >= 0.9 and abs(log_r - round(log_r)) <= 0.05 and sd_ratio is not None and sd_ratio > 0
            and abs(math.log10(sd_ratio) - log_r) <= 0.1):
        return {"unit_change": SUPPORTS}
    return {"unit_change": NEUTRAL}


def _base_entry(current, column):
    return current.base["numeric"].get(column)


def _current_stats(current, column):
    values = [v for _, v in current.numbers(column)]
    return (median(values), fmean(values), pstdev(values)) if values else (None, None, None)


def _scale_ratio(current, column):
    entry, (cur_median, _, cur_sd) = _base_entry(current, column), _current_stats(current, column)
    measured = {"r": _ratio(cur_median, entry and entry["median"]), "sd_ratio": _ratio(cur_sd, entry and entry["sd"])}
    return _rounded(measured), _scale_ratio_rules(measured)


def _spread_ratio_rules(m):
    sd_ratio, shift = m["sd_ratio"], m["mean_shift_sd"]
    if sd_ratio is None or shift is None:
        return {"calibration_offset": NEUTRAL, "noise_increase": NEUTRAL}
    calibration = (SUPPORTS if 0.8 <= sd_ratio <= 1.25 and abs(shift) >= 0.5
                   else REFUTES if sd_ratio < 0.67 or sd_ratio > 1.5 else NEUTRAL)
    noise = (SUPPORTS if sd_ratio >= 1.5 and abs(shift) < 0.5
             else REFUTES if sd_ratio < 1.25 or abs(shift) >= 1 else NEUTRAL)
    return {"calibration_offset": calibration, "noise_increase": noise}


def _spread_ratio(current, column):
    entry, (_, cur_mean, cur_sd) = _base_entry(current, column), _current_stats(current, column)
    sd = entry and entry["sd"]
    shift = None if cur_mean is None or entry is None else _ratio(cur_mean - entry["mean"], sd)
    measured = {"sd_ratio": _ratio(cur_sd, sd), "mean_shift_sd": shift}
    return _rounded(measured), _spread_ratio_rules(measured)


def _flat_share_rules(m):
    share = m["share"]
    return {"stuck_sensor": NEUTRAL if share is None else SUPPORTS if share >= 0.3 else REFUTES if share < 0.05 else NEUTRAL}


def _flat_share(current, column):
    """Share of numeric values in runs of >= FLAT_RUN equal values on consecutive records (a gap breaks a run)."""
    pairs = current.numbers(column)
    flat, start = 0, 0
    for i in range(1, len(pairs) + 1):
        if i == len(pairs) or pairs[i][1] != pairs[start][1] or pairs[i][0] != pairs[i - 1][0] + 1:
            if i - start >= FLAT_RUN:
                flat += i - start
            start = i
    measured = {"share": _ratio(flat, len(pairs))}
    return _rounded(measured), _flat_share_rules(measured)


def _interval_regularity_rules(m):
    ratio, cv = m["ratio"], m["cv"]
    if ratio is None:
        return {"sampling_config_change": NEUTRAL, "partial_load": NEUTRAL}
    changed = ratio < 1 / 1.5 or ratio > 1.5
    sampling = SUPPORTS if changed and cv is not None and cv < 0.25 else REFUTES if 1 / 1.1 <= ratio <= 1.1 else NEUTRAL
    return {"sampling_config_change": sampling, "partial_load": REFUTES if changed else NEUTRAL}


def _stamps(current):
    return [ts for ts in current.stamps if ts is not None]


def _interval_regularity(current, column):
    sampling = current.measurements.get("sampling_interval", {})
    ordered = sorted(set(_stamps(current)))
    gaps = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    cv = _ratio(pstdev(gaps), fmean(gaps)) if len(gaps) >= MIN_GAPS else None
    measured = {"ratio": _ratio(sampling.get("current_seconds"), sampling.get("baseline_seconds")), "cv": cv}
    return _rounded(measured), _interval_regularity_rules(measured)


def _span_ratio_rules(m):
    ratio = m["ratio"]
    short, full = ratio is not None and ratio < 1 / 1.5, ratio is not None and ratio >= 1 / 1.1
    loss = SUPPORTS if short else REFUTES if full else NEUTRAL
    delay = SUPPORTS if full else REFUTES if short else NEUTRAL
    return {"partial_load": loss, "source_outage": loss, "delivery_delay": delay, "sampling_config_change": NEUTRAL}


def _span_ratio(current, column):
    spans = [(parse_timestamp(r["last"]) - parse_timestamp(r["first"])).total_seconds()
             for r in current.base["references"] if r["first"] is not None]
    stamps = _stamps(current)
    span = (max(stamps) - min(stamps)).total_seconds() if len(stamps) >= 2 else None
    measured = {"ratio": _ratio(span, median(spans) if spans else None)}
    return _rounded(measured), _span_ratio_rules(measured)


def _freshness_lag_rules(m):
    lag = m["lag_ratio"]
    if lag is None:
        return {"source_outage": NEUTRAL, "partial_load": NEUTRAL}
    return {"source_outage": SUPPORTS if lag > 1 else REFUTES, "partial_load": REFUTES if lag > 1 else NEUTRAL}


def _freshness_lag(current, column):
    freshness = current.measurements.get("freshness", {})
    measured = {"lag_ratio": _ratio(freshness.get("lag_seconds"), freshness.get("sla_seconds"))}
    return _rounded(measured), _freshness_lag_rules(measured)


def _duplicate_share_rules(m):
    share = m["share"]
    return {"duplicate_delivery": NEUTRAL if share is None else SUPPORTS if share >= 0.2 else REFUTES if share == 0 else NEUTRAL}


def _duplicate_share(current, column):
    """Share of current records whose timestamp equals an earlier record's."""
    share = None
    if current.timed:
        seen, repeats = set(), 0
        for ts in current.stamps:
            repeats += ts is not None and ts in seen
            seen.add(ts)
        share = repeats / len(current.stamps)
    measured = {"share": share}
    return _rounded(measured), _duplicate_share_rules(measured)


def _empty_runs_rules(m):
    share = m["longest_run_share"]
    if share is None:
        return {"field_outage": NEUTRAL, "intermittent_loss": NEUTRAL}
    return {"field_outage": SUPPORTS if share >= 0.8 else REFUTES if share < 0.3 else NEUTRAL,
            "intermittent_loss": SUPPORTS if share < 0.3 else REFUTES if share >= 0.8 else NEUTRAL}


def _empty_runs(current, column):
    """Longest run of consecutive empty cells as a share of all empty cells in the column."""
    longest = total = run = 0
    for cell in current.cells(column) or []:
        run = run + 1 if kind_of(cell) == "empty" else 0
        total += run > 0
        longest = max(longest, run)
    measured = {"longest_run_share": _ratio(longest, total)}
    return _rounded(measured), _empty_runs_rules(measured)


_PROBE_FUNCTIONS = {"scale_ratio": _scale_ratio, "spread_ratio": _spread_ratio, "flat_share": _flat_share,
                    "interval_regularity": _interval_regularity, "span_ratio": _span_ratio, "freshness_lag": _freshness_lag,
                    "duplicate_share": _duplicate_share, "empty_runs": _empty_runs}


# ---------------------------------------------------------------------------------------------------------------------
# Bounded loop with replanning.

def _column_key(column):
    return column is not None, column or ""


def _candidates(hypotheses):
    """(probe, column) pairs in probe order, then column (None first), that concern at least one hypothesis."""
    pairs = []
    for probe in PROBES:
        columns = {h["column"] for h in hypotheses if h["mechanism"] in PROBE_MECHANISMS[probe]}
        if probe not in COLUMN_PROBES:
            columns = {None} if columns else set()
        pairs += [(probe, column) for column in sorted(columns, key=_column_key)]
    return pairs


def _concerned(hypotheses, probe, column):
    return [h for h in hypotheses if h["mechanism"] in PROBE_MECHANISMS[probe] and h["column"] == column
            and h["status"] != "refuted"]


def _resolved(observations, hypotheses):
    by_id = {h["id"]: h for h in hypotheses}
    explained = [o for o in observations if any(o["id"] in h["explains"] for h in hypotheses)]
    for obs in explained:
        supported = [h for h in hypotheses if obs["id"] in h["explains"] and h["status"] == "supported"]
        if len(supported) != 1 or not all(by_id[c]["status"] == "refuted" or by_id[c]["mechanism"] == "genuine_change"
                                          for c in supported[0]["competitors"]):
            return False
    return bool(explained)


def _loop(observations, hypotheses, run_probe, max_probes):
    """Run probes until resolved, nothing informative remains or the budget is spent; return (probe results, stop reason)."""
    if not observations:
        return [], "no_observations"
    pending, results = _candidates(hypotheses), []
    while True:
        if _resolved(observations, hypotheses):
            return results, "resolved"
        options = [(len(_concerned(hypotheses, *pair)), -order, pair) for order, pair in enumerate(pending)]
        options = [option for option in options if option[0] > 0]
        if not options:
            return results, "no_informative_probe"
        if len(results) == max_probes:
            return results, "probe_budget_exhausted"
        pair = max(options)[2]
        pending.remove(pair)
        concerned = _concerned(hypotheses, *pair)
        measured, by_mechanism = run_probe(*pair)
        probe_id = "prb-%d" % (len(results) + 1)
        outcomes = {h["id"]: by_mechanism[h["mechanism"]] for h in concerned}
        for hyp in concerned:
            if outcomes[hyp["id"]] == SUPPORTS:
                hyp["supporting"].append(probe_id)
            elif outcomes[hyp["id"]] == REFUTES:
                hyp["refuting"].append(probe_id)
            hyp["status"] = "refuted" if hyp["refuting"] else "supported" if hyp["supporting"] else "open"
        results.append({"id": probe_id, "probe": pair[0], "column": pair[1], "round": len(results) + 1,
                        "measured": measured, "outcomes": outcomes})


_STATUS_RANK = {"supported": 0, "open": 1, "refuted": 2}


def _rank(hypotheses):
    """Supported (more supporting probes first), then open, then refuted; ties by catalog order, then column."""
    def key(h):
        return (_STATUS_RANK[h["status"]], -len(h["supporting"]) if h["status"] == "supported" else 0,
                MECHANISMS.index(h["mechanism"]), _column_key(h["column"]))
    return [h["id"] for h in sorted(hypotheses, key=key)]


def _verdict(observations, hypotheses):
    if not observations:
        return "no_observations"
    supported = sum(h["status"] == "supported" for h in hypotheses)
    return "none_supported" if supported == 0 else "single_supported" if supported == 1 else "multiple_supported"


def _current_view(base, comparison, profile, payload):
    header, rows = read_table(payload)
    clock = base["time_column"]
    timed = any(c["name"] == clock and c["role"] == "timestamp" for c in profile["columns"])
    aware = any(r["first"] is not None and datetime.fromisoformat(r["first"]).tzinfo is not None for r in base["references"])
    stamps = [None] * len(rows)
    if timed:
        index = header.index(clock)
        parsed = (parse_timestamp(row[index].strip()) for row in rows)
        stamps = [ts if ts is not None and (ts.tzinfo is not None) == aware else None for ts in parsed]
    return _Current(base, comparison["measurements"], header, rows, stamps, timed)


def investigate(baseline, payload, *, as_of=None, max_probes=MAX_PROBES_DEFAULT):
    """Compare ``payload`` with ``baseline`` and run the bounded probe loop; return a validated investigation record.

    Candidate mechanisms only: "supported" means consistent with fixed probes, never a determined cause.
    """
    if type(max_probes) is not int or not 1 <= max_probes <= MAX_PROBES_LIMIT:
        raise InputRejected("max_probes must be an integer from 1 to %d" % MAX_PROBES_LIMIT)
    comparison = compare(baseline, payload, as_of=as_of)
    profile = profile_csv(payload)
    current = _current_view(baseline, comparison, profile, payload)
    observations = observations_from(comparison, profile)
    hypotheses = generate(observations)
    probes, stop = _loop(observations, hypotheses,
                         lambda probe, column: _PROBE_FUNCTIONS[probe](current, column), max_probes)
    record = {"format_version": FORMAT, "engine": ENGINE, "catalog_version": CATALOG_VERSION, "observations": observations,
              "hypotheses": hypotheses, "probes": probes, "budget": {"max_probes": max_probes, "used": len(probes)},
              "stop_reason": stop, "ranking": _rank(hypotheses), "verdict": _verdict(observations, hypotheses),
              "statement": STATEMENT}
    record["trace_sha256"] = trace_digest(record)
    return validate("investigation", record)
