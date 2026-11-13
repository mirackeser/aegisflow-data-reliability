# Durable evaluator access and audit v1

`benchmark.access_registry` combines grant retention, terminal revocation and access auditing in one trusted-host SQLite boundary. A registry contains one immutable `EvaluationAccess` grant; the host retains its canonical SHA-256 digest independently. It contains no encryption key, source, labels or signature envelopes.

- `initialize_access(path, access)` exclusively creates a mode-0600 file and returns the grant digest. Existing files/symlinks are never overwritten. Failed initialization may leave a reserved empty file.
- `evaluate_registered(registry_path, snapshot_path, *, expected_grant_sha256, principal_id, role, expected_sha256, key_id, policy_revision, now_ms, grants, resolve_key)` reads current authority from disk, validates its external digest and serializes evaluation against revocation. It applies the existing exact principal/role/snapshot/key/policy/time checks before key resolution, then revalidates encrypted and signed evidence. The caller supplies no replacement access grant.
- `revoke_access(path, *, expected_sha256, now_ms)` permanently revokes the bound grant. Repetition is idempotent; no reactivation API exists. A new grant requires a new registry and an explicit host decision.
- `access_history(path, *, expected_sha256, after=0, limit=100)` returns ordered audit entries with sequence, host time and fixed outcome only. Limits are 1–100; use the last sequence as the next cursor.

## Transaction and failure semantics

All operations use `BEGIN IMMEDIATE`, a five-second lock timeout, restricted SQLite row length and trusted schema disabled. An in-flight read that acquires the lock first completes before a concurrent revocation; a read after revocation commits is denied. Revocation is not cancellation of a read already in progress. The trusted key resolver must be short-lived and must not reenter this registry.

Evaluation writes STARTED before key resolution and VERIFIED or REJECTED before commit. Labels are returned only after the transaction commits. REVOKED is written atomically with terminal state. Normal audit UPDATE/DELETE and authority mutation/deletion are blocked by triggers. Failure to write the first audit entry prevents key resolution. Failure to commit/write the final entry prevents label delivery and rolls back the transaction. Such failures, process crashes and power loss may leave no audit entry for an attempted operation: this is a transactional decision log, not an independent crash-proof request journal. An earlier STARTED entry is visible only together with its committed outcome. Audit writes never include exception text, plaintext source or keys.

Invalid/unreadable registry bindings fail before evaluation and cannot reliably be audited in that same registry. Errors are sanitized. The result VERIFIED means the encrypted/signed evidence and current access checks succeeded; a signed label disagreement can still be present and exports no quality cases. This does not approve a model's quality.

## Trust boundary and next gate

Registry path, external digest, principal/role, signing grants, clock and resolver are trusted host configuration. A remote caller or model must never populate them as authority. The registry is private authorization metadata, not an identity provider or cryptographically independent audit service. OS owners can replace a registry with an old copy or remove triggers; host filesystem custody and anti-rollback operations remain prerequisites. Grant hashes detect changes to immutable grant bytes, not rollback of revocation/audit history. Multiple replicas must not independently serve copies. Existing low-level APIs remain host-only and are not an isolation boundary against trusted code with key access.

Next: authenticated principal enrollment, managed key lifecycle and access/process separation. Keep enterprise datasets gated until those controls and backup/restore/revocation operations are established.
