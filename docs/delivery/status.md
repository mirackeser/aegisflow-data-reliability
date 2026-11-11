# Implementation status after increment 15

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
- LLM: offline advisory contracts, minimized versioned prompts and durable trusted-host token/cost/deadline admission are implemented. Actual provider tokenization, dispatch/routing, transport enforcement and fallback remain planned; no provider calls enabled.
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
