# AegisFlow AI — Agentic Data Reliability

Evidence-led investigation of batch data pipelines, with bounded tools and human-reviewed remediation as the target architecture.

## Current increment

Increment 40 adds [accounting integrity and offline operational qualification](docs/contracts/operational-qualification-v1.md): persisted arithmetic is validated before admission/replay/recovery, and eight integrated scenarios verify exact costs, conservative holds and restart behavior. Validation covers 730 application/security methods and eleven installed checks. Live model quality and provider activation remain separately gated.

Increment 39 adds [durable checkpoint publication and recovery](docs/contracts/checkpoint-control-v1.md). Pending intents block reads; recovery finishes only the exact recorded transition. Local verification covers 716 application/security methods, including actual process termination and restart. Independent custody of the control store remains required.

Increment 38 adds [shared key policy and lifecycle/restore checks](docs/contracts/shared-key-policy-v1.md). One disable affects participating bindings; restored old files reject against the current external checkpoint. Local verification covers 701 application/security methods. Trusted checkpoint publication and operational recovery remain pending.

Increment 37 adds [verified client identity and exact key-version bindings](docs/contracts/identity-key-binding-v1.md), with persisted binding-scoped disable and explicit renewal/rotation. Validation includes 687 application/security methods. Global managed-key and issuer operations remain pending.

Increment 36 adds [durable evaluator authority and access audit](docs/contracts/access-registry-v1.md), including terminal revocation and commit-before-result semantics. This trusted-host boundary is covered by 671 application/security test methods. Managed identity, key lifecycle and process isolation remain pending.

Increment 34 adds [encrypted signed curation evidence](docs/contracts/encrypted-curation-v1.md): sources, annotations and signing provenance are encrypted before persistence, with current host authority checked before label export. Local regression covers 653 distinct application/security tests and 100% application statement/branch execution. See [current status](docs/delivery/status.md) and [conditional live-output milestones](docs/delivery/live-output-milestones.md). Managed key authorization, enterprise identity, access separation and measured live-model acceptance remain pending.

The batch demo now executes source validation → normalized staging → SQL customer-sales aggregation in an in-memory SQLite database. It checks count/amount conservation and traverses a fixed declared lineage graph for potential downstream impact. Packaged SQL and canonical stage/mart datasets have linked content hashes. Versioned investigation runs now retain exact executed stage/mart CSV, SQL and staging-contract snapshots in the explicit local store. Dashboard execution and inferred root cause remain planned. Source CSV diagnosis now supports the persistent local store described below.


The executable baseline generates synthetic orders and checks a CSV data contract. It detects renamed columns, missing values, duplicate order IDs and invalid amounts. Every report identifies the exact input with SHA-256 and uses logical CSV record numbers as evidence locators. Invalid input and exhausted input budgets fail explicitly.

**This is a deterministic diagnostic foundation, not an agent runtime or root-cause inference system.** The full 36 specialist roles remain planned; two bounded local capability slices (A26 retained evidence read and A27 deterministic verification) are implemented separately. No model calls, third-party data connectors, automatic repair or production writes are enabled.

## Try locally

Python 3.11+; install the validator, test tooling and optional official protocol SDKs to run the complete suite:

```sh
python3 -m pip install ".[test,a2a,mcp,curation]"
python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m aegisflow_dr catalog
PYTHONPATH=src python3 -m aegisflow_dr demo
PYTHONPATH=src python3 -m aegisflow_dr demo --fault schema_drift
PYTHONPATH=src python3 -m aegisflow_dr demo --fault null_total
PYTHONPATH=src python3 -m aegisflow_dr demo --fault duplicate_order
PYTHONPATH=src python3 -m aegisflow_dr inspect fixtures/orders-clean.csv
PYTHONPATH=src python3 -m aegisflow_dr batch-demo
PYTHONPATH=src python3 -m aegisflow_dr batch-demo --transform exclude_first
PYTHONPATH=src python3 -m aegisflow_dr batch-demo --fault schema_drift
```

