# SPDX-License-Identifier: Apache-2.0
"""A07-A22: the specialist roles. Rule agents wrap existing modules through ``ctx.tool``; A22 is RAG plus advisory text.

Claims carry only counts, check names, column names, numbers, statuses and run-local ids. Tool outputs are stored
whole as evidence, so a claim can always be traced to the exact output it summarises. A12 and A16 have no input
source in this deployment and always return NEEDS_EVIDENCE; no output is fabricated for them.
"""
from collections import Counter
from dataclasses import asdict
import re

from ...analysis import analyze_csv
from ...baseline import compare, load_baseline
from ...batch import downstream, run_batch
from ...cardinality import join_cardinality
from ...consistency import compare as consistency_compare
from ...pipeline import diagnose_csv
from ...profiling import profile_csv
from ...schema_registry import diff_columns
from ...similar import signature, similar_runs
from ..prompts import free_text_ok, relevance_schema
from ._base import MAX_LIST, ModelFailure, NeedsEvidence, bounded, executor
from .orchestration import triage

_STATUS = re.compile(r"[A-Z][A-Z_]{0,31}")
# Baseline column roles mapped onto schema-registry types; numeric maps to decimal (integer and decimal are not
# distinguished in a baseline) and timestamp to text, so a timestamp/text role change is left to A17.
_REGISTRY_TYPE = {"numeric": "decimal", "timestamp": "text", "text": "text", "empty": "empty"}
RETRIEVE_LIMIT, MAX_PASSAGE = 5, 400
_CITATION_BOUNDS = {"source": 128, "revision": 64, "citation": 256, "passage": 4000}
WATERMARK_CHECKS = ("timestamp_gap", "timestamp_duplicate", "timestamp_out_of_order", "timestamp_mixed_timezone")


def _need_baseline(run):
    if run.ctx.baseline is None:
        raise NeedsEvidence("NO_BASELINE")


def _need_order(run):
    if not triage(run.ctx)["order_extract"]:
        raise NeedsEvidence("NOT_ORDER_EXTRACT")


def _need_two_orders(run):
    if run.ctx.second_payload is None:
        raise NeedsEvidence("NO_SECOND_SOURCE")
    t = triage(run.ctx)
    if not (t["order_extract"] and t["second_order_extract"]):
        raise NeedsEvidence("NOT_ORDER_EXTRACT")


def _stamp(entry):
    value = entry.get("finished_at") or entry.get("started_at")
    return value if type(value) is str else ""


def summarise_history(history):
    """Counts and latest status of retained run summaries; free-text fields are never read."""
    readable = [entry for entry in history if type(entry) is dict]
    statuses = [e["status"] if type(e.get("status")) is str and _STATUS.fullmatch(e["status"]) else "UNKNOWN"
                for e in readable]
    counts = Counter(statuses)
    latest = None
    if readable:  # history is newest first; a later timestamp wins over position
        latest = statuses[max(range(len(readable)), key=lambda i: (_stamp(readable[i]), -i))]
    return {"runs": len(history), "readable": len(readable), "statuses": dict(sorted(counts.items())),
            "latest_status": latest}


@executor("A07")
def pipeline_run_explorer(run):
    if not run.ctx.history:
        raise NeedsEvidence("NO_HISTORY")
    summary = run.ctx.tool("run_history", summarise_history, run.ctx.history)
    ref = run.put("run_history_summary", summary)
    run.claim("a07.history", {"runs": summary["runs"], "readable": summary["readable"],
                              "latest_status": summary["latest_status"],
                              "statuses": bounded(summary["statuses"]), "counts": bounded(summary["statuses"].values())},
              ref)


def schema_drift(baseline, columns):
    """schema_registry.diff_columns between the baseline's columns and the current header with profile roles."""
    old = [{"name": c["name"], "type": _REGISTRY_TYPE[c["role"]]} for c in load_baseline(baseline)["columns"]]
    new = [{"name": c["name"], "type": _REGISTRY_TYPE[c["role"]]} for c in columns]
    return diff_columns(old, new)


