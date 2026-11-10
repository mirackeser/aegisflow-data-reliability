# Increment 08 — Durable local review reservations and recovery

Goal: make the A26→A27 review schedulable across process restarts with bounded retries, dependency enforcement, cancellation and stale-result rejection, while preserving immutable evidence.

## Delivered and acceptance

- Separate explicitly initialized private queue database, immutable manifests/events and verified mutable projections; no evidence-store migration, history rewrite or fingerprint change.
- Idempotent submission with normalized proposal evidence order; changed requests conflict and terminal work never reopens accidentally.
- Atomic ready-task reservation, unique fenced tokens, expiry, at most three renewals per attempt and bounded exponential retry. Judge dispatch requires successful evidence collection.
- Evidence/Judge execution outside queue write transactions; cancellation and terminal completion races have one committed outcome. Late/stale work cannot commit.
- Idempotent expiry recovery, retry exhaustion, permanent-failure dependency blocking, cross-context/hash/version rejection and sanitized failure history.
- Actual process-exit tests after committed reservation and during dirty SQLite page spill. Queue opens can recover hot journals; an explicit store-recover command handles interrupted evidence writes without changing its existing read-only API or replay fingerprints.
- Operator CLI and installed-wheel process round trips; ADR-0009 and durable-review-v1 document states, bounds, backup/restore, delivery/version/clock limits and migration-free compatibility.

## Measured validation (2026-11-10)

227 application unit/integration/simulation tests and eight repository-hygiene tests passed: 235 distinct test methods, including 50 new queue/recovery tests. Repeated runs, subtests, development scenarios and CI matrix executions are not counted as additional distinct methods.

Coverage.py 7.17.2 measured 487/487 statements and 180/180 branch exits in the workflow package (100% each). Coordination coverage remains 100%; CI enforces both packages on Python 3.11/3.12/3.14. The complete application combined statement/branch report is approximately 97%; legacy modules retain explicitly visible uncovered paths. Coverage is not proof of production readiness, security certification or model accuracy.

The built wheel is checked outside the source checkout, including submission deduplication, two worker invocations in separate processes, retained rejection verdict, terminal IDLE, cancellation/recovery and explicit evidence recovery. All 10 packaged labeled development scenarios remain matched. Redacted secret scanning, candidate/PDF hygiene and known-vulnerability auditing of the runtime dependency graph are required before merge; CI additionally checks fetched Git history and extracted historical PDF text.

## Scope and next gate

This implements one local read-only two-task workflow, not arbitrary remote graphs or an external message broker. Leases use a trusted host clock; cancellation fences results rather than forcibly interrupting reads. Work can execute more than once after expiry, while result commits are fenced; exactly-once external effects are not promised. Store owners/Python hosts remain trusted and queue metadata is unencrypted. No model, certificate issuer, external identity service or background worker is provisioned.

Next: workload identity/authorization, egress policy and one authenticated protocol adapter with certificate/token/negative-access tests before remote connectivity. Deployment/data-residency/identity-provider and model/vector/broker cost decisions precede external provisioning. Local tests and contract work do not require those external decisions.