Exit codes: `0` = checks pass; `1` = quality/reconciliation failure or blocked batch; `2` = input rejected. A failed-quality demo intentionally returns `1`. Reports never expose raw order IDs or customer values. Use synthetic data only; local file inspection has no enterprise access policy.

## Documents

- [Architecture PDF](docs/AegisFlow-AI-Mimari-v1.0.pdf) and [original Turkish architecture](docs/architecture.md)
- [Planned role catalog](docs/agent-catalog.json) and [original diagrams](docs/diagrams/)
- [Engineering workflow](CONTRIBUTING.md), [active backlog](docs/delivery/backlog.md) and [source diagnostic evidence](docs/delivery/increment-01.md) and [batch evidence](docs/delivery/increment-02.md)
- [Baseline design decision](docs/adr/0002-deterministic-diagnostics.md) and [batch/lineage decision](docs/adr/0003-batch-transforms-and-lineage.md)
- [Source provenance](docs/source/provenance.json)
- [Complete delivered inventory, verification and target roadmap](docs/delivery/implementation-and-roadmap.md)

The original Turkish design is an immutable reference archive. New engineering documentation, code and GitHub collaboration use English. Its roadmap and experimental targets are not measured results.

## History preservation

The previous supply/SLA prototype remains separate and unchanged at https://github.com/aegisflow-ai-labs/Aegisflow-ai. This repository starts a distinct Data Reliability implementation; role identifiers must not be interpreted using the old catalog.

## License

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) and [licensing scope](docs/licensing.md). Third-party materials retain their original terms.

## Local tool gateway

`PYTHONPATH=src python3 -m aegisflow_dr gateway-demo` executes one synthetic batch through an exact host-configured tool/dataset grant. The closed request contract cannot supply policies, file paths or arbitrary SQL. Calls and UTF-8 input bytes are bounded; deadlines are checked before/after dispatch. See [ADR-0004](docs/adr/0004-local-tool-policy-and-budgets.md). This local control layer does not provide authentication, OS isolation, hard cancellation or durable quotas.

## Persistent source investigations

Create a synthetic research store explicitly; existing files are never overwritten:

```sh
mkdir -p work
PYTHONPATH=src python3 -m aegisflow_dr store-init --db work/incidents.db
PYTHONPATH=src python3 -m aegisflow_dr record-source --db work/incidents.db --source fixtures/orders-clean.csv --key demo-001
```

Use the returned incident_id as INCIDENT_ID in these examples:

```sh
PYTHONPATH=src python3 -m aegisflow_dr read-incident --db work/incidents.db --incident INCIDENT_ID
PYTHONPATH=src python3 -m aegisflow_dr replay-incident --db work/incidents.db --incident INCIDENT_ID
PYTHONPATH=src python3 -m aegisflow_dr close-incident --db work/incidents.db --incident INCIDENT_ID --expected-revision 2 --actor local-operator
```

Recording exits 0 when the transaction succeeds, even if the saved source-quality status is FAIL. Replay exits 0 for MATCH, 1 for MISMATCH and 2 for rejected/unsupported operations. Same-key/same-byte retries return the original verified record; different bytes conflict. All reads check retained evidence, claim links and event history. Exact replay requires matching diagnostic code and Python implementation/version.

The database contains raw synthetic source snapshots and is not encrypted. Use only synthetic data; do not commit database files. Closure records a local actor label, not authenticated approval. This is not an agent-write tool or enterprise access-control layer. See [ADR-0005](docs/adr/0005-local-incident-and-evidence-store.md), [increment 04](docs/delivery/increment-04.md) and [model reliability gates](docs/research/reliability-gates.md). No model accuracy percentage is claimed.

## Bounded investigations before model integration

After recording a source incident, run:

```sh
PYTHONPATH=src python3 -m aegisflow_dr investigate-incident --db work/incidents.db --incident INCIDENT_ID
PYTHONPATH=src python3 -m aegisflow_dr investigate-incident --db work/incidents.db --incident INCIDENT_ID --transform exclude_first
PYTHONPATH=src python3 -m aegisflow_dr evaluate-investigation
```

