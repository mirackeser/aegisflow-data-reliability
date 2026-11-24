# Design: comparing a current profile with a stored baseline (D05c)

Status: approved for implementation (operator instruction 2026-11-24: "D05 continuation: compare the current profile with a
stored baseline — sampling interval, volume, freshness, distribution shift; end with an honest held-out measurement").

## Problem

`profiling.profile_csv` (increments 60–61) judges one file in isolation. It cannot say that today's delivery arrives at a
different sampling rate, carries far fewer records, is stale, or that a column's values now come from a different
distribution than last week's. Work package D05 lists exactly this as "not yet done". Catalog roles A11 (Freshness & Volume
Analyst) and A20 (Statistical Drift Investigator) are only partly backed today by `monitoring.monitor`, which compares
retained order-file inspections with fixed thresholds.

## Scope

In scope: one new deterministic module `aegisflow_dr.baseline`, its synthetic evaluation `aegisflow_dr.baseline_eval` with a
committed report, a local workbench store and HTTP endpoints, and a bilingual (EN/TR) panel on the Data sources page.

Out of scope: live sources and streaming, scheduled collection, statistical tests that assume independent samples, root-cause
inference, any language model, real sensor data. Nothing here is a model or a root-cause claim.

## Baseline record

`build_baseline(payloads, *, freshness_sla_seconds=None) -> dict` reads 1 to `MAX_REFERENCES` (5) reference CSV payloads
with `profiling.read_table` (so the same 1 MB / 20,000-record / 40-column limits apply to each) and returns a JSON-safe dict:

- `format_version` "1", `engine` "deterministic-baseline-v1".
- `columns`: list of `{"name", "role"}` in header order. Roles come from `profiling._column` on the pooled values of all
  references. All references must have the identical header (same names, same order), otherwise `InputRejected`.
- `time_column`: the first column whose pooled role is `timestamp`, else `None`. Timezone awareness must be the same in every
  parsed timestamp of that column across all references, otherwise `InputRejected` ("mixed timezone awareness").
- `references`: per reference `{"sha256", "records", "first", "last", "median_interval_seconds"}`; `first`/`last` are the
  ISO strings of the earliest/latest parsed timestamp, `median_interval_seconds` is the median of positive gaps between
  sorted distinct timestamps (`None` when fewer than `MIN_DELTAS` = 10 such gaps or no time column).
- `volume`: `{"min_records", "max_records", "median_records"}` over references.
- `sampling`: `{"median_interval_seconds"}` = median of the references' non-`None` medians, else `None`.
- `freshness_sla_seconds`: the caller's positive integer if given, else `FRESHNESS_INTERVALS` (3) x the sampling median
  (rounded to the nearest second, minimum 1), else `None` when there is no sampling median.
- `empty_share`: per column, pooled empty cells / pooled records, rounded to 6 places.
- `numeric`: per column whose role is `numeric`, `{"count", "mean", "sd", "median", "edges", "counts"}` from the pooled
  numeric values (`sd` = `statistics.pstdev`, mean/sd/median rounded to 6). `edges` are the distinct values among the 9 interior deciles (`statistics.quantiles(values, n=10,
  method="inclusive")`), sorted and de-duplicated; a value goes to bin `bisect.bisect_right(edges, v)`, so there are
  `len(edges) + 1` bins. `counts` are the baseline values per bin (integers summing to `count`). When `edges` is empty (a
  constant column) the entry is `{"count", "mean", "sd", "median", "edges": [], "counts": [count]}` and the column is
  reported `not_evaluated` with reason `constant_in_baseline` at comparison time. When fewer than `MIN_VALUES` (150) numeric
  values exist, `edges`/`counts` are `None` and comparison reports `too_few_values_in_baseline`.
- `MIN_VALUES` = 150 (amendment 2026-11-24, previously 50): with no change, E[PSI] ≈ (B − 1)(1/n_baseline + 1/n_current)
  for B = 10 bins; requiring the current-size term (B − 1)/n_current ≤ `PSI_SHIFT` / 4 gives n_current ≥ 144, rounded to
  150. It was set before the held-out split was scored, after an independent reviewer's null simulation showed
  P(PSI > 0.25) ≈ 0.20 at 50 values. The same minimum applies to the baseline and the current file.
- `digest`: SHA-256 hex of the canonical JSON (`sort_keys=True, separators=(",", ":"), ensure_ascii=False`) of every
  other field.

Privacy: the record keeps column names, roles, counts, shares, means, standard deviations, medians and decile edges, not whole
records or text values. Medians and decile edges are values from the data and reveal approximate ranges; they can equal
individual values, and a numeric identifier column gets them too. This is stated in the UI note and the docs.

