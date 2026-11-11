# Increment 23 — Read-only recovery evidence

First B08 slice: consistent version 3 ledger recovery assessment, using a read-only SQLite transaction. Export fixed reasons, usage/attempt counts, unjournaled settlements and stable digests. Unknown usage retains its hold; unfinished routes remain blocked. This supplies evidence for later audited operator decisions, not reconciliation authority.

Validation: 492 application + 13 security/hygiene methods = 505 distinct passing tests, including 12 new recovery tests. New recovery statement/branch coverage is 100%; existing critical gates and nine installed checks remain required. Security/dependency scans and exact-revision CI gate merge. See [ADR-0023](../adr/0023-read-only-recovery-assessment.md).

Next: authenticated/bound operator dispositions and provider usage attestations before any reconciliation write; retention/quotas and B09 failure qualification remain pending. See [live output milestones](live-output-milestones.md) for C05/C08/UI gates and the conditional 6–10-increment estimate to a first controlled live model response.
