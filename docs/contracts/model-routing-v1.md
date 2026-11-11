# Model routing v1 — Trusted local profile

Modules: `advisory.routing`, `advisory.route_store`. Normative exported schemas: [plan](advisory-route-plan-v1.json) and [event](advisory-route-event-v1.json). Runtime/export equality is tested. These are closed bounded contracts, not public network APIs.

1. Create a new bound version 3 usage ledger with `routing=True`. Set `max_total_attempts` and bind one investigation, approved models and absolute deadline.
2. Construct an immutable tuple of 1–8 `RouteCandidate(prepared, quote, adapter)` values, no longer than the shared attempt cap. Every model must be distinct and eligible. Every quote must bind the final input and adapter revision. The whole tuple is validated before any claim or call.
3. Call `execute_route(ledger, candidates)`. It persists the plan and claims the operation once, dispatches candidates in order and stops according to [ADR-0022](../adr/0022-bounded-durable-model-routing.md).
4. Use `RouteJournal(ledger).snapshot()` to inspect `UNCLAIMED`, `RUNNING` or terminal status and sanitized ordered events after reopening. Plan identity includes generated request IDs through hashes: newly preparing a request is a different plan, not permission to resume.

The result contains `version`, `status`, `events` and `replayed`. Each event contains zero-based index, model ID, request hash, attempt UUID, dispatch status and nullable review status. `REVIEWED` requires one of `VERIFIED_ADVISORY`, `REJECTED_ADVISORY`, `ABSTAIN`; all other dispatch statuses require null review status. A deadline terminal status can coexist with a verified event: the operation was too late. Admission denial before a new dispatch adds no event; existing ledger receipts remain authoritative for usage.

The plan contains the operation binding hash and ordered model/request/input/quote hashes. It contains no callable, prompt or raw evidence. `RouteJournal.claim/record/stop` and dispatch ownership tokens are internal trusted-host coordination primitives; model-generated content cannot call them. Low-level host misuse, malicious database replacement and out-of-band provider calls are not prevented by this library.

A finished exact replay returns persisted history with `replayed=true`, never a fresh review. An unfinished route requires explicit future B08 recovery; do not create another ledger or alter the plan to bypass ambiguity. Legacy version 1/2 accounting remains supported without rewriting. Version 3 is opt-in for new scopes only.
