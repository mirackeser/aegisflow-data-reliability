# Evaluating the deterministic checks

`python -m aegisflow_dr.check_evaluation [--markdown] [--include-heldout]` scores the shipped checks (`diagnose_csv` and
`record_issues`) against a synthetic corpus of injected faults. `latest.md` is the committed report; a test fails if it
drifts from what the code produces.

## What is measured
- **Record level.** For every case the injector knows which `(check, column, record)` triples must be flagged and which
  look-alikes must not be (case-different identifiers, blank identifiers, valid edge amounts such as `0` or `007.10`).
  Truth comes from the injector, never from the checks under test.
- **Per check**: true/false positives, false negatives, precision and recall with explicit numerators and denominators and
  a 95% Wilson interval. A rate with no denominator is `n/a`, never 100%.
- **Error categories**: each miss is attributed to the injected pattern, each spurious finding to the variant that caused it.

## Splits and leakage
- 40 base tables ("groups") are assigned to development (60%), validation (20%) or held-out (20%) by a hash of the group id,
  so every variant of one table lives in exactly one split and every split contains every injected pattern.
- `check_leakage` reports groups, whole payloads and individual records that appear in more than one split; the corpus is
  clean and a test proves the checker detects planted leaks.
- Held-out results are produced only with `--include-heldout`. Develop and tune against development and validation; score
  held-out once, at the end. The corpus digest in the report changes if any case or label changes.

## What this does and does not show
- It is a **regression guard with measured sensitivity**: tests run deliberately broken detectors (no whitespace trim,
  case-insensitive ids, blanks as duplicates, negative amounts accepted, valid edge amounts rejected, finds nothing) and
  require the corpus to expose each one.
- 100% on this corpus is expected for simple deterministic rules whose contract the corpus was built from. It is **not**
  evidence about real data, unseen fault kinds, other schemas, or any language model. The fault kinds were chosen by the
  same authors who wrote the contract; independent, real-world labelled data would be needed to say more.

## Profiling evaluation (sensor-style series)

`python -m aegisflow_dr.profiling_eval` scores the generic profiling checks (`profiling.profile_csv`) against injected faults in
generated series: large and small spikes, flat lines, time gaps, repeated and out-of-order timestamps, null bursts and
corrupted values, plus clean series that must stay quiet. `profiling.md` is the committed report and a test fails if it drifts.
It uses the same discipline as above (hash-assigned development, validation and held-out groups, record-level truth from the
injector, Wilson intervals, `n/a` instead of 100% when nothing could be measured) and adds three things: a threshold sweep on
the development split only, a measured false-alarm rate on clean series, and column-level scoring where the finding lists too
few records to score by record. Scope: synthetic series only; nothing here is evidence about real sensors or a language model.

## Baseline comparison evaluation (current file against a stored baseline)

`python -m aegisflow_dr.baseline_eval [--include-heldout]` scores `baseline.compare` (sampling interval, volume, freshness,
empty share and a population stability index per numeric column) on generated series: 60 groups, each with three reference
batches and one current batch in 14 variants (four clean variants that must stay quiet, ten injected changes). `baseline.md`
is the committed report and a test keeps it in sync. It was generated once with held-out, after implementation and an
independent whole-branch review were complete; thresholds were fixed beforehand and not changed afterwards. The realized
split is 37 / 14 / 9 groups, so held-out intervals are wide. Per-check intervals pool correlated keys from one group and
are optimistic; case-level rates are the conservative reading. PSI is a descriptive index, not a significance test, and a
seeded no-change table shows its noise at 150, 200 and 400 values. Scope: synthetic series only; nothing here is evidence
about real sensors, other change kinds or any model.

