# Key-authenticated curation v1

Install the optional profile with `pip install '.[curation]'`. The closed [detached envelope schema](curation-signature-v1.json) is exported from `benchmark.curation_auth.ENVELOPE` and checked for equality in tests. Ed25519 is fixed by version/purpose; no algorithm negotiation or envelope-supplied key lookup occurs.

1. Prepare the existing label-free manifest and distribute source cases to independently enrolled reviewers through the trusted host.
2. The host builds two `ReviewerGrant` values from its approved public-key registry and manifest digest. Private keys remain with the reviewers.
3. Each reviewer computes the exact annotation-byte hash and metadata and signs `annotation_signing_bytes(metadata)`. Encode the detached signature as lowercase hex in the envelope. Hashes and names must match the grant; metadata times are integer milliseconds.
4. Call `reconcile_verified_annotations(manifest_bytes, annotations_tuple, envelopes_tuple, grants=grants_tuple, now_ms=trusted_host_time)`. Tuple positions must correspond. All three tuples contain exactly two elements.
5. The result is the existing AGREED/DISAGREEMENT curation result plus `authentication` containing method, verification time and the two metadata/envelope-hash proofs. A disagreement still exports no quality cases. No provenance or sampling flag is changed.

Reject expired, future or revoked grants and modified bytes or metadata. Reject mismatched purpose, signing identity or dataset binding, reused keys, incomplete labels and malformed contracts. Errors are sanitized. The verification window is inclusive at issue time and exclusive at expiry.

Proof hashes are not a replacement for retained signed artifact bytes. This stateless API has no submission side effect or one-use replay guarantee. It authenticates approved key possession, not human independence, real label quality, protected storage, historical trust or production release. See [ADR-0032](../adr/0032-key-authenticated-curation.md) for required operational integration.
