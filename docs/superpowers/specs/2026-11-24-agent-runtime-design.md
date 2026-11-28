# Design: agent runtime for all 36 catalog roles with a live flow view (F01–F03, F06 slice, I-series)

Status: approved direction (operator 2026-11-24: "all ~36 agents should exist and be used; LLM, RAG, CAG, TAG, Judge, MCP, A2A,
contracts and certificates; I want to watch the agents' live flow"). Local model approved: Ollama + `qwen3:4b`
(Apache-2.0, 2.5 GB, loopback only). Budget USD 0.

## Principle

Every one of the 36 roles in `docs/agent-catalog.json` becomes a **registered, contract-bound executable agent**. An agent
runs only when the router selects it for a case, and each run reports one of these honest outcomes:

- `COMPLETED`: it did real work through allowed tools and returned claims bound to evidence.
- `NEEDS_EVIDENCE`: its inputs do not exist here, e.g. A12 has no logs and A16 has no CDC stream. It says so and stops.
- `POLICY_DENIED`: a tool outside its allowlist was requested.
- `SKIPPED`: the router did not select it, and the reason is recorded.
- `FAILED`: a typed error.

No agent fakes output. "36 agents exist" means 36 contracts, 36 executors and 36 rows in the live view. It does not mean 36
autonomous processes run on every request (catalog rule: at most 8 active specialists per case, waves of at most 4).

## Common contract (JSON Schema `agent-task-v1`, `agent-result-v1`)

- Task: `task_id`, `run_id`, `tenant_id`, `case_id`, `agent_id`, `goal`, `input_refs[]` (evidence ids/digests), `allowed_tools[]`,
  `budget` {max_tool_calls, max_llm_calls, max_tokens, deadline_ms}, `policy_version`.
- Result: `status` (above), `claims[]` {text_key, params, evidence_refs[]}, `evidence_refs[]`, `uncertainty` (low/medium/high
  + reason), `proposed_actions[]` (never executed), `usage` {tool_calls, llm_calls, tokens_in, tokens_out, latency_ms},
  `transport` (in_process | mcp_local | a2a_mtls), `llm` {provider, model, prompt_sha256, temperature, seed} or null,
  `retrieval` {citations[], cache: hit | miss | none} or null, `error_code`.
- Every result is schema-validated, then A27 (Judge) checks that each claim's evidence refs exist in the run's evidence
  store and match their digests before it may appear in a report.

## Execution kinds and honest labels

| kind | meaning | examples |
|---|---|---|
| Rule | deterministic code already in the repo | A08 schema_registry, A09 diagnose_csv, A10 profiling, A11/A20 baseline.compare, A13 lineage, A18 cardinality, A19 reconciliation, A21 consistency, A24/A25/A28 hypotheses |
| LLM | the local model via `agents/llm.py` (Ollama HTTP on 127.0.0.1, JSON-schema constrained output, temperature 0, fixed seed, prompt hash, token and latency usage). Output is advisory and goes through the Judge. | A23 proposes candidate mechanisms from observations; A30 drafts a patch proposal text; A29 drafts a remediation plan |
| Hybrid | an LLM suggestion checked by rules or tools | A22 (RAG retrieval plus an LLM summary with verified citations), A02 (rule plan plus an LLM wording of goals) |
| Control | orchestration roles | A01 supervisor, A03 router, A04 dependency planner, A05 budget controller, A06 recovery, A33 approval, A34 policy, A35 cost, A36 curation |

If the local model is unreachable, LLM agents return `NEEDS_EVIDENCE` with `error_code: MODEL_UNAVAILABLE`. There is no
silent simulation.

## Cross-cutting capabilities, as they appear in the flow

- **TAG / routing:** A03 selects roles from observation-to-role trigger rules; A04 builds the dependency DAG and waves.
- **RAG:** A22 retrieves passages from the knowledge base with revision-bound citations; the Judge verifies every citation.
- **CAG:** prepared LLM contexts are cached by (tenant, agent, prompt version, evidence digest) with `advisory/context_cache`;
  each LLM result reports hit or miss.
- **MCP:** rule agents call tools through the existing `ToolGateway` policy; when the `mcp` extra is installed the same
  tools are exposed through the local MCP profile and the result shows `transport: mcp_local`.
- **A2A + certificates:** the Judge review of the final claim set goes through the existing stateless A2A review profile
  over mutual TLS when the `a2a` extra is installed. The run creates an ephemeral local CA and leaf certificates in a
  temporary private directory (never committed) and shows their SHA-256 fingerprints. Otherwise the review is
  in-process and labelled so.
- **Budgets:** A05 enforces per-run limits (8 specialists, 12 LLM calls, 40,000 tokens, 90 s), as the design document
  specifies.

## Live flow

- Runs execute in a background thread and append typed events (`run_started`, `agent_selected`, `agent_skipped`,
  `agent_started`, `tool_call`, `llm_call`, `retrieval`, `cache`, `agent_finished`, `judge_verdict`, `approval_requested`,
  `run_finished`) to a bounded in-memory log plus the run record. `GET /api/agents/stream?run=` serves them as
  Server-Sent Events (session-authorized, loopback only).
- A new **Agent flow** page (EN/TR) shows the 36 agents grouped by layer, each with its state (idle / selected / running /
  completed / needs evidence / denied / skipped / failed), animated edges for dependencies and messages labelled with their
  transport, a run timeline, budget meters (agents, LLM calls, tokens, time) and a detail drawer per agent (contract,
  input and output JSON, tools, evidence, Judge verdict, LLM model, prompt hash and latency, citations, cache, certificate
  fingerprints). Every animation reflects a real event. Nothing is decorative telemetry.

## Evaluation (held-out, first real model measurement)

- On simulated incident cases (fresh groups 120–179, disjoint from earlier corpora), expected role sets are defined in this
  spec before measuring. Measure role-selection precision and recall, Judge acceptance, LLM JSON validity rate, A23
  top-1 agreement with the injected mechanism (the deterministic loop is reported side by side), and latency p50/p95 on
  this machine. Wilson intervals; held-out scored once. Prompts are fixed before scoring held-out.

## Delivery in two pull requests

1. **Runtime and contracts:** the agents package, the 36 executors, the local LLM adapter, the budgets, Judge
   integration, RAG/CAG wiring, the MCP and A2A paths, the evaluation and the status increment.
2. **Live flow page:** SSE, the Agent flow page, desktop and mobile browser verification, the capability map update.

## Honesty rules

The model is a local 4B model: its accuracy is whatever the held-out run measures, and it never decides alone. The
synthetic and simulated cases are labelled. No production connection, no root cause, no autonomous remediation: A29 and
A30 only propose, and A33 records a human decision.
