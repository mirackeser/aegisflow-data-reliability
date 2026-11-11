# ADR-0020 — Dedicated shared budget foundation

Status: accepted as the first local B07 slice; automatic fallback remains gated.

UsagePolicy adds optional max_total_attempts (integer 1..100000; default None). When explicitly set, the dedicated ledger bounds attempts across all prepared requests/models; every existing attempt counts, including cancelled and zero-use calls. Admission also requires the first recorded absolute deadline and rejects a new request while any prior attempt is RESERVED, IN_FLIGHT or UNKNOWN. Existing charged-plus-held token/cost totals remain shared. All checks occur in the same immediate SQLite transaction. Same-key receipts remain readable at the cap; they never grant redispatch.

The host must dedicate one ledger to one logical operation and share it across its model attempts. This slice does not durably bind an operation ID, evidence record or model allowlist; host ownership remains trusted. Creating a new ledger/request is not an account-wide security boundary. Automatic routing, model switching after UNKNOWN, independent per-tenant/global quotas and reconciliation are not introduced. Next design persisted operation identity/model eligibility before enabling automatic fallback.

No database tables/schema version change. Missing max_total_attempts in old stored JSON is read as None without rewriting the metadata, retaining prior behavior. Old code will reject new policy JSON rather than silently ignoring its extra restriction. Existing source/run/queue schemas and execution fingerprints remain unchanged.

The offline demo uses one retained synthetic run, three separately bound fixture model requests, known trusted token/rate fixtures and a dedicated two-attempt ledger. The host explicitly dispatches the primary and secondary fixture; no production routing algorithm is claimed. The first known failure charges four nUSD; the verified secondary charges 22 nUSD; the third call is denied before invoking its adapter. Output exposes ordered sanitized events and aggregate policy/usage, with no raw data, prompts, keys, database path or operational identifiers. It is a functional backend demonstration, not measured model accuracy or the future UI.

Run python -m aegisflow_dr.advisory.demo after installation (or PYTHONPATH=src from the checkout). Fixture prices/token counts are invented test inputs, not provider estimates. The demo uses temporary synthetic databases, zero network/model calls and preserves retained evidence.

Validation covers cross-model/reopen limits, UNKNOWN blocking, cancelled attempt counting, shared deadline, concurrent admission, idempotent receipts at cap, bad policy types, legacy JSON without rewrite, repeatable sanitized demo and the actual module entrypoint. Existing installed checks exercise the demo outside the checkout.
