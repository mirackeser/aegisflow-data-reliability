# Agent Runtime (PR 1 of 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** All 36 catalog roles as contract-bound executable agents, orchestrated per case by supervisor, planner, router, dependency planner and budget controller roles, using the local model, RAG, CAG, the tool gateway, MCP, A2A over mTLS and the Judge, with a held-out measurement that includes the first real model measurement.

**Architecture:** a new package `src/aegisflow_dr/agents/` with `contracts.py` (schemas `data/agent-task-v1.json`, `data/agent-result-v1.json`), `registry.py` (36 role specs: kind, triggers, allowed tools, budget), `llm.py` (Ollama loopback adapter with an injectable transport for tests), `executors/` (one module per layer group, reusing existing modules), `runtime.py` (run lifecycle, waves, events, budgets, Judge gate), `transport.py` (in-process, MCP-local and A2A-mTLS paths with an ephemeral CA), and `agents_eval.py` (held-out).

**Spec:** `docs/superpowers/specs/2026-11-24-agent-runtime-design.md`.

## Global Constraints

- Gates as in earlier plans: package 100% branch coverage; apps/local; node scripts. Tests never need Ollama: `llm.py` takes an injectable transport, and the tests use recorded responses. A separate opt-in check, `tools/check_local_llm.py`, needs a running model and is not part of CI.
- Ollama access only through `http://127.0.0.1:11434` (refuse any other host); request JSON-schema `format`, `temperature: 0`, `seed: 7`, `think: false`, timeout 30 s, max 512 output tokens; record model, prompt SHA-256, tokens and latency.
- Budgets per run: 8 specialists, 4 per wave, 12 LLM calls, 40,000 tokens, 90 s.
- Outcomes are only `COMPLETED`, `NEEDS_EVIDENCE`, `POLICY_DENIED`, `SKIPPED` or `FAILED`; no fabricated output; LLM output is advisory and is Judge-gated.
- Certificates come from an ephemeral CA in a temporary 0700 directory, deleted at run end; nothing key-like is ever written into the repo.
- Never claim root cause, model accuracy beyond measured held-out, production or autonomous remediation.

## Tasks

1. **Contracts and registry**: both schemas; 36 `RoleSpec`s generated from the catalog plus a hand-written table of kind, triggers, tools and executor; tests that every catalog id has exactly one spec, that each executor is resolvable, and that the schemas accept and reject examples.
2. **LLM adapter**: `LocalModel` (Ollama) with an injectable transport, a loopback-only guard, schema-constrained JSON, usage capture, MODEL_UNAVAILABLE handling, and CAG through `advisory/context_cache`; tests use a fake transport.
3. **Executors**: rule agents wrap existing modules; LLM agents A23, A29, A30 and hybrids A02, A22 use the adapter with fixed prompt templates (versioned, hashed); agents without inputs return NEEDS_EVIDENCE with a reason; tests per agent for COMPLETED and NEEDS_EVIDENCE paths.
4. **Runtime**: supervisor, planner, router, dependency waves (thread pool), budget enforcement, typed event log, evidence store, Judge gate, approval request for proposals; tests for selection, waves, budget stops, policy denial, determinism with a fake LLM.
5. **Transports**: in-process default; MCP-local path when the `mcp` extra is importable; A2A review over mTLS with an ephemeral CA when the `a2a` extra is importable; fingerprints in the run record; tests guarded by import availability (CI installs the extras).
6. **Evaluation**: `agents_eval.py` on fresh groups 120–179, with expected role sets per scenario fixed in the module before any held-out run; role-selection precision and recall, Judge acceptance, LLM JSON validity, A23 top-1 against the injected mechanism (recorded responses for CI; the live run is produced once by the controller with the local model and committed as the report).
7. **Controller**: whole-branch review, fix wave, held-out once with the live local model, docs, status increment 64, PR, merge.
