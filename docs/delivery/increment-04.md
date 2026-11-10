# Increment 04 — Persistent source incident and evidence records

Goal: make existing deterministic source diagnoses recoverable, traceable and verifiable before model orchestration.

Acceptance criteria:

- Explicit initialization refuses existing files and unsupported schemas; opening never creates or migrates implicitly.
- Exact source bytes, canonical report, observation/summary claims, many-to-many links and lifecycle events commit atomically.
- Identical-key retries return one original incident; conflicting bytes are rejected, including concurrent requests.
- Source/report/claim/link/manifest/event corruption is rejected on read and replay; ordinary SQL update/delete attempts are blocked.
- Closure uses revision checking and appends history; it does not overwrite diagnosis or authorize remediation.
- Replay requires the recorded diagnostic code and Python runtime and reports mismatch without rewriting history.
- CLI operations work after process restart and from an installed package outside the checkout.
- Injected transaction failures, abrupt process exit and backup/restore are covered by regression tests.

Current scope is source CSV diagnosis. Durable batch artifacts, arbitrary model claims, enterprise identity, external audit anchoring and production recovery automation are not implemented. See ADR-0005. Test counts and exact-revision CI evidence are recorded in the PR.

Local validation (2026-11-10): 85 regression tests passed on Python 3.14. Built and installed the wheel in an isolated target. From outside the checkout, verified licensing, catalog, gateway, diagnostic/batch scenarios and a multi-process store-init/record/read/replay/close/idempotent-retry flow. CI repeats the checks on Python 3.11/3.12/3.14. No model benchmark result is claimed.
