# SPDX-License-Identifier: Apache-2.0
"""Aggregates over retained, digest-verified agent run records, and a live check of the local model.

Every number comes from the records passed in (their results, Judge verdicts, approvals and ``llm_call`` events); none
is estimated. Percentiles are nearest-rank over the observed values and are None when nothing was observed. The model
check only asks the loopback Ollama endpoint for its model list with a short timeout; it never sends a prompt.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.agents.registry import LAYERS, ROLES

STATUSES = ("COMPLETED", "NEEDS_EVIDENCE", "POLICY_DENIED", "SKIPPED", "FAILED")
RECENT, TOP_FINDINGS = 20, 10
MODEL_HOST, MODEL_PORT, MODEL_TIMEOUT_S, MAX_TAGS_BYTES = "127.0.0.1", 11434, 1.0, 1_000_000
_LAYER = {spec.agent_id: spec.layer for spec in ROLES}


def percentile(values, share):
    """Nearest-rank percentile of ``values`` (None when empty)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def _claim_key(record, agent, index):
    result = next((a["result"] for a in record["agents"] if a["agent_id"] == agent), None)
    claims = (result or {}).get("claims") or []
    return claims[index]["text_key"] if type(index) is int and 0 <= index < len(claims) else None


def summarize(runs):
    """Aggregates over ``runs``: a list of (record, decisions) pairs, oldest first."""
    statuses, layers = Counter(), {layer: Counter() for layer in LAYERS}
    judge, findings, durations, recent, pending = Counter(), Counter(), [], [], []
    llm, agents_status = {}, Counter()
    for record, decisions in runs:
        statuses[record["status"]] += 1
        durations.append(record["duration_ms"])
        for agent in record["agents"]:
            layers[_LAYER[agent["agent_id"]]][agent["result"]["status"]] += 1
            agents_status[agent["result"]["status"]] += 1
        for verdict in record["judge"]["verdicts"]:
            judge[verdict["verdict"]] += 1
        for finding in record["judge"]["accepted_findings"]:
            key = _claim_key(record, finding["agent"], finding["claim"])
            if key:
                findings[(finding["agent"], key)] += 1
        for event in record["events"]:
            if event["type"] == "llm_call":
                row = llm.setdefault(event["agent_id"], {"calls": 0, "ok": 0, "latencies": [], "tokens_in": 0,
                                                         "tokens_out": 0, "cache_hits": 0, "errors": Counter()})
                data = event["data"]
                row["calls"] += 1
                row["ok"] += data["ok"]
                row["latencies"].append(data["latency_ms"])
                row["tokens_in"] += data["tokens_in"]
                row["tokens_out"] += data["tokens_out"]
                row["cache_hits"] += data["cache"] == "hit"
                if data["error_code"]:
                    row["errors"][data["error_code"]] += 1
        items = (record["approvals"][0]["items"] if record["approvals"] else [])
        undecided = [i for i in range(len(items)) if str(i) not in decisions]
        if undecided:
            pending.append({"run_id": record["run_id"], "items": len(items), "undecided": len(undecided)})
        recent.append({"run_id": record["run_id"], "started_at": record["started_at"], "status": record["status"],
                       "duration_ms": record["duration_ms"],
                       "selected": sum(row["selected"] for row in record["selection"]),
                       "accepted_findings": len(record["judge"]["accepted_findings"]),
                       "approvals": len(items), "undecided": len(undecided),
                       "llm_calls": record["usage"]["totals"]["llm_calls"]})
    latencies = [v for row in llm.values() for v in row["latencies"]]
    verdicts = sum(judge.values())
    return {
        "runs": len(runs), "source": "retained_agent_run_records",
        "statuses": dict(sorted(statuses.items())),
        "agents": {status: agents_status[status] for status in STATUSES},
        "layers": {layer: {status: counts[status] for status in STATUSES} for layer, counts in layers.items()},
        "judge": {"accepted": judge["accepted"], "advisory": judge["advisory"], "rejected": judge["rejected"],
                  "verdicts": verdicts, "acceptance": judge["accepted"] / verdicts if verdicts else None},
        "llm": {"calls": sum(r["calls"] for r in llm.values()), "ok": sum(r["ok"] for r in llm.values()),
                "tokens_in": sum(r["tokens_in"] for r in llm.values()),
                "tokens_out": sum(r["tokens_out"] for r in llm.values()),
                "latency_p50_ms": percentile(latencies, 0.5), "latency_p95_ms": percentile(latencies, 0.95),
                "per_agent": {agent: {"calls": r["calls"], "ok": r["ok"], "tokens_in": r["tokens_in"],
                                      "tokens_out": r["tokens_out"], "cache_hits": r["cache_hits"],
                                      "latency_p50_ms": percentile(r["latencies"], 0.5),
                                      "latency_p95_ms": percentile(r["latencies"], 0.95),
                                      "errors": dict(sorted(r["errors"].items()))}
                              for agent, r in sorted(llm.items())}},
        "durations": {"p50_ms": percentile(durations, 0.5), "p95_ms": percentile(durations, 0.95),
                      "last": [{"run_id": r["run_id"], "duration_ms": r["duration_ms"], "status": r["status"]}
                               for r in recent[-RECENT:]]},
        "top_findings": [{"agent": agent, "text_key": key, "runs": count}
                         for (agent, key), count in sorted(findings.items(), key=lambda x: (-x[1], x[0]))[:TOP_FINDINGS]],
        "pending_approvals": pending[::-1],
        "recent": recent[::-1][:RECENT],
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _fetch(url, timeout):
    with _OPENER.open(Request(url, method="GET"), timeout=timeout) as response:
        return response.read(MAX_TAGS_BYTES + 1)


def model_status(fetch=_fetch, *, model=None, timeout=MODEL_TIMEOUT_S):
    """Whether the local model endpoint on 127.0.0.1:11434 answers, and whether the configured model is listed."""
    model = model or LocalModel().model
    status = {"host": MODEL_HOST, "port": MODEL_PORT, "model": model, "reachable": False, "model_listed": None,
              "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        raw = fetch("http://%s:%d/api/tags" % (MODEL_HOST, MODEL_PORT), timeout)
    except Exception:  # refused, timed out, redirected or any transport failure: not reachable
        return status
    status["reachable"] = True
    try:
        if type(raw) is not bytes or len(raw) > MAX_TAGS_BYTES:
            raise ValueError("response")
        names = [item["name"] for item in json.loads(raw)["models"]]
        status["model_listed"] = model in names
    except (ValueError, TypeError, KeyError):
        pass  # it answered, but not with a readable model list
    return status
