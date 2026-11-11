# Increment 20 — Shared operation admission and visible offline demo

B07 first local slice: optional dedicated-ledger total attempt cap shared across prepared model requests, original deadline and unresolved-attempt guards. Existing shared token/cost accounting remains authoritative. Legacy policies open without rewriting. No automatic fallback, operation-ID/evidence/model allowlist binding or account-wide quotas are claimed. See [ADR-0020](../adr/0020-shared-operation-budget-foundation.md).

Validation: 439 application + 13 security/hygiene methods = 452 distinct passing tests, including nine new shared-budget/demo tests. Critical coverage gates and installed-package checks remain required. The visible synthetic demo shows primary failure, secondary verified result, third admission denial, exact usage and unchanged evidence, with zero model/network calls.

Location: stage B, development increment 20, B07 partial. Next: persist logical-operation identity, evidence/model eligibility and shared routing admission before automatic fallback; B08 audited recovery remains pending. UI and live providers stay gated.