`load_baseline(obj) -> dict` re-validates a stored record: exact key set, types, bounds (≤ 40 columns, ≤ 5 references, edges
strictly increasing and length ≤ 9, counts length = edges + 1, non-negative integers summing to `count`) and recomputes the digest.
Any deviation raises `InputRejected`. `compare` always calls it first.

## Comparison

`compare(baseline, payload, *, as_of=None) -> dict` returns:

```
{"format_version": "1", "engine": "deterministic-baseline-v1", "baseline_digest", "source_sha256", "records",
 "as_of", "measurements": {...}, "findings": [...], "not_evaluated": [...], "status": "DRIFT" | "NO_DRIFT"}
```

Amendment (2026-11-24, raised by the interface task): `measurements` carries the measured values whether or not a rule
fired, so a reader can see "baseline → current" for passing checks too: `sampling_interval` `{"baseline_seconds",
"current_seconds"}`, `volume` `{"baseline_min", "baseline_max", "current"}`, `freshness` `{"sla_seconds", "latest",
"lag_seconds"}` (`lag_seconds` is `None` when freshness was not evaluated), `psi` `{column: value}` and `bin_shares`
`{column: {"psi", "edges", "baseline", "current"}}` for every numeric column whose distribution was compared. The
distribution decision uses the unrounded PSI; reported values are rounded to 6 places. No decision rule changed.

Each finding is `{"check", "column", "detail"}`; each `not_evaluated` entry is `{"check", "column", "reason"}`. Findings are
sorted by `CHECKS` order then column name (`None` first). Checks, in order:

| check | rule (thresholds fixed before any measurement) |
|---|---|
| `column_missing` | baseline column absent from the current header; detail `{}`. Later checks skip that column. |
| `column_added` | current column absent from the baseline; detail `{}`. Not compared further. |
| `role_change` | column present in both, roles differ; detail `{"baseline", "current"}`. Distribution is then `not_evaluated` with reason `role_changed`. |
| `sampling_interval_change` | needs a baseline sampling median and ≥ 10 positive gaps in the current time column (else `not_evaluated`, reason `no_baseline_interval` or `too_few_intervals`). Ratio = current median / baseline median; finding when ratio > `SAMPLING_RATIO` (1.5) or < 1 / 1.5; detail `{"baseline_seconds", "current_seconds", "ratio"}` (ratio rounded to 4). Column = time column. |
| `volume_change` | finding when records < `min_records` / `VOLUME_RATIO` (1.5) or > `max_records` x 1.5; detail `{"baseline_min", "baseline_max", "current", "direction": "drop" | "increase"}`; column `None`. |
| `freshness` | needs `as_of`, a time column and an SLA (else `not_evaluated`, reasons `no_as_of`, `no_time_column`, `no_sla`). `as_of` is parsed with `profiling.parse_timestamp`; an unparsable string raises `InputRejected`. Awareness must match the data (else reason `timezone_mismatch`). lag = as_of − latest current timestamp in seconds; lag < 0 gives reason `as_of_before_latest_record`. Finding when lag > SLA; detail `{"lag_seconds", "sla_seconds", "latest"}`. Column = time column. |
| `empty_rate_change` | column in both; current empty share − baseline empty share > `EMPTY_RATE_DELTA` (0.10); detail `{"baseline", "current"}` rounded to 4. |
| `distribution_shift` | numeric in both with baseline edges; needs ≥ `MIN_VALUES` (150) current numeric values (else reason `too_few_values`). Current values are binned with the baseline edges. PSI = Σ (c − b) ln(c / b) over bins, where b and c are bin shares after adding `PSI_SMOOTH` (0.5) to every bin count on both sides. Finding when PSI > `PSI_SHIFT` (0.25); detail `{"psi", "threshold", "baseline_mean", "current_mean", "baseline_sd", "current_sd", "baseline_proportions", "current_proportions", "edges"}` (floats rounded to 6). The decision is PSI only; mean/sd are context. |

The PSI threshold 0.25 is the conventional "significant population shift" rule of thumb in credit-risk practice, chosen before
any measurement; 1.5 for sampling and volume ratios, 3 intervals for freshness and 0.10 for empty share are design choices
made in this document, not fitted. PSI on autocorrelated series is not a hypothesis test and has no p-value; the docs say so.

## Evaluation (`baseline_eval`)

- 60 groups; split by `sha256("aegisflow-baseline-eval-v1:%d")` bucket mod 10: < 6 development, < 8 validation, else held-out.
- Each group is one generated process: `ts` every 60 s from 2026-01-01T00:00:00 (naive), `temp_c` = 20 + A sin(2π i/100 + φ)
  + N(0, σ) with A ∈ {1, 3}, σ ∈ {0.2, 0.5}, `pressure_kpa` = N(100, 1), `flow_lpm` = N(5, 1). Values written with 3 decimals.
