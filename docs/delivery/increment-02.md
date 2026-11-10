# Increment 02 — Batch transformation and declared impact

Goal: extend source diagnostics with actual staging/SQL mart execution, reconciliation evidence and potential downstream impact.

Acceptance criteria:

- A valid synthetic input produces deterministic staging and customer-sales artifacts with linked SHA-256 hashes.
- Money is handled as exact integer cents in SQL; customer groups and row order are deterministic.
- A controlled SQL filtering regression fails count/amount reconciliation and marks the declared dashboard consumer as potentially affected.
- Invalid source quality blocks both transformations; malformed and over-budget input is rejected.
- The report exposes aggregates, check results and hashes, without raw customer or order identifiers.
- The CLI and installed wheel run both clean and faulted batch scenarios with documented exit codes.
- Regression coverage includes zero amounts, maximum bounded amounts, normalized customer grouping, source BOM/reordered headers, blocked inputs and deterministic impact traversal.

Local validation on 2026-11-10: 38 regression tests passed on Python 3.14. Built and installed the wheel into an isolated target, then validated the catalog and seven CLI scenarios from outside the checkout. CI repeats tests and installed-package scenarios on Python 3.11, 3.12 and 3.14; see the pull request for exact-revision results. These are development regression tests, not a held-out research evaluation.

Limits: fixed declared dataset lineage; no dashboard execution, persistent snapshots, external adapters, root-cause inference, agent execution or UI. Count/total reconciliation does not prove correct customer attribution.