@executor("A08")
def schema_drift_investigator(run):
    _need_baseline(run)
    t = triage(run.ctx)
    diff = run.ctx.tool("schema_diff", schema_drift, run.ctx.baseline, t["columns"])
    ref = run.put("schema_diff", diff)
    run.claim("a08.schema_diff", {"status": diff["status"], "removed": bounded(diff["removed"]),
                                  "added": bounded(diff["added"]),
                                  "widened": bounded(c["name"] for c in diff["widened"]),
                                  "narrowed": bounded(c["name"] for c in diff["narrowed"]),
                                  "reordered": diff["reordered"], "possible_renames": len(diff["possible_renames"])}, ref)


@executor("A09")
def data_contract_inspector(run):
    _need_order(run)
    report = run.ctx.tool("diagnose_csv", diagnose_csv, run.ctx.payload)
    ref = run.put("contract_report", asdict(report))
    run.claim("a09.contract", {"status": report.status, "findings": report.finding_count,
                               "truncated": report.findings_truncated, "records": report.row_count}, ref)
    groups = Counter((f.check, f.column) for f in report.findings)
    for (check, column), count in sorted(groups.items())[:MAX_LIST]:
        run.claim("a09.check", {"check": check, "column": column or None, "findings": count}, ref)


@executor("A10")
def data_profiling_specialist(run):
    profile = run.ctx.tool("profile_csv", profile_csv, run.ctx.payload)
    ref = run.put("profile", profile)
    run.claim("a10.profile", {"records": profile["records"], "columns": len(profile["columns"]),
                              "time_column": profile["time_column"], "status": profile["status"],
                              "findings": len(profile["findings"])}, ref)
    for finding in profile["findings"][:24]:
        run.claim("a10.finding", {"check": finding["check"], "column": finding["column"], "count": finding["count"]}, ref)


def _comparison(run):
    comparison = run.ctx.tool("baseline_compare", compare, run.ctx.baseline, run.ctx.payload, as_of=run.ctx.as_of)
    return comparison, run.put("baseline_comparison", comparison)


def _first(items, check):
    return next((item for item in items if item["check"] == check), None)


@executor("A11")
def freshness_volume_analyst(run):
    _need_baseline(run)
    comparison, ref = _comparison(run)
    volume, finding = comparison["measurements"]["volume"], _first(comparison["findings"], "volume_change")
    run.claim("a11.volume", {"baseline_min": volume["baseline_min"], "baseline_max": volume["baseline_max"],
                             "current": volume["current"], "changed": finding is not None,
                             "direction": finding["detail"]["direction"] if finding else None}, ref)
    fresh = comparison["measurements"]["freshness"]
    stale = _first(comparison["findings"], "freshness")
    skipped = _first(comparison["not_evaluated"], "freshness")
    run.claim("a11.freshness", {"evaluated": skipped is None, "lag_seconds": fresh["lag_seconds"],
                                "sla_seconds": fresh["sla_seconds"], "stale": stale is not None,
                                "reason": skipped["reason"] if skipped else None}, ref)


@executor("A12")
def log_trace_analyst(run):
    raise NeedsEvidence("NO_LOG_SOURCE")


@executor("A13")
def lineage_impact_investigator(run):
    _need_order(run)
    potential = run.ctx.tool("query_lineage", downstream, "source_orders")
    ref = run.put("lineage", {"dataset": "source_orders", "potential": list(potential),
                              "lineage_kind": "declared_dataset_dag"})
    run.claim("a13.downstream", {"dataset": "source_orders", "potential": list(potential),
                                 "lineage_kind": "declared_dataset_dag"}, ref)


def _batch(run):
    report = run.ctx.tool("run_batch", run_batch, run.ctx.payload)
    return report, run.put("batch_report", asdict(report))


@executor("A14")
def sql_transformation_analyst(run):
    _need_order(run)
    report, ref = _batch(run)
    run.claim("a14.transform", {"status": report.status, "transform_sha256": report.transform_sha256,
                                "artifacts": len(report.artifacts), "affected_dataset": report.affected_dataset,
                                "source_findings": report.source_check.finding_count}, ref)
    for artifact in report.artifacts:
        run.claim("a14.artifact", {"dataset": artifact.dataset, "rows": artifact.row_count}, ref)


