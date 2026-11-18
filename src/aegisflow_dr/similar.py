# SPDX-License-Identifier: Apache-2.0
"""Find earlier retained inspections whose failure signature resembles a given one.

A signature is the set of failing checks and schema issues found by the deterministic analysis. Two runs are
compared by Jaccard overlap of those sets (shared / union), a plain ratio of exact items. This is lexical
matching over retained evidence, not a learned embedding, not retrieval-augmented generation and not a
statement about cause: a similar signature means the same checks failed, nothing more.
"""
from __future__ import annotations

from .monitoring import _point

VERSION = "1"
MIN_SCORE = 0.5
LIMIT = 3


def signature(run: dict) -> frozenset[str] | None:
    """Failure signature of a run, or ``None`` when the run has no retained analysis."""
    analysis = ((run.get("result") or {}).get("cases") or [{}])[0].get("analysis")
    if not analysis:
        return None
    point = _point(run, analysis)
    return frozenset([f"check:{item}" for item in point["failing_checks"]] + [f"schema:{item}" for item in point["schema_issues"]])


def similar_runs(target: dict, runs: list[dict]) -> list[dict]:
    """Earlier or other runs resembling ``target``; ``runs`` is any order, the target itself is skipped.

    A clean signature (nothing failed) matches nothing, because "no failure" is not an incident to recall.
    """
    own = signature(target)
    if not own:
        return []
    found, seen = [], {target["run_id"]}
    for run in runs:
        if run["run_id"] in seen:
            continue
        seen.add(run["run_id"])
        other = signature(run)
        if not other:
            continue
        shared = own & other
        score = len(shared) / len(own | other)
        if score >= MIN_SCORE:
            analysis = run["result"]["cases"][0]["analysis"]
            found.append({"run_id": run["run_id"], "at": run.get("finished_at") or run.get("started_at"),
                          "source": (run.get("meta") or {}).get("name") or (run.get("meta") or {}).get("kind") or run.get("scenario"),
                          "score": round(score, 2), "shared": sorted(shared), "only_here": sorted(own - other), "only_there": sorted(other - own),
                          "affected_records": analysis["impact"]["affected_records"], "row_count": analysis["row_count"]})
    found.sort(key=lambda item: (-item["score"], item["at"] or "", item["run_id"]))
    return found[:LIMIT]


def similar_index(runs: list[dict]) -> dict[str, list[dict]]:
    """Matches for every run that has at least one."""
    index = {}
    for run in runs:
        matches = similar_runs(run, runs)
        if matches:
            index[run["run_id"]] = matches
    return {"version": VERSION, "min_score": MIN_SCORE, "matches": index}
