# Design: A23 reads qualitative readings (prompt version 3) and a fresh agents evaluation (v2)

## Problem

The committed agents evaluation (v1, prompt version 2) shows that A23's suggestion barely discriminates. On held-out
it names the injected mechanism first in 40/110 modelled cases, and in most cases its list is the catalog order of the
mechanisms that explain the observations.

The cause is the input, not only the model. A23 receives each observation's check name and column, and a catalog
listing which checks each mechanism explains. A `distribution_shift` is explained equally by `unit_change`,
`calibration_offset`, `noise_increase`, `stuck_sensor` and `genuine_change`, so with this input the catalog order is a
rational answer.

## What was tried on development data only

These trials used groups of the v1 development split and the live local model:

| Input | Top-1 on two to four development groups |
|---|---|
| Measured numbers (means, spreads, ratios) and written signatures, with the catalog in the context | 12/22 (the model still copies the first three catalog entries) |
| The same without the catalog in the context | 8/22 |
| Thinking mode on | about 20 s per call, and one empty answer: unusable within the 30 s call limit |
| **Deterministic qualitative readings and written signatures, no catalog in the context** | **44/44** |

A 4B model with schema-constrained output and no thinking does not apply numeric thresholds reliably. It does map named
patterns to named mechanisms.

## Design

**Readings.** A new module, `aegisflow_dr.readings`, turns each observation into a small set of fixed words. It uses
only the aggregates the baseline comparison already reports, plus, for empty values, the pattern of empty cells:

| Check | Reading |
|---|---|
| `distribution_shift` | `mean`: `scaled_power_of_ten`, `sign_reversed`, `shifted_up`, `shifted_down` or `unchanged`; `spread`: `wider`, `narrower` or `unchanged` |
| `volume_change` | `rows`: `drop` or `increase` |
| `freshness` | `data`: `late` |
| `sampling_interval_change` | `interval`: `longer` or `shorter` |
| `empty_rate_change` | `empty_values`: `more` or `fewer`; `empty_pattern`: `contiguous` (longest empty run of at least 80% of the empty cells) or `scattered` |

The thresholds are written once here and are not tuned on any evaluation. A power of ten is `|log10 r| >= 0.9` within
0.05 of an integer. A shift is at least 0.5 baseline standard deviations. A spread ratio of at least 1.5 is wider, and at
most 0.8 is narrower. They are the same thresholds the probe catalog documents.

**Prompt version 3.** A23's system prompt states each mechanism's signature in these words. It asks for the candidates
in order from best to worst fit, each at most once, and for `genuine_change` alone when no signature fits. The context
holds the observations with their readings and no catalog list. The output schema is unchanged. A23 drops a repeated
mechanism, keeping its first place. The other templates are unchanged.

**Versioning.** `Case.prompt_version` defaults to the latest version (3), and the runtime threads it into every model
call, the context record, the suggestion record and the cache identity. Version 2 stays available byte for byte, so the
committed v1 evaluation still replays exactly from its recording. The product (Agent flow, plant incidents) uses
version 3.

**Evaluation v2.** `agents_eval` gains a protocol per version:

| | v1 (committed, unchanged) | v2 (new) |
|---|---|---|
| Groups | 120-159 | 160-199, disjoint from every other corpus |
| Split salt | `aegisflow-agents-eval-v1` | `aegisflow-agents-eval-v2` |
| Prompt version | 2 | 3 |

The v2 scenarios and expected specialist sets are the same as v1. v2 has its own recording, saved facts and report
(`agents-v2.md`). The prompt is frozen before v2 is measured. If v2 development shows a defect, a fix is made on
development only. Validation is checked, and held-out is recorded and scored once.

## Honesty

- The readings are computed deterministically from the same aggregates the probes use, so agreement now measures
  whether the model maps documented signatures to readings. It is not independent diagnosis, and the report says so in
  its first lines.
- The deterministic probe loop still decides what is supported. A23 stays advisory and Judge-gated.
- Changes outside the catalog stay hard: a seasonal amplitude change reads like noise and is expected to be
  misattributed.
- The quality page shows v1 and v2 side by side, so the improvement and its cause are visible.

## Constraints

USD 0, local model only. 100% branch coverage. No new dependencies. EN/TR.
