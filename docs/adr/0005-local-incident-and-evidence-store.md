# ADR-0005: Persist source investigations as atomic, replayable records

Status: accepted for local synthetic research. Date: 2026-11-10.

## Scope and model

Persist deterministic source CSV diagnosis in an explicitly initialized SQLite file. Each incident owns exact source bytes, canonical diagnostic-report bytes, a versioned manifest, generated observation/summary claims, many-to-many claim/evidence links and an append-only event chain. Claims reference both the source snapshot and report. They are source-quality observations, never inferred root causes or model probability estimates. Truncated reports retain the total count and truncation flag; no omitted finding is invented as a claim.

All record writes commit together under BEGIN IMMEDIATE. Repeated request keys with identical bytes return the original verified record, including after closure. Reuse with different bytes is rejected. The per-operation connections, unique key and serialized write transaction prevent concurrent duplicate creation. A failed transaction leaves no partial incident/evidence/event set.

Lifecycle: RECEIVED → DIAGNOSED → CLOSED. Initial events are committed atomically; no externally visible half-created incident is exposed. Closure appends an event and requires the expected revision; stale or duplicate closure is rejected. The actor is an explicitly labeled local operator string, not an authenticated identity. Closing a case does not authorize a fix or certify semantic correctness.

## Integrity and version handling

Database UPDATE/DELETE triggers reject mutation of stored entities. Every read verifies evidence hashes, report/source binding, claim identities, manifest/link consistency and the hash-linked event sequence. A schema fingerprint plus application ID and user_version reject unsupported or modified layouts. Initialization exclusively creates a new file with POSIX mode 0600 and refuses existing files. Opening never silently creates, migrates or repairs a database. Initialization failure can leave a new unsupported file; it is not automatically removed or overwritten.

Replay first validates the stored record, then requires the original pipeline.py content fingerprint and exact Python implementation/version. Under matching conditions it reruns the retained source and compares canonical report hashes. A changed implementation/runtime is explicitly unsupported; a different result is MISMATCH. Neither outcome rewrites history. Old records remain readable across diagnostic changes when the storage schema is supported.

## Operational boundaries

Synthetic local data only. The store contains exact source rows; it is not encrypted. File owners and host code remain trusted: an administrator can remove triggers and rewrite every hash, so this is integrity checking, not externally anchored tamper-proof evidence. There is no tenant ACL, remote API, retention service, production backup automation or PostgreSQL adapter. The CLI is a trusted local operator interface, separate from the read-only agent tool gateway. Persistence is not exposed as an agent-granted write tool.

This increment stores source diagnosis, not batch staging/mart byte snapshots, arbitrary LLM claims or complete agent-call audit. Those extensions require versioned contracts before being called implemented. SQLite backup/restore and process-exit rollback are regression-tested; production recovery objectives and restore drills remain future acceptance gates.