- Baseline: 3 consecutive reference batches of 400 records. Current batch: the next 400 records, then the variant is applied.
  `as_of` = latest current timestamp + 60 s unless the variant says otherwise.
- Variants and truth (set of `(check, column)` keys that must be found; anything else found is unexpected):

| variant | change | truth |
|---|---|---|
| `clean` | none | ∅ |
| `clean_partial_cycle` | current batch has 350 records | ∅ |
| `clean_jitter` | every timestamp moved by an integer U(−10, 10) seconds, order kept | ∅ |
| `clean_recent_lag` | as_of = latest + 150 s (inside the 180 s SLA) | ∅ |
| `mean_shift_large` | temp_c + 1.5 x baseline temp sd | distribution_shift/temp_c |
| `mean_shift_small` | temp_c + 0.25 x baseline temp sd | distribution_shift/temp_c |
| `scale_change` | pressure_kpa noise sd 1 → 2.5 | distribution_shift/pressure_kpa |
| `unit_change` | pressure_kpa x 10 | distribution_shift/pressure_kpa |
| `sampling_slow` | interval 120 s, 400 records | sampling_interval_change/ts |
| `sampling_fast` | interval 30 s, 400 records | sampling_interval_change/ts |
| `volume_drop` | 160 records | volume_change/None |
| `volume_spike` | 1,000 records | volume_change/None |
| `stale` | as_of = latest + 1,800 s | freshness/ts |
| `null_increase` | 25% of flow_lpm cells emptied (fixed seeded positions) | empty_rate_change/flow_lpm |

- Metrics per split and variant: cases, cases detected (every truth key found), cases with an unexpected finding; per check:
  true/false keys, precision and recall with Wilson 95% intervals (`check_evaluation.wilson`), `n/a` for zero denominators.
  Also per split: PSI on clean cases per numeric column (max and the count above 0.1), and the count of `not_evaluated`
  entries by reason.
- Development-only diagnostic: detection of a temp_c mean shift of d ∈ {0.25, 0.5, 0.75, 1.0, 1.5} baseline sd at the fixed
  threshold. It shows sensitivity; it is not used to change the threshold.
- `python -m aegisflow_dr.baseline_eval` prints development and validation only; `--include-heldout` adds held-out. The
  committed report `docs/evaluation/baseline.md` is generated once, with held-out, after implementation is complete, and a
  test keeps it in sync. Thresholds are not changed after held-out is scored; anything held-out reveals is reported as a
  weakness.
- Mutants the corpus must expose (tests): PSI check disabled, PSI threshold ×10, sampling check disabled, volume band
  inverted, freshness ignoring `as_of`, empty-rate check disabled.

## Workbench and interface

- `apps/local/baseline_store.py`: named baselines (slug of 1–64 characters `[a-z0-9_-]`, Turkish letters folded as in the
  knowledge base), at most 50, in `baselines.json`, written atomically with mode 0600; loading re-validates every record with
  `load_baseline` and, on any failure, moves the file aside to `baselines.rejected.json` and starts empty (same policy as
  `schema_store`). Saving an existing name requires `replace: true`.
- Endpoints (session-authorized like the others): `GET /api/baselines` (names, created time, reference count, records, time
  column, digest), `POST /api/baselines/save` JSON `{"name", "references": [csv text, ...], "freshness_sla_seconds"?,
  "replace"?}` (body ≤ 5,300,000 bytes), `POST /api/baselines/compare` JSON `{"name", "csv", "as_of"?}`, `POST
  /api/baselines/remove` JSON `{"name"}`. `InputRejected` → 422 with the message, malformed → 400, unknown name → 404.
- Data sources page: a "Compare with a baseline" panel (EN/TR) next to the profile panel: choose 1–5 reference files and a
  name to save a baseline; pick a saved baseline and compare the selected file with an optional "as of" time and a "Use now"
  button. Result: status chip; four summary tiles (sampling interval, volume, freshness, distribution) showing baseline vs
  current and ok / changed / not evaluated; a PSI bar per numeric column with the 0.25 threshold marked; for a selected
  column a paired bar chart of baseline vs current bin shares; a list of findings and of not-evaluated checks with
  reasons; the honest scope note. Keyboard reachable, labelled controls, text alternatives for charts, works on mobile.
- Capability map: A11 and A20 stay `partial`, gaining the anchor `aegisflow_dr.baseline:compare`.

## Honesty rules carried into every artifact

Synthetic generated series only; no real sensors; fault kinds chosen by the authors of the checks; PSI is a descriptive index,
not a significance test; no root cause, no model, no production connection.
