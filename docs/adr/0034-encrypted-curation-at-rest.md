# ADR-0034 — Encrypt signed evidence before persistence

Status: accepted for local trusted-host storage.

Increment 33 retains signed provenance but leaves sources and labels plaintext. Add a separate AES-256-GCM format that encrypts all inner artifacts in memory before the first SQLite write. Host-supplied keys and externally retained snapshot digests remain outside the file. Bind each ciphertext to its snapshot, artifact name, format and selected key ID. Reuse the existing bounded storage primitives and factor signed semantic verification into an internal shared helper so both readers apply the same current authority checks.

Twelve new methods cover durable roundtrip, plaintext absence in the file, random ciphertext separation, wrong/malformed keys, current signing-policy expiry/revocation, ciphertext corruption and truncation, rehashed tampering, cross-artifact swaps, altered snapshot associated data, invalid contracts, no-overwrite, cross-format rejection and disagreement. Installed verification exercises encrypted reopen and wrong-key rejection. Review corrected a fixture filename collision before publication; no product bypass was found in that test failure.

This delivers local at-rest encryption, not managed key custody, organizational identity or curator/evaluator authorization. Random nonce use requires a conservative host-controlled key lifetime. Existing plaintext files are neither rewritten nor removed. Managed key/access integration is the next increment. See [contract](../contracts/encrypted-curation-v1.md) for resource, key-lifecycle and process-memory boundaries.
