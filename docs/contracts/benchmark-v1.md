# Public validation contract v1

Run `python -m aegisflow_dr.benchmark` after installation. Exit 0 means all deterministic labels/tool sequences match; exit 1 means regression failure. Configuration/contract faults raise sanitized BenchmarkError rather than manufacturing a passing result.

Machine schemas: benchmark-suite-v1.json, benchmark-prediction-v1.json and benchmark-report-v1.json. Runtime definitions are authoritative and equality-tested against exports. Reports record suite/scorer and workflow/policy hashes. Identical same-runtime executions produce identical reports; fingerprints can differ across Python/SQLite versions.

Limits: 1,000,000 suite bytes, 2–64 cases, 16,384 characters per CSV. Both development/validation splits are mandatory. Case IDs are unique; group IDs, family labels and conservative CSV signatures cannot cross splits. Normalization ignores row/column order and surrounding whitespace and intentionally over-rejects some similar content; it is a heuristic, not complete semantic deduplication. Malformed quoted CSV rejects. No caller SQL, URL, path or policy is accepted.

Predictions contain exactly case_id, assessment and tools, one per case. Labels are NO_FAILURE_OBSERVED, SOURCE_QUALITY_FAILURE, TRANSFORMATION_RECONCILIATION_FAILURE, ABSTAIN or ERROR. No confidence value is accepted. Known operational exceptions become ERROR without raw details; inconclusive workflows become ABSTAIN. Unexpected programming faults propagate. Future model predictions require a separate versioned contract.

For N cases, C correct, A abstentions and E errors: exact_match=C/N, coverage=(N-A-E)/N, selective_accuracy=C/(N-A-E). Undefined rates are null. Tool order must match exactly. Per-class FN=support-TP includes abstentions/errors. Binary false_negative counts a true failure called healthy; abstentions/errors have separate counters that must be inspected alongside it. Zero-support classes do not invent recall.

The closed report contains split/family metrics, full confusion matrix, predictions, hashes, model_calls=0, blind_holdout=false and explicit public synthetic scope. No raw datasets are returned. Schema validation checks shape; authoritative arithmetic comes from score(suite, predictions), not external metric assertions.

The frozen gate requires every label/tool sequence to match. This public fixture agreement is not model accuracy or sealed testing. See ADR-0013 for future held-out curation and provider acceptance gates.
