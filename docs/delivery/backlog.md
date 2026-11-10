# Delivery backlog

Work in short, acceptance-driven increments. Estimate the next item after reviewing the previous increment; the architectural 16-week roadmap is a target, not a delivery guarantee.

1. **DR-001 — Deterministic diagnostic baseline:** implemented in increment 01. Reproducible synthetic orders; schema/null/duplicate injection; evidence-linked checks; bounded input; stable CLI outcomes; automated regression coverage.
2. **DR-002 — Real batch transformations and lineage:** implemented in increment 02. Introduce an explicit source/staging/mart fixture and lineage edges; identify downstream impact without pretending that a failing check proves its root cause.
3. **DR-003 — Tool contracts and enforcement:** implemented in increment 03 for local trusted-host sessions; enterprise identity, hard isolation and durable quotas remain planned. Typed requests/results, allowed tool catalog, read-only policy, time/call budgets and negative authorization tests.
4. **DR-004 — Incident and evidence persistence:** next. Incident lifecycle, immutable snapshots, claim/evidence junctions, reproducible replay and version checks.
5. **DR-005 — Bounded orchestration:** planned. Implement deterministic baseline first, then optional model planning behind the same enforcement boundary; track each specialist's tested capability separately.
6. **DR-006 — Investigation interface:** planned. Build the first premium, accessible investigation workspace on working API contracts.
7. **DR-007 — Research evaluation:** planned. Separate development and held-out failure families; compare B0-B4 with controlled tools and budgets.
