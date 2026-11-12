# ADR-0033 — Retain signed curation evidence under external current authority

Status: accepted for the local trusted-host boundary.

## Problem and decision

Increment 32 verifies detached signatures but returns only proof metadata. The unsigned snapshot cannot retain those signatures or the exact policy under which they were accepted. Add a separate signed format that stores exact envelopes, annotations, sources and canonical public grant policy. Bind all bytes and the original authenticated result in a header whose digest is retained outside the file.

Every read requires current host grants, revision and time; archived public keys are never imported as trust. Recompute historical integrity at retention time and require current signature validity before exporting labels. A changed policy, revocation, expiry or clock rollback blocks export. Existing unsigned artifacts are preserved and explicitly rejected by the signed reader.

Share the bounded physical-table reader and exclusive transactional writer with unsigned retention. Preserve its schema/resource limits, transaction semantics and no-overwrite behavior; no schema migration is needed. Introduce no dependency, private-key storage, external request or deployment authority.

## Self-review and verification

The full pre-change application suite passed (612 methods). Review found the planned durable-evidence boundary still missing, rather than evidence of a new vulnerability in the previous scoped signature verifier. Tests exercise real Ed25519 signatures and real temporary SQLite databases: agreement/disagreement, exact evidence/policy retention, current expiry/revocation/revision, untrusted/missing grants, clock rollback, source and signature tampering, rehashed invalid signatures, schema substitution, wrong row counts, cross-format rejection, no-overwrite/symlinks and actual rollback after INSERTs when trigger creation fails. Existing unsigned-format attack tests remain required. Installed-package checks reopen signed evidence and reject stale policy/expiry outside the checkout.

## Consequences

The local integrity portion of signed retention is delivered. Plaintext confidentiality, enterprise identity, independent reviewer enrollment, managed keys and evaluator/curator separation remain open. The trusted host must control policy freshness, time and external digest storage. A policy revision is an opaque exact binding, not a distributed revision log. An expired artifact remains retained but this API will not export its labels. No new model accuracy, sampling approval or production-readiness claim follows from signature or coverage success.

See [wire/API contract and sequence](../contracts/signed-curation-retention-v1.md).
