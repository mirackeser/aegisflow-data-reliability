# Evidence context and prepared prompt v1

Entry point: advisory.context.PreparedAdvisory(runs, run_id, model_id=..., policy=ContextPolicy()). The host supplies an authorized InvestigationRuns reader and trusted model identifier. No service is contacted and no provider credential is accepted.

The schema in evidence-context-v1.json is equality-tested against runtime CONTEXT_SCHEMA. Context contains version, source digest and two/three known summaries. Source summaries expose status, bounded row/finding counts, findings_truncated and deduplicated fixed check names. Batch summaries expose status plus exactly two check-name/pass flags. Impact summaries expose fixed dataset/declared-lineage names and bounded downstream datasets. Each summary has its original report digest. Unknown content rejects.

No raw source or business identifiers/amounts, arbitrary report/column/message text, source record numbers, SQL or expected assessment enters context. Counts and digests are retained intentionally and are not anonymous; operational IDs are still present in advisory request metadata. Real data/provider use needs an explicit data policy before external transmission.

Prepared messages contain one static system instruction and one user JSON string with request_sha256, the existing advisory metadata request, projected evidence and closed response schema. The complete message array is canonically encoded and bounded. The response contract remains advisory-response-v1.json: it cannot invoke tools, change policy, supply free rationale or claim calibrated confidence.

Manifest fields: version, context_sha256, prompt_sha256, input_sha256, request_sha256, record_sha256, response_schema_sha256, policy, context_bytes, prompt_bytes and model_calls=0. Prompt identity includes version/system/context/schema/policy; input hash includes the full unique metadata-bearing message array. These are reproducibility/correlation hashes, not authorization or signatures.

Default byte limits: context 8,192 and full message array 32,768, configurable only by the trusted host within documented ranges. No truncation or fallback occurs on overflow. Request/prompt preparation must finish before any future provider call. Detached messages/manifest accessors protect the prepared bytes from caller mutation; a future transport must ensure it actually sends that snapshot.

Use prepared.request for immutable metadata bytes and prepared.review_response(raw_bytes) for the existing deterministic advice gate. Preparation rejects cross-read record changes. Later missing/changed evidence still causes abstention. Repeated preparations have the same context/prompt identity on identical inputs, but different request and full-input hashes due to unique request IDs.

This contract supplies no provider transport, actual tokenizer, usage accounting, spend reservation, deadline or calibrated model confidence. Those are the next admission-layer gates. See ADR-0015.