The investigator uses one policy/budget session, verifies the retained source version, then conditionally runs source diagnosis, batch reconciliation and declared impact lookup. It does not modify incident history. Results include ordered step reports, evidence hashes and scoped observations. Missing/invalid evidence or tool-policy failure returns INCONCLUSIVE rather than a guessed conclusion.

Investigation exit 0 means COMPLETED, including a completed investigation that found data failure; exit 1 means INCONCLUSIVE; exit 2 means rejected input/command. NO_FAILURE_OBSERVED applies only to the checks performed. This command remains transient; use the explicit durable commands below to retain workflow output and batch-stage bytes. The 10 labeled development regressions are not a held-out model benchmark and do not measure model accuracy. See [ADR-0006](docs/adr/0006-bounded-retained-source-investigation.md) and [suite scope](docs/research/investigation-development-suite.md).

## Durable investigations and explicit schema migration

New stores use schema V2. Existing V1 stores remain readable with unchanged source history; they are never upgraded on open. Back up an existing store using SQLite backup, stop writers and explicitly migrate before recording investigation runs:

```sh
PYTHONPATH=src python3 -m aegisflow_dr store-migrate --db work/incidents.db
PYTHONPATH=src python3 -m aegisflow_dr record-investigation --db work/incidents.db --incident INCIDENT_ID --key run-001
PYTHONPATH=src python3 -m aegisflow_dr read-investigation --db work/incidents.db --run RUN_ID
PYTHONPATH=src python3 -m aegisflow_dr replay-investigation --db work/incidents.db --run RUN_ID
```

Recording returns 0 for a committed run, including INCONCLUSIVE; inspect trace.status and trace.assessment. Read and replay verify the parent source, trace, policy and artifact bindings. Replay returns 0 for MATCH, 1 for MISMATCH and 2 for rejected operations or unavailable implementation. Timing-dependent failures may replay differently; replay never overwrites the original. Exact replay requires matching code, packaged SQL, Python and SQLite versions.

Run keys are scoped to an incident. Same-key/same-request retries return the original verified run without executing tools; changed policy or transform conflicts. The four batch snapshots come from the authorized execution itself. Source failures and denied batches do not trigger hidden batch execution. JSON and CLI output contain metadata and checksums; raw snapshot bytes are accessible only through the trusted local host interface. The database remains unencrypted synthetic research storage. See [ADR-0007](docs/adr/0007-durable-investigation-evidence.md) and [increment 06](docs/delivery/increment-06.md).

## Multi-agent integration foundation

The contract-first coordination package validates internal task/proposal/verdict/receipt messages, routes controlled capability tags through a bounded DAG, reads an existing run via the A26 local slice, and independently reviews a structured assessment via the A27 deterministic slice. This path makes no model calls, modifies no incident/run history and does not expose a network listener.

Use `review-investigation --db work/incidents.db --proposal work/proposal.json` with the [v1 contract](docs/contracts/coordination-v1.md). Wrong assessments or citations reject; unavailable/incomplete evidence abstains. These local messages are not MCP/A2A protocol objects, role labels are not certificates, and the verifier is not an LLM-as-a-Judge. The [ten-component architecture and diagrams](docs/adr/0008-agent-coordination-boundaries.md) document planned MCP/A2A, model routing, RAG, CAG, mTLS and remote transport boundaries. [Increment 07](docs/delivery/increment-07.md) records measured tests and coverage.


## Durable review queue

The optional durable review path stores reservation/retry/cancellation state in a separate private SQLite queue, preserving immutable source/run storage. It dispatches the existing A26→A27 local slices, validates dependencies, rejects stale results, and recovers expired work with bounded exponential backoff. Worker reads run outside queue write transactions. Immediate review remains available.