@executor("A15")
def incremental_load_investigator(run):
    if triage(run.ctx)["time_column"] is None:
        raise NeedsEvidence("NO_TIME_COLUMN")
    profile = run.ctx.tool("profile_csv", profile_csv, run.ctx.payload)
    ref = run.put("profile", profile)
    counts = {check: sum(f["count"] for f in profile["findings"] if f["check"] == check) for check in WATERMARK_CHECKS}
    run.claim("a15.watermark", {"time_column": profile["time_column"], "gaps": counts["timestamp_gap"],
                                "duplicates": counts["timestamp_duplicate"],
                                "out_of_order": counts["timestamp_out_of_order"],
                                "mixed_timezone": counts["timestamp_mixed_timezone"]}, ref)


@executor("A16")
def cdc_replication_investigator(run):
    raise NeedsEvidence("NO_CDC_SOURCE")


@executor("A17")
def type_casting_investigator(run):
    profile = run.ctx.tool("profile_csv", profile_csv, run.ctx.payload)
    profile_ref = run.put("profile", profile)
    mismatches = [f for f in profile["findings"] if f["check"] == "type_mismatch"]
    changes, comparison_ref = [], None
    if run.ctx.baseline is not None:
        comparison, comparison_ref = _comparison(run)
        changes = [f for f in comparison["findings"] if f["check"] == "role_change"]
    if not mismatches and not changes:
        raise NeedsEvidence("NO_TYPE_SIGNAL")
    for f in mismatches[:MAX_LIST]:
        run.claim("a17.type_mismatch", {"column": f["column"], "count": f["count"], "expected": f["detail"]["expected"]},
                  profile_ref)
    for f in changes[:MAX_LIST]:
        run.claim("a17.role_change", {"column": f["column"], "baseline": f["detail"]["baseline"],
                                      "current": f["detail"]["current"]}, comparison_ref)


@executor("A18")
def join_cardinality_investigator(run):
    _need_two_orders(run)
    join = run.ctx.tool("join_cardinality", join_cardinality, run.ctx.payload, run.ctx.second_payload)
    ref = run.put("join_cardinality", join)
    run.claim("a18.join", {"shared_keys": join["shared_keys"], "join_rows": join["join_rows"],
                           "extra_rows": join["extra_rows_from_join"], "fan_out": join["fan_out"],
                           **join["relationship"]}, ref)
    for side in ("first", "second"):
        keys = join[side]
        run.claim("a18.keys", {"side": side, "rows": keys["rows"], "distinct_keys": keys["distinct_keys"],
                               "repeated_keys": keys["repeated_keys"], "blank_keys": keys["blank_keys"]}, ref)


@executor("A19")
def reconciliation_investigator(run):
    _need_order(run)
    report, ref = _batch(run)
    if report.status == "BLOCKED":
        run.claim("a19.blocked", {"status": report.status, "source_findings": report.source_check.finding_count}, ref)
    for check in report.reconciliation:
        run.claim("a19.reconciliation", {"check": check.check, "expected": check.expected, "actual": check.actual,
                                         "passed": check.passed}, ref)


@executor("A20")
def statistical_drift_investigator(run):
    _need_baseline(run)
    comparison, ref = _comparison(run)
    psi = comparison["measurements"]["psi"]
    shifted = {f["column"] for f in comparison["findings"] if f["check"] == "distribution_shift"}
    skipped = [s for s in comparison["not_evaluated"] if s["check"] == "distribution_shift"]
    run.claim("a20.summary", {"measured": len(psi), "shifted": len(shifted), "not_evaluated": len(skipped),
                              "threshold": 0.25}, ref)
    for column in sorted(psi)[:MAX_LIST]:
        run.claim("a20.psi", {"column": column, "psi": psi[column], "shifted": column in shifted}, ref)
    for item in skipped[:12]:
        run.claim("a20.not_evaluated", {"column": item["column"], "reason": item["reason"]}, ref)


@executor("A21")
def cross_source_consistency_investigator(run):
    _need_two_orders(run)
    result = run.ctx.tool("consistency_compare", consistency_compare, run.ctx.payload, run.ctx.second_payload)
    ref = run.put("consistency", result)
    run.claim("a21.consistency", {"matched": result["matched"], "identical": result["identical"],
                                  "differing": result["differing"], "only_in_first": result["only_in_first"],
                                  "only_in_second": result["only_in_second"],
                                  "ambiguous_first": result["first"]["ambiguous_rows"],
                                  "ambiguous_second": result["second"]["ambiguous_rows"],
                                  "compared_columns": result["compared_columns"],
                                  "not_compared": result["not_compared"]}, ref)
    for column, count in sorted(result["differing_by_column"].items()):
        run.claim("a21.column", {"column": column, "differing": count}, ref)


