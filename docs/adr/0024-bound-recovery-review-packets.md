# ADR-0024: Correct event correlation and bind advisory review packets

Status: accepted as the second B08 slice.

## Self-review finding and correction

The previous recovery assessment validated event existence and order, but omitted semantic links between an event, its planned candidate and its usage attempt. A reproduced corrupted event with an unrelated model still yielded `NO_RECOVERY_INDICATED`. Statement/branch coverage did not expose this missing requirement. Add regression cases and require exact model/request/input/quote correlation, settled usage for known results, unresolved usage for UNKNOWN and retryable progression before another event. This validates these links; it is not full ledger integrity certification or protection against a malicious local host.

## Next B08 slice

`prepare_recovery_review` returns immutable bytes governed by the closed [review schema](../contracts/advisory-recovery-review-v1.json). Bind a caller-supplied review UUID, operator UUID, operation hash, snapshot hash, assessment hash and one of two advisory actions: KEEP_BLOCKED or REQUEST_USAGE_ATTESTATION. Reject reviews when no recovery is indicated. `verify_recovery_review` rereads the current assessment and rejects changed/mismatched evidence.

Operator IDs are supplied by the trusted host. UUID validation does not authenticate an operator; the packet is not signed, persisted audit history, approval, execution permission or proof of provider usage. Both functions preserve ledger state. No settle, refund, resume or route closure occurs. Authenticated identity, durable decision records, replay policy, provider usage attestation and reconciliation writes remain future B08 work.

## Validation and limits

Seven additional tests cover the reproduced defect, attempt correlation, usage/result contradictions, terminal progression, shortened plans, fresh/stale review packets, invalid identity/action and unneeded review. Existing tests cover read-only behavior and ambiguous holds. Installed-package checks exercise a blocked route, review packet verification and retained full usage hold. Model quality still requires independent sealed evaluation; infrastructure test success is not model accuracy.
