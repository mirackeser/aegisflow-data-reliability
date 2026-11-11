# Increment 21 — Durable operation identity and model eligibility

B07 second local slice: persist incident/run/record/evidence, prompt/context/schema, allowed models and the original deadline in a new version 2 usage ledger. Opening requires the matching operation UUID. Admission rejects mismatches before adapter invocation, including after restart. Existing version 1 ledgers and retained evidence remain unchanged. No live provider or automatic cross-model fallback is enabled.

Validation: 454 application + 13 security/hygiene methods = 467 distinct passing tests, including 15 new operation tests. Operation and usage code have 100% statement and branch coverage; all existing critical coverage gates and nine installed-package checks pass. Dependency and secret/hygiene scans remain required for merge. See [ADR-0021](../adr/0021-bound-operation-admission.md) and the [contract](../contracts/operation-binding-v1.md).

Location: stage B, development increment 21. B07 remains partial: next add bounded automatic routing among approved models with persisted routing outcomes, preserving unknown-usage stops and independent evidence verification. B08 audited reconciliation, provider-specific token/rate accuracy and sealed model-quality evaluation remain pending. No model accuracy percentage is claimed.
