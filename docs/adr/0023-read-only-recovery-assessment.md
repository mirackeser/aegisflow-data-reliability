# ADR-0023: Read-only recovery assessment before reconciliation authority

Status: accepted as the first B08 slice.

## Decision

Expose `assess_recovery(ledger)` for version 3 ledgers. Open SQLite explicitly with `mode=ro` and one read transaction so route, events, attempts, metadata and accounting come from one consistent snapshot. Preserve the database byte-for-byte. Export status counts, held/charged usage, unjournaled settlements, fixed reason codes, a canonical snapshot digest and an assessment digest. No raw inputs, prompts, provider errors, ownership tokens or attempt UUIDs appear in the report.

The assessment distinguishes `ROUTE_NOT_FINALIZED`, `USAGE_UNRESOLVED`, `RESERVATION_HELD` and `RESULT_NOT_JOURNALED`. Unfinished routes may still be active; this does not declare a worker dead. `NO_RECOVERY_INDICATED` describes only observed state, not an integrity certification or a model quality verdict. Automatic resend and refund flags are always false.

Reject changed ledger scope, invalid attempt/final states, wrong plan bindings, orphan/duplicate/out-of-order events and attempts without a route. The host and database remain trusted; the digest is change detection for exported evidence, not a signature or tamper-proof attestation. Full journal semantic validation, authenticated operator decisions, provider usage attestations, retention/quotas and reconciliation writes remain later B08 work. The assessment does not settle UNKNOWN, close RUNNING or resume routing.

## Validation

Twelve tests cover clean/completed snapshots, reopening, active claims, settled-but-unjournaled calls, reserved/in-flight/unknown holds, state changes, malformed history, missing storage and sanitized errors. Positive cases assert unchanged database bytes, preserved usage and no dispatch/refund authority. Installed-package checks exercise a completed routed call and read-only assessment. Passing tests do not establish real model accuracy.
