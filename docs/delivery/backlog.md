# Delivery backlog

Work in short, acceptance-driven increments. Estimate the next item after reviewing the previous increment; the architectural 16-week roadmap is a target, not a delivery guarantee.

1. **DR-001 — Deterministic diagnostic baseline:** implemented in increment 01. Reproducible synthetic orders; schema/null/duplicate injection; evidence-linked checks; bounded input; stable CLI outcomes; automated regression coverage.
2. **DR-002 — Real batch transformations and lineage:** implemented in increment 02. Introduce an explicit source/staging/mart fixture and lineage edges; identify downstream impact without pretending that a failing check proves its root cause.
3. **DR-003 — Tool contracts and enforcement:** implemented in increment 03 for local trusted-host sessions; enterprise identity, hard isolation and durable quotas remain planned. Typed requests/results, allowed tool catalog, read-only policy, time/call budgets and negative authorization tests.
4. **DR-004 — Incident and evidence persistence:** source diagnosis implemented in increment 04; versioned runs and exact batch artifacts implemented in increment 06. Model-claim verification and enterprise storage remain planned. Incident lifecycle, immutable snapshots, claim/evidence junctions, reproducible replay and version checks.
5. **DR-005 — Bounded orchestration:** deterministic baseline implemented in increment 05; retained source evidence, one policy session, conditional tool routing and development regressions are working. Durable workflow/batch evidence is implemented in increment 06. Contract/TAG/local verification slices are implemented in increment 07; the two-task local durable reservation/retry/cancellation path is implemented in increment 08; remote delivery and model planning remain planned. Implement deterministic baseline first, then optional model planning behind the same enforcement boundary; track each specialist's tested capability separately.
6. **DR-006 — Investigation interface:** planned. Build the first premium, accessible investigation workspace on working API contracts.
7. **DR-007 — Research evaluation:** planned. Separate development and held-out failure families; compare B0-B4 with controlled tools and budgets.

## Infrastructure gates before interface work

The local two-task dependency/reservation/retry/cancellation slice is implemented in increment 08. Certificate/resource/egress foundations are implemented in increment 09. Increment 10 adds official A2A 1.0 stateless review interoperability; increment 11 adds the official MCP local tool profile behind existing grants. Evaluation contracts and a public synthetic baseline are implemented in increment 12; independently curated held-out evaluation remains pending before model activation. Production protocol hosting/operations and authenticated API/access boundaries remain prerequisites for deployment. Do not advance to the web interface merely because the deterministic demo passes its development suite.


## Multi-agent integration sequence

Increment 07 adds local task/proposal/verdict/receipt schemas, controlled capability routing, a bounded DAG and an independent deterministic Judge on retained runs (ADR-0008). Increment 08 implements local reservation/retry/cancellation/recovery for the A26→A27 review in a separate queue with fenced commits and bounded backoff. The queue remains trusted-host only; external idempotency, outbox/inbox, retention/quotas and distributed operations remain future gates.


Increment 09 implements mutual TLS, exact certificate/resource grants and bounded pinned-IP HTTPS for a private read-only review binding. Increment 10 adds a version-pinned official SDK adapter and generated models, strict A2A 1.0 HTTP+JSON stateless consultation and actual SDK/TLS tests. It supplies a host callback, not a production HTTP server, remote Task service or public discovery. Source/run/queue schemas and original architecture/PDF are unchanged. See ADR-0010/0011 and the increment delivery records.


Increment 11 implements the version-pinned official MCP local profile with exact tool grants, native schemas, bounded results and SDK interoperability/negative-access tests. Policy lifetime survives reconnects. No remote MCP endpoint is configured. Increment 12 adds versioned evaluation contracts and a frozen public baseline. Independent held-out data and provider/model acceptance remain gated. Production HTTP framing/error mapping, workload issuer/secrets delivery, revocation/rotation, authenticated audit/rate controls, tenant isolation and task lifecycle remain deployment gates. Agree data residency, cost and operational ownership before external provisioning. Keep interface work deferred; see [current status and ordered next steps](status.md).

Increment 12 establishes versioned evaluation contracts, a frozen 10-development/8-validation public synthetic baseline, leakage checks and explicit error/abstention metrics. This is not a blind holdout: the cases were inspected during development. Next define provider-neutral prediction/evidence contracts and predeclared model acceptance/sealed-evaluation rules before enabling providers. Independently curated holdout, calibration, live model measurements and operational identity/deployment gates remain pending.

