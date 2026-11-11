# Operation binding v1

The normative closed JSON Schema is [advisory-operation-v1.json](advisory-operation-v1.json), exported from the runtime and checked for equality in tests. All fields are mandatory; extra fields, duplicate JSON keys, malformed hashes/UUIDs, duplicate models, booleans as deadlines and oversized payloads are rejected. Maximum payload: 16,384 bytes; 1–16 unique model IDs; 1–4 unique evidence hashes. Model identifiers use the existing advisory request grammar.

`bind_operation(prepared, operation_id=..., allowed_models=(...), deadline_ms=...)` takes a trusted `PreparedAdvisory`, snapshots its identity and requires the initial model to be eligible. The trusted host supplies the UUID and immutable model tuple. The evidence set is normalized by sorting. `OperationBinding` retains immutable validated bytes.

`initialize_usage(path, policy, operation=binding)` creates a new version 2 ledger only if `policy.max_total_attempts` is set. `UsageLedger(path, operation_id=...)` validates persisted identity and policy. `reserve` requires matching incident/run/record/evidence, prompt/context/response schema, model eligibility and exact deadline, before existing per-request/shared budget checks. Request IDs, full input hashes and model-specific quotes may differ between eligible preparations; evidence identity may not.

The snapshot reports version `2` without exporting the binding or its operational identifiers. Version `1` continues to describe an unbound legacy ledger. Do not interpret possession of an operation UUID as authentication, or a reservation receipt as permission to send again. See [ADR-0021](../adr/0021-bound-operation-admission.md) for trust and recovery boundaries.
