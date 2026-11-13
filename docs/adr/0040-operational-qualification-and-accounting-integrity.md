# ADR-0040 — Operational qualification and accounting integrity

Status: Accepted for the local trusted-host profile

## Problem

A fault-injection review reproduced an accounting defect: changing a settled row's charged cost to a negative number caused snapshots to report that number and allowed subsequent admission to use it. Existing transition tests covered values written by the normal API, but did not validate all persisted arithmetic when reopened or reused. The host-controlled SQLite file is not a hostile-writer authentication boundary; nevertheless, internally inconsistent state must never describe available spending capacity.

## Decision

Add one shared accounting validator before opening, snapshotting, reserving, transitioning, route journal operations and recovery assessment. Recompute reservation and settlement arithmetic with exact bounded integers. Validate digest/model fields, state/actual-usage relationships, request and shared-operation limits, immutable operation eligibility/deadline and aggregate budgets. Each open ledger pins the original policy bytes and checks authority metadata on subsequent transactions. Legacy policy JSON is preserved byte-for-byte rather than normalized or migrated.

Limit each scope to 100,000 retained attempt records, including cancelled records. Existing smaller total-attempt limits still apply. Reads are bounded and validation is linear in retained attempts. This is suitable for bounded local scopes, not a claim of distributed billing throughput. A full scope rejects new admission; there is no automatic eviction, pruning or budget reset.

Add an executable offline qualification suite that runs real prepared evidence, route dispatch, deterministic Judge, accounting, reopen/replay and recovery. Seven outcome scenarios plus an interrupted worker must match independently specified totals and call counts. Qualification returns a bounded report only after all checks pass. The installed-wheel check runs this suite in CI on every supported Python version.

## Compatibility and security

No database schema migration, provider call, UI, refund, automatic resend or UNKNOWN reconciliation is introduced. Valid v1/v2/v3 usage ledgers retain their formats. Previously accepted inconsistent ledgers now fail closed with sanitized errors; preserve them for investigation rather than silently repairing money or usage fields. Tests that intentionally corrupt rows retain consistent accounting when targeting a different event-binding invariant.

These checks cannot detect coordinated, internally consistent changes by a privileged writer, a rollback of the entire scope, or replacement before a new handle opens. They are not provider receipts, independent audit attestation, KMS, or anti-rollback protection. A policy's fixture rates do not prove billable categories or real token counts. An offline PASS never authorizes live activation or establishes model quality.

## Evidence and next package

719 application and 13 security/hygiene tests (732 distinct), including 16 new methods, cover malformed accounting, cached authority changes, request/shared caps, legacy compatibility, replay without new calls, conservative UNKNOWN/in-flight holds and qualification regression detection. Full coverage: 4,201 statements and 1,246 branch exits, 100%, no exclusions. Eleven installed checks, dependency/secret scans and PR/main CI are delivery gates; final run links are recorded in the PR.

Next: provider-neutral authenticated usage-attestation contracts and durable operator review decisions, bound to the operation, attempt, quote and exact recovery snapshot. Define replay/conflict/current-authority rules before permitting any reconciliation write. Provider selection, region, retention, credential delivery, spending approval and independent quality evidence remain activation prerequisites.
