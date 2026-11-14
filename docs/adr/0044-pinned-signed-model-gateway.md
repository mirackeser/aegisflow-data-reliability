# ADR-0044 — Pinned signed model-gateway and usage inquiry

Status: Accepted for the local conformance profile.

Reuse the already qualified pinned-IP mTLS HTTP client instead of introducing another networking stack. Add a gateway adapter bound to exact prepared input, approved operation/model and quote, plus an independent metadata-only usage inquiry. Gateway result signatures use a separate model-gateway-result purpose; generated claims still pass the existing Judge.

Carry the original operation deadline into the network budget, check current signer authority before sending, verify signed identities/caps after receiving and never infer free usage from HTTP failure. Usage inquiries release the ledger lock during network I/O and verify freshness after receiving evidence. Explicit operator reconciliation remains separate.

Local validation: 771 application + 13 security/hygiene methods = 784 distinct tests, twelve new. Python 3.12: 4,534 statements / 1,360 branch exits; Python 3.14: 4,471 / 1,360; both 100%, no exclusions. Existing core-gateway tests are preserved byte-for-byte; a test-file naming collision found during full regression was corrected before delivery. Thirteen fresh installed checks include real ephemeral TLS/signature gateway round trips and read-only signed usage inquiry. Dependency/secret/hygiene and PR/main CI are delivery gates; final links are in the PR.

Qualification covers exact input and Judge/accounting, no DNS lookup, pin denial, revoked/expired grant preflight, mutated dispatch, wrong signed model/quote/input/operation, malformed/tampered replies, response caps, stalled response deadlines, HTTP ambiguity holds, concurrent ledger changes during inquiry, query scope/configuration and original deadline preservation. No vendor API/model calls occur.

Remaining deployment responsibilities include gateway ingress authorization, upstream receipt retention, managed current authority, credential custody, real provider-specific tokenization/billing and independent model quality. Successful wire proof envelopes are not automatically persisted locally; usage inquiry returns exact evidence for existing durable recovery decisions. See the [contract](../contracts/model-gateway-v1.md).

Next: select and document a concrete provider-specific adapter and activation conditions (model/version, region/retention, data class, credential delivery and spending), and qualify independent usage acquisition before real calls.
