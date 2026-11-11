# Increment 12 — Evaluation contracts and frozen public baseline

Delivered: closed suite/prediction/report schemas, frozen packaged suite/digest, group/family/content split checks, label-free execution projection, deterministic split/family scoring, installed CLI and CI coverage gates. The original ten development cases and existing workflow/evidence/queue schemas are unchanged.

Eight newly curated public validation cases cover quoted/unicode records, combined source violations, normalization collisions and transform-loss combinations. Baseline agreement is 10/10 development and 8/8 validation with zero abstentions/errors and zero model calls. These cases were authored/inspected during development and are not a blind holdout. Curated family partitioning does not establish unseen failure mechanisms.

Measured locally on 2026-11-11: 314 application tests plus 13 security/hygiene tests passed, **327 distinct methods**, including 18 new benchmark tests. Core validation/scoring, runner and report cover 161/161 statements and 38/38 branch exits. Existing critical coordination/workflow/security/integration coverage remains 100%. Legacy uncovered paths remain visible in the overall coverage report; the new CLI is exercised in both subprocess and failure-exit tests. Coverage is not model accuracy.

Negative tests cover wrong labels/tool order, false positives/negatives, abstention/error denominators, all-error execution, label isolation, unknown/duplicate/missing predictions, schema/digest drift, invalid fields/types/Unicode/nonfinite JSON, malformed CSV and group/family/near-copy leakage. Installed checks validate packaged fixtures, scoring, report contract and repeatable CLI execution outside checkout. Security gates retain dependency/full-history/PDF/file scans.

Next: provider-neutral model prediction/evidence contracts and acceptance/sealed-evaluation process before live calls. Independently curated held-out data, calibration, citation/abstention, token/cost/latency measurement and deployment thresholds remain pending. No provider, production listener or UI is enabled.
