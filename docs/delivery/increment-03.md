# Increment 03 — Local tool contracts and execution controls

Goal: establish a deterministic host-controlled tool boundary before introducing agents.

Acceptance criteria: reject unknown fields/types and unauthorized exact tool/dataset pairs; enforce UTF-8 byte limits; atomically reserve calls including failed executions; check a monotonic session deadline before/after dispatch; return sanitized failures; preserve valid quality-failure reports; exercise installed-package gateway execution.

Scope: three local tools, closed request parsing, immutable host policy, session call/byte budgets, cooperative deadline and gateway-demo. No runtime identity or enterprise access guarantee is claimed. See ADR-0004 for lifecycle and isolation limits. Validation results are recorded in the PR and exact-revision CI.

Local validation (2026-11-10): 55 regression tests passed on Python 3.14. The wheel was built and installed into an isolated target. From outside the checkout, license metadata/files, catalog, gateway demo and seven diagnostic/batch CLI scenarios passed. CI repeats the suite and installed checks on Python 3.11/3.12/3.14.
