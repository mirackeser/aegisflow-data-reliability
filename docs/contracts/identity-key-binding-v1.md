# Verified peer identity and key-version binding v1

`benchmark.identity_keys` joins existing TLS 1.3 mutual authentication, durable evaluator authority and encrypted curation. It exposes a host callback, not a production HTTP endpoint. No identity header or principal/role claim is accepted by `evaluate_peer`.

## Binding and lifecycle

`IdentityKeyBinding` is a frozen contract containing client certificate SHA-256, principal ID, immutable evaluator-grant digest, key ID, exact 256-bit encryption-material digest and validity interval. It contains no secret. `initialize_binding(path, binding)` exclusively creates a private mode-0600 SQLite file and returns the canonical binding digest for independent host retention. The initial record is immutable; the only mutable states are terminal identity revocation and key disable flags.

`disable_binding(path, *, expected_sha256, component='identity'|'key')` checks the external binding digest and persistently sets the selected flag. Repeated calls are idempotent; reactivation, mutation and deletion are blocked by normal SQL triggers. This is **binding-scoped** disabling: other bindings, replicas or hosts that use the same key/certificate are not automatically disabled. Global issuer revocation and KMS disable operations remain external work.

`evaluate_peer(binding_path, registry_path, snapshot_path, *, expected_binding_sha256, peer, expected_sha256, policy_revision, now_ms, grants, resolve_key)` extracts the remote client leaf fingerprint from an actual verified server-side TLS 1.3 socket using the existing strict mTLS helper. It loads the externally bound policy, rejects inactive/expired/wrong peers, derives principal and key ID from that policy, and invokes durable evaluator authorization. The resolver's returned key must be exact bytes of length 32 with the bound material digest. Existing snapshot/grant/policy/clock and signed-evidence checks remain mandatory. Wrong secrets and resolver failures are sanitized through the existing gateway.

A binding database write transaction is held across the nested evaluator transaction to serialize disabling with reads. Lock order is binding then evaluator registry. Paths must be distinct. A read already admitted may finish before a concurrent disable; after disabling commits, subsequent reads reject. Host callbacks must be short-lived, must not reenter either registry, and must not acquire locks in reverse order. No asynchronous cancellation of in-flight reads is claimed.

## Explicit renewal and rotation

Certificate renewal requires a new externally approved binding with the new leaf fingerprint. A newly issued certificate from the same CA does not inherit an old principal binding. Disable the old identity binding according to host policy. Existing records are retained.

Encryption-key rotation requires explicit retention into a new encrypted snapshot under the new key ID/material, a new evaluator grant bound to its digest, and a new identity/key binding. Tests exercise that complete flow and confirm old snapshots remain present. No key is generated, distributed, replaced or destroyed by this module, and no automatic bulk re-encryption is added. Private material comes from the runtime resolver; never use password-derived/low-entropy material as the 256-bit key.

## Trust and audit boundaries

The TLS context, principal enrollment, registry paths, external digests, clock and resolver configuration belong to the trusted host. Certificate possession is authenticated; organizational enrollment/human identity still depends on the host's issuance and binding procedure. This does not deploy enterprise SSO, a managed issuer, KMS or process isolation. Do not expose lower-level host APIs to untrusted callers.

Failures after entering evaluator authorization are recorded by the existing access registry. Rejection during TLS extraction or identity/key policy checks occurs before that registry and is not automatically logged there; an ingress audit service remains required for all attempted remote requests. Identity/key lifecycle flags themselves are not an append-only lifecycle event ledger. SQLite triggers and external immutable digests do not prevent privileged rollback of mutable state or copies of retired material. Backup/restore and global revocation operations remain gated. Enterprise data and production exposure remain deferred.
