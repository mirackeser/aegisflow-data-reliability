# Design: measured quality page and the agents held-out (step 4 of the new direction)

Goal: one page that shows, honestly and with numbers computed from committed artefacts, how well each part of the system
works. It covers plant incident detection, the agents running the live local model, the hypothesis loop, the baseline
comparison, profiling and the CSV checks. Each part shows its development, validation and held-out splits, and says what
the measurement does not show.

## Agents held-out, scored once

- The prompt (version 2), the role table, the expected specialist sets and the scoring were fixed before development was
  scored, and they are not changed here.
- The development and validation report shows a weak A23 (the model suggestion). In many cases it repeats the catalog
  order of the explaining mechanisms instead of discriminating between them, and its first mechanism is the injected one
  in only 4 of the 11 modelled scenarios. The protocol does not allow a fix at this point. A fix would need a new prompt
  version and a fresh corpus, so it is a follow-up, not part of this step.
- The held-out split (10 groups, 140 cases) is recorded live once with `qwen3:4b` and scored once. Whatever it shows is
  reported, weaknesses included.

## Saved case measurements (agents)

A full replay of 560 cases takes over a minute, and about five times longer under coverage tracing on Python 3.11/3.12.
`agents_eval` therefore follows the pattern of `plant_eval`:

- `collect(recording, splits)` returns compact per-case facts: selected roles, agent outcome labels, Judge counts, the
  advisory verdicts, the model call outcomes with their latencies, A23's mechanisms, the catalog order of the explaining
  mechanisms, the loop's supported mechanisms, run status, budget limits, replay misses and live-vs-replay agreement.
- `summarise_collected` scores those facts. `evaluate` is `summarise_collected(collect(...))`, so there is one scoring
  path.
- `--save-cases` and `--from-cases` save and read the facts, kept in `fixtures/evaluations/agents-cases-v1.json`.
- A test renders the committed `docs/evaluation/agents.md` from the saved facts. Another test replays the first case of
  each split and requires the same facts.

## Quality summary (`aegisflow_dr.quality`)

`summary()` returns, for each evaluation, a uniform card with these fields:

- `id`;
- the committed report path;
- the split sizes;
- headline metrics per split;
- for plant and agents, a per-scenario table.

Every rate is normalised to `{numerator, denominator, value, low, high}` (Wilson 95%), with `value` null when the
denominator is zero. Headline rates pool cases across scenarios. Cases of one group or seed are correlated, so pooled
intervals are optimistic, and the page says so.

| Evaluation | Source | Headline metrics |
|---|---|---|
| Plant incidents | `plant-cases-v1.json` (saved cases) | detected; injected mechanism sole-supported on change-point evidence; wrong mechanism supported; false alarms per clean hour |
| Agents, live model | `agents-cases-v1.json` (saved facts) | exact specialist set; schema-valid model JSON; A23 lists the injected mechanism (any, top-1); A23 misattributes outside the catalog; replay fidelity |
| Hypothesis loop | `hypotheses_eval.evaluate` (about 6 s) | injected mechanism sole-supported; supported; misattribution on unmodelled changes |
| Baseline comparison | `baseline_eval.evaluate` (about 6 s) | injected change detected (case level); clean variants with any finding |
| Profiling | `profiling_eval.evaluate` (about 2 s) | fault detected (case level); clean series with any finding |
| CSV checks | `check_evaluation` (existing) | precision and recall per check |

The workbench serves `GET /api/quality`. It is computed once per process, warmed on a background thread at start, and
uses no state and no run data.

## Page

- `/quality` (navigation "Measured quality / Ölçülmüş kalite") replaces "Check accuracy", and `/evidence` stays as an
  alias.
- The top band states the scope: simulated and synthetic data only, held-out scored once, Wilson intervals, and `n/a`
  for an empty denominator.
- Headline tiles show held-out numbers.
- A split selector (development / validation / held-out) drives every table on the page.
- Each evaluation has a section with what it measures, its metrics, the scenario table where there is one, and its
  limits.
- The agents section states the A23 weakness in plain words.
- The existing retrieval and passage panels stay at the bottom.

## Constraints

- Every number comes from the API. No root-cause or accuracy-on-real-data claims.
- EN/TR, keyboard operable, works at 375 px.
- 100% branch coverage. No new dependencies. Budget USD 0.
