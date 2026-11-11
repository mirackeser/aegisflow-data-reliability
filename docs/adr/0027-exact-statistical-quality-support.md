# ADR-0027: Versioned exact statistical support for quality thresholds

Status: Accepted. Delivery requires exact-revision PR and post-merge main CI evidence recorded in the PR.

## Problem and decision

Protocol v1 compares observed rates against predeclared thresholds. Exactly 95% observed success does not establish sufficient statistical support for a 95% population target. Likewise, 30/30 in a rare family can pass the v1 support floor while leaving substantial uncertainty. Preserve v1 byte contracts and historical results; add v2 with an exact one-sided binomial support test for overall accuracy, each class precision/recall and every declared family accuracy.

For each metric with `s` successes, `n` trials and predeclared target `p0`, compute the upper binomial tail `P(X >= s | n, p0)`. Support requires this tail to be at most `alpha / m`, where `m = 1 + 2 * 3 + number_of_declared_families`. This is the inversion of an exact lower confidence bound at the target; the implementation returns the support decision, not a rounded confidence interval. The binomial construction follows [NIST's exact proportion intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm). [Bonferroni's inequality](https://itl.nist.gov/div898/handbook/prc/section4/prc473.htm) supplies the simultaneous correction.

The fixed method is `exact-binomial-bonferroni-v1`. The default family-wise error budget is 500 basis points (5%), with only stricter budgets down to one basis point permitted. The existing target defaults stay 9500 basis points (95%). Error budget and accuracy target are different quantities. All comparisons use integer arithmetic on rational probabilities; no floating point approximation or external statistics dependency is introduced. Inputs are bounded to 10,000 trials and at most 71 comparisons. Zero trials/successes and a requested perfect population rate receive no support. Early rejection is safe because remaining probability terms are nonnegative.

Every v1 provenance, support, error, unsupported-claim, class and family rule remains in force. Version 2 additionally requires a trusted-host `sampling_assumptions_approved` attestation, default false. Registration binds the complete method, targets, significance budget and attestation before outcomes. Registered failed results remain in history. New model acceptance should use v2; v1 remains historical observed-rate evidence and neither version is deployment authorization.

## Assumptions and limits

Within each metric, the inference assumes independent Bernoulli observations under the specified sampling design. Correlated incidents, repeated customers, artificial class balancing and distribution shift can invalidate population inference. In particular, precision and overall accuracy depend on the sampled prevalence/mixture. The trusted domain reviewer must approve representativeness, grouping and sampling before setting the attestation. Local booleans are not authenticated proof.

The simultaneous correction covers the fixed metrics in one predeclared evaluation, including empty/failed metrics. It does not correct repeated candidate selection, optional stopping or repeated use of the same holdout. Those require a separately governed selection protocol, fresh confirmation data or sequential error spending. Under the assumptions, the significance bound concerns the procedure's long-run false-support rate; it is not a posterior probability, guaranteed model correctness or assurance under future drift. Independent labels, protected sealing, authenticated provenance and activation enforcement remain necessary.

## Review and evidence

Self-review identified observed-rate uncertainty as a missing acceptance condition and added the sampling attestation before shipping the new version. Reproduce the v1/v2 distinction with 1140/1200 synthetic correct outputs: v1 passes its observed thresholds while v2 blocks statistical support. A perfect 30-case family also blocks. The exact lower-limit example from NIST (4/20, lower bound approximately 0.071354 at one-sided 5%) is checked on both adjacent basis points. An independently written rational sum checks small count grids, targets and multiplicities. Test alpha equality, stricter budgets, large supported/unsupported samples, malformed policies, version/model/data substitution, provenance, zero predictions and registered blocked-result replay. Existing v1 regression tests remain unchanged.