Start with `queue-init --queue work/reviews.db`, then `submit-review --queue work/reviews.db --db work/incidents.db --proposal work/proposal.json --key review-001`. Run `work-once` with both paths to process one task; inspect `read-job --queue work/reviews.db --job JOB_ID`. See the [operator/API contract](docs/contracts/durable-review-v1.md), [state and recovery decision](docs/adr/0009-durable-local-review-execution.md) and [increment 08 evidence](docs/delivery/increment-08.md).

This is a trusted local, read-only execution baseline with at-least-once work and fenced result commits. It does not provide distributed identity, remote delivery, hard cancellation, exactly-once external effects or a background worker service. A completed review job may reject or abstain; inspect its Judge verdict. No model accuracy is claimed.


## Certificate identity and bounded HTTPS review

The integration foundation now supports TLS 1.3 mutual authentication, explicit leaf-certificate pins, exact incident/run grants and pinned-IP egress for a private read-only review binding. Proposal inputs cannot supply identity, policy or endpoint configuration. Real loopback TLS tests cover certificate failures, default denial, cross-resource access, rotation, response budgets and shared network deadlines.

Use the [secure review host contract](docs/contracts/secure-review-v1.md) and [ADR-0010](docs/adr/0010-mtls-resource-and-egress-boundaries.md). No production listener or external service is configured. The private JSON binding remains available independently of the A2A profile below. Existing evidence/queue history and the original Turkish architecture remain preserved. [Increment 09](docs/delivery/increment-09.md) records its validation.

## Official A2A stateless review profile

The optional `a2a` extra pins `a2a-sdk==1.3.0`. An A2A 1.0 HTTP+JSON client and host callback wrap the existing read-only review using official generated protobuf models. Only synchronous `POST /message:send` with one JSON proposal and one direct verdict message is supported. Fixed endpoints, mutual TLS, exact certificate/resource grants, strict input/output contracts and bounded transport remain enforced before SDK compatibility decoding. No discovery, remote task lifecycle, streaming, files, push delivery or automatic protocol fallback is enabled.

Base installation does not require the SDK; install `".[a2a]"` to use `integration.a2a_client.review_a2a`. The host supplies private TLS files, pinned endpoint and resource grants. Tests exercise the real SDK over temporary local TLS channels; no production A2A HTTP server is shipped. See [profile contract](docs/contracts/a2a-review-v1.md), [ADR-0011](docs/adr/0011-official-a2a-stateless-review.md) and [Increment 10](docs/delivery/increment-10.md). This profile adds transport interoperability, with no model calls or new accuracy claim.

## Official MCP local tool profile

Install `".[mcp]"` for the separately pinned official `mcp==2.3.0` SDK. `integration.mcp_tools.LocalToolSession` wraps the existing tool gateway in an official MCP Server for a trusted in-process Client using protocol revision `2026-07-28`. Host grants control both discovery and dispatch of `diagnose_csv`, `query_lineage` and `run_batch`. Exact input schemas, bounded results and persistent per-instance call/deadline budgets apply; reconnecting a client does not reset them. Batch execution stays in memory with the clean packaged transform.

This increment validates SDK client/server calls in process. It does not expose a network endpoint or connect MCP calls to the A2A certificate identity. See [MCP contract](docs/contracts/mcp-local-tools-v1.md), [ADR-0012](docs/adr/0012-official-mcp-local-tools.md), [Increment 11](docs/delivery/increment-11.md) and [current implementation status](docs/delivery/status.md). Next establish held-out evaluation and model acceptance contracts before enabling provider calls or interface work.

## Versioned public validation baseline

`python -m aegisflow_dr.benchmark` runs a frozen synthetic suite with 10 development and 8 public validation cases. Closed suite/prediction/report schemas, cross-split leakage checks, label-free execution and per-family confusion/precision/recall/F1, abstention/error/coverage metrics make failures visible. Exact label and tool-sequence matching is a deterministic regression gate. The new cases are public and were inspected during development; their 8/8 agreement is not a blind holdout or model accuracy. Zero model calls are made.

See [ADR-0013](docs/adr/0013-versioned-public-validation.md), [versioned contracts](docs/contracts/benchmark-v1.md) and [Increment 12](docs/delivery/increment-12.md). Next define provider-neutral prediction/evidence contracts and predeclared acceptance/sealed-evaluation rules before live model calls. Production identity, deployment operations and interface work remain gated.

