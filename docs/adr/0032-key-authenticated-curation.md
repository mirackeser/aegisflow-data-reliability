# ADR-0032: Dataset-scoped authentication of annotation signing keys

Status: Accepted for the local authentication boundary. PR/main evidence records delivery.

## Decision and data flow

Local reviewer names alone do not authenticate artifact origin. Add detached Ed25519 annotation envelopes verified against explicit trusted-host `ReviewerGrant` objects. Each grant binds one reviewer name, one 32-byte public key, one exact manifest digest, a validity interval and current revocation state. The grant is never derived from an envelope or supplied by a model. The signing-key fingerprint is SHA-256 of the public bytes.

The signed metadata contains version/purpose, reviewer/key/manifest/annotation digests and issued/expiry times. Signing bytes are the fixed `aegisflow/curation-annotation/v1` domain, one NUL separator and canonical UTF-8 metadata JSON. `annotation_signing_bytes` exposes this format without private-key handling. Verification uses the pinned cryptography Ed25519 API; see the [upstream signing/verification interface](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/). No custom cryptographic primitive is implemented.

`verify_annotation` validates closed contracts, exact input bytes and the grant scope, enforces `grant.not_before <= issued <= host_now < expiry <= grant.expires`, then verifies the signature. Envelope size is at most 4,096 bytes; annotation inputs retain the shared one-megabyte bound. Signature encoding is exactly 128 lowercase hex characters. Integer millisecond timestamps reject booleans/floats. Active revocation is checked from the current host grant, not a signed self-claim.

`reconcile_verified_annotations` requires exactly two annotation/envelope/grant triples with distinct reviewer names and distinct public keys. It binds both grants to the exact manifest before verification and calls the existing full-coverage consensus logic only after both signatures pass. Returned authentication evidence includes the host verification time, metadata and exact envelope hashes. Signature validity cannot resolve disagreements, approve provenance/sampling or authorize model deployment/tools/data writes.

## Trust, operations and boundaries

This authenticates possession of explicitly granted keys; it does not establish employment, human identity or independence of two people. Key enrollment and reviewer-name binding must come from a trusted organizational identity process. No account, persistent credential, live issuer, public service or production permission is provisioned here. Only tests/installed checks generate ephemeral in-memory signing keys.

The host must supply a trusted clock and current grants/revocation state on every verification. Verification is stateless and exact repeated verification is allowed: signatures are immutable artifact proofs, not one-use task tokens. No global replay/submission ledger, managed rotation/revocation distribution, historical trust archive or human authentication flow is implemented.

Retain the original annotation and detached envelope bytes plus the trust-policy revision in a protected audit store before relying on long-term authenticated evidence. This API currently returns evidence but does not persist signed envelopes. Existing v1 curation snapshots retain unsigned annotation bytes and are not upgraded to authenticated records by calling them afterwards. Encrypted storage, key management, evaluator/curator access separation, durable signed evidence and authenticated ingress remain subsequent gates. Legacy local curation APIs stay trusted-host only; future untrusted ingress must enforce the signature boundary explicitly.

## Validation and review

Fourteen new methods exercise actual signatures, independent signer formatting, domain separation, changed annotation bytes, validly signed scope violations, modified metadata, wrong keys, revocation, expiry boundaries, invalid times/contracts, key aliases, exact pair coverage, disagreements and existing quality gates. A tenth installed distribution check verifies valid reconciliation and expiry outside checkout. The `curation` optional dependency group declares the already-pinned cryptography version and is explicitly installed in CI.

Self-review identified key aliases, metadata tampering, time-boundary and durable-proof overclaim risks and addressed them with rejection tests and explicit scope. No claim is made that a signature establishes correct labels, sealed data or model accuracy. Whole-application coverage and existing security/install gates remain required.
