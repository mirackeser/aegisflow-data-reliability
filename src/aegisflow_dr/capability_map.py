# SPDX-License-Identifier: Apache-2.0
"""Which of the 36 design-catalog roles correspond to code that really exists.

The catalog is a design catalog: every role there is ``planned``. This map states, per role, how much of
it a deterministic capability in this repository covers, and names the code that does it so a test can
confirm the code is there. Nothing here is an autonomous agent or a model call.
"""
from __future__ import annotations

import importlib
import json
from importlib.resources import files

STATUSES = ("implemented", "partial", "unavailable", "disabled", "planned")

# role -> (status, "module:attribute" evidence anchors). Roles absent from this table are planned.
COVERAGE: dict[str, tuple[str, tuple[str, ...]]] = {
    "A07": ("partial", ("apps/local/workbench.py:Workbench.snapshot",)),
    "A08": ("partial", ("aegisflow_dr.monitoring:monitor",)),
    "A09": ("implemented", ("aegisflow_dr.pipeline:diagnose_csv",)),
    "A10": ("implemented", ("aegisflow_dr.analysis:discover_schema", "aegisflow_dr.analysis:analyze_csv")),
    "A11": ("partial", ("aegisflow_dr.monitoring:monitor", "aegisflow_dr.baseline:compare")),
    "A13": ("implemented", ("aegisflow_dr.batch:downstream",)),
    "A17": ("partial", ("aegisflow_dr.analysis:record_issues",)),
    "A18": ("implemented", ("aegisflow_dr.cardinality:join_cardinality",)),
    "A19": ("implemented", ("aegisflow_dr.batch:run_batch",)),
    "A20": ("partial", ("aegisflow_dr.monitoring:monitor", "aegisflow_dr.baseline:compare")),
    "A21": ("implemented", ("aegisflow_dr.consistency:compare",)),
    "A22": ("partial", ("aegisflow_dr.similar:similar_runs",)),
    "A23": ("unavailable", ()),
    "A26": ("implemented", ("aegisflow_dr.storage.store:IncidentStore",)),
    "A27": ("implemented", ("aegisflow_dr.coordination.judge:review",)),
    "A29": ("disabled", ()),
    "A33": ("implemented", ("apps/local/workbench.py:Workbench.review",)),
    "A36": ("partial", ("aegisflow_dr.check_evaluation:evaluate",)),
}


def _roles() -> list[dict]:
    return json.loads(files("aegisflow_dr").joinpath("data/agent-catalog.json").read_text("utf-8"))


def capability_map() -> dict:
    roles = []
    for role in _roles():
        status, anchors = COVERAGE.get(role["agent_id"], ("planned", ()))
        name, priority = role["name_priority"].split(" · ")
        roles.append({"agent_id": role["agent_id"], "name": name, "priority": priority, "status": status,
                      "implemented_by": list(anchors)})
    counts = {status: sum(1 for r in roles if r["status"] == status) for status in STATUSES}
    return {"total": len(roles), "counts": counts, "roles": roles}


def resolve(anchor: str):
    """Import ``module:attribute`` (dotted attributes allowed); raises if the named code is missing."""
    module, attribute = anchor.split(":")
    target = importlib.import_module(module)
    for part in attribute.split("."):
        target = getattr(target, part)
    return target