## Agent connections and current visibility

Open the [agent connection/state map](docs/agents/README.md) to see the implemented A26 → A27 dependency and surrounding tool/protocol components. The existing read-job command provides a verified local queue snapshot and recorded history. Other catalog roles remain planned; a continuous authenticated live observer is future work.

## Offline model-advisory contracts

Host-owned AdvisorySession binds metadata-only requests to verified retained evidence, model/prompt hashes and a unique request digest. Strict structured advice is checked against the current record and existing deterministic Judge. It cannot authorize tools or writes. No provider, complete generation prompt or model confidence is enabled. See [ADR-0014](docs/adr/0014-offline-advisory-boundary.md), [security review](docs/security/review-2026-11-11.md) and [Increment 13](docs/delivery/increment-13.md).

## Minimized evidence context and bounded prompts

PreparedAdvisory now builds a versioned prompt from allowlisted diagnostic summaries, excluding raw source/business identifiers, monetary values and arbitrary report/header text. Host-owned context/full-prompt byte limits reject overflow; context/schema/policy/record/input hashes bind the prepared snapshot to the existing advisory response gate. Accessors return detached objects. No provider is contacted, and counts/hashes/operational metadata still require data-policy review before external use.

See [context contract](docs/contracts/evidence-context-v1.md), [ADR-0015](docs/adr/0015-allowlisted-evidence-context.md) and [Increment 14](docs/delivery/increment-14.md). Byte budgets remain separate from usage admission below.

## Durable usage admission before model dispatch

The trusted host can reserve token/cost capacity in a separate local SQLite ledger using an approved quote bound to the exact prepared input and model. Atomic reservations, one-shot start, original request deadlines, bounded attempts and idempotent settlement survive reopening. Unknown usage retains the entire hold and blocks retry for that request; timeouts never imply a free call. Costs use integer nano-US dollars with explicit host rates, not floating-point estimates.

See [usage contract](docs/contracts/usage-ledger-v1.md), [ADR-0016](docs/adr/0016-durable-usage-admission.md) and [Increment 15](docs/delivery/increment-15.md). This adds local accounting without a provider, tokenizer or dispatch scheduler. Next implement the simulated adapter boundary and bounded retry/backoff; actual payload tokenization, transport deadlines, output limits, shared fallback budgets and approved live evaluation remain activation gates.

## One-shot advisory dispatch

A trusted synchronous adapter now connects immutable prepared inputs to durable usage admission/start, exact settlement and independent Judge review. Repeated or concurrent attempt keys cannot dispatch twice; ambiguous outcomes retain holds. Limits are propagated and late/oversized results rejected. No live provider or hard I/O preemption is supplied. See [ADR-0017](docs/adr/0017-one-shot-advisory-dispatch.md) and [Increment 16](docs/delivery/increment-16.md).

## Bounded cooperative advisory streams

The trusted synchronous dispatcher can consume owned async streams with a shared timeout, bounded bytes/frame count, final trusted usage and source cleanup. Timeout/incomplete streams retain usage holds. Sources must cooperate with cancellation; real provider I/O enforcement remains gated. See [ADR-0018](docs/adr/0018-bounded-cooperative-stream.md) and [increment 18](docs/delivery/increment-18.md).

## Bounded same-model retry

Trusted workers may explicitly retry only settled known retryable failures, with capped attempts/backoff and the original input/model/deadline. Usage remains charged and the durable ledger controls admission. Unknown usage and duplicate/restarted operation keys stop safely. See [ADR-0019](docs/adr/0019-bounded-advisory-retry.md). Bounded cross-model failover is available in the opt-in routing profile below; automatic crash resumption remains disabled.

## See the backend work without a web interface

