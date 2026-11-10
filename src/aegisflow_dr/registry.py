"""Validate design metadata without pretending to execute agents."""
import json
from pathlib import Path


def load_catalog(path: Path) -> list[dict]:
    roles = json.loads(path.read_text(encoding="utf-8"))
    expected = {f"A{i:02}" for i in range(1, 37)}
    if len(roles) != 36 or {r["agent_id"] for r in roles} != expected:
        raise ValueError("Catalog must contain exactly A01-A36")
    for role in roles:
        if not all(role.get(k) for k in ("name_priority", "activation_conditions", "responsibility")):
            raise ValueError("Incomplete role definition")
        if role["implementation_status"] != "planned":
            raise ValueError("No implemented capability is claimed by this scaffold")
    return roles
