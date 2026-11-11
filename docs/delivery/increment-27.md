# Increment 27 — Statistical support for model acceptance

Adds registered quality protocol v2 with exact one-sided binomial support, a predeclared family-wise significance budget and Bonferroni adjustment across all class/family/overall metrics. Sampling assumption approval defaults to false; every existing provenance/safety/support condition remains enforced. V1 semantics and historical registry records remain compatible.

Self-review reproduced the gap between observed 95% success and sufficient support for a 95% population target. Regression tests preserve v1 behavior and demonstrate v2 rejection at that boundary, insufficient rare-family evidence, empty predictions and invalid sampling/provenance approval. No actual model accuracy is claimed.

Validation: 553 application + 13 security/hygiene methods = 566 distinct tests, including 16 new statistical tests. Local Python 3.12/3.14 runs and all nine installed distribution checks passed. Critical coverage is 2,379 statements and 692 branch exits at 100%; candidate security/hygiene and dependency checks passed. See the PR for exact-revision CI evidence.

Next: authenticated independent curation, protected sealed holdout and adjudication, sampling/selection governance and approved provider evaluation. B08 authenticated recovery/usage attestations and actual provider quoting remain open. No UI or live provider access is introduced. See [ADR-0027](../adr/0027-exact-statistical-quality-support.md).
