# SPDX-License-Identifier: Apache-2.0
"""A33-A36: approval request, the A34 policy review, the usage roll-up and the evaluation record.

A33 only records a pending approval item: no proposal is executed and no human decision is simulated. A34 re-checks
every model context recorded in this run (and the observation context the model roles use) against the context rule,
and every earlier result against its role's tool allowlist.
"""
from ...pipeline import InputRejected
from ..contracts import STATUSES
from ..prompts import safe_context
from ..registry import ROLES, role
from ._base import Skip, bounded, executor
from ..context import PolicyDenied
from .orchestration import triage

_AGENT_IDS = frozenset(spec.agent_id for spec in ROLES)
USAGE_KEYS = ("tool_calls", "llm_calls", "tokens_in", "tokens_out", "latency_ms")


def _results(prior):
    return [(agent, result) for agent, result in sorted(prior.items())
            if agent in _AGENT_IDS and type(result) is dict and result.get("status") in STATUSES]


@executor("A33")
def human_approval(run):
    items = [{"agent": agent, "text_key": action["text_key"], "params": action["params"]}
             for agent, result in _results(run.ctx.prior) if result["status"] == "COMPLETED"
             for action in result.get("proposed_actions") or []]
    if not items:
        raise Skip("NO_PROPOSALS")
    ref = run.put("approval_request", {"case_id": run.ctx.case_id, "items": items, "decision": "pending",
                                       "executed": False})
    run.claim("a33.pending_approval", {"proposals": len(items), "agents": bounded(sorted({i["agent"] for i in items})),
                                       "decision": "pending"}, ref)


@executor("A34")
def policy_access_reviewer(run):
    ctx = run.ctx
    header, cells = run.vocabulary()
    t = triage(ctx)
    contexts = [{"observations": t["observations"], "signals": t["signals"]}]
    contexts += [ctx.evidence.get(ref)["context"] for ref in ctx.evidence.refs("llm_context")]
    for context in contexts:
        try:
            safe_context(context, header=header, cells=cells)
        except InputRejected:
            raise PolicyDenied("RAW_VALUE_IN_CONTEXT") from None
    results = _results(ctx.prior)
    for agent, result in results:
        tools = role(agent).allowed_tools
        usage = result.get("usage") if type(result.get("usage")) is dict else {}
        if (result.get("llm") is not None and "local_llm" not in tools) or (usage.get("tool_calls") and not tools):
            raise PolicyDenied("TOOL_NOT_ALLOWED")
    ref = run.put("policy_review", {"contexts_checked": len(contexts), "results_checked": [a for a, _ in results],
                                    "rule": "aggregates_ids_column_names_only"})
    run.claim("a34.reviewed", {"contexts": len(contexts), "results": len(results), "denied": 0}, ref)


def _count(usage, key):
    value = usage.get(key)
    return value if type(value) is int and value >= 0 else 0


@executor("A35")
def agentops_cost(run):
    rows = []
    for agent, result in _results(run.ctx.prior):
        usage = result.get("usage") if type(result.get("usage")) is dict else {}
        rows.append({"agent": agent, "status": result["status"], **{k: _count(usage, k) for k in USAGE_KEYS}})
    totals = {k: sum(r[k] for r in rows) for k in USAGE_KEYS}
    ref = run.put("usage_rollup", {"agents": rows, "totals": totals, "external_spend_usd": 0})
    run.claim("a35.usage", {"agents": len(rows), **totals}, ref)
    for row in rows[:30]:
        run.claim("a35.agent", {"agent": row["agent"], **{k: row[k] for k in USAGE_KEYS}}, ref)


@executor("A36")
def evaluation_curator(run):
    results = _results(run.ctx.prior)
    statuses = {agent: result["status"] for agent, result in results}
    judge_ref, verdict = run.prior_evidence("A27", "judge_verdict")
    judged = None
    if verdict is not None:
        judged = {name: sum(v["verdict"] == name for v in verdict["verdicts"]) for name in ("accepted", "advisory",
                                                                                           "rejected")}
    record = {"case_id": run.ctx.case_id, "selected": [a for a, s in statuses.items() if s != "SKIPPED"],
              "statuses": statuses, "judge": judged, "labels": {"cases": "synthetic_or_simulated_unless_stated"}}
    ref = run.put("evaluation_record", record)
    refs = [ref] + ([judge_ref] if judge_ref else [])
    run.claim("a36.recorded", {"agents": len(statuses), "selected": len(record["selected"]),
                               **{"judge_" + name: None if judged is None else judged[name]
                                  for name in ("accepted", "advisory", "rejected")}}, *refs)

