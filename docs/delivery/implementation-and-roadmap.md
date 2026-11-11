# AegisFlow implementation inventory and complete target roadmap

Review date: 2026-11-11. Executable baseline: `c3205510e253172941521da0f50009e5f754b53a` ([commit](https://github.com/mirackeser/aegisflow-data-reliability/commit/c3205510e253172941521da0f50009e5f754b53a)).

This is the complete work-package inventory for the currently agreed six-layer, 36-role research/product target. It is a scoped plan, not a claim that every future discovery is known. Re-estimate after each acceptance gate; new pilot findings require explicit backlog entries. Completed implementation increments are not elapsed weeks.

## Verified current state

Fresh local run: 374 application + 13 security/hygiene test methods = **387 passing tests**, zero failures/skips. Eight fresh installed-wheel checks and the independent installed benchmark CLI pass. The 10 development and 8 public validation cases match expected labels/tool order; no model calls. These inspected cases are not a blind holdout.

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
3. **LLM:** Offline contracts/prompts/usage admission implemented; provider calls, tokenization, routing and fallback pending.
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

**84 remaining work packages** across A–J, plus the individual role acceptances above. Packages vary in size; their count is not a progress percentage. Within a phase, order follows dependencies. A and production preparation H can overlap other work; UI I stays gated. Select infrastructure technologies by approved ADR when their actual need is known; original FastAPI/PostgreSQL/LangGraph/dbt/pgvector/Compose choices are targets, not installed components.

### A — Acceptance and engineering hardening

May run alongside B; required before live activation.

- **A01:** Freeze PRD/SRS, MVP boundaries, user stories and measurable acceptance criteria.
- **A02:** Define latency/capacity/availability/recovery targets and retention budgets from pilot needs.
- **A03:** Review threat model, trust boundaries, data classification and tenant model.
- **A04:** Cover remaining retained-evidence/CLI defensive branches with targeted corruption and failure tests.
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
