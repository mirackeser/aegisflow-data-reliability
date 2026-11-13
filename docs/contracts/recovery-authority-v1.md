# Recovery evidence and durable decisions v1

Install `.[recovery]` to use the optional Ed25519 recovery modules. They require the same pinned cryptography version as the test/curation profiles. Existing unsigned recovery review packets remain advisory inputs; their bytes alone confer no new authority.

## Trust and signed inputs

`RecoverySigner` is an immutable host-provided grant containing principal UUID, one purpose (`usage-attestation` or `recovery-decision`), exact operation SHA-256, 32-byte Ed25519 public key, validity interval and terminal host-provided revocation flag. The host must supply the current grant and trusted time on every verification; stored public keys never become authority. Managed issuer enrollment, live provider receipt acquisition and organization-wide revocation delivery are deployment prerequisites.

A closed signature envelope binds purpose, principal, operation, exact payload digest, key digest and issued/expiry times. Signature bytes are domain-separated canonical JSON with `aegisflow/recovery/v1` followed by a NUL byte. Numeric times/counts require exact integers; booleans and floating point coercion are rejected. Private keys are never accepted or retained by the library. Public `signing_bytes(metadata)` defines the external signer format.

A usage attestation binds the exact operation, current recovery snapshot and assessment, attempt UUID, request/input/quote digests, receipt digest and actual input/output counts. `verify_usage_attestation` accepts only UNKNOWN or IN_FLIGHT attempts within reserved caps and current grant validity. It returns verified evidence and a **proposed** token/cost projection under the stored rates (`charged_tokens`, `charged_cost_nusd`); it does not apply those charges. The signature authenticates an approved issuer's assertion, not the underlying provider receipt contents or completeness of billable categories.

## Signed operator decision

Prepare the existing snapshot-bound review packet, then call `decision_payload(review, attestation=None, attestation_envelope=None)`. The operator signs these bytes, which bind the exact review, optional usage attestation and its exact signature envelope. Adding, removing or substituting an attachment invalidates the operator signature. Supported review actions remain KEEP_BLOCKED and REQUEST_USAGE_ATTESTATION. Attached usage evidence must have a different principal and different key from the operator; separate keys do not establish independently employed humans.

`initialize_decisions(path, operation_sha256=...)` exclusively reserves a new private mode-0600 local file and creates an operation-scoped log. Existing files are never overwritten. Initialization failure may leave a reserved incomplete file; inspect it rather than automatically replacing it.

`record_decision(path, ledger, review, operator_envelope, grant=..., now_ms=..., attestation=..., attestation_envelope=..., issuer_grant=...)` validates current ledger authority, current review snapshot, operator signature, attachment signatures and exact operation/attempt bindings. All attachment arguments must be provided together. Lock order is usage ledger → separate decision log. Holding the usage write lock prevents a competing usage writer from changing the reviewed snapshot before the log commits. No key/material/prompt/response is stored; exact signed metadata bytes and the host-recorded decision timestamp are retained.

The decision ID is the review UUID. Exact replay revalidates current authority/freshness, then returns the existing digest without adding a record or changing its timestamp. Reusing the ID for different bytes is rejected. Capacity is 10,000 decisions; exact replay remains available at capacity. SQLite update/delete triggers preserve append-only behavior for normal clients. Write/commit failures return a sanitized error and never release an unresolved hold. A retry after an uncertain commit must use the same signed bytes and ID while still authorized and fresh.

`decision_history(path, operation_sha256=..., after=0, limit=100)` returns bounded pages with sequence, recorded timestamp, digest and exact signed artifacts encoded as hex. It checks local record digests but does not reauthorize an expired signature or certify the record as a current decision. History is an audit export; it cannot authorize dispatch or settlement.

```mermaid
sequenceDiagram
    participant I as Approved usage issuer
    participant H as Trusted recovery host
    participant O as Operator signer
    participant U as Usage ledger
    participant D as Decision log
    I->>H: Signed usage assertion bound to current snapshot
    H->>H: Verify grant, signature, attempt and caps
    H->>O: Review plus exact evidence/signature digests
    O->>H: Signed decision payload
    H->>U: Hold transaction; validate current snapshot
    H->>H: Verify operator and independent issuer
    H->>D: Commit exact signed artifacts and timestamp
    H-->>O: Durable record digest
    Note over U,D: Usage remains held; no refund, resend or settlement occurs
```

## Boundaries and next gate

This is a local trusted-host evidence and audit implementation. A privileged owner can replace or consistently rewrite/roll back the files; local hashes/triggers are not independent tamper attestation. Grant revocation/fresh time is host supplied. A durable decision does not prove provider delivery, model quality, human independence, or production process isolation. Actual reconciliation requires a separately reviewed state-transition policy, independent provider accounting, operator authorization and crash-safe atomicity; automatic retry/refund remains blocked. There are zero live provider calls in qualification.
