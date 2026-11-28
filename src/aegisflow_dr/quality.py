# SPDX-License-Identifier: Apache-2.0
"""Measured quality: one summary of every committed evaluation, for the workbench's quality page.

Design: docs/superpowers/specs/2026-11-28-quality-page-design.md.

Each evaluation becomes a card with its committed report, its split sizes, headline metrics per split and, for the plant
and the agents, a per-scenario table. Nothing is measured here: every number is read from an evaluation's own report,
which is either recomputed (the deterministic, seconds-long evaluations) or rendered from committed case measurements
(the plant simulation and the live-model agent runs). Rates are normalised to ``{numerator, denominator, value, low,
high}`` with a 95% Wilson interval and ``value`` None when the denominator is zero. Headline rates pool every case of
the split across scenarios; cases of one group or seed are correlated, so a pooled interval is optimistic.
"""
import json
from pathlib import Path

from . import baseline_eval, check_evaluation, hypotheses_eval, plant_eval, profiling_eval
from .agents import agents_eval
from .check_evaluation import wilson

VERSION = "1"
SPLITS = ("development", "validation", "heldout")
EVALUATIONS = Path(__file__).resolve().parents[2] / "fixtures" / "evaluations"
PLANT_CASES = EVALUATIONS / "plant-cases-v1.json"
AGENTS_CASES = EVALUATIONS / "agents-cases-v2.json"  # the latest agents evaluation (prompt version 3)
AGENTS_V1_CASES = EVALUATIONS / "agents-cases-v1.json"  # the previous one (prompt version 2), kept for comparison
HIGHER, LOWER = "higher", "lower"


def rate(numerator, denominator):
    low, high = wilson(numerator, denominator) or (None, None)
    return {"numerator": numerator, "denominator": denominator,
            "value": None if denominator == 0 else round(numerator / denominator, 4), "low": low, "high": high}


def from_report(value):
    """A rate in either report shape (``successes/trials`` or ``numerator/denominator``), normalised; None stays None."""
    if value is None:
        return None
    if "successes" in value:
        return rate(value["successes"], value["trials"])
    return rate(value["numerator"], value["denominator"])


def pool(values):
    """Every case of the given rates in one rate; rates that do not apply (None) are left out."""
    values = [v for v in values if v is not None]
    return rate(sum(v["numerator"] for v in values), sum(v["denominator"] for v in values))


def _metric(key, direction, per_split):
    return {"key": key, "kind": "rate", "better": direction, "splits": per_split}


def _scenarios(columns, rows):
    return {"columns": list(columns), "rows": rows}


def plant_card(report):
    splits = report["splits"]
    rows = lambda key: {s: pool(from_report(sc["rates"][key]) for sc in b["scenarios"].values())
                        for s, b in splits.items()}
    columns = ("detected", "onset_within", "sole_supported", "wrong_supported", "step1_sole_supported")
    names = list(next(iter(splits.values()))["scenarios"]) if splits else []
    return {"id": "plant", "report": "docs/evaluation/plant.md", "available": True,
            "units": {s: {"seeds": b["seeds"][1] - b["seeds"][0] + 1} for s, b in splits.items()},
            "metrics": [_metric("detected", HIGHER, rows("detected")),
                        _metric("onset_within", HIGHER, rows("onset_within")),
                        _metric("sole_supported", HIGHER, rows("sole_supported")),
                        _metric("wrong_supported", LOWER, rows("wrong_supported")),
                        {"key": "false_alarms", "kind": "per_hours", "better": LOWER,
                         "splits": {s: {"count": b["clean_incidents"], "hours": b["clean_hours"]}
                                    for s, b in splits.items()}}],
            "scenarios": _scenarios(columns, [
                {"name": name, "splits": {s: {c: from_report(b["scenarios"][name]["rates"][c]) for c in columns}
                                          for s, b in splits.items()}} for name in names])}


