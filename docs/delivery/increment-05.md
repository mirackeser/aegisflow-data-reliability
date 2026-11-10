# Increment 05 — Bounded retained-source investigation

Goal: connect retained source evidence, policy enforcement and diagnostic tools into one reproducible local investigation.

Acceptance criteria:

- Clean, source-failure and transformation-failure cases follow distinct documented tool paths.
- A single gateway session enforces permissions and budgets across every step.
- Source/version mismatch, unavailable evidence, denial, tool failure and malformed output cannot become a final successful assessment.
- Source and tool-report hashes anchor structured observations; no root cause or probability is invented.
- Existing incident records remain unchanged, including closed cases.
- Installed CLI supports investigations and labeled development regressions outside the checkout.
- Development labels are used only after execution; changing an expected label causes evaluation failure rather than changing the workflow.

The 10-case development suite is reviewable at fixtures/evaluations/investigation-development-v1.json and packaged identically. Its result is regression agreement, not a model accuracy benchmark or held-out evaluation. No LLM calls are made. See ADR-0006 for transient workflow/batch evidence and remaining infrastructure gates.

Local validation (2026-11-10): 109 application tests and eight repository-hygiene tests passed. All 10 labeled development scenarios matched their expected assessments and tool paths. The installed wheel passed license/catalog/gateway/source/batch/persistence checks, clean and faulted investigations, and the packaged development evaluation from outside the checkout. These are regression results, not model accuracy measurements.
