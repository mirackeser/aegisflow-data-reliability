# SPDX-License-Identifier: Apache-2.0
"""Qualitative readings of hypothesis-loop observations, in fixed words, for the model-using A23 role.

Design: docs/superpowers/specs/2026-11-28-a23-readings-design.md.

A reading names the pattern an observation shows (for example a mean scaled by a power of ten, a wider spread, rows that
dropped), computed deterministically from the aggregates the baseline comparison already reports and, for empty values,
from where the empty cells sit. It carries no cell value. The thresholds are written here once and were not tuned on any
evaluation; they follow the probe catalog's documented signatures. A reading describes data, never a cause.
"""
import math

from .hypotheses import PROFILE_CHECKS
from .profiling import read_table

POWER_OF_TEN, POWER_TOLERANCE = 0.9, 0.05  # |log10 r| >= 0.9 and within 0.05 of an integer
SHIFT_SD, WIDER, NARROWER, CONTIGUOUS = 0.5, 1.5, 0.8, 0.8
WORDS = ("scaled_power_of_ten", "sign_reversed", "shifted_up", "shifted_down", "unchanged", "wider", "narrower", "drop",
         "increase", "late", "longer", "shorter", "more", "fewer", "contiguous", "scattered")
KEYS = ("mean", "spread", "rows", "data", "interval", "empty_values", "empty_pattern")


def _mean(detail):
    base, current, sd = detail["baseline_mean"], detail["current_mean"], detail["baseline_sd"]
    if base and current / base < 0:
        return "sign_reversed"
    if base and current:
        exponent = math.log10(abs(current / base))
        if abs(exponent) >= POWER_OF_TEN and abs(exponent - round(exponent)) <= POWER_TOLERANCE:
            return "scaled_power_of_ten"
    shift = (current - base) / sd if sd else 0.0
    return "shifted_up" if shift >= SHIFT_SD else "shifted_down" if shift <= -SHIFT_SD else "unchanged"


def _spread(detail):
    ratio = detail["current_sd"] / detail["baseline_sd"] if detail["baseline_sd"] else 1.0
    return "wider" if ratio >= WIDER else "narrower" if ratio <= NARROWER else "unchanged"


def empty_patterns(payload):
    """Per column with empty cells: ``contiguous`` when its longest empty run holds at least 80% of them, else
    ``scattered``."""
    header, rows = read_table(payload)
    patterns = {}
    for index, name in enumerate(header):
        empties = [row[index].strip() == "" for row in rows]
        total, longest, run = sum(empties), 0, 0
        for empty in empties:
            run = run + 1 if empty else 0
            longest = max(longest, run)
        if total:
            patterns[name] = "contiguous" if longest / total >= CONTIGUOUS else "scattered"
    return patterns


def reading(finding, patterns):
    """The reading of one baseline-comparison finding (``{}`` for a check without one)."""
    check, detail = finding["check"], finding["detail"]
    if check == "distribution_shift":
        return {"mean": _mean(detail), "spread": _spread(detail)}
    if check == "volume_change":
        return {"rows": detail["direction"]}
    if check == "freshness":
        return {"data": "late"}
    if check == "sampling_interval_change":
        return {"interval": "longer" if detail["current_seconds"] > detail["baseline_seconds"] else "shorter"}
    if check == "empty_rate_change":
        return {"empty_values": "more" if detail["current"] > detail["baseline"] else "fewer",
                "empty_pattern": patterns.get(finding["column"], "scattered")}
    return {}


def observation_readings(comparison, profile, payload):
    """Readings in the order of ``hypotheses.observations_from``: every baseline finding, then the profile's flatline
    and duplicate findings (which carry no reading)."""
    patterns = empty_patterns(payload)
    picked = [reading(f, patterns) for f in comparison["findings"]]
    return picked + [{} for f in profile["findings"] if f["check"] in PROFILE_CHECKS]
