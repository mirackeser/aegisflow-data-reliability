# Design: agents at the centre of the workbench (approved option B, 2026-11-25)

## Intent

The operator could not see any of the agent work in the product: the 36-agent runtime ran only in tests, and the screens still looked like the earlier CSV checker. The agents must be the visible centre of the product, with every view driven by real run records.

## Approaches

- **A — separate Agent flow page only.** Smallest change, but the main workflow and Overview would stay unchanged and the agents would stay hidden behind one link. Rejected: it does not fix what the operator saw.
- **B — agents at the centre (chosen by the operator).** The inspection action starts a 36-agent investigation and opens the live flow. The Agent flow page shows the run. Overview becomes an operations dashboard over real runs.

## What gets built

1. **Main workflow:** on the Data sources page, "Inspect this file" keeps the existing deterministic inspection and also starts an agent investigation on the same bytes (with the selected baseline and as-of if any), then navigates to `/flow?run=<id>`. A visible "Investigate with agents" button does the same from the baseline panel. Navigation gains "Agent flow / Ajan akışı" as a primary item.
2. **Agent flow page:** as specified in `docs/superpowers/plans/2026-11-24-agent-flow-page.md` (in progress).
3. **Overview operations dashboard** (`/overview`), computed only from retained agent run records and existing inspections, and saying so:
   - KPI tiles: investigations run, agents completed vs needing evidence, Judge acceptance rate, LLM calls with p50/p95 latency and token totals, model availability (live check of the local model, shown as reachable or unreachable).
   - Charts: run duration over the last runs (bars), agent status mix per layer (stacked bars), LLM latency per agent, and the most common findings.
   - A recent investigations table with status, selected agents, accepted findings, pending approvals and a link to the flow.
   - A "Measured quality" card that links the committed evaluation reports (profiling, baseline, hypotheses, agents) with their held-out headline numbers and limits.
   - Every tile answers four questions: what this is, what you can do, what happened, what to do next. Empty states explain how to start a run.
4. **Persistence:** agent run records (sealed, digest-verified) are retained in the state directory, up to 50 records written atomically with mode 0600, so that the dashboard and history survive restarts. Edited files are set aside, as the other stores do.

## Constraints

Real data only, with no invented telemetry. EN/TR. Accessible, keyboard operable and usable at 375 px. The local model is advisory and Judge-gated. Budget USD 0. Existing tests stay green and coverage stays at 100%.

## Left to the builder

Chart styling within the existing tokens; the exact KPI wording; empty and loading states.
