# Binding role table for the agent runtime (36 roles)

Case input (`Case`): `payload` (current CSV bytes, required), `baseline` (stored baseline record or None), `as_of` (str or None),
`second_payload` (bytes or None, a second extract for cross-source/join checks), `retriever` (callable(query, limit) -> list of
{source, revision, passage, citation} or None; the workbench injects its Knowledge base), `history` (list of retained run
summaries or None), `tenant_id`, `case_id`.

Triggers use the observation checks produced by profiling.profile_csv / baseline.compare / pipeline.diagnose_csv plus case
inputs. "always" roles are control roles that run every case and do not count toward the 8-specialist limit.

| id | name | kind | runs when | executor (existing code it uses) | NEEDS_EVIDENCE when |
|---|---|---|---|---|---|
| A01 | Global Supervisor | control | always | runtime: opens/closes run, final status | never |
| A02 | Investigation Planner | hybrid | always | rule plan from observations; LLM rewrites goals as short questions (advisory, Judge-checked that every goal maps to an observation) | model unavailable → rule plan only, status COMPLETED with llm null |
| A03 | Dynamic Agent Router | control | always | trigger table below → selected specialists (max 8) with reasons; others SKIPPED with reason | never |
| A04 | Dependency & Parallelism Planner | control | always | coordination.routing DAG → waves (max 4 per wave) | never |
| A05 | Budget & Escalation Controller | control | always | enforces 8 specialists / 12 LLM calls / 40,000 tokens / 90 s; stops run with BUDGET_EXCEEDED | never |
| A06 | Investigation Recovery Coordinator | control | after any FAILED agent | records retry-once decision (same input) or safe stop; no retry for POLICY_DENIED | no failed agent → SKIPPED |
| A07 | Pipeline Run Explorer | rule | history given | summarise retained run history (counts, last status) | no history |
| A08 | Schema Drift Investigator | rule | baseline given | schema_registry.diff_columns between baseline columns and current header/roles | no baseline |
| A09 | Data Contract Inspector | rule | header matches the order contract | pipeline.diagnose_csv | payload is not an order extract → NEEDS_EVIDENCE (contract not applicable) |
| A10 | Data Profiling Specialist | rule | always selected as first specialist | profiling.profile_csv | never |
| A11 | Freshness & Volume Analyst | rule | baseline given | baseline.compare volume + freshness measurements | no baseline |
| A12 | Log & Error Trace Analyst | rule | selected only if logs provided | — | always (no log source connected) |
| A13 | Data Lineage & Impact Investigator | rule | order extract | batch.downstream("source_orders") | not an order extract |
| A14 | SQL Transformation Analyst | rule | order extract | batch.run_batch transform report | not an order extract |
| A15 | Incremental Load Investigator | rule | time column present | profiling timestamp_gap / duplicate / out-of-order findings as watermark evidence | no time column |
| A16 | CDC & Replication Investigator | rule | selected only if CDC stream provided | — | always (no CDC source) |
| A17 | Data Type & Casting Investigator | rule | profile has type_mismatch or schema role change | profiling type_mismatch + baseline role_change | none of those |
| A18 | Join & Cardinality Investigator | rule | second_payload given and both order extracts | cardinality.join_cardinality | otherwise |
| A19 | Reconciliation Investigator | rule | order extract | batch.run_batch reconciliation | not an order extract |
| A20 | Statistical Drift Investigator | rule | baseline given | baseline.compare PSI measurements | no baseline |
| A21 | Cross-Source Consistency Investigator | rule | second_payload given and both order extracts | consistency.compare | otherwise |
| A22 | Incident Similarity & Knowledge Agent | hybrid | retriever or history given | RAG: retriever(query from observations) with citations; LLM 1-sentence relevance per citation (advisory); Judge verifies every citation | neither given |
| A23 | Root Cause Hypothesis Generator | llm | observations exist | LLM proposes up to 3 catalog mechanisms (schema-constrained enum = hypotheses.MECHANISMS) with the observation ids they explain; advisory; compared with A24/A25 result | model unavailable |
| A24 | Counter-Hypothesis Agent | rule | baseline given and observations exist | hypotheses.investigate competitors | no baseline |
| A25 | Active Probe Planner | rule | same as A24 | hypotheses.investigate probe sequence | no baseline |
| A26 | Evidence Collector | control | always | stores every agent result + input digests in the run evidence store (in memory, digest-addressed) | never |
| A27 | Evidence Verification Agent | control | always (Judge) | every claim's evidence refs exist and match digests; LLM claims additionally must reference observation ids that exist; rejects otherwise | never |
| A28 | Root Cause Ranking & Uncertainty Reviewer | rule | A24 ran | hypotheses ranking + verdict as uncertainty | A24 did not run |
| A29 | Remediation Strategy Planner | llm | accepted findings exist | LLM drafts up to 3 remediation options (text, risk, rollback) as proposals only | model unavailable or nothing accepted |
| A30 | Patch Proposal Agent | llm | A29 produced options and the case is an order extract | LLM drafts a SQL/CSV-cleaning proposal text; never executed | otherwise |
| A31 | Sandbox Validation Orchestrator | rule | A30 produced a proposal | re-runs profiling/diagnose on the unchanged payload in memory and states the proposal is NOT applied (validation of proposals needs a sandbox writer, unavailable) → NEEDS_EVIDENCE with reason SANDBOX_WRITES_DISABLED | always NEEDS_EVIDENCE today |
| A32 | Regression & Backfill Validator | rule | A30 produced a proposal | same honest NEEDS_EVIDENCE (no backfill target) | always |
| A33 | Human Approval Coordinator | control | proposals exist | creates a pending approval item (no action executed) | no proposals → SKIPPED |
| A34 | Policy & Data Access Reviewer | control | always, before any LLM call | checks the LLM context contains no raw record values (only aggregates/ids/column names) and the tool request is in the allowlist; POLICY_DENIED otherwise | never |
| A35 | AgentOps & Cost Analyst | control | always (end) | usage roll-up: tool calls, LLM calls, tokens, latency per agent | never |
| A36 | Evaluation & Feedback Curator | control | always (end) | writes an evaluation record (selected roles, statuses, Judge outcomes) for later curation | never |

LLM context rule (A34): prompts may include column names, check names, counts, rounded statistics, observation ids and mechanism
names. Never record values, identifiers or free text from the file.
