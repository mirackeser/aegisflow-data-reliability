# SPDX-License-Identifier: Apache-2.0
"""A01-A06: the control roles, as pure functions over the case intake and the results of earlier agents.

``triage`` is the case intake the binding role table describes ("triggers use the observation checks produced by
profiling.profile_csv / baseline.compare / pipeline.diagnose_csv plus case inputs"). It calls those modules
directly, once per case, because routing needs them before any specialist runs; it keeps only names, roles, counts,
flags and observation ids (no cell values). The runtime (next batch) wires these executors into a run: these
functions decide, they never start, stop or retry anything themselves.
"""
from uuid import NAMESPACE_URL, uuid5

from ...baseline import compare
from ...coordination.routing import TaskGraph
from ...hypotheses import observations_from
from ...pipeline import EXPECTED_COLUMNS, InputRejected, diagnose_csv
from ...profiling import profile_csv, read_table
from ..contracts import STATUSES
from ..registry import ROLES, role
from ._base import MAX_LIST, ModelFailure, Skip, bounded, executor
from ..prompts import planner_schema

ORDER_KEY = "order_id"
SPECIALISTS = tuple("A%02d" % n for n in range(7, 23))
REASONING = ("A23", "A24", "A25")
MAX_SPECIALISTS, MAX_WAVE = 8, 4
LIMITS = {"specialists": 8, "llm_calls": 12, "tokens": 40_000, "elapsed_ms": 90_000}
MAX_NAME = 128
NO_RETRY = frozenset({"INPUT_REJECTED", "RESULT_REJECTED", "TOOL_BUDGET_EXCEEDED"})
_PRIORITY = {"P0": 0, "P1": 1, "P2": 2}
_AGENT_IDS = frozenset(spec.agent_id for spec in ROLES)


def is_order_extract(header):
    """The order contract applies: ``order_id`` plus at least one more contract column (a renamed column still counts)."""
    return ORDER_KEY in header and sum(column in header for column in EXPECTED_COLUMNS) >= 2


def _intake(ctx):
    header, _ = read_table(ctx.payload)
    if any(len(name) > MAX_NAME for name in header):
        raise InputRejected("Column names longer than %d characters are not supported" % MAX_NAME)
    profile = profile_csv(ctx.payload)
    comparison = None if ctx.baseline is None else compare(ctx.baseline, ctx.payload, as_of=ctx.as_of)
    order = is_order_extract(header)
    second_order = False
    if ctx.second_payload is not None:
        try:
            second_order = is_order_extract(read_table(ctx.second_payload)[0])
        except InputRejected:
            second_order = False
    found = [(f["check"], f["column"]) for f in profile["findings"]]
    found += [(f["check"], f["column"]) for f in (comparison or {"findings": []})["findings"]]
    if order:
        found += [(f.check, f.column or None) for f in diagnose_csv(ctx.payload).findings]
    signals = sorted(set(found), key=lambda item: (item[0], item[1] or ""))
    observations = observations_from(comparison or {"source_sha256": profile["source_sha256"], "findings": []}, profile)
    return {
        "records": profile["records"],
        "columns": [{"name": c["name"], "role": c["role"]} for c in profile["columns"]],
        "time_column": profile["time_column"], "order_extract": order, "baseline": comparison is not None,
        "second_payload": ctx.second_payload is not None, "second_order_extract": second_order,
        "retriever": ctx.retriever is not None, "history": bool(ctx.history),
        "signals": [{"id": "sig-%d" % number, "check": check, "column": column}
                    for number, (check, column) in enumerate(signals, 1)],
        "observations": [{key: o[key] for key in ("id", "source", "check", "column", "direction")} for o in observations],
        "type_mismatch": any(f["check"] == "type_mismatch" for f in profile["findings"]),
        "role_change": any(f["check"] == "role_change" for f in (comparison or {"findings": []})["findings"]),
    }


def triage(ctx):
    """The case intake (memoised per case). Raises InputRejected for an unreadable payload or a tampered baseline."""
    return ctx.remember("triage", lambda: _intake(ctx))


# agent -> (trigger over the intake, reason when met, reason when not met); see the binding role table.
TRIGGERS = {
    "A07": (lambda t: t["history"], "history_given", "no_history"),
    "A08": (lambda t: t["baseline"], "baseline_given", "no_baseline"),
    "A09": (lambda t: t["order_extract"], "order_extract", "not_order_extract"),
    "A10": (lambda t: True, "first_specialist", "never"),
    "A11": (lambda t: t["baseline"], "baseline_given", "no_baseline"),
    "A12": (lambda t: False, "never", "no_log_source"),
    "A13": (lambda t: t["order_extract"], "order_extract", "not_order_extract"),
    "A14": (lambda t: t["order_extract"], "order_extract", "not_order_extract"),
    "A15": (lambda t: t["time_column"] is not None, "time_column_present", "no_time_column"),
    "A16": (lambda t: False, "never", "no_cdc_source"),
    "A17": (lambda t: t["type_mismatch"] or t["role_change"], "type_signal", "no_type_signal"),
    "A18": (lambda t: t["order_extract"] and t["second_order_extract"], "two_order_extracts", "no_second_order_extract"),
    "A19": (lambda t: t["order_extract"], "order_extract", "not_order_extract"),
    "A20": (lambda t: t["baseline"], "baseline_given", "no_baseline"),
    "A21": (lambda t: t["order_extract"] and t["second_order_extract"], "two_order_extracts", "no_second_order_extract"),
    "A22": (lambda t: t["retriever"] or t["history"], "knowledge_source_given", "no_history_or_retriever"),
    "A23": (lambda t: bool(t["observations"]), "observations_exist", "no_observations"),
    "A24": (lambda t: t["baseline"] and bool(t["observations"]), "baseline_and_observations", "no_baseline_or_observations"),
    "A25": (lambda t: t["baseline"] and bool(t["observations"]), "baseline_and_observations", "no_baseline_or_observations"),
}


