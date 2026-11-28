# Implementation status and increment history

Latest implementation: increment 68, the measured quality page and the live-model held-out of the 36-role agents (see the last section). Increments 46 to 67 are recorded below; [increment 45](increment-45.md) remains the record of the retained evaluation campaigns.

This record distinguishes delivered capabilities from the original target architecture. The six-layer design, 36-role catalog and 16-week plan are reference targets, not a claim that all layers or roles are running.

## Delivered foundation

1. Preserved original Turkish architecture/PDF and diagrams, a separate English engineering repository and the previous prototype's history. Apache-2.0 licensing and distribution notices are in place.
2. Deterministic synthetic CSV diagnosis: schema drift, missing data, duplicates, amounts, exact input hashes and evidence locators.
3. Real source/staging/mart execution in memory, packaged SQL, count/amount reconciliation and declared dataset lineage.
4. Host-owned tool grants, strict requests, input/call/deadline budgets and sanitized tool outcomes.
5. Local SQLite incident/evidence persistence, retained run artifacts, integrity/replay/version checks, idempotency and explicit recovery/migration.
6. Closed coordination contracts, capability routing and bounded DAG. A26 retained-read and A27 deterministic verification are executable capability slices. All 36 catalog roles are contract-bound executors in the agent runtime (increment 64), most wrapping deterministic modules, five with an optional, advisory local model.
7. Local durable review queue: leases, fenced commits, bounded retries/backoff, cancellation and crash recovery.
8. TLS 1.3 certificate validation, server/client leaf pins, exact resource grants and pinned-IP read-only HTTPS transport. Production issuer operations remain gated.
9. Official A2A 1.0 stateless review profile tested through the SDK over real temporary mTLS; no deployed general task server.
10. Official MCP 2026-07-28 local tool profile: three tools, grant-filtered discovery, bounded results and shared policy lifetime; no remote endpoint.
11. English PR-based delivery, Python 3.11/3.12/3.14 CI, installed-package checks, dependency auditing, full-history/PDF secret scanning and file hygiene. Increment 11 has 309 distinct passing tests; critical coordination/workflow/security/integration coverage is 100%, whole application rounds to 98%.

## Ten-component architecture reality

- MCP: local official SDK tools implemented; authenticated remote transport and operational quotas pending.
- A2A: official stateless review implemented; remote durable Task lifecycle, delivery and production hosting pending.
- LLM: offline advisory contracts, minimized versioned prompts and durable trusted-host token/cost/deadline admission are implemented. Offline dispatch, cooperative streaming, bounded retry and durable routing are implemented. Pinned signed mTLS gateway I/O is implemented; actual provider tokenization/pricing and vendor qualification remain pending; no live provider calls enabled.
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

## Increment 36 — durable authority and audit

Persistent evaluator grants, terminal revocation and transactionally committed access outcomes are delivered together. Twelve new tests cover denial, reopen, audit failure and concurrent revocation. See [increment 36](increment-36.md). Identity enrollment, managed key lifecycle and process isolation remain next.

## Increment 37 — verified identity and key versions

Actual verified mTLS peers now map to durable principal/grant/key bindings. Persisted binding-scoped identity/key disable, exact material checks, certificate renewal and new-key/new-snapshot transitions are tested together. 687 distinct tests apply. See [increment 37](increment-37.md). Global key policy/lifecycle audit and restore safety remain next; issuer/KMS operations and process isolation are still open.

## Increment 38 — shared key control and restore guard

One terminal key disable now affects all bindings using the shared policy. Hash-linked lifecycle events and an externally retained current checkpoint reject old database restores before key resolution. 701 distinct tests apply. External checkpoint freshness/publication remains a host prerequisite; see [increment 38](increment-38.md).

## Increment 39 — checkpoint publication and recovery

Managed disable now commits an exact intent before policy mutation, blocks reads while pending, and publishes only the verified successor. Recovery handles a tested process exit after policy commit without duplicate events. 716 distinct tests apply. See [increment 39](increment-39.md); control-state custody remains a deployment prerequisite.

## Increment 40 — investigation workspace and honest execution view

The local interface was rebuilt as a dark multi-page workspace around one vertical slice: validate a source, investigate grouped findings with affected records, evidence and downstream impact, and record human decisions. New deterministic modules compute schema discovery with suggested (never auto-applied) mappings, exact quality dimensions, decimal amount exposure and duplicate-pattern observations (`analysis.py`), and a dependency/reason-coded execution plan from the real tool trace (`execution_view.py`). Per-finding references reuse the existing revision-bound knowledge store. 825 Python tests, 20 local-app tests and JavaScript presentation/workspace/i18n assertions pass; package coverage remains 100%. This is a deterministic local inspection: no live model, root-cause inference, enterprise connector or measured model accuracy is claimed.

## Increment 41 — read-only connected folder source

