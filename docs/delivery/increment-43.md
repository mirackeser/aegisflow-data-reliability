# Increment 43 — Explicit accounting reconciliation and crash recovery

Delivered a new opt-in v4 routing/usage scope, separately signed operator settlement authority, independent issuer verification, atomic evidence/accounting receipts, conservative delivery blocking, late-worker fencing and sequence-paged audit export.

Validation: 759 application + 13 security/hygiene = 772 distinct methods, fourteen new. Full statement/branch coverage is 100% on local Python 3.12/3.14. Real process exits before/after commit, database failures, concurrency, replay/conflict and invalid authority/evidence are tested. Twelve installed checks and fresh security scans apply. Final PR/main CI links are retained in the PR. Original architecture and existing profiles remain preserved.

See [ADR-0043](../adr/0043-explicit-atomic-usage-reconciliation.md) and the [contract](../contracts/usage-reconciliation-v1.md). Next: provider transport/independent usage acquisition and managed identity/custody qualification. Live provider and measured quality activation remain separately gated.