def route(t):
    """Specialists (A07-A22, at most 8: A10 first, then catalog priority, then id) and reasoning roles A23-A25."""
    triggered = [a for a in SPECIALISTS if TRIGGERS[a][0](t)]
    ordered = sorted(triggered, key=lambda a: (a != "A10", _PRIORITY[role(a).priority], a))
    kept = set(ordered[:MAX_SPECIALISTS])
    selected, skipped = [], []
    for agent in SPECIALISTS + REASONING:
        met, yes, no = TRIGGERS[agent]
        if agent in kept or (agent in REASONING and met(t)):
            selected.append({"agent": agent, "reason": yes})
        else:
            skipped.append({"agent": agent, "reason": "specialist_limit" if agent in triggered else no})
    selected.sort(key=lambda item: (item["agent"] != "A10", item["agent"]))
    return {"selected": selected, "skipped": skipped, "dropped": [a for a in ordered[MAX_SPECIALISTS:]]}


def _graph(agents, depends, case_id):
    ids = {"incident_id": str(uuid5(NAMESPACE_URL, "aegisflow:case:" + case_id)),
           "run_id": str(uuid5(NAMESPACE_URL, "aegisflow:plan:" + case_id))}
    tasks = [{"version": "1", "task_id": agent, **ids, "capability": "evidence.read", "required_tags": ["read-only"],
              "depends_on": [d for d in depends(agent) if d in agents]} for agent in agents]
    graph, done, waves = TaskGraph(tasks), frozenset(), []
    while len(done) < len(agents):
        wave = list(graph.ready(done)[:MAX_WAVE])
        waves.append(wave)
        done |= frozenset(wave)
    return waves


def plan_waves(selected, case_id):
    """Dependency waves of at most 4: specialists (every one after A10), then the reasoning roles.

    Uses ``coordination.routing.TaskGraph`` for validation, cycle detection and ready sets; its host worker
    assignment (A26 for read-only evidence work) is not used here.
    """
    specialists = [a for a in selected if a in SPECIALISTS]
    reasoning = [a for a in selected if a in REASONING]
    stages = []
    if specialists:
        stages += [("specialists", w) for w in _graph(specialists, lambda a: () if a == "A10" else ("A10",), case_id)]
    if reasoning:
        stages += [("reasoning", w) for w in _graph(reasoning, lambda a: (), case_id)]
    return stages


def _statuses(prior):
    return {agent: result["status"] for agent, result in sorted(prior.items())
            if agent in _AGENT_IDS and type(result) is dict and result.get("status") in STATUSES}


def _usage(result, key):
    usage = result.get("usage")
    value = usage.get(key) if type(usage) is dict else None
    return value if type(value) is int and value >= 0 else 0


def budget_usage(prior, elapsed_ms):
    """Run usage against the per-run limits; ``exceeded`` names every limit above its maximum."""
    results = [r for a, r in sorted(prior.items()) if a in _AGENT_IDS and type(r) is dict]
    used = {"specialists": sum(r.get("agent_id") in SPECIALISTS and r.get("status") not in ("SKIPPED", None)
                               for r in results),
            "llm_calls": sum(_usage(r, "llm_calls") for r in results),
            "tokens": sum(_usage(r, "tokens_in") + _usage(r, "tokens_out") for r in results),
            "elapsed_ms": elapsed_ms}
    return used, [name for name in LIMITS if used[name] > LIMITS[name]]


@executor("A01")
def global_supervisor(run):
    statuses = _statuses(run.ctx.prior)
    counts = {status.lower(): sum(s == status for s in statuses.values()) for status in STATUSES}
    final = ("failed_agents" if counts["failed"] else
             "completed_with_gaps" if counts["needs_evidence"] or counts["policy_denied"] else "completed")
    ref = run.put("run_summary", {"case_id": run.ctx.case_id, "statuses": statuses, "final": final})
    run.claim("a01.run_status", {"agents": len(statuses), **counts, "final": final}, ref)


def _goal_refs(signal, observations):
    """The signal's id plus every observation of the same check and column."""
    return [signal["id"]] + [o["id"] for o in observations
                             if o["check"] == signal["check"] and o["column"] == signal["column"]]


