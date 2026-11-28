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

## Hypothesis loop evaluation (simulated mechanisms)

`python -m aegisflow_dr.hypotheses_eval [--include-heldout]` runs `hypotheses.investigate` on 14 simulated scenarios per
group: eleven mechanisms from the fixed catalog, a clean batch and two changes outside the catalog (a sign flip and a
seasonal amplitude change). It uses 60 fresh groups (60 to 119), disjoint from the baseline-comparison corpus; an earlier
draft reused those groups and was corrected before held-out was scored. The split is 30 / 18 / 12 groups. `hypotheses.md`
was generated once with held-out after the whole-branch review, and a test keeps it in sync. The catalog and the injections
were written by the same authors, so modelled-scenario success measures internal consistency, not diagnosis. The two
unmodelled scenarios measure misattribution on two hand-picked changes only. A `resolved` stop does not mean correct, and
no result here is a root cause.


## Agent runtime evaluation (live local model)

`python -m aegisflow_dr.agents.agents_eval [--include-heldout]` runs the 36-role runtime on the fourteen scenarios of the
hypothesis loop evaluation, on fresh groups 120 to 159, with the local model `qwen3:4b` (temperature 0, JSON-schema
constrained, advisory and Judge-gated). `--live` records every model reply by the SHA-256 of its exact request into
`fixtures/evaluations/agents-llm-recording-v1.json`. The report always replays that recording, so CI regenerates it without
a model. The prompt (version 2), the role table and the expected specialist sets were fixed before development was scored.
The held-out split (10 groups, 140 cases) was recorded live once and scored once. `agents.md` is the committed report. It
is rendered from the per-case facts in `fixtures/evaluations/agents-cases-v1.json` (`--save-cases` / `--from-cases`). A
test keeps both in sync and replays the first case of each split to show the saved facts match the code. The report
states the model's weakness plainly: its suggestion often repeats the catalog order of the explaining mechanisms instead
of telling them apart. Agreement with an injected label on simulated cases is not diagnostic accuracy on real data.

**v2 (prompt version 3).** The v1 weakness came from A23's input: given only check names, several catalog mechanisms
explain the same observation. In v2 A23 instead reads a deterministic qualitative reading of each observation
(`aegisflow_dr.readings`) and the mechanisms' signatures in those words. The prompt was tried on v1 development groups
and frozen before v2 was recorded on fresh groups 160 to 199 (`--protocol 2`, `agents-v2.md`). Held-out, scored once:

- the model's first choice is the injected mechanism in 99/99 modelled cases, against 40/110 in v1;
- a sign flip outside the catalog is left to `genuine_change`;
- a seasonal amplitude change is still misattributed;
- on duplicate delivery the model pads its list with two wrong-direction mechanisms, which the Judge rejects;
- one remediation draft (A29) timed out.

The readings use the same aggregates and documented thresholds as the probes. The agreement therefore shows correct
mapping of documented signatures, not independent diagnosis. v1 stays as committed.

## Measured quality page

The workbench's `/quality` page shows every evaluation above through `aegisflow_dr.quality.summary()` (`GET /api/quality`).
It reads each report's own numbers and normalises its rates to counts with a 95% Wilson interval, and it adds no
measurement of its own. Headline rates pool the cases of a split across scenarios. Cases of one group or seed share data,
so a pooled interval is optimistic, and the per-scenario tables are the conservative reading.
