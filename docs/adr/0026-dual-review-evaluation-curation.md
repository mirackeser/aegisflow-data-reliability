# ADR-0026: Label-free evaluation manifests and dual-review reconciliation

Status: Proposed implementation; dependent on PR #28 and exact-revision CI before merge.

## Context

The quality gate can calculate acceptance only as reliably as the source cases and labels it receives. Public development fixtures do not establish independent performance. A repeated group can inflate support; matching aggregate class counts cannot reveal missing or conflicting individual annotations. C01/C02 need an offline preparation boundary before authenticating curators and conducting a sealed evaluation.

## Decision

Add `benchmark.curation` without provider access, deployment authority or new dependencies. `prepare_manifest(development_bytes, candidate_bytes)` accepts closed label-free corpus contracts, binds exact source bytes and emits only case/family/group identifiers and conservative content signatures. It rejects duplicate case IDs, repeated candidate groups/content and known cross-split ID/family/group/content overlap. Row/column order, surrounding whitespace, BOM and transformation changes do not bypass the existing conservative CSV signature. Repeated families inside the candidate set remain valid; repeated groups do not.

`reconcile_annotations` requires the expected manifest digest, exactly two distinct trusted-host reviewer IDs and exactly one annotation per manifest case from each reviewer. Artifact/model predictions, unknown properties, extra/missing/duplicate cases, unknown reviewers, reused identities and manifest substitutions fail closed. Any label disagreement yields `DISAGREEMENT`, sorted case IDs and no exported quality cases. Exact agreement yields deterministically ordered quality cases plus their digest and both exact annotation digests. Labels are restricted to the three currently supported assessment classes; ambiguous cases require separate taxonomy and adjudication work.

The existing registered quality gate consumes the exported case bytes through its existing API. Curation never automatically sets provenance flags, lowers thresholds or changes acceptance decisions. Agreement cannot authorize a model call, release or remediation. Preserve the source artifacts, manifest, annotation bytes, disagreement reports and quality history in a host-controlled private record before predeclaring model evaluation.

## Trust and limitations

Reviewers are local names supplied by the trusted host. Distinct names do not prove two people, authentication, blind annotation or independence. The trusted host must distribute label-free source packages separately, prevent prediction/label leakage, establish source rights and independently review claim correctness. This implementation does not itself distribute packages, store annotations, adjudicate disagreement, seal an encrypted holdout, attest timestamps or enforce model/curator access separation. Candidate data and labels must not be committed to the public repository.

CSV signatures are intentionally conservative and may reject distinct cases that normalize identically. They cannot detect paraphrases, semantic duplicates, related unseen groups or contamination in model pretraining. Exact dataset hashes bind bytes rather than establish quality or independence. Correlated groups require domain review; numerical support alone is insufficient. Statistical uncertainty and calibration gates remain planned before model activation.

## Review and validation

Adversarial tests cover source byte changes, known split overlap, BOM/order/whitespace/transform variants, duplicate support inflation, malformed/oversized/closed contracts, manifest substitution, reviewer reuse, coverage mismatches and disagreement. An integration test passes agreed synthetic annotations through protocol registration/evaluation and verifies that provenance/sample gates still retain `BLOCK`. Synthetic tests establish these mechanics only.

Self-review also corrected increment 25's application-test subtotal (523 + 13 = 536) and made the uppercase UUID rejection fixture deterministic. No defect was reproduced in the existing quality calculations or usage/recovery execution during this scoped review. Full required gates and installed-package checks apply; CI waiting is not completed DoD.
