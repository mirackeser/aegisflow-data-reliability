# Increment 07 — Contract-first multi-agent coordination

Goal: define the ten requested ecosystem boundaries and implement the first safe local integration slice without changing retained investigation semantics or storage history.

## Delivered

- ADR-0008 analyzes MCP, A2A, LLM routing/prompts/fallback, RAG, CAG, contracts, certificates/identity, TAG, transport and Judge. Flow and sequence diagrams identify implemented and planned boundaries.
- Four versioned, closed JSON Schema contracts are packaged and enforced for inbound/outbound task, proposal, verdict and receipt messages; parsing is bounded, duplicate keys/nonfinite JSON reject and schema resolution is offline.
- A host-owned controlled capability/tag registry and bounded DAG reject missing/cyclic/cross-context dependencies, unavailable/ambiguous workers and invalid scheduler states.
- A26 reads integrity-verified retained runs. A27 independently derives scoped assessments from evidence and returns ACCEPT, REJECT or ABSTAIN. These are two deterministic local slices of the original design roles, not full autonomous agents or LLM-as-a-Judge.
- review-investigation CLI and installed-wheel smoke checks cover positive/contradictory proposals across process boundaries. Existing investigator code, database schema, source and run records are unchanged.
- CI measures application coverage, enforces 100% statement/branch coverage on the coordination Python package, checks Python 3.11/3.12/3.14, and adds known-vulnerability auditing of resolved runtime dependencies.

## Verification

Local Python 3.12 validation on 2026-11-10: 177 application unit/integration/simulation tests plus eight repository-hygiene tests passed (185 distinct test methods total). The 31 added tests include schema/malformed-message cases, privilege-field injection, bounded and cyclic DAGs, forged assessments, bad citations, corrupt/unavailable/cross-context evidence, dependency blocking and CLI outcomes. Repeated runs and subtests are not counted as additional distinct test methods.

Coverage.py 7.17.2 measured 205/205 statements and 78/78 branch exits covered in the new coordination package (100% each). The complete application report is approximately 96% combined statement/branch coverage; see CI for per-module detail. This is test-path coverage, not model accuracy, security certification or completeness of all ten target components.

The built wheel passed installed licensing/catalog/gateway/source/batch/persistence/investigation/evaluation/run/Judge checks outside the checkout. All 10 labeled development scenarios remained matched; they are not an independent held-out model benchmark. Redacted local Gitleaks scanning and candidate-file/PDF hygiene passed; the declared runtime dependency graph had no known vulnerabilities in the pip-audit result at scan time. CI also scans reachable Git history and extracted historical PDF versions.

## Explicit limits and next step

MCP/A2A adapters, mTLS/certificate issuance, signed tokens, remote transports, model routing/fallback, vector retrieval and CAG remain planned. No certificates/keys or real enterprise data were introduced; no network listener or model call is enabled. Certificate validation and remote identity negative tests belong to the authenticated adapter increment and are not claimed complete here. The current coordination path is a read-only in-process simulation, with ephemeral receipts and no durable delivery, retries or cancellation.

Next: durable execution reservations/leases, idempotent dispatch, retry/backoff, cancellation and crash recovery. Then select deployment/identity/data-residency constraints before implementing one authenticated protocol adapter. Model/vector/broker provider and budget choices require operator agreement before external provisioning; local infrastructure work can continue without those choices. Original architecture archive and prior repositories remain preserved.
