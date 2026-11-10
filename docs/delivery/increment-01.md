# Increment 01 — Synthetic CSV diagnostics

Goal: give later investigation agents a reproducible, evidence-producing diagnostic foundation.

Acceptance criteria:

- Clean synthetic orders pass and yield an exact decimal total.
- Controlled schema, null and duplicate faults produce the corresponding check failures.
- Identical input yields identical JSON, SHA-256 and logical record references.
- Malformed CSV, ambiguous headers, invalid encoding and input-budget excess are rejected.
- Findings are bounded and truncation is explicit; a failing dataset never publishes a valid total.
- The CLI distinguishes pass, quality failure and rejected input with exit codes 0/1/2.
- The installed package can validate its catalog without depending on repository-relative files.

Local validation (2026-11-10): 23 unit/integration regression tests passed on Python 3.14. A wheel was built and installed into an isolated target; catalog, clean demo and all three failing-quality demos were verified from outside the checkout. CI also tests Python 3.11, 3.12 and 3.14 and repeats installed-package smoke checks. See the PR checks for this exact revision. These are development regressions, not a held-out research benchmark.

Remaining scope: batch transformations, lineage, incident persistence, tool authorization, agent execution, frontend and held-out experiments. All 36 roles remain design metadata.
