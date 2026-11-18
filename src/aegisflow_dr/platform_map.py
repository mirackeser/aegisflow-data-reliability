# SPDX-License-Identifier: Apache-2.0
"""What exists, and what does not, for the ten platform components the project committed to.

Each component states its real status, the code that backs the claim (a test imports every anchor) and the
tests that exercise it. ``live`` is true only if the component talks to a real external service; today none
does. Nothing here measures model accuracy, because no model has been run.
"""
from __future__ import annotations

STATUSES = ("implemented", "partial", "not_implemented")

COMPONENTS = (
    {"id": "MCP", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.integration.mcp_tools:LocalToolSession",), "tests": ("tests/test_mcp.py",)},
    {"id": "A2A", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.integration.a2a_client:VerifiedA2AHTTPTransport", "aegisflow_dr.integration.a2a_profile:handle_send"),
     "tests": ("tests/test_a2a.py",)},
    {"id": "LLM", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.advisory.dispatch:dispatch", "aegisflow_dr.advisory.usage:UsageLedger"),
     "tests": ("tests/test_advisory.py", "tests/test_dispatch.py", "tests/test_usage.py")},
    {"id": "RAG", "status": "partial", "live": False,
     "anchors": ("apps/local/knowledge.py:Knowledge.retrieve",), "tests": ("apps/local/test_knowledge.py", "apps/local/test_retrieval_eval.py")},
    {"id": "CAG", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.advisory.context_cache:ContextCache",), "tests": ("tests/test_context_cache.py", "tests/test_context.py")},
    {"id": "CONTRACTS", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.coordination.contracts:parse", "aegisflow_dr.advisory.contracts:decode", "aegisflow_dr.pipeline:diagnose_csv"),
     "tests": ("tests/test_coordination.py", "tests/test_pipeline.py")},
    {"id": "CERTIFICATES", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.security.mtls:server_context", "aegisflow_dr.security.policy:AccessPolicy"),
     "tests": ("tests/test_a2a.py", "tests/test_security_adversarial.py")},
    {"id": "TAG", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.coordination.routing:TaskGraph",), "tests": ("tests/test_routing.py",)},
    {"id": "CONNECTIONS", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.connectors:SourceCatalog", "aegisflow_dr.gateway:ToolGateway"),
     "tests": ("tests/test_connectors.py", "tests/test_gateway.py")},
    {"id": "JUDGE", "status": "partial", "live": False,
     "anchors": ("aegisflow_dr.coordination.judge:review",), "tests": ("tests/test_coordination.py",)},
)


def platform_map() -> dict:
    counts = {status: sum(1 for c in COMPONENTS if c["status"] == status) for status in STATUSES}
    return {"total": len(COMPONENTS), "counts": counts, "live": sum(1 for c in COMPONENTS if c["live"]),
            "components": [{"id": c["id"], "status": c["status"], "live": c["live"],
                            "implemented_by": list(c["anchors"]), "tests": list(c["tests"])} for c in COMPONENTS]}