Run `python -m aegisflow_dr.advisory.demo` after installation, or `PYTHONPATH=src python -m aegisflow_dr.advisory.demo` from this checkout. The offline synthetic demonstration prints ordered primary/secondary fixture events, independent verification, shared usage and a denied third attempt. It makes zero provider calls and uses no credentials. The demo uses actual bounded local routing, persists outcomes, replays completed history without sending again and denies a manual third call. See [increment 22](docs/delivery/increment-22.md).

### Bound operation admission

Bound operation admission was introduced with version 2 ledgers bound to one retained investigation, its evidence/context, approved fixture models and the original deadline. A different run, changed context or unapproved model is denied before dispatch; an eligible answer still passes independent evidence review. See [increment 21](docs/delivery/increment-21.md) and the [operation contract](docs/contracts/operation-binding-v1.md). No measured live-model accuracy is claimed. The demo now opts into version 3 routing.

### Controlled model routing

`execute_route` accepts an ordered tuple of at most eight distinct approved candidates on a new version 3 ledger. It switches models only after a settled retryable technical failure. Rejected, abstained or malformed answers and unknown usage stop safely. The same database records route ownership, exact candidate order, accounting and sanitized outcomes. Interrupted routes never auto-resume; completed replay is historical. See the [routing contract](docs/contracts/model-routing-v1.md) and [ADR-0022](docs/adr/0022-bounded-durable-model-routing.md).

### Recovery evidence and live output milestones

`assess_recovery(ledger)` inspects routing/accounting in one read-only transaction, reports unresolved holds and unjournaled settlements, and exports canonical digests for operator review. It grants no resend or refund authority. See [increment 23](docs/delivery/increment-23.md) and [live output milestones](docs/delivery/live-output-milestones.md).

### Bound recovery review requests

Recovery assessment now checks event/plan/attempt correlation and known/unknown usage consistency. `prepare_recovery_review` binds an advisory request to one operation and exact snapshot; `verify_recovery_review` rejects stale evidence. Operator UUIDs remain host-supplied, with no authentication or state-change authority. See [increment 24](docs/delivery/increment-24.md).

### Model quality acceptance

The provider-neutral quality gate computes exact-count PASS/BLOCK against a frozen dataset/model/policy. Candidate defaults require 95% overall accuracy, per-class precision/recall and per-family accuracy, with minimum samples, independent provenance and zero errors/unsupported claims. Perfect public fixtures remain blocked. See [ADR-0025](docs/adr/0025-measurable-model-quality-acceptance.md). Actual sealed evaluation and activation enforcement remain pending.

Quality evaluations can now run through an immutable local protocol registration and append-only result history. Both accepted and blocked runs are retained, and a repeated run ID cannot substitute new results. See [registration contract](docs/contracts/evaluation-registration-v1.md).

Offline curation preparation now binds label-free source corpora, rejects known split overlap/repeated candidate groups and reconciles exactly two host-approved annotation artifacts. Any disagreement exports no quality labels. Agreement still requires independent provenance and registered quality acceptance. See [curation contracts and data flow](docs/contracts/evaluation-curation-v1.md) and [ADR-0026](docs/adr/0026-dual-review-evaluation-curation.md). Authenticated reviewer identity and sealed-data operations remain pending.

New acceptance protocols can use [statistical quality v2](docs/contracts/statistical-quality-v2.md): exact binomial support for overall/class/family targets, a fixed simultaneous error budget and explicit sampling approval (false by default). V1 historical behavior is preserved. Agreement and passing tests do not establish measured model performance. See [ADR-0027](docs/adr/0027-exact-statistical-quality-support.md).

Curation artifacts can be retained in private local snapshots and revalidated against an externally trusted digest on every read. Agreement and disagreement are preserved; real datasets remain outside this public repository. See [snapshot contract and trust boundaries](docs/adr/0028-verified-curation-snapshots.md).

The optional `curation` profile adds [dataset-scoped annotation signature verification](docs/contracts/curation-authentication-v1.md). Explicit trusted-host public-key grants authenticate exact annotation bytes before two-reviewer consensus. This does not enroll human identities or make legacy unsigned snapshots authenticated; protected signed-evidence retention remains pending.