def known_ids(t):
    """Every signal and observation id of the case intake."""
    return {s["id"] for s in t["signals"]} | {o["id"] for o in t["observations"]}


def unmapped(items, goal_ids, known):
    """True when any goal or worded question lacks a known goal id or rests on no, or an unknown, signal/observation."""
    return any(item.get("goal", item.get("id")) not in goal_ids or type(item.get("refs")) is not list
               or not item["refs"] or not set(item["refs"]) <= known for item in items)


@executor("A02")
def investigation_planner(run):
    t = triage(run.ctx)
    known = known_ids(t)
    goals = [{"id": "g%d" % n, "check": s["check"], "column": s["column"], "refs": _goal_refs(s, t["observations"])}
             for n, s in enumerate(t["signals"][:MAX_LIST], 1)]
    goal_ids = [g["id"] for g in goals]
    if unmapped(goals, goal_ids, known):  # the role table: every goal maps to the intake's evidence
        raise InputRejected("Plan goal does not map to a signal or observation")
    ref = run.put("investigation_plan", {"goals": goals, "observations": [o["id"] for o in t["observations"]]})
    run.claim("a02.plan", {"goals": len(goals), "checks": bounded(sorted({g["check"] for g in goals}))}, ref)
    if not goals or "local_llm" not in run.ctx.allowed_tools:
        return
    try:
        data, suggestion = run.ask("a02", {"goals": goals}, planner_schema(goal_ids, sorted(known)), goals=goals)
        if unmapped(data["questions"], goal_ids, known):
            raise ModelFailure("UNMAPPED_GOAL")
    except ModelFailure:
        # Per the role table the fallback is the rule plan with llm null; the attempted call stays in usage and its
        # context stays in the evidence store, so budgets and the A34 review still see it. Rejected wording is
        # never cited by a claim.
        run.llm = run.retrieval = run.advisory = None
        run.uncertainty = ("medium", "rule_plan_only")
        return
    questions = data["questions"]
    run.uncertainty = ("medium", "model_wording_advisory")
    if questions:
        run.claim("a02.worded", {"goals": bounded(sorted({q["goal"] for q in questions}))}, suggestion)
        run.advise(" ".join("%s: %s" % (q["goal"], q["question"]) for q in questions))


@executor("A03")
def dynamic_agent_router(run):
    routing = route(triage(run.ctx))
    ref = run.put("routing", routing)
    run.claim("a03.selected", {"selected": [s["agent"] for s in routing["selected"]],
                               "skipped": bounded([s["agent"] for s in routing["skipped"]]),
                               "dropped": routing["dropped"], "limit": MAX_SPECIALISTS}, ref)
    for item in routing["selected"][:MAX_LIST]:
        run.claim("a03.reason", {"agent": item["agent"], "reason": item["reason"]}, ref)


@executor("A04")
def dependency_planner(run):
    routing_ref, routing = run.prior_evidence("A03", "routing")
    if routing is None:
        routing = route(triage(run.ctx))
        routing_ref = run.put("routing", routing)
    stages = plan_waves([s["agent"] for s in routing["selected"]], run.ctx.case_id)
    ref = run.put("wave_plan", {"stages": [{"stage": stage, "agents": wave} for stage, wave in stages],
                                "max_wave": MAX_WAVE})
    run.claim("a04.plan", {"waves": len(stages), "max_wave": MAX_WAVE}, ref, routing_ref)
    for number, (stage, wave) in enumerate(stages, 1):
        run.claim("a04.wave", {"wave": number, "stage": stage, "agents": wave}, ref)


@executor("A05")
def budget_controller(run):
    used, exceeded = budget_usage(run.ctx.prior, run.ctx.elapsed_ms())
    ref = run.put("budget_check", {"used": used, "limits": LIMITS, "exceeded": exceeded})
    params = {**{"used_" + k: v for k, v in used.items()}, **{"limit_" + k: v for k, v in LIMITS.items()},
              "exceeded": exceeded}
    run.claim("a05.budget_exceeded" if exceeded else "a05.within_budget", params, ref)


@executor("A06")
def recovery_coordinator(run):
    statuses = _statuses(run.ctx.prior)
    failed = [a for a, s in statuses.items() if s == "FAILED"]
    if not failed:
        raise Skip("NO_FAILED_AGENT")
    decisions = []
    for agent in failed:
        code = run.ctx.prior[agent].get("error_code")
        code = code if type(code) is str else None
        decisions.append({"agent": agent, "error_code": code,
                          "decision": "safe_stop" if code in NO_RETRY else "retry_once_same_input"})
    denied = [a for a, s in statuses.items() if s == "POLICY_DENIED"]
    ref = run.put("recovery_decision", {"decisions": decisions, "no_retry_policy_denied": denied})
    for item in decisions[:MAX_LIST]:
        run.claim("a06.decision", {"agent": item["agent"], "decision": item["decision"], "error_code": item["error_code"]},
                  ref)
    if denied:
        run.claim("a06.no_retry", {"agents": bounded(denied), "reason": "policy_denied"}, ref)
