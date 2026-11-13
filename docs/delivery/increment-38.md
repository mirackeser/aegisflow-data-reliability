# Increment 38 — Shared key policy, lifecycle history and restore guard

The delivery combines three related controls: shared terminal key disabling across participating identity bindings, persistent hash-linked lifecycle records, and rejection of restored old databases against a current external checkpoint. Peer identity, grant and encrypted/signed evidence remain independently checked. Concurrency tests exercise the complete admitted-read/disable ordering.

Validation: 688 application + 13 security/hygiene methods = 701 distinct tests, including 14 new methods. Whole application coverage, local Python compatibility, ten installed checks, dependency/secret scans and PR/main CI remain required; final figures are recorded in the PR.

General baseline qualification passed before implementation. No new demo, provider or public endpoint is introduced. The trusted host must publish a monotonic checkpoint outside the database and stop on mismatch; this change does not provision that external service. Next: checkpoint publication/recovery orchestration and restore tests with operational failure handling. See [ADR-0038](../adr/0038-shared-key-policy-and-restore-checkpoint.md).
