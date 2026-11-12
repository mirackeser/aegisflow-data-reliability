# Increment 32 — Annotation signing-key authentication

Adds detached Ed25519 annotation verification with exact reviewer/key/data/time binding and trusted-host dataset-scoped grants. Two distinct reviewer names and keys are required before existing curation consensus. Revocation/expiry and malformed or altered artifacts fail closed. No automatic label adjudication, provenance approval, deployment or storage authority is added.

Validation: 612 application + 13 security/hygiene methods = 625 distinct tests, including 14 new authentication methods. Full Python 3.12/3.14 suites, 100% application statement/branch gates, ten installed distribution checks and security/dependency scans apply. Exact-head PR/push and post-merge main checks record delivery in the PR.

The optional `curation` profile explicitly declares the pinned cryptography dependency. Core local APIs and unsigned v1 snapshots remain compatible. Self-review distinguishes possession of approved keys from actual human identity/independence and durable authenticated evidence. Next: retain signed evidence and trust-policy provenance in protected storage, with separate curator/evaluator access and managed key/identity integration. UI and live providers remain deferred. See [ADR-0032](../adr/0032-key-authenticated-curation.md).