An opt-in `--source-dir` exposes CSV and SQLite files from one folder through `connectors.py`: listing-matched names only (no traversal or symlinks), read-only SQLite with an authorizer and query deadline, bounded exports with explicit sampling provenance, and the same deterministic inspection as an upload. The Data sources page gained a "Connected folder" flow reusing structure validation and confirmed mappings; runs and reports are labelled "Connected source". Tests cover traversal, symlinks, write refusal, size and row limits, timeouts and the HTTP boundaries, with 100% branch coverage on the module. Network databases, credentials and scheduled collection are not implemented.

## Increment 42 — record-level evaluation of the deterministic checks

`check_evaluation.py` generates 1,120 synthetic cases (40 base tables x 28 injected patterns, including hard negatives such as case-different identifiers, blank identifiers and valid edge amounts) whose ground truth comes from the injector, not from the checks. Base tables are hashed into development, validation and held-out splits as whole groups; a leakage check reports shared groups, payloads and records. It reports per-check true/false positives and false negatives, precision and recall with explicit denominators and Wilson intervals, and error categories. Tests run six deliberately broken detectors and require the corpus to expose each, and a committed report (`docs/evaluation/latest.md`) is tested against the code. Both shipped detectors score 100% on all three splits with no tuning between them; that is a regression guard for rules the corpus was built from, not evidence about real data, unseen fault kinds or any model.

## Increment 43 — change monitor and execution timeline

`monitoring.py` derives per-source series and rule-based change alerts (quality, new failing checks, schema change and restoration, row count, average amount, recovery) from retained inspections; every value is an exact count from the analysis and a source needs two inspections. The Overview and Reports pages show a multi-series change monitor with marked inspections and plain-language sentences (TR/EN); Execution flow shows a measured timeline from real event timestamps and a staged, animated capability graph. A real sample sequence exposed a rule defect (a repaired schema was labelled as degradation), fixed by separating `SCHEMA_RESTORED`. Package coverage stays 100%. Drift rules are fixed thresholds, not statistical tests or root-cause inference.

## Increment 44 — check accuracy page

A new Check accuracy page and `GET /api/evaluation` surface the record-level evaluation (increment 42) inside the workbench in Turkish and English, with the same limits stated next to the numbers. Executive-summary and print-ready report polish remain open.

## Increment 45 — report executive summary and print layout

