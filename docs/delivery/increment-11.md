# Increment 11 — Official MCP local tools and policy lifetime

Goal: provide the next official protocol adapter behind existing tool grants before introducing model services or UI.

## Delivered

- Optional official mcp 2.3.0 Server/Client integration with explicit 2026-07-28 profile revision and native SDK models.
- Three existing tools exposed through one host-owned LocalToolSession: source diagnosis, clean in-memory batch and declared lineage. Discovery and dispatch derive from the same exact tool/dataset grants.
- Closed input schemas, bounded structured/text result envelope, sanitized protocol/tool errors, denied custom metadata/tasks/continuations and local-only raw snapshots.
- Shared immutable-policy call/deadline lifetime across reconnects, concurrent reservation enforcement and cancellation checkpoint before dispatch. Default server telemetry middleware replaced by the profile guard.
- Twenty new tests with actual official in-process client/server calls plus negative/fault cases; installed-distribution MCP checks and CI across Python 3.11/3.12/3.14.
- ADR-0012, profile contracts/diagrams, licensing/security notes and an implementation status record. Existing schema/fingerprint/architecture archives remain preserved.

## Measured validation (2026-11-11)

296 application unit/integration/simulation methods and 13 security/hygiene methods passed: **309 distinct tests**. Matrix repetitions, subtests, reruns and installed smoke checks are not counted again.

The new MCP module covers 87/87 statements and 24/24 branch exits. The combined security/integration package covers 417/417 statements and 82/82 branch exits (100%). Coordination and workflow remain at 100%. Whole-application combined coverage rounds to 98%: 2,204 statements and 700 branch exits, with 40 statements and 32 branch exits still uncovered in older modules. Coverage is not model accuracy or security certification.

New tests cover official discovery/version/capabilities, all three tools, successful quality FAIL/BLOCKED reports, empty grants, dataset isolation, forbidden fields, missing/wrong/oversized/Unicode input, sanitized failure, budget persistence across reconnects, concurrent reservations, expired deadlines, unsupported legacy/resources/prompts/metadata, detached schemas, bad/oversized/nonfinite tool output and pre-dispatch cancellation. All previous TLS/A2A, evidence replay and queue recovery tests remain active.

Runtime and all optional dependency graphs, including MCP's transitive packages, reported no known vulnerabilities at scan time. Installed-wheel checks exercise MCP discovery/dispatch/default denial/shared budgets outside the source checkout, alongside existing data/evidence/queue/TLS/A2A checks. Candidate secret/file/PDF hygiene runs before publishing; CI also scans fetched Git history and historical PDF text.

## Practical boundary and next increment

The MCP SDK calls are in process. This does not validate a remote MCP HTTP transport, hostile byte framing, mTLS identity propagation to MCP, durable quotas or hard preemption. No listener, model provider, external service or UI is enabled. Original source/run/queue schemas and execution fingerprints remain unchanged.

Next: versioned evaluation contracts, separate held-out failure families and a deterministic baseline, followed by model acceptance/abstention/cost/latency gates before provider integration. The current ten labeled development cases match expected behavior but are neither held-out results nor model accuracy. See [implementation status and remaining gates](status.md).
