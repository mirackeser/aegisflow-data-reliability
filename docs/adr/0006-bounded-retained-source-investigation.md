# ADR-0006: Coordinate retained evidence with a bounded deterministic workflow

Status: accepted for the local development baseline. Date: 2026-11-10.

## Execution contract

Read a verified source snapshot from the existing incident store without mutating its lifecycle. Reject changed diagnostic code/Python runtime before invoking tools. Use one host-owned ToolGateway session for the whole investigation; routing cannot create a replacement budget.

The workflow is source diagnosis → conditional batch reconciliation → conditional impact lookup. A failing source skips batch work and requests source-level declared impact. A clean source permits batch execution; a failing batch requests customer-sales impact. A passing batch terminates with NO_FAILURE_OBSERVED. At most three admitted tool calls are needed. There is no automatic retry or model-driven replan in this version.

Tool reports are not accepted merely because transport returned OK. Source output must equal the retained canonical diagnosis, including exact source hash. Batch checks validate source binding, packaged SQL/staging contract hashes, artifact linkage, typed counts, arithmetic consistency, check evidence references and agreement between status and results. Impact output must match the fixed declared DAG. Invalid reports are discarded and the workflow returns INCONCLUSIVE without final observations/assessment. Previously accepted step reports remain diagnostic trace, not a completed conclusion.

## Meaning of results

COMPLETED describes workflow completion, including observed source or transformation failures. CLI exit 0 therefore does not mean healthy data. INCONCLUSIVE returns exit 1; invalid command/input returns exit 2. Assessments are NO_FAILURE_OBSERVED, SOURCE_QUALITY_FAILURE or TRANSFORMATION_RECONCILIATION_FAILURE. They are scoped observations, not inferred root causes, confidence probabilities or automatic repair approvals.

Each result records source, policy and implementation fingerprints plus ordered tool outcomes, canonical report hashes and observation references. Reports omit raw input rows. A byte-order mark is preserved through tool input encoding, so source evidence binding remains exact.

## Boundaries

The baseline has deterministic conditional routing, not 36 working specialists or a model planner. Source incidents stay persistent; returned workflow traces and batch report contents are currently transient JSON output. Staging/mart byte snapshots are not retained. Report validation establishes structural consistency and source binding, not independent proof of every transformation's semantics or an authenticated claim against compromised host code. The prior customer-attribution blind spot remains documented.

Host code and local operator access remain trusted. The gateway's cooperative deadlines, session-local quotas and absence of enterprise identity are unchanged. Durable workflow runs, retained batch evidence, retry/cancellation policies, model-provider contracts and semantic verification are infrastructure work before UI readiness.
