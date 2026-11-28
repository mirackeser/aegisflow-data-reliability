# Design: accurate incident investigations and the Incident page (step 2 of the new direction)

Operator direction on 2026-11-28: continue systematically, keep nothing illogical, use clean code and a prestigious interface,
and make the decision mechanisms and agents accurate.

## Problem (measured, not assumed)

In step 1, an agent investigation ran on the monitor window in which the incident was first detected. That window
mixes readings from before and after the change. On the simulated plant (20 development seeds per fault, seeds 1–20):

- On the **detection window**, the deterministic probe loop (`hypotheses.investigate`) found the injected mechanism in
  only a minority of cases. For unit ×10 it found none, because the median of a mixed window stays near the baseline.
- On a window that holds **only post-change readings and covers a full monitoring window**, it found the injected
  mechanism in 19–20 of 20 cases for calibration offset, unit change, stuck sensor and sampling slowdown on every
  sensor, and for noise increase on pressure and flow.
- Post-change windows **shorter** than a monitoring window are wrong by construction. The baseline volume and span are
  defined per 200 s window, so a short window looks like a partial load.

So accuracy depends on when and on what the investigation runs, not on the agents themselves.

## Decision

An incident's evidence is the **first full monitoring window after the estimated change onset**. The onset is estimated
from the data only. The simulator's injection time is never read by the estimator; it is shown beside the estimate as
simulation ground truth.

1. **Seasonality learnt at commissioning:** for each sensor, a single-harmonic least-squares fit over periods of 20–200 s
   (1 s grid, refined to 0.05 s) on the commissioning readings. A sensor is seasonal when the harmonic explains at
   least 50% of its variance; on the simulated plant only `temp_c` is (period ≈ 100 s, R² ≈ 0.95).
2. **Onset:** the maximum-likelihood split of the series into two segments, each with its own mean and variance and,
   for a seasonal sensor, its own harmonic of the learnt period (least squares from prefix sums; a variance floor of
   the rounding error; at least 10 values per side). It is applied to the incident sensor's readings, or, for stream
   incidents, to the gaps between arrivals. The analysed range starts twice the window length before the incident opened
   and runs to now. The statistic (twice the log-likelihood ratio against one segment) is reported. On clean
   development data (seeds 1–10, 90 windows of 400 s per sensor) its maximum was 17 for the non-seasonal sensors and 26
   for the seasonal one. An estimate is **clear** at 30 or more; otherwise the page says the change point is uncertain.
   - *History:* the first version adjusted the series once with a common harmonic and then split on mean and variance.
     Validation (seeds 21–40) showed that this misplaces the onset of a stuck seasonal sensor, because the adjustment
     adds the wave back onto the frozen value. The per-segment harmonic model replaced it before held-out was scored,
     so validation is not independent for this change.
3. **Data stopped:** when the last reading is older than the baseline freshness SLA, the onset is the second after the
   last reading. The evidence is the monitoring window that ends a full window after the last reading. That window
   holds the last reading only, so freshness, volume and span describe the outage.
4. **Readiness:** an incident is *collecting evidence* until a full window has elapsed after the onset. Collection
   continues after the incident closes, because a flickering detection does not end the change. This was also adopted
   after validation, where noise faults closed before their evidence was complete. Only an incident that closed before
   any onset could be estimated has no evidence. The page shows
   the elapsed and needed seconds. After that the evidence is **frozen**, with a digest, bounds, the number of records,
   `as_of`, the onset and the statistic. An investigation can only start on frozen evidence; earlier requests get
   `409 EVIDENCE_NOT_READY` with the progress.

## Incident page (`/incident?id=INC-0001`), EN/TR

1. **Header:** id, sensor, severity, open or closed, opened time, duration, and the "Simulated plant" label.
2. **Lifecycle stepper**, live: detected → change onset estimated → evidence collected (progress) → agents
   investigated → Judge decided → awaiting human decision (step 3). Each step shows its time and a one-line meaning.
3. **Sensor chart** around the onset:
   - the baseline band;
   - the estimated onset marker, labelled with the statistic;
   - the injected-fault start (simulation ground truth) and the onset error in seconds;
   - the frozen evidence window, shaded;
   - a table alternative.
4. **Findings table:** check, column, severity, measured values, first seen.
5. **Candidate explanations**, taken from the investigation record of the agent run (A24/A28):
   - each mechanism with its status and the probes, showing measured values against the fixed thresholds;
   - the model's suggestion (A23), marked advisory, with agreement against the rule result;
   - the Judge decisions.
6. **Agent operations:** run state, agents completed or needing evidence, LLM calls, duration, and a link to the full
   Agent flow.
7. **Evidence:** window bounds, `as_of`, record count, the window and baseline digests, and a CSV download of the
   frozen window.

The Command Center incident cards show the evidence progress and link to the Incident page.

## Measured quality (this step)

`plant_eval.py` measures the plant loop end to end. For each fault and sensor it records detection, detection delay,
onset error, and whether the probe loop supports exactly the injected mechanism.

- **Splits:** seeds 1–20 for development (seen while designing), 21–40 for validation, 41–60 held out. Held-out is
  scored once after review.
- **Reporting:** Wilson 95% intervals, and n/a when the denominator is zero.

Known limits, reported and not hidden:

- **Noise on a seasonal sensor:** the fixed spread probe compares marginal spreads, and the seasonal swing dominates
  them, so the noise mechanism is refuted.
- **Duplicate burst:** a 30-row burst is 13% of a window, below the fixed 20% support threshold, so the mechanism stays
  open.

Probe thresholds from F04 are not changed in this step.

## Constraints

- Pure Python, deterministic, with 100% branch coverage. The estimator never reads the simulator's fault records.
- No claim of root cause: "supported" still means "consistent with fixed probes".
- Budget USD 0. EN/TR, keyboard operable, works at 375 px, and respects `prefers-reduced-motion`.
