# ADR-0016 — Durable provider-neutral usage admission

Status: accepted for trusted local hosts; no provider activated.

## Context and decision

Prepared prompts already have byte limits and evidence binding. Bytes do not establish token counts, prices, or a safe retry policy. Add a separate SQLite usage ledger before implementing dispatch. Preserve evidence, run fingerprints, review queue and original architecture artifacts.

The host explicitly initializes a new empty database with a frozen lifetime token/cost/attempt/duration policy. A trusted adapter quote binds the exact prepared input digest, model, tokenizer/pricing/framing revision, input tokens, output cap and integer per-token rates. Quotes are host configuration; model response fields cannot set budgets or settle usage. Rates use nano-US dollars to avoid floating-point accounting. The adapter must conservatively account for every billable category and rounding; unsupported pricing requires denial before activation.

SQLite immediate transactions serialize admission and lifecycle updates across connections/processes sharing the file. Charged plus held usage must fit policy. Each request shares one original absolute deadline and a bounded number of attempts; only a known settled or cancelled attempt permits another reservation. Idempotency keys are hashed and bound to the exact request, quote and deadline. A receipt never grants repeat dispatch: start is a one-shot state transition.

Ambiguous in-flight outcomes retain their entire hold, including after restart. No timeout refund is inferred. UNKNOWN blocks further attempts for the same request and requires a future separately audited reconciliation process. A process crash leaving IN_FLIGHT also retains the hold. Known late usage can settle from IN_FLIGHT. Invalid or over-cap usage leaves the reservation intact for investigation.

## Boundaries and consequences

This is a trusted local accounting library, not a remote service, account-wide spending guarantee or multi-tenant authorization system. Local database/configuration access is trusted. Request hashes correlate data; they do not authenticate callers. Creating another request or ledger does not share per-request attempts or budget scope. No daily reset, garbage collection, operator reconciliation, distributed database, global tenant quota or retention service is supplied.

Admission checks the wall clock and a persisted nondecreasing observation watermark. A backwards clock denies mutations; operators must restore time before resuming. Start is rejected at expiry, but no running call is interrupted. A future adapter must apply the remaining deadline to its transport, enforce output caps, dispatch the exact snapshot once and report trusted usage or UNKNOWN on ambiguity. External effects cannot be made exactly once by this database transaction.

Next implement and simulate that adapter/dispatcher boundary, bounded retry/backoff and explicit model fallback policy. A fallback to another model needs a newly bound prepared input and an additional shared logical-operation budget; it must not silently reset attempts/deadline. Provider choice, data residency, pricing and live spending remain approval gates. Independently sealed evaluation remains necessary before model-quality claims.
