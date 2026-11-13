# Implementation status and increment history

Latest implementation: increment 34, encrypted signed curation at rest under host-supplied keys. Local validation: 640 application + 13 security/hygiene methods, 100% application statement/branch coverage. PR/main checks record final delivery. Managed key authorization, organizational identity and curator/evaluator access separation remain open. Historical records below describe their original revisions.

This record distinguishes delivered capabilities from the original target architecture. The six-layer design, 36-role catalog and 16-week plan are reference targets, not a claim that all layers or roles are running.

## Delivered foundation

1. Preserved original Turkish architecture/PDF and diagrams, a separate English engineering repository and the previous prototype's history. Apache-2.0 licensing and distribution notices are in place.
2. Deterministic synthetic CSV diagnosis: schema drift, missing data, duplicates, amounts, exact input hashes and evidence locators.
3. Real source/staging/mart execution in memory, packaged SQL, count/amount reconciliation and declared dataset lineage.
4. Host-owned tool grants, strict requests, input/call/deadline budgets and sanitized tool outcomes.
5. Local SQLite incident/evidence persistence, retained run artifacts, integrity/replay/version checks, idempotency and explicit recovery/migration.
6. Closed coordination contracts, capability routing and bounded DAG. A26 retained-read and A27 deterministic verification are executable capability slices; the other specialist roles remain planned.
7. Local durable review queue: leases, fenced commits, bounded retries/backoff, cancellation and crash recovery.
8. TLS 1.3 certificate validation, server/client leaf pins, exact resource grants and pinned-IP read-only HTTPS transport. Production issuer operations remain gated.
9. Official A2A 1.0 stateless review profile tested through the SDK over real temporary mTLS; no deployed general task server.
10. Official MCP 2026-07-28 local tool profile: three tools, grant-filtered discovery, bounded results and shared policy lifetime; no remote endpoint.
11. English PR-based delivery, Python 3.11/3.12/3.14 CI, installed-package checks, dependency auditing, full-history/PDF secret scanning and file hygiene. Increment 11 has 309 distinct passing tests; critical coordination/workflow/security/integration coverage is 100%, whole application rounds to 98%.

## Ten-component architecture reality

- MCP: local official SDK tools implemented; authenticated remote transport and operational quotas pending.
- A2A: official stateless review implemented; remote durable Task lifecycle, delivery and production hosting pending.
- LLM: offline advisory contracts, minimized versioned prompts and durable trusted-host token/cost/deadline admission are implemented. Offline dispatch, cooperative streaming, bounded retry and durable routing are implemented. Actual provider tokenization/pricing and real I/O enforcement remain pending; no live provider calls enabled.
- RAG: retrieval adapters, tenant/source filtering, provenance/citation checks and retrieval evaluation are planned.
- CAG: bounded context caching, identity-aware keys, invalidation, confidentiality and prompt-version isolation are planned.
- Contracts: existing business JSON Schemas, official protocol models and MCP tool schemas implemented; specialist/model-specific contracts pending.
- Certificates/security: tested mTLS and exact resource/egress controls implemented; managed issuance, rotation/revocation operations, JWT/OAuth, production tenant/audit/rate controls pending.
- TAG: local deterministic capability routing/DAG implemented; semantic routing and distributed assignment pending.
- Connections: bounded HTTPS/A2A plus local MCP implemented; production queues/streams, backpressure, observability and distributed delivery pending.
- Judge: independent deterministic retained-evidence checks implemented; advisory LLM Judge and independent calibration/benchmarking pending. A model Judge will not override deterministic policy or authorize writes.

## Ordered next steps before interface work

1. Evaluation foundation: versioned cases/labels/metrics, development versus held-out family separation, leakage checks and frozen deterministic baseline. Report per-family errors, false positives/negatives and abstentions instead of a single unsupported accuracy number.
2. Model contracts and provider-neutral adapter: structured claims/citations, model/prompt version capture, token/cost/latency budgets, controlled routing/fallback and fail-closed handling. Set acceptance thresholds before inspecting held-out results; agree provider/data-residency/spending constraints before live calls.
3. RAG/CAG: enforce source provenance, tenant filtering, retrieval metrics, cache isolation/invalidation and prompt-injection resistance; use the evaluation gates from step 1.
4. Advisory LLM Judge and specialist increments: independently labeled evaluation, calibration/abstention, adversarial cases and specialist-specific contracts. Activate roles only as their tests and operational boundaries are ready.
5. Production protocol/API operations: authenticated ingress, issuer/secrets delivery, revocation/rotation, tenant access, audit/rate limits, remote task lifecycle, outbox/inbox/idempotency, capacity/backpressure and recovery exercises. These may progress alongside steps 1–4, but external provisioning needs explicit deployment decisions.
6. Investigation interface: build the premium accessible workspace only after stable authenticated APIs, evidence explainability and measured quality gates exist. Controlled remediation stays behind human approval and separate rollback tests.

