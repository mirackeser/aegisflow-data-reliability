# Agent Flow Page (PR 2 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A bilingual, accessible "Agent flow" page where an operator starts an investigation on a file and watches the 36 agents work live. It shows a flow diagram, per-agent states, the messages between agents and their transports, outputs, evidence, Judge verdicts, model, RAG and CAG details, certificates and budgets, each with a plain explanation.

**Spec:** `docs/superpowers/specs/2026-11-24-agent-runtime-design.md` (section "Live flow") and the role table.

## Global Constraints

- Only real run events drive the view; no decorative or invented telemetry. Every state shown maps to an event in the run record.
- Server-Sent Events from `GET /api/agents/stream?run=<id>`, session-authorized, loopback only, bounded event buffer, reconnect with `Last-Event-ID`; `POST /api/agents/run` starts a run (body: base64 CSV, optional baseline name, optional as-of, optional second file); `GET /api/agents/runs/<id>` returns the full record for replay.
- The UI follows the existing h()/t() patterns, text-only DOM, CSP-safe styles and EN/TR strings (Turkish: ajan, akış, kanıt, hakem/Judge, bağlam önbelleği, bilgi getirme), keyboard navigation, visible focus, `prefers-reduced-motion`, no horizontal scroll at 375 px, and a text table alternative for every diagram.
- Design pass with the ui-ux-pro-max skill (data-dense dark operations dashboard) before implementation.

## Page layout

1. **Header strip:** the run selector (live or past), status, elapsed time, and budget meters for agents 8, LLM calls 12, tokens 40k and time 90 s, each showing used/limit.
2. **Flow diagram (SVG):** five swimlanes (Orchestration A01–A06 → Specialists A07–A22 → Reasoning A23–A28 → Remediation A29–A32 → Governance A33–A36). The 36 nodes show their state by colour plus icon plus text: idle, selected, running (pulse unless reduced motion), completed, needs evidence, denied, skipped, failed. Edges show dependencies from A04 waves and message hops, labelled with the transport (in-process / MCP / A2A+mTLS / local LLM). The wave number is shown on nodes.
3. **Live event timeline:** a virtualised list with time, agent, event type and a one-line explanation.
4. **Agent detail drawer** (opens on node click or Enter): role description and limit, why it was selected or skipped, the contract (input and output JSON, collapsible), tools called with latency, evidence refs with digests, claims with the Judge verdict per claim, the LLM block (model, prompt hash, tokens, latency, cache hit/miss), RAG citations (verified ✓/✗), transport and certificate fingerprints, and the error code with a plain explanation.
5. **Results panel:** accepted findings, candidate explanations (from A24/A25/A28), model suggestions marked "advisory, Judge-gated", proposals awaiting human approval (A33) with approve/reject recording only, and the usage roll-up (A35).
6. **"How this works" explainer:** a short bilingual walkthrough of the pipeline with links to each agent's detail.

## Tasks

1. Server: run manager (background thread, bounded history of 20 runs), the three endpoints, SSE framing and tests (auth, 404, reconnect, bounded buffer, malformed body).
2. Flow page: diagram, timeline, drawer, results, explainer; strings; JS tests (event reducer is a pure function tested in Node: events → node states).
3. Browser verification: desktop and 375 px, EN and TR; a run with the local model and one with the model stopped (LLM agents show MODEL_UNAVAILABLE honestly); screenshots in the PR.
4. Controller: review, docs (status increment 65, README screenshots), PR, merge.
