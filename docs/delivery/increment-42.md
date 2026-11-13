# Increment 42 — Signed usage evidence and durable recovery decisions

B08 now verifies operation-scoped usage assertions and durably records signed operator reviews with exact attachment binding. Current snapshot checks, independent issuer/operator keys, idempotent commits, bounded append-only history and failure/concurrency qualification form one delivery package. Usage holds remain unchanged.

Validation: 745 application + 13 security/hygiene tests = 758 distinct methods; fourteen new. Full statement/branch coverage is 100% on local Python 3.12/3.14 with no exclusions. Twelve installed-package checks, security scans and PR/main CI remain delivery gates; final run evidence is recorded in the PR. See [ADR-0042](../adr/0042-signed-recovery-evidence-and-decisions.md).

Next: explicit operator-authorized reconciliation transitions and atomic failure/recovery design. Live provider usage retrieval, deployment authority and independent real-model accuracy measurement remain prerequisites for activation.
