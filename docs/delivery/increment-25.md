# Increment 25 — Executable model-quality acceptance policy

Prioritized the C03 first slice at user request while preserving the B08 backlog. Add provider-neutral exact-count PASS/BLOCK evaluation with frozen dataset/model/policy, class/family support, overall and per-class/family thresholds, zero errors/unsupported claims and fail-closed provenance. Add the recurring engineering-review procedure and record the architectural/self-review decisions in ADR-0025.

Validation: 511 application + 13 security/hygiene methods = 524 distinct tests, including 12 new quality tests. The new gate has 100% statement/branch coverage; existing critical/installed/security gates remain required. Installed checks demonstrate that perfect public fixtures cannot establish model acceptance. No actual model or sealed evaluation has been run.

Next: independent dataset/label/claim review and enforceable preregistration, plus the still-pending B08 authenticated operator/durable decisions/provider attestations. Actual activation must wire this gate to the approved model revision and deployment process. See [ADR-0025](../adr/0025-measurable-model-quality-acceptance.md).
