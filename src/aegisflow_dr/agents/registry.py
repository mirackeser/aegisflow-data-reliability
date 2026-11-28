# SPDX-License-Identifier: Apache-2.0
"""The 36 catalog roles as frozen specs: catalog name and priority plus the binding role table.

Names and priorities come from ``data/agent-catalog.json``; kind, tools, executor and trigger summary are written
here by hand from docs/superpowers/specs/2026-11-24-agent-runtime-roles.md. An executor reference is a
``module:function`` string under ``aegisflow_dr.agents.executors``; it is resolved by the runtime, not here.
A role listed here is a contract, not a claim that it runs on every case (the router selects specialists).
"""
from dataclasses import dataclass
from importlib.resources import files
import json

from ..pipeline import InputRejected

KINDS = ("control", "rule", "llm", "hybrid")
LAYERS = ("orchestration", "specialists", "reasoning", "remediation", "governance")
_LAYER_BOUNDS = ((6, "orchestration"), (22, "specialists"), (28, "reasoning"), (32, "remediation"), (36, "governance"))
TOOLS = frozenset({"run_history", "schema_diff", "diagnose_csv", "profile_csv", "baseline_compare", "query_lineage",
                   "run_batch", "join_cardinality", "consistency_compare", "knowledge_retrieve", "investigate_hypotheses",
                   "local_llm"})
_SEPARATOR = " · "


@dataclass(frozen=True)
class RoleSpec:
    agent_id: str
    name: str
    priority: str
    kind: str
    layer: str
    allowed_tools: tuple
    executor_ref: str
    trigger_summary: str


# agent_id -> (kind, allowed tools, executor function, trigger summary); see the binding role table.
_TABLE = {
    "A01": ("control", (), "global_supervisor", "always: opens and closes the run"),
    "A02": ("hybrid", ("local_llm",), "investigation_planner", "always: rule plan, optional model wording of goals"),
    "A03": ("control", (), "dynamic_agent_router", "always: selects at most 8 specialists by trigger rules"),
    "A04": ("control", (), "dependency_planner", "always: dependency DAG into waves of at most 4"),
    "A05": ("control", (), "budget_controller", "always: enforces run budgets"),
    "A06": ("control", (), "recovery_coordinator", "after any FAILED agent"),
    "A07": ("rule", ("run_history",), "pipeline_run_explorer", "run history given"),
    "A08": ("rule", ("schema_diff",), "schema_drift_investigator", "baseline given"),
    "A09": ("rule", ("diagnose_csv",), "data_contract_inspector", "header matches the order contract"),
    "A10": ("rule", ("profile_csv",), "data_profiling_specialist", "always the first specialist"),
    "A11": ("rule", ("baseline_compare",), "freshness_volume_analyst", "baseline given"),
    "A12": ("rule", (), "log_trace_analyst", "only if logs are provided (none are connected)"),
    "A13": ("rule", ("query_lineage",), "lineage_impact_investigator", "order extract"),
    "A14": ("rule", ("run_batch",), "sql_transformation_analyst", "order extract"),
    "A15": ("rule", ("profile_csv",), "incremental_load_investigator", "time column present"),
    "A16": ("rule", (), "cdc_replication_investigator", "only if a CDC stream is provided (none is connected)"),
    "A17": ("rule", ("profile_csv", "baseline_compare"), "type_casting_investigator",
            "type mismatch in the profile or a schema role change"),
    "A18": ("rule", ("join_cardinality",), "join_cardinality_investigator",
            "second extract given and both are order extracts"),
    "A19": ("rule", ("run_batch",), "reconciliation_investigator", "order extract"),
    "A20": ("rule", ("baseline_compare",), "statistical_drift_investigator", "baseline given"),
    "A21": ("rule", ("consistency_compare",), "cross_source_consistency_investigator",
            "second extract given and both are order extracts"),
    "A22": ("hybrid", ("knowledge_retrieve", "local_llm"), "incident_similarity_knowledge",
            "retriever or run history given"),
    "A23": ("llm", ("local_llm",), "hypothesis_generator", "observations exist"),
    "A24": ("rule", ("investigate_hypotheses",), "counter_hypothesis", "baseline given and observations exist"),
    "A25": ("rule", ("investigate_hypotheses",), "active_probe_planner", "baseline given and observations exist"),
    "A26": ("control", (), "evidence_collector", "always: stores results and input digests"),
    "A27": ("control", (), "evidence_verification", "always: the Judge checks every claim's evidence"),
    "A28": ("rule", ("investigate_hypotheses",), "ranking_uncertainty_reviewer", "A24 ran"),
    "A29": ("llm", ("local_llm",), "remediation_strategy_planner", "accepted findings exist"),
    "A30": ("llm", ("local_llm",), "patch_proposal", "A29 produced options and the case is an order extract"),
    "A31": ("rule", ("profile_csv", "diagnose_csv"), "sandbox_validation", "A30 produced a proposal"),
    "A32": ("rule", (), "regression_backfill_validator", "A30 produced a proposal"),
    "A33": ("control", (), "human_approval", "proposals exist"),
    "A34": ("control", (), "policy_access_reviewer", "always, before any model call"),
    "A35": ("control", (), "agentops_cost", "always, at the end"),
    "A36": ("control", (), "evaluation_curator", "always, at the end"),
}


def _layer(agent_id):
    number = int(agent_id[1:])
    return next(layer for bound, layer in _LAYER_BOUNDS if number <= bound)


def _build(entries):
    if [entry.get("agent_id") for entry in entries] != list(_TABLE):
        raise InputRejected("Agent catalog does not match the role table")
    roles = []
    for entry in entries:
        name, separator, priority = entry["name_priority"].rpartition(_SEPARATOR)
        if not separator:
            raise InputRejected("Agent catalog does not match the role table")
        agent_id = entry["agent_id"]
        kind, tools, function, trigger = _TABLE[agent_id]
        layer = _layer(agent_id)
        roles.append(RoleSpec(agent_id, name, priority, kind, layer, tools,
                              "aegisflow_dr.agents.executors.%s:%s" % (layer, function), trigger))
    return tuple(roles)


ROLES = _build(json.loads(files("aegisflow_dr").joinpath("data", "agent-catalog.json").read_text(encoding="utf-8")))
_BY_ID = {spec.agent_id: spec for spec in ROLES}


def role(agent_id):
    """Return the spec for ``agent_id`` (A01..A36); raise InputRejected for anything else."""
    if type(agent_id) is not str or agent_id not in _BY_ID:
        raise InputRejected("Unknown agent role")
    return _BY_ID[agent_id]
