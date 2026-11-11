# ADR-0017 — One-shot synchronous advisory dispatch

Status: accepted for trusted local adapters and offline simulation.

The prepared prompt and durable usage ledger previously had no integrated invocation boundary. `advisory.dispatch` now validates the adapter revision against the approved quote, snapshots canonical immutable message bytes, reserves capacity and commits one start before calling the adapter. Concurrent/repeated keys cannot invoke twice, even after restart or settlement.

AdapterRequest carries exact message bytes, request digest, model, remaining milliseconds, output-token cap and maximum response bytes. AdapterResult separates trusted adapter usage from untrusted response bytes. Adapter code/configuration is trusted; neither a response nor a prompt may supply an adapter, quote or policy. No adapter is dynamically imported from external data.

Known usage is settled before reviewing content. Invalid/oversized responses and late results are rejected without refunding known usage. Invalid/missing/over-cap usage and adapter exceptions retain the full UNKNOWN hold. Cancellation propagates after attempting to mark UNKNOWN; if ledger recovery fails, IN_FLIGHT also retains the hold. Errors never include adapter exception text. No automatic retry or fallback occurs. Existing deterministic Judge outcomes are preserved, including rejection/abstention.

The remaining duration is sampled after atomic start and passed to the adapter. Both elapsed monotonic time and the absolute wall deadline reject late returned results. This synchronous wrapper cannot preempt arbitrary host Python, bound memory already allocated by a callback, or prevent a trusted adapter from making unauthorized out-of-band calls. Future transport adapters must enforce streaming/body/output limits, cancellation and deadlines at the I/O boundary. Tokenization, framing and provider pricing remain host-quote prerequisites, not capabilities supplied here. No live provider, tokenizer or model accuracy is introduced.

Ledger and external effects are not one atomic transaction. A crash after start can leave an IN_FLIGHT hold even when no call was made; conservative operator reconciliation is future work. Receipts are not reusable send authorizations. Requests/results contain operational metadata; no logging or credential persistence is added. No schema, original run fingerprint or evidence archive is changed.

Validation: 15 new integration/concurrency/failure tests; one-shot immutable inputs, exact limits, restart/duplicate denial, simultaneous dispatch, wrong revision/configuration, malformed result/usage/content, deadline rejection, cancellation, storage failure and independent Judge rejection. Dispatch statement/branch coverage is 100% (75 statements, 12 branch exits). Installed dispatch is checked outside the source tree.

Roadmap: B01/B02 are implemented for this trusted synchronous boundary. B03 supplies revision/input quote binding only; actual provider tokenization/pricing verification remains pending. B04 supplies remaining-limit propagation and late/oversized result rejection only; hard I/O enforcement/cancellation remains pending. Next implement a bounded simulated transport and typed known-failure classification before retry/backoff and shared fallback budgets. A04 defensive coverage and independent evaluation remain gates before live activation.
