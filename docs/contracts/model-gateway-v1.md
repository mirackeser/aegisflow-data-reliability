# Pinned signed model-gateway and independent usage inquiry v1

Module: `aegisflow_dr.advisory.gateway`; install `.[recovery]`. These are explicit client profiles for an operator-controlled gateway, not an upstream vendor SDK or a deployed service. Qualification uses temporary loopback servers and zero live model calls.

## Bound model dispatch

`gateway_adapter(prepared, quote, operation, endpoint=..., material=..., grant=..., clock_ms=...)` returns the existing `Adapter`. It verifies approved operation/model eligibility and exact prepared-input/quote binding. The host supplies an `EgressPolicy`, strict TLSFiles, current operation-scoped `RecoverySigner` with purpose **model-gateway-result**, and trusted current-time function. Private keys are not accepted by this API; existing TLS key files require restrictive permissions.

The exact request/operation/input/quote/model identities are fixed at adapter construction. Each send rejects changed dispatch bytes, model, request or output cap. Grant revocation/validity is checked before transmitting the request. Grants are immutable host snapshots: the host must replace/disable configured adapters when authority changes; no managed issuer/revocation feed is deployed here.

The request carries closed metadata, exact minimized messages encoded as hex, original output cap and remaining milliseconds. The network budget is the minimum of dispatch remainder, original operation deadline minus current host time, and 10 seconds. No fresh operation deadline is created. The shared HTTPS client pins the literal IP and exact server leaf, checks CA/SAN/TLS 1.3 and client certificate identity, and uses a shared socket-I/O deadline. DNS lookup, proxy discovery, redirects and automatic retry are not used. Host Python/file preparation remains trusted; this is not arbitrary-code process preemption.

The gateway returns `{result, signature_hex}`. Its closed result binds operation/request/input/quote/model, exact response bytes, usage counts and receipt digest. The detached envelope signs the canonical `encode('gateway-result', result)` bytes using the existing domain-separated recovery signature format and the dedicated gateway-result purpose. Verify current grant/time, signature, all identity bindings and exact integer token caps before returning `AdapterResult`.

The generated response remains untrusted. Existing dispatch settles known, verified usage and then invokes the independent deterministic Judge. Gateway signing does not establish claim correctness. Any HTTP/TLS/framing/signature/binding error propagates as a sanitized advisory failure; dispatch conservatively keeps UNKNOWN/IN_FLIGHT holds. HTTP status alone never proves zero usage or permits fallback.

## Bounds

Complete JSON wire messages are at most 16,384 bytes. Request messages are at most 8,192 raw bytes before hex encoding; the full-frame bound can be tighter after metadata. Model responses are at most 4,096 raw bytes; signature envelopes at most 2,048 raw bytes. Smaller dispatch response limits still apply. Excess input/output is rejected rather than truncated. No source prompt/body, key, URL or provider error detail is included in rejection messages.

Successful gateway signature envelopes/receipt contents are not automatically retained in the local usage ledger; that ledger persists accounting and provenance digests under its existing contract. The operator gateway must retain independently inspectable upstream receipts. The separate usage inquiry below returns exact signed evidence for durable decision/reconciliation records.

## Independent usage inquiry

`fetch_usage_attestation(ledger, attempt_id, endpoint=..., material=..., grant=..., now_ms=..., timeout=5.0)` supports v3/v4 routing ledgers. The issuer grant must have usage-attestation purpose and exactly match the operation. Expired/revoked grants reject before I/O.

Inside a short ledger transaction, validate the ledger and capture current recovery snapshot/assessment plus unresolved attempt/input/request/quote digests. Release the lock before the network call. The closed query contains metadata only, with no prompt or generated response. The gateway returns exact `attestation_hex` and `signature_hex` under the existing signed usage contract.

After I/O, reacquire the ledger transaction and invoke existing usage-attestation verification with the current clock/grant and current snapshot. A concurrent ledger change makes the reply stale and rejects it. Return exact signed bytes plus verification; do not record a review, release a hold, settle accounting or resend. Explicit signed operator reconciliation remains a separate authority.

```mermaid
sequenceDiagram
  participant H as Bound host dispatcher
  participant G as Pinned mTLS gateway
  participant J as Deterministic Judge
  participant U as Usage ledger
  H->>G: Exact prepared input + operation/quote + original time budget
  G-->>H: Structured result + separately signed usage metadata
  H->>H: Verify signer, scope, bytes and caps
  H->>U: Settle known verified usage
  H->>J: Verify untrusted generated claims
  Note over H,U: On ambiguity, retain the full hold
  H->>U: Capture metadata-only recovery query
  H->>G: Fetch independent signed usage evidence without ledger lock
  G-->>H: Exact scoped usage attestation + signature
  H->>U: Revalidate current snapshot under lock
  H-->>H: Return evidence; operator reconciliation is separate
```

## Deployment and accuracy gates

The gateway service must separately enforce client operation/resource authorization, upstream credential custody, provider/tokenizer/pricing/framing revisions, billable category completeness, output/transport limits and receipt retention. This module supplies no public ingress server, API key storage, provider selection or real model evaluation. Approved issuer signatures authenticate assertions; they do not independently prove all provider charges.

Before real calls, record provider/model/version, region/retention policy, approved data class, runtime credential delivery, spending ceiling, authority/revocation ownership and independently measured quality protocol. Local protocol PASS and code coverage do not measure model accuracy. Next work should turn these into a concrete provider-specific adapter/activation record and independently acquired usage qualification.
