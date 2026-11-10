# Layer ownership

- L1 — Presentation: `apps/web`; planned.
- L2 — Integration and observability: `integration`; synthetic input generation is the current local baseline.
- L3 — Quality and diagnostics: `pipeline.py` and `batch.py`; source contract checks, in-memory staging/SQL aggregation, count/amount reconciliation and fixed declared dataset-level impact implemented.
- L4 — Agentic orchestration: `orchestration`; planned. `registry.py` validates design metadata only.
- L5 — Evidence, remediation and workflow: `workflow`; persistence and approvals planned. Current reports bind local observations to exact byte hashes.
- L6 — Security and operations: `infrastructure`; enterprise enforcement planned. Local diagnostic input/output budgets and CI are implemented.

All 36 specialists remain planned. Diagnostic functions are not claimed as full agent implementations. Module boundaries can be split when real dependencies justify it.

Local L4/L6 foundation: gateway.py implements exact host-configured grants, closed tool requests, per-session atomic call budgets, byte limits and cooperative deadlines. It does not implement agents or enterprise identity enforcement.

L5 local source-research foundation: storage/ atomically records source snapshots, diagnostic reports, generated claim/evidence links and append-only events. Explicit initialization, replay/version checks and revision-controlled local closure are implemented. Durable batch snapshots, model semantic verification, enterprise authorization and remediation approval remain planned.
