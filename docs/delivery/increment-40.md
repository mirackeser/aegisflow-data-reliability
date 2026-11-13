# Increment 40 — Accounting integrity and operational qualification

This package combines a reproduced persisted-accounting defect fix, validation at spending/replay/recovery boundaries, eight integrated operational scenarios and an installed-wheel CI gate.

The initial 703 application tests passed. Additional fault injection showed that a negative persisted charge could influence admission. The new validator rejects inconsistent reservations, charges, statuses, authority changes, request/shared limits and operation scope before they can authorize spending or produce a clean assessment. Existing legacy records are supported without rewriting metadata.

Final local validation: 719 application + 13 security/hygiene tests = 732 distinct methods, 16 new. Full application statement/branch coverage: 4,200 / 1,246, 100%, zero exclusions. Eleven installed checks now include offline operational qualification. Dependency/secret/hygiene checks and PR/main CI remain required, with final evidence in the PR. Original architecture/PDF and established pipeline/workflow execution are preserved.

See [ADR-0040](../adr/0040-operational-qualification-and-accounting-integrity.md) and the [qualification contract](../contracts/operational-qualification-v1.md). Next: authenticated provider-neutral usage attestations and durable operator decisions for B08. No automatic reconciliation, provider activation or measured model-accuracy claim is introduced.