The downloadable HTML report opens with an executive summary built only from the retained analysis: verdict, records and customers affected, valid amount in affected records, amount that could be counted twice, where to look first, quality-dimension bars (ratios floored, never rounded up), the change since the previous inspection of the same source, and counts of review decisions. It prints on A4 (use the browser's Print to save as PDF; the report allows no scripts). Turkish and English, escaped against injection, and absent when a run has no retained analysis. The report still makes no model or root-cause claim.

## Increment 46 — capability map

A Capability map page and `GET /api/capabilities` show all 36 design-catalog roles with an honest status: 7 implemented, 6 partly implemented (each with its stated limit), 1 unavailable (root cause needs a model), 1 disabled (read-only policy) and 21 planned. Every claim is tied to named code that a test resolves. Next: implement further deterministic roles one at a time, each with its own evaluation, before it is shown as running.

## Increment 47 — cross-source consistency (A21)

`consistency.py` compares two order extracts by identifier and reports identical, differing (per column), one-sided and ambiguous records, with masked bounded samples. A randomized test injects known one-sided, amount and customer differences into 60 table pairs and requires exact recovery; writing it exposed a real defect (an id repeated in only one source was reported as one-sided), fixed by excluding ambiguous ids from both sides. The Data sources page gained the comparison panel and `POST /api/source/compare`; the Capability map now lists A21 as implemented (8 implemented, 20 planned). It compares only the order contract columns, and only sources inside the connected folder.

## Increment 48 — join cardinality and fan-out (A18)

`cardinality.py` profiles key repetition and computes the exact effect of joining two connected order extracts on `order_id`: relationship per shared id, join row count, extra rows and amount inflation per side. Tests compare the closed-form figures with a brute-force nested-loop join over 80 random table pairs and keep 100% branch coverage. The compare endpoint returns it as `cardinality` and the Data sources page shows a Join safety section in English and Turkish. The capability map now lists 9 implemented, 6 partial, 1 unavailable, 1 disabled and 19 planned roles. Limit: two extracts by order id only; no foreign-key discovery and no connection to a warehouse.

## Increment 49 — similar earlier inspections (A22, partial)

`similar.py` builds a failure signature (failing checks plus schema issues) for each retained inspection and finds earlier ones with at least 50% Jaccard overlap, most similar first, at most three. The workbench snapshot returns `similar`, and the Investigations page shows a panel in English and Turkish with a button to open the earlier inspection. Tests keep 100% branch coverage. Browser check: two `null_total` samples find each other and a `duplicate_order` sample matches neither. The capability map now lists 9 implemented, 7 partial, 1 unavailable, 1 disabled and 18 planned roles. A22 is partial because it searches only the retained inspections of this workbench, with exact matching; it is not semantic search and not production RAG.

## Increment 50 — platform component audit

Audit of the ten committed components against the code. Result: nine are partly built and tested (MCP and A2A with the official SDKs, offline LLM contracts and accounting, lexical RAG references, strict contracts, mTLS and grants, capability routing, a read-only connected folder, a deterministic Judge) and CAG is not built; the only cache is a short-lived retrieval-result cache. None talks to a live service and no model has ever been run, so no model accuracy exists to report. `platform_map.py` records this with anchors that a test imports, `GET /api/platform` serves it and the Agents page shows it in English and Turkish. Next gates, in order: retrieval evaluation with provenance for RAG, then isolated cache keys for CAG, both deterministic; a measured model result needs a model run on a held-out labelled set and the user's approval of any download.

## Increment 51 — measured reference retrieval (RAG baseline)

The six built-in reference documents moved to `reference_documents.py`. `retrieval_eval.py` measures retrieval on 32 labelled queries. First measurement found a defect: function words such as `the` counted as evidence, so 67% of out-of-scope queries returned documents. Dropping function words from both sides brought that to 0% (0/6, interval up to 39%). Results now: same-wording queries 18/18 right first; paraphrase queries 3/8 right first and 4/8 in the top three (wide intervals); out-of-scope 6/6 correctly empty. Tests pin these figures, prove results never leave the granted sources or tenant, verify every returned citation and show the measurement reacts to a broken retriever. Limits stay explicit: authored with the corpus in view, English reference text only, no embeddings, no ingestion, no generated answers. Next: tenant- and version-isolated cache keys (CAG), then document ingestion with provenance.

## Increment 52 — isolated context cache (CAG building block)

`advisory/context_cache.py` adds a bounded cache of prepared evidence contexts. Entries are found only by exact identity (tenant, kind, version, evidence digest, scope), never by a hash of them, so another tenant, grant set, prompt version or changed evidence cannot reach them. Stored bytes are re-hashed on every hit and a mismatch rebuilds the entry; entries expire at the TTL, are evicted least-recently-used by count and bytes, and can be invalidated by tenant, kind, version or evidence digest. `PreparedAdvisory` can use it through an optional `cache` argument; the cached context is identical to the uncached one. A 600-step randomized workload checks that no identity ever receives another's bytes. CAG is now partly built: it is a cache primitive, not a model key-value cache, so no latency or cost saving is claimed and nothing is generated. Next: document ingestion with provenance for RAG, then the first measured step toward a model result once a model is approved.

## Increment 53 — knowledge base with provenance (RAG ingestion)

`knowledge_base.py` lets the operator add text documents to the reference collection: bounded size and count, NFC normalisation, control characters rejected, slug names with Turkish letters handled (a defect found by tests: the dotless i vanished from names), built-in names reserved, content-hash revisions, atomic 0600 persistence and re-validation on load so a hand-edited file cannot bypass limits. Search returns verified citations; an edited document invalidates old citations. A property test ingests 50 synthetic documents and finds each by its own marker phrase (50/50, which says the plumbing works, not that retrieval is semantically good). The Knowledge page gained add, remove and search in English and Turkish. Browser check also confirmed hostile text renders as text only, and fixed a raw translation key and a mobile column that hid the Remove button. Limits: text only (no PDF or Word parsing), no chunking, no embeddings, no generated answers. Next: chunking with per-chunk provenance and an extended retrieval evaluation, then the model-approval decision.

## Increment 54 — passages with exact spans and a measured comparison

`chunking.py` splits documents into passages (paragraph-aware, at most 800 bytes, sentence-end cuts, enormous words cut on character boundaries). A review found an overshoot case (a long sentence followed by a long word could leave a window over the limit); the cut is now a loop, and a 250-document property test checks exact spans, the byte limit, no overlap and full coverage. `Knowledge.retrieve_passages` and `verify_passage` add passage-level citations; document-level retrieval is unchanged, and built-in documents are single passages. Knowledge-base search now returns passages with their span. `passage_eval.py` compares whole-document and passage retrieval on 12 generated documents and 96 queries per group: with four distinctive words both find the right document 96/96 and the returned context shrinks from 2018 to 250 bytes with the exact span; with two words the passage method found the right document 94/96 versus 90/96, which is not shown to be a real difference (intervals overlap). The corpus is synthetic word lists, so no claim is made about real documents. Next: the model-approval decision, because no further measurable quality gain is available without a model or real documents.

## Increment 55 — model selection dossier (decision preparation)

`docs/decisions/model-selection-dossier.md` records the sandbox limits (2 CPUs, about 7 GB RAM, no GPU, model hosts unreachable), a licence-first shortlist of Apache-2.0/MIT open-weight families, the evaluation protocol (held-out labelled set, Wilson intervals, calibration, operator-set thresholds) and the three decisions needed from the operator. Documentation only: nothing was downloaded or run, and no accuracy is claimed. Licence facts come from third-party summaries and must be re-checked against model cards. Next: operator decision on where a model runs and on labelled data (C01–C04).

## Increment 56 — dependency SBOM and licence check (A05, partial)

`supplychain.py` resolves the transitive closure of the declared runtime and optional dependencies from installed metadata, writes a deterministic CycloneDX-shaped SBOM (no timestamp or serial, so equal inputs give equal bytes) and applies a fail-closed licence check: unknown licences, parentheses and unrecognised operators are rejected, `A OR B` passes if either side is allowed. `tools/check_supply_chain.py` runs it in CI before the tests. The first real run found 4 packages whose licence was only in the free-text `License` field (now read) and one package under MPL-2.0 (certifi), reported as REVIEW rather than silently allowed: whether MPL-2.0 is acceptable for this project is an operator decision. Platform-specific dependencies (pywin32, and others) are listed as conditional, not as gaps. Limits: the SBOM describes the environment it runs in, it is not a lock file, it does not scan for vulnerabilities (`pip-audit` does) and licence text is taken from package metadata, not legal review. Open in A05: lock files, build-dependency pinning, container digests.

## Increment 57 — deterministic route clock in tests (flaky test fixed)

A recovery test failed once on a slow CI runner. Cause: `execute_route` compares a real monotonic clock with a 1 s budget (deadline 2000 ms minus wall start 1000 ms), so a one-second stall mid-route stopped it after one event and broke the test's precondition. Reproduced by injecting a real 1.2 s delay into dispatch (failed before, passes after). `RoutingTests.setUp`, which the routing, recovery, integrity, authority, reconciliation and accounting tests share, now freezes the default clock; tests that exercise clocks still pass `clock=` explicitly. Test-only change: production behaviour is unchanged, 950 tests at 100% coverage.

## Increment 58 — model decision recorded

The operator decided the model stays a simulation for now, may connect real sensors later through an internship company, and approves a download only when at their own computer and stated at that time. The dossier records this; labelled real data is deferred until a real model or sensor data exists. Documentation only; nothing downloaded or run. Next: deterministic simulation-side work (D04 schema registry, F04 hypothesis contracts).

## Increment 59 — schema registry (D04)

`schema_registry.py` keeps numbered, append-only schema versions per subject. Each version commits to its predecessor by hash, and loading a saved registry re-verifies every hash, so an edited file cannot forge history (the local store sets such a file aside as `schemas.rejected.json` instead of trusting or overwriting it). `diff_columns` reports added, removed, widened and narrowed types, reordering and possible renames: removal and type widening are BREAKING, additions and narrowing are COMPATIBLE, a column with no values gives no type evidence, and a possible rename is a hint that is never applied. A subject can pin a contract version, and a new observation is compared with it (CONFORMS, DRIFT_COMPATIBLE, DRIFT_BREAKING). The Data sources page shows the panel after file validation in English and Turkish. Checks: 400 random schema pairs against symmetry properties, every single hash field edit rejected on load, four mutants all caught, 975 package tests at 100% coverage, 85 local tests, and a browser run on desktop and mobile with no overflow or console errors. Limits: types are inferred from the sample that was read, not declared by the data owner; positional readers are not protected from reordering; the registry stores column names and types only, never values; live database schemas are not covered. Known and unrelated: the local-app test run prints ResourceWarnings about unclosed SQLite connections that already existed before this change.

## Increment 60 — generic profiling and time-series checks with a held-out measurement (D05)

`profiling.py` reads any CSV within hard limits (1 MB, 20,000 records, 40 columns) and reports per-column role and statistics plus ten deterministic checks, each naming exact 1-based records: many empty values, wrong-type values, duplicate rows, constant columns, isolated jumps, flat lines, repeated timestamps, out-of-order timestamps, time gaps and mixed time zones. The Data sources page has a bilingual "Profile data" panel (`POST /api/profile`).

`profiling_eval.py` measures it on nine kinds of injected fault in generated series, scored by record against the injector's truth, with development, validation and held-out groups and Wilson intervals (`docs/evaluation/profiling.md`, kept in sync by a test).

What the measurement taught, and what was changed because of it:
- A local-median (Hampel) outlier rule gave false alarms in 5 of 31 development series: slow curvature in low-noise seasonal signals biased its residuals, worst at the series ends. It was replaced by second differences, which removed the false alarms.
- Unit tests then showed that a jump in the very first or last value was blamed on its neighbour (record 2 or 99). That is now only accepted with the full spike signature; first and last values are never flagged.
- The flat-line finding counted only the last record of a run; it now lists every record in the run.
- The threshold K=4.5 came from a false-alarm design target (about 1e-5 per clean Gaussian value), not from the small-spike score. The held-out split then showed one false flag in 15,300 clean values (about 1.9e-5 overall, 95% interval up to 1e-4), higher than the target. K was not changed after seeing held-out, and the report states this.

Held-out results (17 series): large spikes 51/51, flat lines 204/204, gaps, repeated and out-of-order timestamps and corrupted values all found, null bursts 17/17 by column, small spikes (4 to 6 noise units) only 17/51 by design. Limits: synthetic series from one family (trend, one seasonal wave, Gaussian noise), fault kinds chosen by the same authors who wrote the checks, no real sensors, no language model, no root cause. Real sensor noise is usually heavier-tailed, so expect more false alarms than measured here. 1027 package tests at 100% coverage, 86 local tests, browser run on desktop and mobile in EN and TR.

## Increment 61 — level-shift check, found by measuring a gap (D05b)

Probing the profiler with a persistent step (what a recalibrated or replaced sensor produces) showed that 43 of 60 series with a large step were reported as an isolated jump, often on the wrong record, because a step leaves an equal and opposite pair in the second differences. A new `level_shift` check looks at first differences: a single large difference with no opposite partner is a step, an adjacent opposite pair is a spike. Records that belong to a step are excluded from the outlier check. The step is reported on the first record at the new level, with its size.

Two new injected fault kinds measure it (`level_shift_large` 10 to 15 noise units, `level_shift_small` 3 to 5). Held-out (17 series): large steps 17/17 located exactly; small steps 1/17 by design. The check reuses K=4.5 and a partner ratio of 0.5 fixed before measuring; nothing was tuned on development or held-out for it. Held-out had already been scored for the older kinds, so only the two new kinds are a first look; the report says so.

An honest limit it exposed: at low signal-to-noise the two shapes overlap. A 4 to 6 unit spike was once read as a step and a 3 to 5 unit step once as a spike on development, and held-out shows one such case; these appear as unexpected findings in the small-kind rows rather than being hidden. Tests add mutants for a missing step check, a missing partner rule and a missing step exclusion, each caught. 1035 package tests at 100% coverage, 86 local tests, browser run on desktop and mobile in EN and TR.

## Increment 62 — comparison with a stored baseline, measured on held-out (D05c)

`baseline.py` builds a baseline from 1 to 5 earlier CSV files of the same shape and compares a new file with it. The baseline keeps column names and roles, record counts, the median sampling interval, a freshness limit, empty shares, and per numeric column the mean, standard deviation, median and decile edges with bin counts. It never keeps whole records, but medians and decile edges are values from the data and reveal approximate ranges. A SHA-256 digest over the record is re-checked on every load, so an edited baseline is rejected (the local store sets such a file aside). The comparison reports eight fixed-rule checks: missing, added and retyped columns, sampling-interval change (ratio outside 1/1.5 to 1.5), volume change (outside the reference range ÷1.5 to ×1.5), freshness (lag after an operator-given time above the limit, three intervals by default), empty-share increase above 0.10, and distribution shift (PSI above 0.25 on the baseline's decile bins). Checks that cannot run are listed with a reason, never silently passed, and a `measurements` block gives baseline and current values for passing checks too.

The Data sources page has a bilingual "Compare with a baseline" panel: save a baseline from reference files, compare the selected file, and read status tiles, a PSI bar per numeric column with the 0.25 line, and baseline-versus-current bin shares, each with a text alternative. Files travel as exact bytes, and "as of" is read in the baseline's clock (UTC for time-zone-aware data). Checked in a browser at 375 and 1024 px in English and Turkish.

`baseline_eval.py` measures it on generated series (60 groups; 37 development, 14 validation, 9 held-out). Thresholds were fixed before measuring. One was changed before held-out was scored: an independent review simulated unchanged data and found PSI above 0.25 in about 20% of columns at the original minimum of 50 values. The minimum was raised to 150 from the formula E[PSI] ≈ (bins − 1)(1/n_baseline + 1/n_current), and the report includes a seeded no-change table (mean PSI 0.067 at 150 values, 0 of 1,000 draws above 0.25). Held-out was scored once, at the end (`docs/evaluation/baseline.md`):

- Large mean shift, spread increase, unit change (×10), sampling twice as slow or fast, volume drop and spike, stale data and a null increase: 9/9 cases each, Wilson 95% lower bound 70%.
- Small mean shift (0.25 standard deviations): 3/9 (33%, interval 12–65%). Development showed 11/37 and validation 6/14. This is partly found by design; detection reaches 37/37 at 0.75 standard deviations on development.
- Four clean variants (no change, partial seasonal cycle, jittered timestamps, lag inside the limit): 0/9 cases with any finding each. The largest clean PSI was 0.072.
- Per-check precision was 100% on held-out. Distribution-shift recall was 30/36, all misses being small shifts.

Weaknesses this exposed and reports: a 160-record batch that covers only 1.6 seasonal cycles once produced PSI 0.262 on development, a false shift. Held-out is only 9 groups, so its intervals are wide. Keys from one group are correlated, so per-check intervals are optimistic. PSI is descriptive, not a significance test. Everything is synthetic: one family of generated series with changes chosen by the authors of the checks, no real sensors, no model, no root cause. Capability map: A11 and A20 stay partial, now also anchored to `baseline.compare`. 1096 package tests at 100% branch coverage, 100 local tests and the three browser-script checks pass. Work was planned and executed with subagent-driven development: each of five tasks got an implementer and an independent reviewer, then a whole-branch review led to one fix wave.

## Increment 63 — hypothesis contracts and a bounded probe loop, measured on held-out (F04)

`hypotheses.py` adds versioned JSON-Schema contracts (`data/hypothesis-contracts-v1.json`) for observations, hypotheses, probe results and whole investigations, and a deterministic loop over them. Findings from the baseline comparison and the profile become observations. A fixed catalog of 12 simulated mechanisms turns them into hypotheses, each listing its competitors (the counter-hypotheses): unit change, calibration offset, noise increase, stuck sensor, a real process change, sampling change, partial load, duplicate delivery, delivery delay, source outage, field outage and intermittent loss. Eight probes with thresholds fixed in the spec measure scale and spread ratios, flat runs, interval regularity, time span, freshness lag, duplicate share and empty runs. Each round the loop runs the probe that concerns the most unrefuted hypotheses, then replans on the updated statuses, within a budget of 6 probes. Statuses are only supported, open or refuted. "Real process change" can never be tested from these data, so it stays open. Every record carries the baseline digest, source hash and "as of" time under a trace digest, so an explanation cannot be shown against a different comparison.

The Data sources page gained "List candidate explanations" (EN/TR). It shows the verdict with the fixed statement "Candidate mechanisms consistent with fixed probes on these measurements. Not a root-cause determination.", hypothesis cards with competitors and the measured evidence, and a probe timeline by round. Mechanism descriptions are written as conditionals ("If this were the change: …"). Checked in a browser in English and Turkish at desktop and 375 px.

`hypotheses_eval.py` measures it on 60 fresh groups (30 development, 18 validation, 12 held-out), disjoint from the baseline-comparison corpus. The whole-branch review found that an earlier draft reused that corpus's groups, so held-out would not have been independent; this was fixed before held-out was scored. Held-out was scored once (`docs/evaluation/hypotheses.md`):

- 10 of 11 modelled mechanisms: the injected mechanism was the only supported hypothesis in 12/12 cases each (Wilson lower bound 76%).
- Stuck sensor: always supported (12/12), but calibration offset was also supported in 8/12, so it was the only candidate in just 4/12. Development showed 13/30 and validation 5/18 co-support. A stuck run moves the mean while the spread ratio stays in the offset band.
- Unmodelled sign flip: misattributed to calibration offset in 12/12 with the stop reason "resolved". This follows structurally from the probe rules, so a "resolved" stop does not mean correct.
- Unmodelled amplitude change: misattributed to noise increase in 7/12 (development 22/30, validation 10/18). The rest ended with no supported candidate.
- Clean batches produced no observations (12/12), so false support was never tested.

What this does not show: the catalog and the injections were written by the same authors, so the modelled results measure internal consistency, not diagnosis. Misattribution is measured on two hand-picked changes only. The intervals cover only group-to-group variation of fixed, large injections. The probes assume one mechanism per column at a time. Replanning added nothing measurable on this corpus (at most 3 of 6 probes were ever needed). No model, no live agent, no root cause. Capability map: A24 Counter-Hypothesis, A25 Active Probe Planner and A28 Ranking & Uncertainty are now partial (anchored to `hypotheses.investigate`); A23 stays unavailable. The counts are 9 implemented, 10 partial, 1 unavailable, 1 disabled and 15 planned. 1191 package tests at 100% branch coverage, 103 local tests and the browser-script checks pass. Planned and executed with subagent-driven development: three implementation tasks, a review for each, a whole-branch review and one fix wave.

## Increment 64 — agent runtime for all 36 catalog roles, with a live Agent flow page

`aegisflow_dr.agents` registers all 36 roles of `docs/agent-catalog.json` as contract-bound executors. Tasks and results are validated against `agent-task-v1` and `agent-result-v1`, and a whole run against `agent-run-v1`. An agent reports only one of five outcomes: completed, needs evidence, policy denied, skipped or failed. Most executors wrap the existing deterministic modules. A02, A22, A23, A29 and A30 can call an optional local model through `agents/llm.py`: Ollama on a literal loopback address only, temperature 0, a fixed seed, thinking off and JSON-schema output. Prompts receive a safe context (A34) without raw cell values. Model output is stored as advisory evidence, and the Judge (A27) never accepts it as a finding.

Each case is routed to at most 8 specialists. They run in dependency waves of up to 4, with budgets of 12 model calls, 40,000 tokens and 90 s. Unmet dependencies, deadlines and abandoned threads are handled explicitly, and the run record is sealed with a digest. Tools run in-process or through the local MCP profile, and the Judge review travels over A2A with mutual TLS from an ephemeral CA.

The workbench retains up to 50 run records, written with mode 0600. It streams events by Server-Sent Events, with the session token sent in a header, never in the URL. The bilingual Agent flow page shows the 36 agents by layer, edges labelled with their transport, the timeline, budgets, a detail drawer per agent, a plain-language run summary and a replay at readable speed. The approved local model is `qwen3:4b` (2.5 GB, Apache-2.0, USD 0).

`agents_eval.py` holds the evaluation harness, with expected role sets fixed before measuring. It replays recorded model responses, so CI needs no model. A recorder fix in this increment stops recording when the model stops answering. Previously the recorder wrote such runs as ordinary results: 203 of 420 recorded development and validation cases had been recorded against a stopped model, and they were removed and recorded again. The held-out live measurement is not run yet.

## Increment 65 — Command Center with a live simulated plant

The Overview became the Command Center. `simulation.py` is a seeded, deterministic plant with temperature (a 100 s wave), pressure and flow. Its baseline comes from a 600-reading commissioning period. Seven fault injectors are available: calibration offset, unit ×10, stuck sensor, noise ×3, sampling slowdown, ingestion pause and duplicate burst. A live monitor compares the latest 200 s window with the baseline and profiles it every 15 simulated seconds. It opens one incident per sensor or stream and closes it after two clean checks.

The page shows:
- live charts with the baseline band and detection markers;
- the fault console and the incidents;
- KPIs computed from the plant and the retained run records;
- agent activity.

"Investigate with agents" starts a run on the incident and opens the Agent flow. The plant is labelled as a simulation everywhere.

## Increment 66 — accurate incident evidence, the Incident page and an end-to-end held-out measurement

A measurement showed the weak point of increment 65. The window in which an incident is detected mixes readings from before and after the change, so the probe loop seldom found the injected mechanism there (unit ×10: never). Each incident now estimates its change onset from the readings alone, with `changepoint.py`:
- a single change point in mean and variance;
- for a seasonal sensor, each side also gets its own harmonic of the period learnt at commissioning;
- for stream incidents, the change point is taken on the gaps between arrivals, and a pinned "data stopped" onset is used when data stops.

The incident then collects the first full 200 s window after the onset and freezes it with its digest. Investigations run only on frozen evidence, and the API answers 409 while it is still collecting. Injected faults are shown beside the estimate as simulation ground truth, and a test proves the estimator never reads them.

The new bilingual Incident page (`/incident?id=…`) shows:
- a live lifecycle from detection to the human decision;
- the sensor around the change, with the estimated onset, the injected start, the detection and the evidence window;
- the findings;
- candidate explanations with measured probe values and fixed thresholds;
- the model's advisory suggestion and the Judge counts;
- the evidence with a CSV download.

The measured probe values come from the same deterministic call on the same frozen bytes as the agents' A24. They are shown only when that record's evidence reference matches the run's A24 evidence exactly.

`plant_eval.py` measures the loop end to end: 15 scenarios, 20 plants per split, with development seeds 1–20, validation 21–40 and held-out 41–60. Two changes followed the first validation run and are reported as such: per-segment harmonics, and collection that continues after an incident closes. Held-out was scored once, after an independent review and its fixes (`docs/evaluation/plant.md`):
- **The injected mechanism was the only supported candidate on the frozen evidence** in 13 of 15 scenarios at 90–100%. Investigating the detection window instead gave 0–45%.
- **No scenario ever supported a wrong mechanism.**
- **Change onset:** within ±5 s in 85–100% of cases for every fault except noise on temperature and the duplicate burst.
- **False alarms:** 1 incident in 20 simulated fault-free hours.

Limits reported rather than tuned away:
- Noise on the seasonal temperature sensor is refuted by the fixed marginal spread probe.
- A 30-row duplicate burst stays below the fixed 20% duplicate-share threshold.

Everything is simulated, so these numbers measure internal consistency, not diagnosis on real sensors. There is no root cause and no production connection. The review also fixed:
- a stream pause overriding sensor incidents' evidence;
- a probe-cache race;
- stale wording;
- a gitleaks false positive on a claim-key comparison in `flow.js`, allowlisted by fingerprint;
- stale README and agent-page claims that the roles were planned and no model calls existed.

## Increment 67 — evidence chain, human decision and the incident report

An incident now ends in a verifiable case file (`casefile.py`). A hash chain links five records:
- the plant baseline;
- the frozen evidence window;
- the probe-loop record on it;
- the sealed agent run;
- the human decision.

Each link carries its record's SHA-256 and the previous link's hash. The server recomputes every link from its source on each request:
- evidence bytes against their digest;
- the probe record's trace digest;
- the run record through `verify_record`, plus a check that the run's A24 evidence is exactly that probe record;
- the decision's digest.

The page shows each link as verified, mismatch or missing. Tests change each source in turn and see its link turn to a mismatch. The digests are integrity checks anyone can recompute, not signatures.

After the agent run, a reviewer records one decision: accept a supported candidate as the working explanation, reject the candidates, or ask for more evidence. The decision carries the reviewer's name and a note. The server refuses to accept a candidate the probes do not support on the frozen evidence. Decisions are recorded and never executed. Every version is kept in `incident-decisions.json`, written atomically with mode 0600. A tampered file is set aside on load. Decisions are keyed by the evidence digest, so a plant reset never attaches an old decision to a new incident.

The report page (`/report?incident=…`) prints the whole case to A4 through the browser's "Save as PDF". This keeps Turkish characters, needs no new dependency and costs USD 0. The footer carries the chain head and the case file's content digest.

## Increment 68 — measured quality page and the live-model held-out of the agents

The agents' held-out split (10 groups, 140 cases) was recorded live once with the local model `qwen3:4b`. It was scored once with prompt version 2. The prompt, the role table and the expected specialist sets were fixed before development was scored. Results on held-out:

- **Role selection:** 140/140 exact specialist sets.
- **Model replies:** 400/400 schema-valid.
- **Judge on specialist claims:** 1310/1310 accepted.
- **Replay:** reproduced every live outcome, 140/140.
- **Deterministic loop (A24):** supports only the injected mechanism in 107/110 modelled cases.

The model's suggestion (A23) is weak, and the report and the page say so. It lists the injected mechanism in 90/110 modelled cases, but names it first in only 40/110. Its list is often just the catalog order of the explaining mechanisms. On the two changes outside the catalog it suggests a catalog mechanism every time. Fixing this needs a new prompt version and a fresh corpus. It was not tuned here.

`agents_eval` now scores saved per-case facts (`fixtures/evaluations/agents-cases-v1.json`), so the report renders in a fraction of a second. A test keeps `docs/evaluation/agents.md` in sync with those facts. Another test replays the first case of each split to show the facts match the code. The refactor was checked by rendering the full report through the old and the new path: the two were byte-identical.

The new `/quality` page ("Measured quality") replaces "Check accuracy"; the old `/evidence` address still opens it. It shows the plant, agents, hypothesis-loop, baseline, profiling and CSV-check evaluations from `GET /api/quality` (`aegisflow_dr.quality`). It has a split selector, held-out headline tiles, per-scenario tables and a model-weakness note computed from the API's own numbers. Each rate shows its counts and a Wilson interval, drawn as a bar. The page lists the limits of every evaluation, works in EN and TR, and works at 375 px.

## Increment 69 — polish: mobile, TR/EN, a demo GIF and stale claims corrected

An audit of every page at 375 px in both languages and a full end-to-end run in the browser found and fixed these issues:

- **Incident chart.** On a long or fast run (20×), the readings around the change point dropped out of the plant's 1,200-reading buffer, so the onset fell outside the chart. The readings around the change are now kept when the evidence is frozen, and live readings continue the series only while they still join on. A regression test covers it.
- **Command Center at 375 px.** It scrolled sideways because a screen-reader-only table cannot shrink to 1 px. That table is now inside a clipped box.
- **Turkish percentages.** They now put the sign first (`%87,4`).
- **Singular counts.** A count of one now reads in the singular: "1 finding", not "1 findings" or "finding(s)". The rule (`key.one`) is tested.
- **Turkish terminology.** The Judge is called "Hakem" everywhere in Turkish; some strings used the English "Judge" or "Yargıç".
- **Smaller fixes.** The incident header no longer leaves an empty band. The report summary no longer nests parentheses. The Agent flow title fits plant incidents as well as files.

Statements that were no longer true are corrected:
- the footer;
- the platform panel's "no model has ever been run";
- the Capability map's "no model is configured" for A23. It now says the map covers the CSV workflow, while the agent runtime runs all 36 roles.
- the opening of the README and of the workbench README.

The README opens with a captioned 12-frame demo GIF (`docs/media/aegisflow-demo.gif`, 1.1 MB). It was made from browser screenshots of one real run, assembled with the local Pillow and no new dependency. The run covers fault injection, detection, the frozen evidence, 36 agents, probes, a recorded decision, the verified chain, the report and measured quality.

## Increment 70 — A23 reads qualitative readings (prompt version 3), measured on a fresh corpus

The v1 agents evaluation showed A23's suggestion barely discriminating: 40/110 first choices on held-out, mostly the
catalog order. The cause was its input. Given only check names, five catalog mechanisms explain the same
`distribution_shift`. Trials on v1 development groups showed three things:
- numbers alone did not help the 4B model under constrained decoding;
- thinking mode took about 20 s per call;
- deterministic qualitative readings with written signatures worked.

**What changed.**
- `aegisflow_dr.readings` turns each observation into fixed words from aggregates only: mean scaled by a power of ten,
  shifted or unchanged; spread wider, narrower or unchanged; rows dropped or increased; late data; empty values in one
  contiguous run or scattered.
- Prompt version 3 gives A23 those readings and the signatures, without the catalog list, and asks for a ranking.
- `Case.prompt_version` threads the version through every model call and record. Version 2 stays byte for byte, so the
  committed v1 evaluation replays unchanged.
- `agents_eval` has a protocol per version. v2 uses fresh groups 160 to 199 and its own recording, facts and report.
- The product (Agent flow, plant incidents) uses version 3.

**v2 results** (prompt frozen beforehand; held-out recorded and scored once):

| | Development (26 groups) | Validation (5 groups) | Held-out (9 groups) |
|---|---|---|---|
| A23 first choice is the injected mechanism | 286/286 | 55/55 | 99/99 |

- **Sign flip:** left to `genuine_change` (0 misattributed), while the loop still misattributes it.
- **Seasonal amplitude change:** still misattributed, because it reads like noise.
- **Duplicate delivery:** the model pads its list with two wrong-direction mechanisms, and the Judge rejects those
  claims. The advisory rate is therefore 92.3% rather than 100%.
- **One remediation draft (A29)** timed out on held-out.

Because the readings use the same aggregates and thresholds as the probes, this is correct mapping of documented
signatures, not independent diagnosis. The quality page shows v1 and v2 side by side, with the change in numbers.
