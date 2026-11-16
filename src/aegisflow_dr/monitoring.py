# SPDX-License-Identifier: Apache-2.0
"""Rule-based change detection across retained inspections of the same source.

Every number comes from the deterministic analysis of a retained run; nothing is predicted. The
thresholds below are fixed, documented rules, not statistical tests, and with a handful of runs a
flagged change is a prompt to look, never proof of a cause.
"""
from __future__ import annotations

from decimal import Decimal

VERSION = "1"
RULES = {"quality_degraded_rate_points": 0.05, "row_count_shift_ratio": 0.5, "amount_level_shift_ratio": 0.5}
MAX_RUNS = 20
DEGRADING = ("SCHEMA_CHANGED", "QUALITY_DEGRADED", "NEW_CHECK_FAILURE", "ROW_COUNT_SHIFT", "AMOUNT_LEVEL_SHIFT")


def stream_key(meta: dict | None, scenario: str | None) -> tuple[str, str]:
    """Group runs of one source; labelled synthetic samples share a stream so fault changes are visible."""
    meta = meta or {}
    kind = meta.get("kind") or scenario or "unknown"
    if kind == "synthetic_sample":
        return "synthetic-sample", "synthetic-sample"
    name = meta.get("name") or kind
    return f"{kind}:{name}", name


def _point(run: dict, analysis: dict) -> dict:
    rows, impact = analysis["row_count"], analysis["impact"]
    dimensions = analysis["dimensions"]
    valid = dimensions["validity"]["passed"]
    return {
        "run_id": run["run_id"], "at": run.get("finished_at") or run.get("started_at"), "row_count": rows,
        "affected_records": impact["affected_records"],
        "affected_rate": round(impact["affected_records"] / rows, 4) if rows else None,
        "dimensions": {name: dimensions[name]["ratio"] for name in sorted(dimensions)},
        "mean_valid_amount": f"{Decimal(impact['valid_amount_total']) / valid:.2f}" if valid else None,
        "schema_issues": sorted(f"{i['check']}:{i['column']}" for i in analysis["schema_issues"]),
        "failing_checks": sorted(f"{h['check']}:{h['column']}" for h in analysis["heatmap"] if h["records"]),
    }


def _changes(before: dict, after: dict) -> list[dict]:
    found = []

    def add(code, **detail):
        found.append({"code": code, "detail": detail})

    appeared = sorted(set(after["schema_issues"]) - set(before["schema_issues"]))
    resolved = sorted(set(before["schema_issues"]) - set(after["schema_issues"]))
    if appeared:
        add("SCHEMA_CHANGED", before=before["schema_issues"], after=after["schema_issues"])
    elif resolved:
        add("SCHEMA_RESTORED", before=before["schema_issues"], after=after["schema_issues"])
    if before["affected_rate"] is not None and after["affected_rate"] is not None:
        if after["affected_rate"] - before["affected_rate"] >= RULES["quality_degraded_rate_points"]:
            add("QUALITY_DEGRADED", before=before["affected_rate"], after=after["affected_rate"])
    new = sorted(set(after["failing_checks"]) - set(before["failing_checks"]))
    if new:
        add("NEW_CHECK_FAILURE", checks=new)
    if before["row_count"] and after["row_count"]:
        shift = abs(after["row_count"] - before["row_count"]) / before["row_count"]
        if shift >= RULES["row_count_shift_ratio"]:
            add("ROW_COUNT_SHIFT", before=before["row_count"], after=after["row_count"])
    if before["mean_valid_amount"] and after["mean_valid_amount"]:
        old = Decimal(before["mean_valid_amount"])
        if old and abs(Decimal(after["mean_valid_amount"]) - old) / old >= Decimal(str(RULES["amount_level_shift_ratio"])):
            add("AMOUNT_LEVEL_SHIFT", before=before["mean_valid_amount"], after=after["mean_valid_amount"])
    if before["affected_records"] and not after["affected_records"] and not after["schema_issues"]:
        add("RECOVERED", before=before["affected_records"], after=0)
    return found


def monitor(runs: list[dict]) -> dict:
    """``runs`` oldest first; runs without a retained analysis are skipped."""
    streams: dict[str, dict] = {}
    seen = set()
    for run in runs:
        analysis = ((run.get("result") or {}).get("cases") or [{}])[0].get("analysis")
        if not analysis or run["run_id"] in seen:
            continue
        seen.add(run["run_id"])
        key, label = stream_key(run.get("meta"), run.get("scenario"))
        stream = streams.setdefault(key, {"key": key, "label": label, "kind": (run.get("meta") or {}).get("kind") or run.get("scenario"), "runs": []})
        point = _point(run, analysis)
        previous = stream["runs"][-1] if stream["runs"] else None
        point["changes"] = _changes(previous, point) if previous else []
        stream["runs"].append(point)
    result = []
    for stream in streams.values():
        stream["runs"] = stream["runs"][-MAX_RUNS:]
        codes = {change["code"] for change in stream["runs"][-1]["changes"]}
        stream["status"] = ("INSUFFICIENT_HISTORY" if len(stream["runs"]) < 2
                            else "RECOVERED" if codes & {"RECOVERED", "SCHEMA_RESTORED"}
                            else "DEGRADED" if codes & set(DEGRADING) else "STABLE")
        stream["latest_changes"] = stream["runs"][-1]["changes"]
        result.append(stream)
    return {"version": VERSION, "rules": RULES, "streams": sorted(result, key=lambda s: s["key"])}