Increment 13 reviews repository security/hygiene and adds offline advisory metadata/response contracts, unique request/evidence binding and deterministic Judge revalidation. The agent map documents implemented A26/A27 connections and current queue snapshot visibility. Next: bounded evidence context/redaction, prompt assembly, provider-neutral usage/timeout/cost admission and predeclared acceptance/sealed evaluation before live calls. No model provider or live dashboard is enabled.

Increment 14 implements minimized semantic evidence context, versioned prompt assembly, host-owned byte limits, immutable prepared snapshots and context/policy/record/input provenance. Next implement provider-neutral usage reservation/accounting and token/cost/time admission with controlled retry/fallback before live calls. Independent sealed evaluation and model/provider/data-residency/spending decisions remain prerequisites for activation; interface work stays deferred.

Increment 15 implements durable trusted-host usage admission/accounting in a separate SQLite ledger. Exact prepared-input/model quote binding, atomic token/cost holds, original deadlines, bounded per-request attempts and one-shot start prevent local oversubscription and duplicate start. UNKNOWN/crash-left in-flight usage remains held. Next implement the offline simulated adapter/dispatcher, actual remaining-deadline/output-cap checks and bounded retry/backoff. Model fallback requires explicit shared logical-operation limits; live providers and independent sealed evaluation remain gated.

The [complete target roadmap](implementation-and-roadmap.md) is the authoritative expanded inventory after the comprehensive verification. Next functional slice: B01–B04 (simulated adapter/dispatcher); A04 closes remaining defensive coverage before live activation. A–J contains all currently planned work packages, individual role acceptance, quality/production/UI dependencies and user decision gates. Historical increment notes retain their original delivery-time scope.

## Update after increment 16

B01/B02 now have a working trusted synchronous adapter boundary with immutable input, one-shot durable start, usage settlement and independent response review. B03 still needs actual provider tokenization/pricing verification; B04 still needs transport-level hard limits and cancellation. The wrapper propagates limits and rejects late/oversized returned results; it cannot interrupt arbitrary host Python. 402 tests pass; dispatch statement/branch coverage is 100%. See [dispatch ADR](../adr/0017-one-shot-advisory-dispatch.md). The 84-package inventory above is the review-time baseline; this update records subsequent progress without declaring complete provider execution. Next: bounded simulated transport and typed failure classification before retry/fallback.

## Update after increment 17

Trusted known failure classification and settlement are implemented, with ambiguous outcomes retaining full holds. 409 tests pass; no automatic retry or transport preemption is claimed. See [increment 17](increment-17.md). Next: bounded transport/cancellation simulation before controlled retry.

## Update after increment 18

Stage B: B01/B02 local foundations and B05 classification are working; B03 remains partial; B04 now has bounded cooperative streaming with timeout/cancellation closure and conservative holds. 425 tests pass; stream statement/branch coverage is 100%. See [increment 18](increment-18.md). These increments do not equal completed sequential work packages or a measured project percentage. Next B06: bounded retry/backoff; real provider I/O, shared fallback budgets and sealed evaluation remain pending.

## Update after increment 19

B06 now has bounded same-model retry/backoff under the original deadline and durable admission. 443 tests pass; retry statement/branch coverage is 100%. Repeat/restarted operation keys cannot automatically resume or resend. See [increment 19](increment-19.md). Next B07/B08: shared logical-operation/fallback scope and audited recovery; B03 provider-specific quoting and sealed model evaluation remain gates. No live model or UI is enabled.

## Update after increment 20

B07 now has a dedicated shared-ledger total-attempt/deadline/unresolved-call guard and a runnable offline demonstration. 452 tests pass; legacy JSON is preserved. B07 remains partial: persisted operation/evidence/model eligibility and automatic fallback are pending. See [increment 20](increment-20.md). This is development increment 20, not work package 20/84.

## Update after increment 21

B07 now persists operation identity, incident/run/evidence/context/schema binding, model eligibility and the original deadline in a new version 2 ledger. Legacy ledgers are preserved. 467 distinct tests pass; binding/usage statement and branch coverage is 100%. See [increment 21](increment-21.md). Next: bounded approved-model routing with persisted outcomes; audited recovery and independently measured model quality remain gates. Development increment 21 is not work package 21/84.

## Update after increment 22

