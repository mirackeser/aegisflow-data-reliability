# Increment 36 — Durable authorization and audited access

This delivery combines two backlog slices: persistent evaluator authority/terminal revocation and transactional access-decision auditing. Exact scope checks precede key resolution; audit commit precedes label delivery. A concurrent read/revocation integration test verifies the defined ordering. No demo, model provider or UI was introduced.

Validation targets: 658 application + 13 security/hygiene methods = 671 distinct tests, including 12 new methods; full application coverage, Python compatibility, ten installed checks, dependency/secret scans and PR/main CI. Final delivery evidence is recorded in the PR.

See [ADR-0036](../adr/0036-durable-authority-and-audit.md) and [contract](../contracts/access-registry-v1.md). The next package should combine authenticated principal binding and managed key policy integration with explicit key lifecycle/restore tests. Organizational identity and process isolation remain prerequisites for enterprise data. Local transaction audit has documented crash/privileged-host limits.
