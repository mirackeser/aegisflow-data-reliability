# Design: observation, hypothesis, counter-hypothesis and probe contracts with bounded replanning (F04)

Status: approved for implementation (operator instruction 2026-11-24: "then F04 hypothesis contracts; end each step with an
honest held-out measurement and report weaknesses").

## Problem

Profiling (D05) and baseline comparison (D05c) report *what* changed. Catalog roles A23–A25 and A28 describe the next step:
propose candidate explanations, look for competing ones, choose the next safe test, and rank what survives with its
uncertainty. No model is approved, so this increment builds the **contracts and a deterministic, bounded loop** around a
fixed catalog of simulated mechanisms. It is bookkeeping of candidate explanations, not root-cause inference: a
"supported" hypothesis means fixed probes found the measurements consistent with it and inconsistent with none, nothing more.

## Contracts (JSON Schema Draft 2020-12, `src/aegisflow_dr/data/hypothesis-contracts-v1.json`)

One schema file with `$defs` for `observation`, `hypothesis`, `probe_result` and `investigation`; validated with the existing
`jsonschema` dependency, offline (no remote `$ref`), `additionalProperties: false` everywhere.

- **observation**: `{"id": "obs-N", "source": "baseline" | "profile", "check": str, "column": str | null,
  "direction": "drop" | "increase" | null, "evidence_sha256": hex64}` where `evidence_sha256` is the `source_sha256` of the
  inspected file and `direction` is the volume finding's direction (null for every other check).
- **hypothesis**: `{"id": "hyp-N", "mechanism": one of MECHANISMS, "column": str | null, "explains": [obs ids, ≥1],
  "competitors": [hyp ids], "status": "open" | "supported" | "refuted", "supporting": [probe ids], "refuting": [probe ids]}`.
  `competitors` lists the other hypotheses that explain at least one of the same observations (the counter-hypotheses).
- **probe_result**: `{"id": "prb-N", "probe": one of PROBES, "column": str | null, "round": int ≥ 1,
  "measured": {str: number | null}, "outcomes": {hyp id: "supports" | "refutes" | "neutral"}}`.
- **investigation**: `{"format_version": "1", "engine": "deterministic-hypotheses-v1", "catalog_version": "1",
  "observations": [...], "hypotheses": [...], "probes": [...], "budget": {"max_probes", "used"}, "stop_reason":
  "no_observations" | "no_informative_probe" | "probe_budget_exhausted" | "resolved", "ranking": [hyp ids],
  "verdict": "no_observations" | "none_supported" | "single_supported" | "multiple_supported", "statement": str,
  "trace_sha256": hex64}`. `statement` is fixed text: "Candidate mechanisms consistent with fixed probes on these
  measurements. Not a root-cause determination." `trace_sha256` is the SHA-256 of the canonical JSON of everything else.

## Mechanism catalog (version "1")

| mechanism | explains (observation check) | column scope |
|---|---|---|
| `unit_change` | distribution_shift | that column |
| `calibration_offset` | distribution_shift | that column |
| `noise_increase` | distribution_shift | that column |
| `stuck_sensor` | distribution_shift, flatline (profile) | that column |
| `genuine_change` | distribution_shift | that column |
| `sampling_config_change` | sampling_interval_change, volume_change | none (time column) |
| `partial_load` | volume_change with direction drop | none |
| `duplicate_delivery` | volume_change with direction increase, duplicate_rows (profile), timestamp_duplicate (profile) | none |
| `delivery_delay` | freshness | none |
| `source_outage` | freshness, volume_change with direction drop | none |
| `field_outage` | empty_rate_change | that column |
| `intermittent_loss` | empty_rate_change | that column |

One hypothesis per (mechanism, column) that explains at least one observation; it lists every observation it explains.
`genuine_change` (a real change in the measured process) is deliberately not testable from these data alone: no probe
supports or refutes it, so it stays `open` whenever it is generated. That is the honest counterweight to every
instrument-fault explanation.

## Probes (thresholds fixed here, before any measurement)

All probes read only the stored baseline record and the current file (through `baseline.compare` measurements and
`profiling.read_table`); none writes anything. Each returns `measured` values and an outcome per open hypothesis it
concerns; hypotheses it does not concern get no entry.

| probe | measured | outcomes |
|---|---|---|
| `scale_ratio(col)` | `r` = current median / baseline median (null if baseline median is 0), `sd_ratio` = current sd / baseline sd | `unit_change`: supports when r > 0, \|log10 r\| ≥ 0.9 and \|log10 r − round(log10 r)\| ≤ 0.05 and \|log10 sd_ratio − log10 r\| ≤ 0.1; refutes when 0.5 ≤ \|r\| ≤ 2 or r ≤ 0; else neutral. |
| `spread_ratio(col)` | `sd_ratio`, `mean_shift_sd` = (current mean − baseline mean) / baseline sd | `calibration_offset`: supports when 0.8 ≤ sd_ratio ≤ 1.25 and \|mean_shift_sd\| ≥ 0.5; refutes when sd_ratio < 0.67 or > 1.5. `noise_increase`: supports when sd_ratio ≥ 1.5 and \|mean_shift_sd\| < 0.5; refutes when sd_ratio < 1.25 or \|mean_shift_sd\| ≥ 1. Else neutral. |
| `flat_share(col)` | share of current numeric values that sit in runs of ≥ 8 identical consecutive values | `stuck_sensor`: supports when ≥ 0.3; refutes when < 0.05; else neutral. |
| `interval_regularity` | `ratio` = current / baseline median interval, `cv` = coefficient of variation of positive gaps | `sampling_config_change`: supports when ratio outside [1/1.5, 1.5] and cv < 0.25; refutes when ratio inside [1/1.1, 1.1]; else neutral. `partial_load`: refutes when ratio outside [1/1.5, 1.5]. |
| `span_ratio` | `ratio` = current time span / median reference span | `partial_load` and `source_outage`: support when ratio < 1/1.5, refute when ratio ≥ 1/1.1. `delivery_delay`: supports when ratio ≥ 1/1.1, refutes when ratio < 1/1.5. `sampling_config_change`: neutral. |
| `freshness_lag` | `lag_ratio` = lag / SLA from the comparison's freshness measurement (null when freshness was not evaluated) | `source_outage`: supports when lag_ratio > 1, refutes when lag_ratio ≤ 1. `partial_load`: refutes when lag_ratio > 1. Null → neutral for both. |
| `duplicate_share` | share of current records whose timestamp equals an earlier record's | `duplicate_delivery`: supports when ≥ 0.2; refutes when 0. |
| `empty_runs(col)` | `longest_run_share` = longest run of consecutive empty cells / all empty cells in the column | `field_outage`: supports when ≥ 0.8; refutes when < 0.3. `intermittent_loss`: supports when < 0.3; refutes when ≥ 0.8. |

## Bounded loop and replanning

`investigate(baseline, payload, *, as_of=None, max_probes=6) -> dict`:

1. Run `baseline.compare` and `profiling.profile_csv` on the payload; turn baseline findings and the profile findings named in
   the catalog into observations (stable order: baseline findings in their order, then profile findings in theirs).
   Profile findings used: `flatline`, `duplicate_rows`, `timestamp_duplicate`; others are ignored.
2. Generate hypotheses from the catalog; fill `competitors`.
3. Each round: among (probe, column) pairs not yet run, pick the one that concerns the most hypotheses that are not
   refuted, open or supported, so a leading hypothesis keeps being tested (a probe concerns a hypothesis when the table above gives that mechanism an outcome rule and the column matches);
   ties by probe order in the table above, then column name (None first). A pair that concerns no unrefuted hypothesis is never
   run. Run it, record outcomes, update statuses
   (refuted if any probe refutes; supported if ≥ 1 supports and none refutes; else open). This is the replanning step: the
   next choice is made on the updated statuses.
4. Stop with `resolved` when every observation that has at least one candidate hypothesis is explained by exactly one supported hypothesis (observations no mechanism explains, such as `column_added`, are listed but do not block it) and all its competitors are
   refuted or are `genuine_change`; `no_informative_probe` when no remaining pair concerns an unrefuted hypothesis;
   `probe_budget_exhausted` when `max_probes` (1–20, default 6) have run; `no_observations` when there was nothing to explain.
5. Ranking: supported (more supporting probes first), then open, then refuted; ties by catalog order then column.

Every probe result carries the round it ran in. The record is validated against the schema before it is returned.

## Evaluation (`hypotheses_eval`)

- Uses `baseline_eval`'s process code (same generator, seeded by the group number) on 60 **fresh groups, numbers 60–119**,
  with its own salt `aegisflow-hypotheses-eval-v1` for the split hash. The corpus is disjoint from the D05c evaluation
  corpus (groups 0–59): no group, base series or payload is shared. Every investigation starts with `baseline.compare`,
  whose checks were developed on groups 0–59, so reusing them would measure the observation layer on data it was
  developed on. An earlier draft of this design reused groups 0–59; this was corrected before held-out was scored.
  Each scenario injects one **simulated mechanism** into the current batch with the baseline from the three
  references:

| scenario | simulated mechanism | injection |
|---|---|---|
| `unit_change` | unit_change | pressure_kpa x 10 |
| `calibration_offset` | calibration_offset | temp_c + 1.5 x baseline temp sd |
| `noise_increase` | noise_increase | pressure_kpa noise sd 1 → 3 |
| `stuck_sensor` | stuck_sensor | temp_c repeats one value for records 150–399 |
| `sampling_config_change` | sampling_config_change | interval 120 s, 400 records |
| `partial_load` | partial_load | only the last 160 records of the batch, as_of normal |
| `duplicate_delivery` | duplicate_delivery | 400 records plus records 0–299 repeated after them |
| `delivery_delay` | delivery_delay | complete batch, as_of = latest + 1,800 s |
| `source_outage` | source_outage | only the first 160 records, as_of = expected end of the full batch + 60 s |
| `field_outage` | field_outage | flow_lpm empty in one contiguous run of 100 records |
| `intermittent_loss` | intermittent_loss | flow_lpm empty in 100 seeded scattered records |
| `clean` | none | none |
| `unmodelled_sign_flip` | not in catalog | pressure_kpa x −1 |
| `unmodelled_amplitude` | not in catalog (a genuine process change) | temp_c seasonal amplitude 1 ↔ 3 swapped |

- Metrics per split: for modelled scenarios — true mechanism supported (rate), true mechanism is the only supported
  hypothesis, true mechanism refuted (false refutation), any other catalog mechanism supported (wrong support); for clean —
  any hypothesis generated; for unmodelled — any catalog mechanism other than `genuine_change` supported
  (misattribution). Plus probes used (mean, max) and stop reasons. Wilson 95% intervals, `n/a` for zero denominators.
- Development and validation are printed by default; `--include-heldout` adds held-out, generated once at the end and kept
  in sync by a test. Thresholds above are not changed after held-out is scored.
- Mutants the corpus must expose: `scale_ratio` disabled, spread thresholds swapped between offset and noise, span probe
  inverted, probe budget 1, replanning disabled (probes run in fixed order without status updates).

## Interface

Inside the baseline comparison result: a "Candidate explanations" section (EN/TR) from `POST /api/baselines/investigate`
(same body as compare). It shows the verdict and the fixed statement, observation chips, one card per hypothesis with
status (text + icon), competitors, and the probes that supported or refuted it with measured values; a probe timeline by
round with the budget used and the stop reason. No wording implies a cause was found.

## Capability map

A24 (Counter-Hypothesis), A25 (Active Probe Planner) and A28 (Ranking & Uncertainty) become `partial`, anchored to
`aegisflow_dr.hypotheses:investigate`, each with a limit sentence: fixed catalog of simulated mechanisms, deterministic
probes, no model. A23 stays `unavailable`; its limit text adds that a fixed candidate catalog exists but naming a root cause
needs a model and real labelled data.

## Honesty rules

Simulated mechanisms only, written by the same authors as the catalog, so modelled-scenario success measures internal
consistency, not real-world diagnosis. The two unmodelled scenarios exist to show misattribution. No root cause, no model, no
live agent, no production connection.
