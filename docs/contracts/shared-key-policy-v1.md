# Shared key policy, lifecycle history and restore guard v1

`benchmark.key_policy` adds a shared local control point above verified peer identity, evaluator grants and encrypted evidence. Every participating binding must use the same policy path and current externally retained checkpoint. Direct lower-level host APIs do not acquire this policy automatically.

## Catalog and checkpoint

`initialize_key_policy(path, keys)` accepts 1–64 key IDs mapped to distinct SHA-256 digests of random 256-bit key material. IDs follow the existing identifier contract. Aliases for the same material are rejected within a catalog. The private mode-0600 SQLite file contains immutable public catalog bytes and append-only lifecycle events, never secret keys. Creation is exclusive; failed initialization may leave a reserved empty file. There is no automatic catalog migration or replacement.

The returned closed checkpoint has `catalog_sha256`, exact integer `sequence`, and `event_sha256`. Initial sequence is zero; the initial event digest is SHA-256 of the domain `aegisflow/key-policy/v1`. The host must persist the current checkpoint separately from the database in an access-controlled, monotonic/CAS-managed location. It must never obtain the expected checkpoint from the restored policy file or an untrusted request.

`disable_key(path, *, checkpoint, key_id, now_ms)` validates the complete current chain and appends one DISABLED event, returning the next checkpoint after commit. Events bind catalog digest, contiguous sequence, previous event digest, key ID, fixed action and exact host time. Disable is terminal within this policy; repetition with the current checkpoint is idempotent. It applies across all bindings routed through this same policy, and checks before the external resolver. It does not revoke copies served by unrelated policy databases or external KMS services.

`key_history(path, *, checkpoint)` validates and returns the complete lifecycle history. Normal catalogs allow at most 64 unique disable events; a defensive 10,000-row read bound rejects corrupt floods. SQLite payload length limits remain active. Catalog/event UPDATE and DELETE are blocked by normal SQL triggers. Sequence defines ordering; host timestamps are not an independent time authority.

## Evaluation and concurrency

`evaluate_with_key_policy(policy_path, binding_path, registry_path, snapshot_path, *, checkpoint, resolve_key, **request)` checks the external checkpoint and wraps the existing peer-evaluation entry point. The requested grant's key must exist, remain active and match the actual resolver bytes. Identity, grant, snapshot, signature and policy checks remain in force. The resolver is never called for an unknown/disabled key. Existing evaluator audit records key-policy rejections occurring during authorization.

The shared policy transaction stays locked through the entire peer evaluation. Lock order is key policy, identity binding, evaluator registry. These three paths must be distinct. Short host resolvers must not reenter any registry or acquire locks in reverse order. A read already admitted may complete before disabling commits; subsequent reads are denied. SQLite uses a five-second lock timeout. Multiple independent hosts/replicas require a real centralized service, not copied SQLite files.

## Restore and publication behavior

After disabling a key, restoring an older database while retaining the current external checkpoint rejects both history reads and evaluation before key resolution. Modified chains, stale checkpoints and catalog substitution also reject. Restoring both the database and its external checkpoint defeats this guard; monotonic external checkpoint custody is an explicit prerequisite, not implemented by this module.

Database commit and external checkpoint publication are not one atomic transaction. The trusted host must publish the returned checkpoint before serving further requests, serialize publication with CAS, and suspend service on mismatch. A crash between the two commits blocks with the old checkpoint against the newer database. There is no automatic acceptance of database-derived state or rollback recovery. Reconciliation requires an explicit trusted recovery procedure. A newly created catalog must not silently replace a policy carrying revoked-key history.

This is local key-policy enforcement, not managed secret delivery, cryptographic privileged-owner tamper protection or an independent lifecycle audit service. Identity/binding rollback, global issuer/KMS revocation, ingress-attempt logging, trusted checkpoint storage and restore operations remain separate production gates. Keys, certificates and enterprise datasets are not provisioned by this change.
