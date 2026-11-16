# SPDX-License-Identifier: Apache-2.0
"""Describe which capabilities actually ran, which were skipped and why.

The plan is derived from the executed tool trace and the verification outcome, never from the
design catalog alone. Role identifiers name the design-catalog role a deterministic capability
corresponds to; they do not mean an autonomous agent or a model call took place.
"""
from __future__ import annotations

import json
from importlib.resources import files

STATUSES = ("completed", "skipped", "awaiting", "unavailable", "disabled", "rejected")


def _names() -> dict[str, str]:
    catalog = json.loads(files("aegisflow_dr").joinpath("data/agent-catalog.json").read_text("utf-8"))
    return {role["agent_id"]: role["name_priority"].split(" · ")[0] for role in catalog}


def build_plan(*, tools_run: frozenset[str] | set[str], source_failed: bool, profiled: bool,
               has_actions: bool, judge_decision: str | None, retained: bool) -> list[dict]:
    """Return ordered capability steps with dependencies and explicit reason codes."""
    names = _names()

    def step(step_id: str, role: str, capability: str, depends_on: list[str], status: str,
             reason: str | None = None) -> dict:
        return {"id": step_id, "role": role, "role_name": names[role], "capability": capability,
                "depends_on": depends_on, "status": status, "reason": reason,
                "mode": "deterministic" if status in ("completed", "skipped", "rejected") else "planned"}

    contract = "completed" if "diagnose_csv" in tools_run else "skipped"
    batch = ("completed" if "run_batch" in tools_run
             else "skipped")
    verification = ("rejected" if judge_decision not in (None, "ACCEPT")
                    else "completed" if judge_decision == "ACCEPT" else "skipped")
    return [
        step("contract_check", "A09", "diagnose_csv", [], contract,
             None if contract == "completed" else "NOT_EXECUTED"),
        step("profiling", "A10", "profile_orders", ["contract_check"],
             "completed" if profiled else "skipped", None if profiled else "NO_FILE_PROFILE_FOR_EXAMPLE"),
        step("reconciliation", "A19", "run_batch", ["contract_check"], batch,
             None if batch == "completed" else "SOURCE_QUALITY_FAILURE" if source_failed else "NOT_EXECUTED"),
        step("impact", "A13", "query_lineage", ["contract_check"],
             "completed" if "query_lineage" in tools_run else "skipped",
             None if "query_lineage" in tools_run else "NOT_EXECUTED"),
        step("evidence", "A26", "read_retained_evidence", ["contract_check", "profiling"],
             "completed" if retained else "skipped", None if retained else "NO_RETAINED_RUN"),
        step("verification", "A27", "verify_independently", ["evidence"], verification,
             None if verification == "completed" else "VERIFICATION_REJECTED" if verification == "rejected"
             else "NO_VERIFICATION"),
        step("human_review", "A33", "human_review", ["verification"],
             "awaiting" if has_actions else "skipped", None if has_actions else "NO_ACTIONS_PROPOSED"),
        step("root_cause", "A23", "infer_root_cause", ["verification"], "unavailable", "NO_MODEL_CONFIGURED"),
        step("remediation", "A29", "apply_remediation", ["human_review"], "disabled", "READ_ONLY_POLICY"),
    ]