Local B07 controlled routing is implemented: approved ordered candidates, shared limits, durable outcomes, single-owner dispatch, historical replay and no automatic recovery from ambiguity. Only settled retryable technical failures permit model switching. 493 distinct tests pass, with critical statement/branch gates at 100%. See [increment 22](increment-22.md). Next B08 is audited reconciliation/recovery; live model quality remains unmeasured and must pass independent sealed evaluation. Development increment 22 is not work package 22/84.

## Update after increment 23

B08 now has consistent read-only recovery evidence with fixed reason codes, accounting and canonical digests. No resend/refund or reconciliation write authority is introduced. 505 distinct tests pass; new module statement/branch coverage is 100%. See [increment 23](increment-23.md). Next: bound operator decisions and provider usage attestations. [Live output milestones](live-output-milestones.md) separate current offline output, C05 live response, C08 quality acceptance and later UI.

## Update after increment 24

Self-review reproduced and corrected missing event/plan/attempt correlation in recovery assessment. Bound advisory review requests now reject stale snapshots and preserve all usage holds. 512 distinct tests pass; new recovery code has 100% statement/branch coverage. See [increment 24](increment-24.md). Authenticated identities, durable decisions and provider usage attestations remain the next B08 scope; no reconciliation write or measured model accuracy is claimed.

## Update after increment 25

C03 first slice prioritized: executable strict quality gate with candidate 95% overall/class/family targets, sample support, independent provenance and zero error/unsupported-claim rules. 536 distinct tests pass; no live model result is claimed. See [increment 25](increment-25.md) and [recurring engineering review](engineering-review.md). B08 remains partial; real sealed data, independent annotation and activation enforcement remain pending.

## Increment 26 prepared — pending dependency and CI

C01/C02 now have offline label-free source manifests, known split-overlap/repeated-group checks and exact dual-review annotation reconciliation. Disagreement exports no quality cases; agreement does not approve provenance or activate a model. 550 distinct tests pass locally, including 14 new curation tests; critical statement/branch gates remain 100%. See [increment 26](increment-26.md) and [curation data flow](../contracts/evaluation-curation-v1.md). PR #28 and this dependent change must pass CI before delivery. Authenticated independent curators, protected sealed storage/access, adjudication and real model measurements remain pending.

## Increment 27 — statistical acceptance support

Registered protocol v2 adds exact binomial support and a simultaneous significance budget for all overall/class/family metrics. Sampling assumptions must be explicitly approved; defaults block. Observed 95% success alone can no longer satisfy v2. V1 records remain compatible. Local verification: 566 distinct tests, critical statement/branch coverage 100%; PR/main CI remain delivery gates. See [increment 27](increment-27.md). Independent authenticated curation, protected holdout, selection governance and actual model evaluation remain next; B08 and UI prerequisites are unchanged.

## Increment 28 — verified curation retention

Local private snapshots now retain exact source and annotation artifacts, including disagreements. Every read checks an external trusted digest and recomputes curation semantics. 577 distinct tests are covered by delivery gates. This is local integrity/retention; authenticated identity, encrypted storage, access separation and independent evaluation remain next. See [increment 28](increment-28.md).

## Increment 29 — adversarial review and reader hardening

Local schema substitution and metadata resource bounds were reproduced/reviewed and hardened before expanding curation authority. Seven new adversarial test methods cover storage and message attacks; 584 distinct tests are subject to the delivery gates. See [increment 29](increment-29.md) and [finding, fix and remaining boundaries](../adr/0029-curation-reader-security-hardening.md). Authenticated curation, protected storage and deployment security remain next.

## Increment 30 — system QA and report consistency

Full regression/installation review reproduced a report-reader consistency defect and fixed it by recomputing metrics and the regression gate against the frozen suite. Six new methods plus installed negative verification cover forged and stale report values. 590 distinct tests pass locally; critical coverage is 100%, whole-application statement coverage 98.8707% and branch coverage 96.9101%. Historical snapshots are labeled; stale routing/milestone prose is corrected. See [increment 30](increment-30.md) and [ADR-0030](../adr/0030-recomputed-benchmark-report-validation.md). A04 and production/model activation gates remain explicit.

## Increment 31 — A04 defensive coverage closed

A04 now covers the previously unexecuted 40 statements and 33 branch exits through 21 negative/integration/fault-injection methods. Full application coverage is 3542/3542 statements and 1068/1068 branch exits, 100%, with no exclusions; CI enforces the full gate. 611 distinct tests pass locally. Product source and archived artifacts are unchanged. See [increment 31](increment-31.md). Next: authenticated curation identity and protected storage; model/production activation remains separately gated.