def agents_card(report, ident="agents"):
    """The agents evaluation; ``ident`` names the card ("agents" for the latest, "agents_v1" for the previous one)."""
    splits = report["splits"]
    modelled = [n for n in agents_eval.SCENARIOS if agents_eval.truth_of(n) is not None]
    unmodelled = list(hypotheses_eval.UNMODELLED)  # changes outside the catalog; A23 is not asked on a clean batch

    def scenario_pool(key, names):
        return {s: pool(from_report(b["scenarios"][n]["rates"][key]) for n in names) for s, b in splits.items()}

    columns = ("a23_any", "a23_top1", "a23_echo", "loop_sole", "a23_misattributed", "loop_misattributed")
    return {"id": ident, "family": "agents", "report": agents_eval.PROTOCOLS[report["version"]].report,
            "available": True, "evaluation_version": report["version"],
            "model": report["recording"]["model"], "prompt_version": report["recording"]["prompt_version"],
            "units": {s: {"groups": b["groups"], "cases": b["runs"]["cases"]} for s, b in splits.items()},
            "metrics": [_metric("selection_exact", HIGHER, {s: from_report(b["selection"]["exact"])
                                                            for s, b in splits.items()}),
                        _metric("model_json_valid", HIGHER, {s: pool(from_report(st["rates"]["valid"])
                                                                     for st in b["llm"].values())
                                                             for s, b in splits.items()}),
                        _metric("a23_any", HIGHER, scenario_pool("a23_any", modelled)),
                        _metric("a23_top1", HIGHER, scenario_pool("a23_top1", modelled)),
                        _metric("a23_misattributed", LOWER, scenario_pool("a23_misattributed", unmodelled)),
                        _metric("loop_sole", HIGHER, scenario_pool("loop_sole", modelled)),
                        _metric("replay_fidelity", HIGHER, {s: from_report(b["runs"]["fidelity"])
                                                            for s, b in splits.items()}),
                        {"key": "run_p50_ms", "kind": "ms", "better": LOWER,
                         "splits": {s: b["runs"]["p50"] for s, b in splits.items()}}],
            "scenarios": _scenarios(columns, [
                {"name": name, "splits": {s: {c: from_report(b["scenarios"][name]["rates"][c]) for c in columns}
                                          for s, b in splits.items()}} for name in agents_eval.SCENARIOS])}


def hypotheses_card(report):
    splits = report["splits"]
    rows = lambda key: {s: pool(from_report(sc["rates"][key]) for sc in b["scenarios"].values())
                        for s, b in splits.items()}
    return {"id": "hypotheses", "report": "docs/evaluation/hypotheses.md", "available": True,
            "units": {s: {"groups": b["groups"]} for s, b in splits.items()},
            "metrics": [_metric("truth_sole_supported", HIGHER, rows("truth_sole_supported")),
                        _metric("truth_supported", HIGHER, rows("truth_supported")),
                        _metric("other_supported", LOWER, rows("other_supported")),
                        _metric("misattributed", LOWER, {s: pool(from_report(b["scenarios"][n]["rates"]["misattributed"])
                                                                 for n in hypotheses_eval.UNMODELLED)
                                                         for s, b in splits.items()})]}


def baseline_card(report):
    splits = report["splits"]
    clean = [v for v in baseline_eval.VARIANTS if not baseline_eval.TRUTH[v]]
    return {"id": "baseline", "report": "docs/evaluation/baseline.md", "available": True,
            "units": {s: {"groups": b["groups"]} for s, b in splits.items()},
            "metrics": [_metric("case_detection", HIGHER, {s: pool(from_report(r["case_detection"])
                                                                   for r in b["variants"].values())
                                                           for s, b in splits.items()}),
                        _metric("clean_with_finding", LOWER, {s: pool(from_report(b["variants"][v]["unexpected_cases"])
                                                                      for v in clean) for s, b in splits.items()})]}


def profiling_card(report):
    splits = report["splits"]
    return {"id": "profiling", "report": "docs/evaluation/profiling.md", "available": True,
            "units": {s: {"groups": b["groups"]} for s, b in splits.items()},
            "metrics": [_metric("case_detection", HIGHER, {s: pool(from_report(r["case_detection"])
                                                                   for r in b["kinds"].values())
                                                           for s, b in splits.items()}),
                        _metric("record_recall", HIGHER, {s: pool(from_report(r["record_recall"])
                                                                  for r in b["kinds"].values())
                                                          for s, b in splits.items()}),
                        _metric("clean_with_finding", LOWER, {s: from_report(b["kinds"]["clean"]["false_alarm_cases"])
                                                              for s, b in splits.items()})]}


def checks_card(report):
    results = report["results"]
    metric = lambda name, key: _metric("%s.%s" % (name, key), HIGHER,
                                       {s: from_report(r["overall"][key]) for s, r in results[name].items()})
    return {"id": "checks", "report": "docs/evaluation/latest.md", "available": True,
            "units": {s: {"groups": report["corpus"]["per_split"][s]["groups"]} for s in results["diagnose_csv"]},
            "metrics": [metric(name, key) for name in results for key in ("precision", "recall")]}


def _saved(path, summarise, card, ident):
    if not path.exists():
        return {"id": ident, "available": False}
    return card(summarise(json.loads(path.read_text("utf-8"))))


def summary():
    """Every evaluation's card, in the order the page shows them."""
    return {"version": VERSION, "splits": list(SPLITS), "evaluations": [
        _saved(PLANT_CASES, plant_eval.summarise_collected, plant_card, "plant"),
        _saved(AGENTS_CASES, agents_eval.summarise_collected, agents_card, "agents"),
        _saved(AGENTS_V1_CASES, agents_eval.summarise_collected, lambda r: agents_card(r, "agents_v1"), "agents_v1"),
        hypotheses_card(hypotheses_eval.evaluate(splits=SPLITS)),
        baseline_card(baseline_eval.evaluate(splits=SPLITS)),
        profiling_card(profiling_eval.evaluate()),
        checks_card(check_evaluation.evaluate(include_heldout=True))]}
