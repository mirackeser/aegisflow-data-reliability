# Increment 26 — Evaluation curation preparation

Delivery follow-up: PR #28 completed first. PR #29 was retargeted to main, synchronized and merged after all four PR and all four push checks passed. Post-merge main run 43101511334 passed all four jobs. The original queue delay is retained in historical PR evidence.

Add label-free exact-byte manifests, conservative known split-leakage/duplicate-group checks, two-reviewer annotation contracts and disagreement-safe export into the existing registered quality gate. No provider calls, automatic adjudication or production identity authority are added. See [ADR-0026](../adr/0026-dual-review-evaluation-curation.md) and [curation contracts/data flow](../contracts/evaluation-curation-v1.md).

Local validation: 537 application + 13 security/hygiene methods = 550 distinct tests, including 14 curation tests. Application tests pass on Python 3.12 and 3.14. Critical coverage is 2,322 statements and 672 branch exits at 100%, including the new curation module. All nine installed-package checks, dependency audit and candidate security/hygiene checks pass. GitHub CI and post-merge status are recorded in the PR; local success does not establish independent model accuracy.

Self-review corrected an inaccurate subtotal in increment 25 and replaced a probabilistic uppercase UUID fixture with a fixed invalid value. Synthetic agreement is explicitly tested to remain blocked by model provenance/sample gates. No independent dataset or measured model result is claimed.

Next: independent source/label ownership and authenticated, access-separated curation/sealing; preserve disagreement/adjudication history before the first controlled model evaluation. B08 provider attestations/durable authenticated decisions, provider quoting and statistical/calibration gates remain open. UI work remains deferred.
