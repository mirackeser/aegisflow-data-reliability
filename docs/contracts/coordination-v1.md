# Coordination v1 contract reference

The authoritative schema files are packaged in src/aegisflow_dr/coordination/schemas. They describe internal JSON, not MCP or A2A wire objects. Python API: contracts.parse(name, bytes) and contracts.encode(name, mapping). The parser accepts only UTF-8 JSON bytes up to 16,384 bytes, rejects duplicate keys/nonfinite values, and validates using Draft 2020-12. Only packaged schemas are loaded, with offline reference resolution. Validation errors do not echo field values.

## Task

All fields are required: version (1 as string), task_id (1–64 controlled ASCII identifier characters), incident_id and run_id (canonical lowercase UUID-shaped identifiers), capability (evidence.read or assessment.review), required_tags (1–4 unique controlled tags), depends_on (0–8 unique task IDs). Graphs contain 1–8 tasks; the host checks shared incident/run, dependency existence, acyclicity and exactly one matching enabled worker. Agent identity, grants, endpoint URLs and credentials cannot be supplied in a task. Role IDs are registry metadata, not authenticated remote identities.

## Proposal

All fields are required: version, run_id, incident_id, assessment and evidence_sha256. Assessment is restricted to NO_FAILURE_OBSERVED, SOURCE_QUALITY_FAILURE or TRANSFORMATION_RECONCILIATION_FAILURE. Evidence contains 1–4 unique lowercase SHA-256 strings, and must exactly match the source and accepted report hashes used in the completed investigation. Free-text causal claims, confidence percentages and policy instructions are not accepted. A syntactically valid UUID or checksum does not prove record existence or ownership.

## Verdict and receipt

A verdict contains version, run_id, decision, reason, assessment, reviewer (A27), mode (deterministic) and record_sha256. ACCEPT/MATCH means the scoped assessment and evidence set agree. REJECT/CONTRADICTION and REJECT/EVIDENCE_MISMATCH distinguish false assessment and unsupported citations. ABSTAIN identifies incomplete, inconsistent or unavailable context; unavailable context has no exposed record hash. The assessment is null on abstention. A receipt binds task_id, registry agent_id, state, result_sha256 and sanitized reason; COMPLETED requires a result hash and null reason, FAILED/BLOCKED require no hash and the appropriate failure reason. A completed review task may correctly produce REJECT or ABSTAIN.

Every object rejects additional properties. Outbound messages use sorted compact JSON with UTF-8 and no nonfinite numbers; these are local checksums, not RFC 8785 signatures. The task/dependency association and ephemeral receipts are process-local; durable signed message envelopes require a later identity/transport design.

## CLI

After an existing run has been recorded, write proposal.json with its real identifiers, assessment and source/step report hashes, then run:

```sh
python -m aegisflow_dr review-investigation --db work/incidents.db --proposal work/proposal.json
```

The CLI reads at most 16,385 bytes to detect oversized proposals. Exit 0 means ACCEPT; 1 means REJECT or ABSTAIN; 2 means rejected input/store/command. Output includes validated tasks, metadata receipts and verdict only. Neither JSON nor repr output exposes raw rows. The database remains a trusted, unencrypted local synthetic store.
