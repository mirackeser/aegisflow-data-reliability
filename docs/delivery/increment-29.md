# Increment 29 — Adversarial review and bounded snapshot reads

Reproduced and fixed local curation schema substitution acceptance and unbounded metadata materialization. The supported physical schema, SQLite runtime limits and six-row metadata cap now apply before payload trust. Seven new adversarial methods complement the existing authorization, mTLS, transport, integrity, replay, usage and quality tests.

Validation: 571 application + 13 security/hygiene methods = 584 distinct tests. Both local Python versions, all nine installed checks, security/dependency scans, critical 100% coverage and exact-revision PR/push/main gates apply. See the PR for final delivery evidence and [ADR-0029](../adr/0029-curation-reader-security-hardening.md) for the finding, scope and remaining boundaries.

No authenticated curator identity, encryption, production exposure or measured model quality is introduced. Next: authenticated identity and protected storage after this security correction. UI remains deferred.
