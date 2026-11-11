# Increment 28 — Retained and verified curation artifacts

Adds private local snapshots binding exact development/candidate bytes, both annotations, approved reviewer names and recomputed manifest/result hashes. Agreement and disagreement are retained. Every reopen verifies structure, external digest and curation semantics before returning evaluator labels. Existing files are never overwritten; normal SQL mutations are denied.

Validation: 564 application + 13 security/hygiene methods = 577 distinct tests, including 11 new snapshot tests. Python 3.12/3.14, critical statement/branch gates, all nine installed checks and security/dependency checks are required before merge. The PR records exact-head CI and post-merge main results.

Scope: local trusted-host integrity and retention. No encryption, authenticated reviewer, access separation, adjudication, live model call or UI is claimed. See [ADR-0028](../adr/0028-verified-curation-snapshots.md). Next is authenticated curation and protected storage, followed by independently governed real evaluation.
