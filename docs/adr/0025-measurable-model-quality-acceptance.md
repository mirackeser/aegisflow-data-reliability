# ADR-0025: Measurable model quality acceptance before activation

Status: executable candidate policy; C03 first slice prioritized after the user's quality requirement. B08 recovery work remains partial.

## Decision and thresholds

Compute PASS/BLOCK from exact ground-truth cases and prediction records, never from caller-supplied percentages. Freeze dataset bytes, model revision hash, policy and expected scenario families before evaluation. Require exact one-to-one case coverage, unique IDs and unchanged dataset/model binding. Contracts reject extra fields, duplicate JSON keys, invalid labels, coercible policy values and nonfinite data.

Candidate defaults: at least 1,000 cases, 100 truth cases per each of the three existing diagnostic classes and 30 per expected scenario family; at least 95% overall exact accuracy, 95% precision and recall for each class, and 95% exact accuracy per family. Require zero execution errors and zero independently reviewed unsupported claims. ABSTAIN and ERROR remain in the accuracy/recall denominator. Undefined precision/recall blocks acceptance. Integer basis-point comparisons avoid rounding at the boundary. These are observed sample thresholds, not a statistical lower confidence bound or proof of generalization.

All four provenance attestations (independent labels, sealed data, leakage check and independent claim review) default false. Any false flag blocks. The flags are trusted-host attestations, not cryptographic proof. Unsupported-claim annotations must come from independent review, never the model being evaluated. Actual sealed cases, identity/annotation review and preregistration/registry enforcement remain required before live activation. Public synthetic fixtures cannot supply that evidence.

The module supplies no model calls, credentials, auto-deployment or live accuracy measurement. Future C05/release integration must require an accepted result bound to its exact model/data/policy revision; a library PASS alone is not release authorization. Production thresholds remain subject to domain risk review and can be tightened. The supported labels concern diagnostic assessment, not broad causal root-cause accuracy.

## Self-review and tests

Reviewed for threshold rounding, class/family imbalance, selective-accuracy inflation, provenance defaults and spoofed aggregate percentages. Added explicit integer checks after noticing JSON Schema treats integral floats as integers. Include exact 95% boundary and one-case-below, all-abstain, rare-family failure despite high overall accuracy, separate precision/recall failure, unsupported claims/errors, changed hashes and missing/duplicate cases. Installed checks prove a perfect tiny public fixture is BLOCKED. No new model-performance claim is made.

The strict parser bounds each document to 1 MB; schemas additionally bound arrays to 10,000 cases and 64 families. This local gate is for bounded evaluation batches. Larger datasets and uncertainty estimates require a later version, not silent truncation.