## Increment 32 — dataset-scoped annotation signing keys

Detached Ed25519 envelopes now bind exact annotation/manifest/reviewer/key/time under trusted-host grants before consensus. Two distinct reviewer names and keys are required; scope, expiry/revocation and tampering fail closed. 625 distinct tests pass locally; full application coverage remains 100%. This authenticates granted key possession, not human independence or durable protected storage. See [increment 32](increment-32.md) and [authentication contract](../contracts/curation-authentication-v1.md). Next: protected retention of signed evidence/trust provenance and organizational identity integration.

## Increment 33 — durable signed curation evidence

A separate local format retains exact signatures, annotations, sources and the public grant policy under an external digest. Reopening reconstructs original integrity and requires current host grants, revision and signature validity. No stored key becomes authority; expired/revoked/changed policy blocks label export. Legacy unsigned records remain unchanged. 641 distinct tests and full application coverage apply. See [increment 33](increment-33.md). Next: confidentiality, curator/evaluator access separation and managed identity/key policy. Model activation and UI gates remain open; the [milestones](live-output-milestones.md) record conditional effort estimates.

## Increment 34 — encrypted signed evidence

All signed source/annotation/envelope/policy artifacts are encrypted before persistence with a host-supplied key. Current signing authority remains mandatory after decryption. 653 distinct tests and full application coverage apply. See [increment 34](increment-34.md) and [encryption contract](../contracts/encrypted-curation-v1.md). Managed key authorization and curator/evaluator access separation are next. The [milestones](live-output-milestones.md) now include a conditional November 11-intensity estimate.

## Increment 35 — scoped evaluator authorization

Trusted-host grants now bind evaluator identity, encrypted snapshot, key, policy and time before key resolution. Six new methods verify denial and encrypted read behavior. See [increment 35](increment-35.md). Managed identity, current durable key policy and process separation remain next.

## Increment 36 — durable authority and audit

Persistent evaluator grants, terminal revocation and transactionally committed access outcomes are delivered together. Twelve new tests cover denial, reopen, audit failure and concurrent revocation. See [increment 36](increment-36.md). Identity enrollment, managed key lifecycle and process isolation remain next.

## Increment 37 — verified identity and key versions

Actual verified mTLS peers now map to durable principal/grant/key bindings. Persisted binding-scoped identity/key disable, exact material checks, certificate renewal and new-key/new-snapshot transitions are tested together. 687 distinct tests apply. See [increment 37](increment-37.md). Global key policy/lifecycle audit and restore safety remain next; issuer/KMS operations and process isolation are still open.

## Increment 38 — shared key control and restore guard

One terminal key disable now affects all bindings using the shared policy. Hash-linked lifecycle events and an externally retained current checkpoint reject old database restores before key resolution. 701 distinct tests apply. External checkpoint freshness/publication remains a host prerequisite; see [increment 38](increment-38.md).

## Increment 39 — checkpoint publication and recovery

Managed disable now commits an exact intent before policy mutation, blocks reads while pending, and publishes only the verified successor. Recovery handles a tested process exit after policy commit without duplicate events. 716 distinct tests apply. See [increment 39](increment-39.md); control-state custody remains a deployment prerequisite.


## Increment 40 — accounting integrity and operational qualification

Persisted accounting is now revalidated before spending, historical replay and recovery. A reproduced negative-charge admission defect is fixed; legacy policy records retain their original bytes. Eight integrated offline scenarios and a new installed CI gate qualify bounded fallback, rejection, ambiguity, deadlines, cost limits and interrupted workers. 732 distinct methods and full application coverage apply. See [increment 40](increment-40.md). Next B08 scope: authenticated usage-attestation contracts and durable operator review decisions; reconciliation writes and live model activation remain gated.


## Increment 41 — route-result integrity

Cross-system regression passed before fault injection reproduced unsupported historical success. Shared route history and event-write validation now reject contradictory outcomes and usage states. 744 distinct tests and full coverage apply; see [increment 41](increment-41.md). Next: authenticated usage attestations and durable review decisions before reconciliation authority.


## Increment 42 — signed recovery evidence and durable decisions

B08 now has operation-scoped usage assertion verification and signed durable operator reviews, with exact attachment binding, snapshot freshness and idempotent append-only local records. 758 distinct tests and full coverage apply; see [increment 42](increment-42.md). Reconciliation writes, managed issuer deployment and live model activation remain gated. Next: explicit authorized reconciliation state transitions and crash/failure atomicity.
