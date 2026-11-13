# AegisFlow implementation inventory and complete target roadmap

Review date: 2026-11-11. Executable baseline: `c3205510e253172941521da0f50009e5f754b53a` ([commit](https://github.com/mirackeser/aegisflow-data-reliability/commit/c3205510e253172941521da0f50009e5f754b53a)).

This is the complete work-package inventory for the currently agreed six-layer, 36-role research/product target. It is a scoped plan, not a claim that every future discovery is known. Re-estimate after each acceptance gate; new pilot findings require explicit backlog entries. Completed implementation increments are not elapsed weeks.

## Historical verified baseline (review revision above)

Historical local run: 374 application + 13 security/hygiene test methods = **387 passing tests**, zero failures/skips. Eight fresh installed-wheel checks and the independent installed benchmark CLI pass. The 10 development and 8 public validation cases match expected labels/tool order; no model calls. These inspected cases are not a blind holdout.

Whole-application statement coverage: **2641/2681 = 98.5080%**. Branch coverage: **789/822 = 95.9854%**. Combined coverage: **97.9161%**. Critical advisory/coordination/workflow/security/integration/benchmark core-runner-report gates are **100%** (1582 statements, 460 branch exits). Forty unexecuted statements and 33 branch exits remain across defensive storage/CLI/legacy validation paths; A04 tracks targeted follow-up. This is a coverage gap, not a finding that these paths are defective.

Fresh dependency audit reports no known vulnerabilities. Candidate/PDF secret scanning and file hygiene are release checks. Existing main CI checks Python 3.11/3.12/3.14, installed behavior and full Git-history/PDF hygiene. Repository review is not a penetration test, load test, live provider evaluation or production acceptance.

## Delivered steps

1. **History and clean project boundary.** Original prototype remains separate; current repository is public with engineering topics; no rename/archive/history rewrite.
2. **Architecture archive.** Original Turkish architecture, six Mermaid sources/SVGs and verified 46-page PDF retained.
3. **Source diagnosis.** Bounded CSV diagnostics, deterministic reports, hashes and evidence locators. [PR #1](https://github.com/mirackeser/aegisflow-data-reliability/pull/1)
4. **Actual batch execution.** Actual in-memory SQL transformation, reconciliation and declared downstream impact. [PR #2](https://github.com/mirackeser/aegisflow-data-reliability/pull/2)
5. **Apache-2.0 distribution.** Apache-2.0 with packaged license and attribution notices. [PR #3](https://github.com/mirackeser/aegisflow-data-reliability/pull/3)
6. **Tool enforcement.** Host grants, strict inputs, atomic call budget, byte limits and cooperative deadlines. [PR #4](https://github.com/mirackeser/aegisflow-data-reliability/pull/4)
7. **Incident evidence persistence.** Local incident store, linked source/report evidence, immutable events and replay. [PR #5](https://github.com/mirackeser/aegisflow-data-reliability/pull/5)
8. **Repository hygiene.** Internal archive metadata cleanup and full-history/PDF secret scanning. [PR #6](https://github.com/mirackeser/aegisflow-data-reliability/pull/6)
9. **Bounded deterministic investigation.** One policy session, conditional tool routing and ten labeled development cases. [PR #7](https://github.com/mirackeser/aegisflow-data-reliability/pull/7)
10. **Durable investigation runs.** Exact execution artifacts, immutable runs, integrity/replay checks and explicit migration. [PR #8](https://github.com/mirackeser/aegisflow-data-reliability/pull/8)
11. **Coordination and independent verification.** Closed coordination contracts, local capability routing/DAG and A26/A27 deterministic slices. [PR #9](https://github.com/mirackeser/aegisflow-data-reliability/pull/9)
12. **Durable review queue.** Fenced local reservations, dependency scheduling, retries/backoff, cancellation and recovery. [PR #10](https://github.com/mirackeser/aegisflow-data-reliability/pull/10)
13. **Certificate and egress foundation.** Real temporary mTLS tests, exact leaf/resource grants and bounded pinned-IP transport. [PR #11](https://github.com/mirackeser/aegisflow-data-reliability/pull/11)
14. **Official A2A interoperability.** Official generated models and SDK over actual local mTLS; stateless review profile only. [PR #12](https://github.com/mirackeser/aegisflow-data-reliability/pull/12)
15. **Official local MCP profile.** Official in-process MCP discovery/calls behind the existing tool grants and budgets. [PR #13](https://github.com/mirackeser/aegisflow-data-reliability/pull/13)
16. **Public evaluation baseline.** Frozen inspected public synthetic cases, leakage checks and exact deterministic regression gates. [PR #14](https://github.com/mirackeser/aegisflow-data-reliability/pull/14)
17. **Offline model-advisory boundary.** Strict offline advice, request/evidence binding and deterministic revalidation; no provider. [PR #15](https://github.com/mirackeser/aegisflow-data-reliability/pull/15)
18. **Minimized evidence and prompts.** Allowlisted context, immutable prepared snapshots, byte budgets and provenance hashes. [PR #16](https://github.com/mirackeser/aegisflow-data-reliability/pull/16)
19. **Durable usage admission.** Atomic host-quoted admission, original deadlines, attempt limits and exact integer settlement. [PR #17](https://github.com/mirackeser/aegisflow-data-reliability/pull/17)

## Six-layer reality

- **L1 Presentation:** Planned. Six product screens and authenticated live UI do not exist.
- **L2 Integration/observability:** Partial. Local input and official protocol adapter profiles exist; real source connectors and deployed telemetry remain planned.
- **L3 Quality/diagnostics:** Working bounded baseline. CSV checks, in-memory SQL, reconciliation and fixed declared lineage exist; broad SQL/log/statistical diagnostics remain planned.
- **L4 Agentic orchestration:** Partial. Deterministic routing/DAG, A26/A27 slices, queue and offline advisory/prepared-input/accounting exist; model planner and specialist runtime remain planned.
- **L5 Evidence/remediation/workflow:** Partial. Source/run evidence, events, snapshots and deterministic verification exist; semantic claim/hypothesis system, patch sandbox and authenticated human approval remain planned.
- **L6 Security/AgentOps/infrastructure:** Partial. Local grants/budgets, mTLS/egress and CI scanning exist; tenant identity, managed credentials, production audit/telemetry and recovery operations remain planned.

## Ten requested ecosystem components

1. **MCP:** Official local SDK, three grant-filtered tools implemented; authenticated remote hosting pending.
2. **A2A:** Official stateless SDK/mTLS review implemented; remote durable task lifecycle and hosting pending.
3. **LLM:** Offline contracts/prompts/usage admission implemented; offline dispatch/retry/routing now implemented in subsequent increments; live provider calls and provider-specific tokenization/pricing remain pending.
4. **RAG:** Not implemented; ingestion/index/retrieval/provenance evaluation planned in E.
5. **CAG:** Not implemented; isolation/versioned keys/invalidation/eviction planned in E.
6. **Contracts:** Strict existing JSON/protocol contracts implemented; executable specialist/API contracts pending.
7. **Certificates/security:** mTLS, pins and exact resource grants implemented; managed issuance/rotation/revocation and JWT/OAuth deployment pending.
8. **TAG:** Local capability tags and bounded dependency DAG implemented; semantic routing/distributed allocation pending.
9. **Connections:** Bounded HTTPS and local SDK communication implemented; production servers/queues/streams/backpressure pending.
10. **Judge:** Independent deterministic retained-assessment verification implemented; calibrated advisory model Judge and general claim semantics pending.

## All 36 roles and their delivery status

Zero full specialist roles are complete against the original catalog definition. A26 and A27 have working narrow deterministic slices. Other tools/components support future roles but do not turn those roles into implemented agents. The original catalog remains frozen design metadata; this document is the current capability overlay.

Each role requires a validated input/output contract, actual allowed tools, negative authorization cases, evidence binding, failure/abstention behavior, budget enforcement, version capture and case-specific quality acceptance. P0/P1/P2 are delivery priorities, not runtime processes.

- **A01 — Global Supervisor · P0:** planned specialist.
- **A02 — Investigation Planner · P0:** planned specialist.
- **A03 — Dynamic Agent Router · P0:** planned specialist.
- **A04 — Dependency & Parallelism Planner · P1:** planned specialist.
- **A05 — Budget & Escalation Controller · P0:** planned specialist.
- **A06 — Investigation Recovery Coordinator · P1:** planned specialist.
- **A07 — Pipeline Run Explorer · P0:** planned specialist.
- **A08 — Schema Drift Investigator · P0:** planned specialist.
- **A09 — Data Contract Inspector · P1:** planned specialist.
- **A10 — Data Profiling Specialist · P0:** planned specialist.
- **A11 — Freshness & Volume Analyst · P1:** planned specialist.
- **A12 — Log & Error Trace Analyst · P0:** planned specialist.
- **A13 — Data Lineage & Impact Investigator · P0:** planned specialist.
- **A14 — SQL Transformation Analyst · P0:** planned specialist.
- **A15 — Incremental Load Investigator · P1:** planned specialist.
- **A16 — CDC & Replication Investigator · P2:** planned specialist.
- **A17 — Data Type & Casting Investigator · P0:** planned specialist.
- **A18 — Join & Cardinality Investigator · P1:** planned specialist.
- **A19 — Reconciliation Investigator · P1:** planned specialist.
- **A20 — Statistical Drift Investigator · P2:** planned specialist.
- **A21 — Cross-Source Consistency Investigator · P1:** planned specialist.
- **A22 — Incident Similarity & Knowledge Agent · P2:** planned specialist.
- **A23 — Root Cause Hypothesis Generator · P0:** planned specialist.
- **A24 — Counter-Hypothesis Agent · P0:** planned specialist.
- **A25 — Active Probe Planner · P1:** planned specialist.
- **A26 — Evidence Collector · P0:** partial: trusted retained-evidence read, not general evidence ingestion.
- **A27 — Evidence Verification Agent · P0:** partial: deterministic scoped assessment/citation check, not a model/general semantic verifier.
- **A28 — Root Cause Ranking & Uncertainty Reviewer · P1:** planned specialist.
- **A29 — Remediation Strategy Planner · P0:** planned specialist.
- **A30 — Patch Proposal Agent · P2:** planned specialist.
- **A31 — Sandbox Validation Orchestrator · P0:** planned specialist.
- **A32 — Regression & Backfill Validator · P1:** planned specialist.
- **A33 — Human Approval Coordinator · P0:** planned specialist.
- **A34 — Policy & Data Access Reviewer · P0:** planned specialist.
- **A35 — AgentOps & Cost Analyst · P1:** planned specialist.
- **A36 — Evaluation & Feedback Curator · P2:** planned specialist.

## Remaining ordered work packages

**84 work packages in the expanded review-time backlog** across A–J, plus the individual role acceptances above. Packages vary in size; their count is not a progress percentage. Within a phase, order follows dependencies. A and production preparation H can overlap other work; UI I stays gated. Select infrastructure technologies by approved ADR when their actual need is known; original FastAPI/PostgreSQL/LangGraph/dbt/pgvector/Compose choices are targets, not installed components.

### A — Acceptance and engineering hardening

May run alongside B; required before live activation.

- **A01:** Freeze PRD/SRS, MVP boundaries, user stories and measurable acceptance criteria.
- **A02:** Define latency/capacity/availability/recovery targets and retention budgets from pilot needs.
- **A03:** Review threat model, trust boundaries, data classification and tenant model.
- **A04:** Delivered in increment 31: retained-evidence/CLI defensive rejection and rollback tests close the recorded coverage gap; whole-application statement/branch CI gate is 100%.
- **A05:** Lock transitive/build dependencies; pin scanner/container digests; produce SBOM and license checks.
- **A06:** Define versioning, schema compatibility/deprecation and release evidence conventions.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### B — Provider-neutral execution without live providers

Next functional increment; requires existing prepared input and usage ledger.

- **B01:** Define typed adapter requests/results and separate untrusted response content from trusted usage.
- **B02:** Dispatch the exact prepared input once after atomic start; preserve correlation and provenance.
- **B03:** Validate tokenizer, framing, output cap, pricing revision and all billable categories before quoting.
- **B04:** Enforce remaining transport deadline, output/body limits and cancellation behavior.
- **B05:** Classify certain failures versus ambiguous delivery and retain UNKNOWN holds on ambiguity.
- **B06:** Implement bounded retry/backoff for eligible known outcomes without resetting the original deadline.
- **B07:** Add shared logical-operation budgets and explicit allowed model routing/fallback.
- **B08:** Design audited UNKNOWN reconciliation, quotas/retention and operator recovery.
- **B09:** Simulate malformed responses, timeouts, rate limits, duplicate delivery, crashes and budget exhaustion.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### C — Quality gates and controlled model activation

Evaluation protocol before inspecting sealed outcomes; live work requires user decisions.

- **C01:** Expand ground-truth scenarios across pipelines and failure families, including clean and insufficient evidence.
- **C02:** Independently curate and seal holdout cases; hash splits and prevent prompt/routing leakage.
- **C03:** Predeclare quality, unsupported-claim, abstention, cost and latency thresholds and regression tolerances.
- **C04:** Agree provider/model, data residency, retention terms, credential delivery and spending ceiling.
- **C05:** Integrate one approved provider behind the adapter and inject credentials only at runtime.
- **C06:** Measure live token/cost/latency and verify provider usage against reservation assumptions.
- **C07:** Calibrate confidence/abstention using development data; test adversarial and contradictory claims.
- **C08:** Accept the initial model slice only on predeclared independent evaluation; retain every failed run.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### D — Real data integration and diagnostic tools

Read-only synthetic/staging integration before enterprise data; supports E and F.

- **D01:** Select one realistic pipeline runtime and implement a reproducible local integration environment.
- **D02:** Implement read-only database/file connector grants, bounded queries, pooling and backpressure.
- **D03:** Ingest job/run metadata and redacted logs with validated source provenance.
- **D04:** Retain schema versions and implement schema diff and contract registry.
- **D05:** Expand profiling, freshness/volume checks, type handling and declared lineage ingestion.
- **D06:** Implement SQL AST diagnostics, join/cardinality and reconciliation tools with scoped evidence.
- **D07:** Add incremental/watermark, CDC, distribution and cross-source adapters only for supported pilot cases.
- **D08:** Test connector denial, schema change, network failure, duplicates, recovery and realistic data volumes.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### E — RAG and CAG with provenance and isolation

Depends on source access policy and evidence contracts; supports specialist reasoning.

- **E01:** Define document/incident ingestion, chunking, metadata, versioning and deletion rules.
- **E02:** Choose and test embedding/index adapters; isolate tenant/source permissions before retrieval.
- **E03:** Implement retrieval/reranking with immutable citations and source freshness checks.
- **E04:** Measure retrieval recall/precision, citation support and hostile-document handling.
- **E05:** Implement cache keys bound to tenant, grants, model, prompt and evidence versions.
- **E06:** Add cache TTL/invalidation, size/eviction budgets and deletion propagation.
- **E07:** Test cache poisoning, cross-tenant leakage, stale data and concurrent misses.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### F — Agent runtime and the full specialist catalog

Depends on tested tools and advisory gates; roles activate only after individual acceptance.

- **F01:** Define executable per-role contracts, allowed tools, evidence policy, budgets and failure behavior for all 36 roles.
- **F02:** Implement supervisor, investigation planner, capability router and dependency/parallelism planning.
- **F03:** Add durable state/checkpoints and integrate recovery, cancellation and escalation across investigation tasks.
- **F04:** Implement observation/hypothesis/counter-hypothesis/probe contracts and bounded replanning.
- **F05:** Extend A26/A27 beyond retained-read/scoped assessment to supported semantic claim/evidence verification.
- **F06:** Add an advisory model Judge with independent labels and deterministic veto/abstention.
- **F07:** Deliver every P0 specialist individually with its real tools and case-specific acceptance.
- **F08:** Deliver each P1 and P2 specialist only when its connectors, evidence and evaluation are ready.
- **F09:** Test cycles, starvation, parallel updates, denied tools, contradictory findings and bounded stopping.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### G — Controlled remediation and human approval

Requires supported hypotheses/evidence; production writes excluded from initial release.

- **G01:** Define remediation plans with preconditions, risks, evidence and rollback requirements.
- **G02:** Generate bounded reviewable SQL/Python patch proposals without execution authority.
- **G03:** Build an isolated test environment with restricted network, credentials and resource limits.
- **G04:** Run positive/negative, regression, reconciliation and backfill impact tests on each proposed patch.
- **G05:** Implement authenticated approval/rejection, separation of duties and version-bound decisions.
- **G06:** Prove that failed tests, changed evidence or absent approval block promotion; exercise rollback.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### H — Production API, transport and operations

Local preparation may progress in parallel. H13 decisions precede any external provisioning; applicable gates precede deployed pilot and UI integration.

- **H01:** Implement the authenticated case/evidence/task API with versioned contracts and safe error mapping.
- **H02:** Enforce tenant/resource authorization, least privilege, rate limits and durable audit trails.
- **H03:** Deploy MCP/A2A hosting with strict HTTP framing and chosen remote task/delivery semantics.
- **H04:** Implement workload identity, managed certificate issuance, rotation/revocation and runtime secret delivery.
- **H05:** Add inbox/outbox, external idempotency, message ordering, dead-letter handling and backpressure.
- **H06:** Introduce production persistence/object storage with migrations, encryption, retention and access policy.
- **H07:** Add OpenTelemetry traces/metrics, redacted logs, cost attribution and service alerts.
- **H08:** Expose an authenticated read-only agent observer with event cursor, reconnect and snapshot reconciliation.
- **H09:** Distinguish queued, leased, running, stale and next-eligible tasks using trustworthy worker signals.
- **H10:** Add reproducible containers/environment configuration, health checks and deploy/rollback pipelines.
- **H11:** Exercise backup/restore, crash/disaster recovery and documented recovery objectives.
- **H12:** Load/soak/chaos test limits and perform deployment-specific security/tenant-isolation testing.
- **H13:** Approve infrastructure owner, hosting region, capacity, operational budget and pilot access.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### I — Investigation interface after infrastructure gates

Starts after stable authenticated APIs and relevant quality/operational gates.

- **I01:** Define the restrained accessible visual system, navigation and evidence hierarchy.
- **I02:** Build Command Center for pipeline health, active incidents and investigation summaries.
- **I03:** Build Pipeline and Lineage Explorer with declared/inferred lineage clearly identified.
- **I04:** Build Incident Investigation Workspace for findings, hypotheses and cited evidence.
- **I05:** Build Agent Operations Center showing active roles, dependencies, next tasks, cost and freshness.
- **I06:** Build Evidence and Remediation Center with patch/test review and authenticated approvals.
- **I07:** Build Evaluation and Research Lab for comparable runs, errors and ablations.
- **I08:** Complete keyboard/contrast/responsive behavior and loading/empty/error/stale states.
- **I09:** Run authenticated end-to-end, accessibility, browser compatibility and usability acceptance.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

### J — Research comparison, pilot and release

Evaluation design begins in C; final comparative claims follow implemented variants.

- **J01:** Implement comparable B0 deterministic, B1 single-agent, B2 static, B3 dynamic and B4 verified/counter-hypothesis variants.
- **J02:** Run all variants on the same sealed cases, allowed tools, budgets and recorded stochastic settings.
- **J03:** Report Top-1/Top-3 root-cause, evidence precision, unsupported claims and abstention/coverage.
- **J04:** Report completion, remediation pass rate, tool failures, cost and p95 latency with uncertainty.
- **J05:** Ablate routing, counter-hypothesis and verifier separately; analyze failure families and limitations.
- **J06:** Complete literature review, reproducibility package, dataset/model/license documentation and research report.
- **J07:** Run an approved read-only pilot with acceptance criteria, human feedback and incident exercises.
- **J08:** Close pilot findings; perform release review, tagged build and deployment verification.
- **J09:** Deliver operator/developer/user guides, demo/defense material and ownership/support handoff.

Phase exit: its behavior is implemented, relevant positive/negative/integration tests pass, installed distribution works, trust/quality limits are documented, security checks and exact-revision CI pass, and the reviewable PR is merged. External activation additionally requires the named approval gate.

## Original 16-week reference mapping

Weeks 1–2: requirements, research design and role contracts (A/C/F). Weeks 3–4: realistic pipeline and data faults (D). Weeks 5–6: diagnostics, lineage and tool gates (D). Weeks 7–8: supervisor/router/P0 runtime (B/F). Weeks 9–10: evidence, counter-hypothesis and sandbox/P1 (F/G). Weeks 11–12: advanced P2 and UI only after gates (F/I). Weeks 13–14: B0–B4, ablations and analysis (J). Weeks 15–16: security, operations, docs and defense (H/J).

This is an aggressive historical target, not the remaining calendar schedule or proof that elapsed weeks are complete. Current priority deliberately moves authentication, measured quality and operational prerequisites before UI. The proposed 80–120 research cases are a target subject to independent curation, not delivered data. No 36 separate LLM services, Kubernetes, Kafka, Neo4j, separate vector database or production auto-write is required by default.

## Validation breakdown

- A2A: 23 passing test methods.
- Offline advisory: 14 passing test methods.
- Batch: 15 passing test methods.
- Benchmark: 18 passing test methods.
- Context: 18 passing test methods.
- Coordination: 31 passing test methods.
- Development evaluation: 4 passing test methods.
- Gateway: 17 passing test methods.
- Investigation: 20 passing test methods.
- MCP: 20 passing test methods.
- Pipeline: 20 passing test methods.
- Queue: 50 passing test methods.
- Registry: 3 passing test methods.
- Retained runs: 37 passing test methods.
- mTLS/security: 26 passing test methods.
- Incident store: 30 passing test methods.
- Usage: 28 passing test methods.
- Security/hygiene tooling: 13 passing test methods.

## Decisions, limitations and next action

No approval is needed for local test/docs work or the next simulated adapter. Live provider/model, data region/retention, API spend, enterprise data access, production hosting/issuer and pilot ownership require concrete decisions before activation. Repository rename/archive/history rewrite and production remediation are not authorized by this plan.

Agent visibility today is the static docs/agents map plus local read-job snapshots/history. LEASED is reservation, not proof of active computation. Authenticated live events/heartbeats and Agent Operations Center are H08/H09 and I05.

The architecture PDF is a preserved reference, not a live implementation specification. This review does not upload files to a ChatGPT Project; no such upload has been verified. No production endpoint or working web application link exists yet.

Immediate functional work: B01–B04 with simulated providers; prioritize A04 defensive coverage follow-up before live activation. Quality evaluation C and production prerequisites H remain gates. There is no measured model accuracy or reliable percentage derived from tests/role count. Earlier 25–30% was a scope-based estimate, not measured progress.

Repository review identified stale active layer/reliability status prose; those descriptions are corrected without changing archived architecture or executable source. No blocking application regression was found by this test run. Zero known scan findings do not establish absence of every possible vulnerability.

## Update after increment 16

B01/B02 now have a working trusted synchronous adapter boundary with immutable input, one-shot durable start, usage settlement and independent response review. B03 still needs actual provider tokenization/pricing verification; B04 still needs transport-level hard limits and cancellation. The wrapper propagates limits and rejects late/oversized returned results; it cannot interrupt arbitrary host Python. 402 tests pass; dispatch statement/branch coverage is 100%. See [dispatch ADR](../adr/0017-one-shot-advisory-dispatch.md). The 84-package inventory above is the review-time baseline; this update records subsequent progress without declaring complete provider execution. Next: bounded simulated transport and typed failure classification before retry/fallback.

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
