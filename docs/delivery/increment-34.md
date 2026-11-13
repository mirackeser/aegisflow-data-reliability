# Increment 34 — Encrypted signed evidence

Signed curation sources, labels, detached envelopes, public grant policy and the original signed header are now encrypted in memory before transactional storage. Every read requires the external digest, external encryption key and current signing authority. Existing formats remain compatible through their own APIs.

Validation: 640 application + 13 security/hygiene methods = 653 distinct tests, including 12 new encryption methods. Whole application coverage: 3699/3699 statements and 1104/1104 branch exits, 100%, zero exclusions. Full local Python 3.12/3.14 suites, ten installed-package checks, dependency/secret/hygiene scans and exact-revision PR/push/main CI are delivery gates; the PR records final results.

Self-review covers cryptographic associated-data binding, random nonce/key lifecycle, plaintext exposure paths, bounded ciphertext overhead and shared signed validation. No runtime key or real enterprise data is committed. Next: host key authorization and curator/evaluator access separation, then provider recovery/accounting and independent model evaluation. See [ADR-0034](../adr/0034-encrypted-curation-at-rest.md).
