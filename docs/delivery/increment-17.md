# Increment 17 — Known adapter failure accounting

The trusted adapter can now return AdapterFailure(kind, input_tokens, output_tokens). Exact kinds RETRYABLE and TERMINAL produce KNOWN_RETRYABLE_FAILURE and KNOWN_TERMINAL_FAILURE after durable settlement. The dispatcher never derives these classifications from model content or HTTP status alone. The adapter must establish delivery/usage certainty; timeouts, disconnects and ambiguous exceptions remain UNKNOWN with full holds.

Known zero usage can release its reservation. Known billed failures are charged. Late failures settle known usage but return DEADLINE_EXCEEDED. Invalid kind/usage or failed settlement retains the hold; no failure enters Judge review. A retryable label does not authorize automatic retry, reset a deadline or bypass attempt admission. No retry scheduler, fallback, live provider or hard transport cancellation is enabled.

Validation: 396 application + 13 security/hygiene methods = 409 passing tests. Seven new regressions cover known zero/billed outcomes, unrecognized classification, invalid usage, deadline expiry, settlement failure and duplicate-send denial. Advisory statement/branch coverage remains 100%. Installed dispatch also validates known failure settlement outside the checkout.

Next: bounded transport simulation and explicit cancellation/timeout enforcement, then a scheduler that consumes these known outcomes under the original deadline/attempt budget. Provider tokenization/pricing and sealed model evaluation remain gates. Existing persisted schemas, evidence fingerprints and architecture archive remain unchanged.
