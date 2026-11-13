# Increment 37 — Authenticated identity binding and key lifecycle

This delivery combines verified client-certificate identity binding with persisted binding-scoped identity/key disable and explicit renewal/rotation flows. The new entry point derives principal from an actual verified TLS connection and checks exact resolver material before encrypted reads. No provider, demo or UI is introduced.

Validation: 674 application + 13 security/hygiene methods = 687 distinct tests, including 16 new integration/negative methods. Full application coverage, local Python 3.12/3.14 suites, ten installed checks, dependency/secret scans and PR/main CI remain required. The PR records final results.

Next: global managed-key policy/usage and lifecycle events, with restore/rollback and ingress-audit tests. Enterprise enrollment, issuer/KMS provisioning and process separation remain prerequisites for production data. See [ADR-0037](../adr/0037-verified-identity-and-key-lifecycle.md).
