# Current layer ownership

The original six-layer architecture is a target. This page records implemented boundaries after increment 15; archived architecture/catalog text is preserved separately.

- **L1 — Presentation and investigation:** `apps/web` is planned. No product UI or continuous authenticated agent dashboard exists.
- **L2 — Integration and observability:** `integration` supplies official local MCP tools, stateless A2A review and private read-only HTTPS adapters. Synthetic CSV input is working; real pipeline/database/log connectors, deployed protocol servers and production telemetry remain planned.
- **L3 — Quality and diagnostics:** `pipeline.py` and `batch.py` implement bounded source checks, in-memory staging/SQL aggregation, count/amount reconciliation and fixed declared dataset impact. These checks do not prove general causal diagnosis or correct attribution when totals balance.
- **L4 — Agentic orchestration:** `gateway.py`, `investigation.py`, `coordination/` and `workflow/` implement controlled tools, conditional deterministic investigation, capability tags/DAG and the durable local A26→A27 review. `advisory/` adds offline contracts, minimized prepared prompts and durable local usage admission. Model planning/dispatch, dynamic specialist reasoning and general distributed execution remain planned.
- **L5 — Evidence, remediation and workflow:** `storage/` retains immutable source/report/claim links, event chains, investigation traces and exact stage/mart/SQL snapshots. Explicit migration, version/integrity checking and replay work. Deterministic scoped verification exists. General semantic claims/hypotheses, patch sandbox, authenticated approval and remediation remain planned.
- **L6 — Security, AgentOps and infrastructure:** `security/` and integration boundaries implement TLS 1.3, certificate/resource pins, bounded fixed-IP egress and local host grants. CI supplies multi-version tests, critical coverage gates, installed checks, dependency audit and full-history/PDF scanning. Production tenant identity, managed issuer/secret lifecycle, audit/observability, distributed quotas and operational recovery remain planned.

A26 retained-read and A27 deterministic assessment verification are narrow working role slices. No full specialist meets the original role definition yet, and no LLM worker is active. `registry.py` validates the frozen 36-role design catalog; it is not an executable agent registry.

See the [complete delivered inventory and remaining roadmap](delivery/implementation-and-roadmap.md), [agent connection map](agents/README.md), [current status](delivery/status.md) and individual ADRs/contracts. Do not infer completed product layers from the existence of a directory or registered role.
