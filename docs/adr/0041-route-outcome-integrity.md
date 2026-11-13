# ADR-0041 — Validate route outcomes against persisted history

Status: Accepted for the trusted-host local profile.

## Finding

After the existing 719 application tests passed, fault injection set `route.final_status` to `VERIFIED_ADVISORY` immediately after claim, without an event or dispatched attempt. Historical replay returned success and recovery reported `NO_RECOVERY_INDICATED`. A scalar status could contradict the actual recorded work. This was a result-integrity defect even though no live provider is active.

## Change

One shared route-state reader now validates physical event positions, semantic indices, bounded event count (eight; read at most nine to detect overflow), route identity, unique referenced attempts, plan/attempt/event correlations and usage states. The final outcome must agree with the final event: reviewed verdict, terminal dispatch outcome, or exhausted retry plan. A running state is valid only before a terminal outcome. Deadline override remains permitted because a response may finish after the original deadline; admission denial is permitted before a terminal event.

All journal reads, ownership, historical replay, admission and recovery use this reader. Event writes also validate the proposed event against the actual settled or unresolved usage before commit. Recovery reuses the common checks rather than maintaining a weaker duplicate. Existing downstream progression enforcement remains as a secondary guard.

## Qualification

731 application + 13 security/hygiene tests = 744 distinct methods, including twelve new methods. Local Python 3.12: 4,223 statements / 1,260 branch exits; Python 3.14: 4,165 / 1,260. Both achieve 100% with no exclusions. Tests cover forged success, contradictory terminal/running states, physical position changes, orphan/flooded events, invalid route rows, unconsumed reservations reported as reviewed results, inconsistent UNKNOWN results, exact historical replay and deadline override. The installed-package dispatch check also rejects a contradictory outcome without modifying evidence.

The full suite exercises pipeline/lineage/evidence, queue/orchestration, TLS, official MCP/A2A profiles, advisory accounting/routing/recovery, curation/key/access boundaries and model-quality rejection gates. Inspection concentrated on historical outcome authority and cross-module validation reuse. Passing these tests is not a proof that every possible attack or defect is absent.

## Limits and next step

An internally consistent rewrite by a privileged storage owner remains outside this local trust boundary. A historical reviewed event is not a fresh model/evidence evaluation or an authenticated provider receipt. No schema migration or reconciliation write is introduced.

Proceed next with provider-neutral authenticated usage-attestation contracts and durable operator decisions. They must bind operation, attempt, quote and current recovery evidence. Real quality acceptance still requires independent protected holdout data, predeclared sampling assumptions, per-class/family thresholds and measured model results. Current synthetic tests supply no real model accuracy figure.
