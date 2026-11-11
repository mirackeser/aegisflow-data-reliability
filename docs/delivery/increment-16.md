# Increment 16 — One-shot advisory dispatch

Integrated prepared input, trusted adapter identity, durable admission/start, known usage settlement and independent response review. Failure/cancellation ambiguity retains holds; no retry or provider is activated. See [ADR-0017](../adr/0017-one-shot-advisory-dispatch.md) for the lifecycle and explicit transport limits.

Validation: 389 application + 13 security/hygiene methods = 402 distinct passing tests, including 15 new dispatch tests. Dispatch covers 75/75 statements and 12/12 branch exits; existing critical coverage gates remain 100%. Nine installed-package checks include dispatch outside the source checkout. Dependency, candidate/PDF and full-history CI scanning remain release requirements.

Next: bounded simulated transport, typed known-failure outcomes and deadline/cancellation tests; then controlled retry/backoff. Provider-specific tokenizer/pricing, independent sealed evaluation, account-wide fallback budgets and production identity remain pending. UI stays deferred.
