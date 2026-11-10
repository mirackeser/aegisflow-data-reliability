# ADR-0007 — Durable investigation runs and exact batch evidence

Status: accepted. Supersedes the transient-evidence limitation of ADR-0006; its deterministic reasoning limits still apply.

## Problem and decision

Source incidents were durable, but workflow traces and canonical stage/mart bytes were lost after execution. Persist a separate immutable run aggregate: request and host policy, ordered trace, source checksum, implementation fingerprint, and named artifact descriptors. Retain the exact authorized execution's staging CSV, mart CSV, packaged SQL and staging-contract bytes. Never execute an extra tool merely to populate storage. Raw bytes remain outside JSON and repr output.

Keep incidents and their lifecycle unchanged. A completed failure investigation and an inconclusive investigation can both be durably recorded. Do not create causal claims or model confidence scores from deterministic observations. No specialist or model capability is added by persistence.

## Atomicity and identity

Schema V2 adds investigation_runs and run_artifacts with foreign keys, unique (incident_id, request_key), and update/delete rejection triggers. BEGIN IMMEDIATE serializes concurrent retries. The parent incident, request, workflow trace and artifact checksums are verified on reads and retries. Identical retries return the original; a different policy or transform conflicts. Inserts and artifacts commit together, and exceptions/process exit before commit leave no partial run. Closed source incidents can be investigated without modifying closure or prior events.

The transaction holds a SQLite write lock while bounded deterministic tools execute. This is deliberate for the local baseline; it is not appropriate for network/model work. Before adding slow providers, implement durable execution reservations, dependency/retry/cancellation states, crash recovery and bounded lock contention. Current operations have a five-second lock wait and cooperative tool deadlines, not hard interruption.

## Explicit additive migration

Fresh stores initialize V2. Verified V1 stores still support source operations without implicit migration. Run operations require V2. Operators must stop writers, make a SQLite backup and invoke store-migrate. The migration checks application ID, exact schema and supported version before changing anything. DDL and user_version change in one explicit transaction; executescript is avoided because it would commit implicitly. Repeating a verified V2 migration is a no-op. Unsupported/modified schemas fail closed. No automatic downgrade is provided; restore a verified backup with writers stopped if rollback is required.

## Replay and bounds

Read validates retained bytes without requiring current code to match historical code. Exact replay additionally requires the recorded workflow/source implementation fingerprint, packaged SQL, Python and SQLite version. Replay compares the canonical trace and all artifact bytes, returns MATCH/MISMATCH, and never replaces the original. Timing-dependent or transient failures can legitimately yield MISMATCH. A code/version mismatch rejects exact replay while retaining historical read access.

Source CSV remains bounded at 1 MB. A run trace is bounded at 4 MB; each of four batch artifacts is bounded at 2 MB and their combined content at 4 MB. The current tools execute only packaged SQL against synthetic in-memory SQLite data. Denied/failed/late tool results cannot expose batch bytes; accepted batch evidence may remain on an inconclusive run if a later lineage call fails.

## Security and remaining boundaries

This is a trusted local operator API, not an agent-write capability. Raw synthetic source and batch snapshots are stored unencrypted; JSON exposes metadata only. The private store file is not committed. There is no identity, tenant authorization, retention administration, external audit anchor or protection against a malicious file owner who can rewrite all bytes and checksums. Integrity checks detect corruption and inconsistent bindings, not authenticated provenance.

## Validation

Unit/integration coverage includes migration and rollback, concurrent idempotency, partial writes, immutable rows, exact artifacts, corruption and evidence substitution, replay/version rejection, backup restoration, source-quality failures, denied tools and installed CLI round trips. Test counts and measured results are recorded in increment 06. Numeric line/branch coverage has not been measured; passing scenarios do not establish model accuracy or production readiness.
