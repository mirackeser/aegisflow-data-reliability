# Increment 06 — Durable investigation evidence

Goal: retain reproducible investigation runs and exact authorized batch evidence without changing source incidents.

Acceptance criteria completed:

- Explicit, atomic V1-to-V2 migration; V1 source history remains readable and replayable without implicit migration. The extracted V1 DDL was compared byte for byte with the published V1 implementation.
- Immutable run/manifest/trace records and four bounded batch snapshots: staging CSV, mart CSV, executed SQL and staging contract.
- Incident-scoped idempotency, concurrent same-request serialization and changed-request rejection.
- Atomic rollback for interrupted/failed writes; source closure and prior events remain unchanged.
- Evidence/checksum verification on read, retry and replay; incompatible implementations reject exact replay while preserving historical reads.
- Explicit durable CLI commands and installed-package checks across process restarts.

Validation on 2026-11-10: 146 application unit/integration tests and eight repository-hygiene tests passed (154 tests total). All 10 labeled development scenarios matched; these are also exercised by the evaluation tests and are not an independent model benchmark. The built wheel passed installed licensing/catalog/gateway/source/batch/store/workflow/run checks from outside the checkout. Candidate-file/PDF hygiene and redacted local Gitleaks scanning passed. GitHub CI additionally runs Python 3.11/3.12/3.14 and scans full reachable Git history and extracted historical PDFs.

Scenario coverage includes clean and faulty data, source-quality rejection, denied tools, missing/forged/oversized evidence, malformed metadata, corruption, key conflicts, concurrent retries, partial inserts, process exit before commit, immutable rows, foreign keys, backup/restore, migration failure and unsupported versions. Numeric line/branch coverage is not measured. No model calls or accuracy percentage are claimed.

Next: durable execution reservations and dependency/retry/cancellation contracts before external or model work. The current deterministic workflow executes under a local write transaction; it must not be extended to slow providers without that next boundary. See ADR-0007 for migration operations, privacy and replay limits.