def _citation(item):
    """A retriever item reduced to its bounded fields, or None when it is malformed."""
    if type(item) is not dict:
        return None
    for key, limit in _CITATION_BOUNDS.items():
        if type(item.get(key)) is not str or not 1 <= len(item[key]) <= limit:
            return None
    return {key: item[key] for key in _CITATION_BOUNDS}


def _readable(entry):
    if (type(entry) is not dict or type(entry.get("run_id")) is not str or not 1 <= len(entry["run_id"]) <= 64
            or (entry.get("meta") is not None and type(entry["meta"]) is not dict)
            or any(entry.get(key) is not None and type(entry[key]) is not str for key in ("finished_at", "started_at"))):
        return False
    try:
        signature(entry)
    except (AttributeError, KeyError, TypeError, IndexError, ValueError, ArithmeticError):
        return False
    return True


def similar_history(payload, history):
    """similar.similar_runs for the current case against retained runs; unreadable runs are left out."""
    target = {"run_id": "current-case", "result": {"cases": [{"analysis": analyze_csv(payload)}]}}
    return similar_runs(target, [entry for entry in history if _readable(entry)])


@executor("A22")
def incident_similarity_knowledge(run):
    ctx = run.ctx
    if ctx.retriever is None and not ctx.history:
        raise NeedsEvidence("NO_HISTORY_OR_RETRIEVER")
    t = triage(ctx)
    checks = sorted({s["check"] for s in t["signals"]})
    columns = sorted({s["column"] for s in t["signals"] if s["column"]})
    passages = []
    if ctx.retriever is not None:
        query = " ".join(checks + columns) or "data quality incident"
        items = ctx.tool("knowledge_retrieve", ctx.retriever, query, RETRIEVE_LIMIT)
        items = items if type(items) is list else []
        kept = [c for c in (_citation(item) for item in items[:RETRIEVE_LIMIT]) if c is not None]
        ref = run.put("retrieval", {"query": query, "citations": kept, "rejected": len(items) - len(kept)})
        run.claim("a22.retrieved", {"citations": len(kept), "rejected": len(items) - len(kept)}, ref)
        passages += kept
    if ctx.history:
        matches = ctx.tool("knowledge_retrieve", similar_history, ctx.payload, ctx.history)
        found = [{"source": "run_history", "revision": m["run_id"], "citation": "run:" + m["run_id"],
                  "passage": "Shared failing checks: " + ", ".join(m["shared"])} for m in matches]
        ref = run.put("similar_runs", {"matches": matches, "citations": found})
        run.claim("a22.similar_runs", {"matches": len(matches), "scores": [m["score"] for m in matches]}, ref)
        passages += found
    passages = passages[:MAX_LIST]
    run.retrieval = {"citations": [{k: p[k] for k in ("source", "revision", "citation")} for p in passages],
                     "cache": "none"}
    run.uncertainty = ("medium", "retrieval_lexical")
    if not passages or "local_llm" not in ctx.allowed_tools:
        return
    names, cells = run.vocabulary()
    offered = []
    for number, passage in enumerate(passages, 1):
        text, source = passage["passage"][:MAX_PASSAGE], passage["source"]
        if free_text_ok(text, cells, names) and free_text_ok(source, cells, names):
            offered.append({"id": "c%d" % number, "kb_source": source, "passage": text})
    if not offered:
        return
    try:
        data, suggestion = run.ask("a22", {"checks": checks, "columns": columns, "citations": offered},
                                   relevance_schema([o["id"] for o in offered]), citations=[o["id"] for o in offered])
    except ModelFailure:
        return
    rated = data["relevance"]
    if rated:
        run.claim("a22.relevance", {"citations": bounded(sorted({r["citation"] for r in rated}))}, suggestion)
        run.advise(" ".join("%s: %s" % (r["citation"], r["sentence"]) for r in rated))