## Accuracy and operational decisions

Current evaluation consists of ten labeled development and eight public synthetic validation scenarios with zero LLM calls. No independently sealed held-out benchmark or measured model accuracy exists yet. Passing tests and code coverage do not establish real-world root-cause inference quality.

No approval is needed for the next offline simulated adapter increment. Provider/model selection, data residency, live API spending, production certificate issuer/hosting and access to enterprise datasets require concrete choices before activation. Production exposure and remediation writes remain separately gated. No shared history rewrite or repository archive/rename is required for this work.

## Update after increment 12

Versioned suite/prediction/report contracts and a frozen public synthetic validation baseline are implemented. The original 10 development cases remain unchanged; eight new validation cases are split by curated family/group/content checks. Label projection, explicit confusion/FP/FN, abstention/error/coverage metrics and exact deterministic regression gates are tested. 327 distinct tests pass; benchmark scorer/runner/report coverage is 100%. The module CLI is exercised in subprocess and installed checks.

Current fixture agreement is 10/10 development and 8/8 public validation with zero model calls. These inspected public cases are not independently sealed held-out data, and no model accuracy exists yet. Next: provider-neutral prediction/evidence contracts, acceptance/sealed-evaluation process and budget/abstention rules before provider activation. Earlier ordered steps remain targets; the public baseline completes only the local evaluation-contract portion of step 1.

## Update after increment 13

Repository security/hygiene review and known-vulnerability dependency audit are complete within the documented scope. Offline provider-neutral metadata/response contracts now bind advice to a unique host request and verified retained evidence; the deterministic Judge controls scoped acceptance. 341 distinct tests pass; new advisory statement/branch coverage is 100%. No live model or calibrated model accuracy is introduced.

The agent connection/state map in docs/agents/README.md describes implemented A26/A27 capability slices, current queue snapshots and the future authenticated live observer. Next: bounded evidence-context selection/redaction, prompt assembly, provider-neutral accounting/timeout/cost admission and acceptance/sealed-evaluation rules before live provider activation.

## Update after increment 14

Allowlisted evidence context and versioned offline prompt preparation are implemented around the existing advisory gate. Raw source/business identifiers/amounts and arbitrary report/header text are excluded, with host byte limits, context/schema/policy/input hashes and cross-read record binding. Counts, operational IDs and digests remain intentional metadata. 359 distinct tests pass; advisory statement/branch coverage remains 100%. No provider calls or model accuracy are measured.

Next: provider-neutral usage reservation/accounting, token/cost/time admission and bounded retry/fallback before approved provider activation and sealed evaluation. Byte limits do not replace provider tokenization/billing or runtime deadlines. Agent scheduling, production identity/operations and interface gates remain unchanged.

## Update after increment 15

Durable usage admission/accounting now uses a separate local SQLite database with host-owned lifetime scope, exact input/model/quote binding, atomic token/cost holds, one-shot start, original request deadlines, bounded attempts and exact integer settlement. UNKNOWN or crash-left in-flight reservations stay held and block another attempt for that request. 387 distinct tests pass; usage and combined advisory statement/branch coverage are 100%. No model calls or accuracy measurements are introduced.

Next: offline simulated provider-neutral dispatch, typed adapter results, remaining transport deadline/output-cap enforcement and bounded retry/backoff. Cross-model fallback needs a shared logical-operation budget and newly bound prepared request; it is not silently enabled by per-request accounting. Provider tokenization/pricing validation, sealed evaluation, production identity/operations and interface gates remain pending.

## Comprehensive verification and inventory — 2026-11-11

The executable main revision after PR #17 was rechecked: 374 application + 13 security/hygiene tests pass; eight freshly built/installed distribution checks and the installed public benchmark CLI pass. Critical coverage gates remain 100%. Whole-application statement coverage is 2641/2681 (98.5080%); branch coverage is 789/822 (95.9854%). Remaining defensive storage/CLI/validation coverage is explicitly tracked in work package A04 rather than reported as 100% application coverage.

The [complete implementation inventory and roadmap](implementation-and-roadmap.md) lists 19 delivered inventory steps, all 36 role statuses and 84 remaining work packages with dependencies and activation gates. Active layer/reliability prose was corrected where it still described delivered evidence persistence as future work. Original architecture/PDF/catalog and executable source remain unchanged. No new product capability or measured model accuracy is claimed by this documentation review.

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
