# Design: Command Center with a live simulated plant (step 1 of the new direction)

Approved by the operator on 2026-11-26 ("make it professional"). Goal: the first screen must feel like a live operations product.
Data streams in, faults can be injected, detections happen visibly, incidents open, and agent investigations can be
launched and watched. Everything is labelled honestly: the plant is a **simulation** until real sensors are connected.

## What the operator sees (Overview becomes "Command Center" / "Komuta Merkezi")

1. **Status bar:** the simulation state (running / paused, speed 1x/5x/20x) with Start, Pause and Reset, a permanent
   "Simulated plant" badge, local model status (reachable or unreachable, model name), and the time since start.
2. **KPI row, all computed from real state:** active incidents; detections in this session; agent investigations run;
   Judge acceptance of specialist claims (from retained runs); median investigation time; data points processed.
   Each KPI has a one-line meaning and an n/a state.
3. **Live sensor panel:** three synchronised line charts (temp_c, pressure_kpa, flow_lpm) over the last 300 readings,
   updating about once per second. They show the baseline band (mean ± 3 sd from the reference window), vertical
   markers where a detection fired (with a text label), and the injected-fault window shaded and labelled "injected".
   The current values are shown as large numbers with a units label. A data table toggle gives a text alternative.
4. **Fault injection console:** buttons for calibration offset, unit change ×10, stuck sensor, noise increase, sampling
   slowdown, ingestion pause and duplicate burst, each with a target sensor select. Each button explains in one line
   what it simulates. The injected fault is listed with start time and a Clear action. The console states plainly that
   this injects a simulated fault for demonstration and evaluation.
5. **Incidents list:** auto-opened incidents, each with severity, detected checks (sampling, volume, freshness, PSI
   distribution shift, level shift, flatline, duplicates), the affected sensor, the time, and actions: "Investigate
   with agents" (starts a real agent run on the incident window and opens /flow?run=...) and "View evidence".
6. **Agent activity:** a stacked bar of agent outcomes per layer from the retained runs, and the last 5 investigations
   with status and link.
7. **Next step hint:** a short guide for the current state ("Start the simulation" → "Inject a fault" → "Investigate").

## How it works (engine)

- `src/aegisflow_dr/simulation.py`: a deterministic, seeded plant simulator in pure Python.
  - Readings every simulated second: temp_c = 20 + 3 sin(2π t/100) + N(0, 0.5), pressure_kpa = N(100, 1),
    flow_lpm = N(5, 1).
  - Fault injectors: calibration offset (+1.5 sd), unit change ×10, stuck sensor, noise ×3, sampling slowdown (one reading
    every 2 s), ingestion pause (no readings while active), duplicate burst (repeat the last 30 rows).
  - Bounded ring buffer of readings with ISO timestamps; `export_window(n) -> CSV bytes`.
- **Live monitor** (also in `simulation.py`): the baseline is built with `baseline.build_baseline` from the first 3
  windows of 120 readings; every 15 simulated seconds the latest 120-reading window is compared with `baseline.compare`
  and checked with `profiling.profile_csv`. New findings open an incident with id, window CSV digest, findings and
  severity rule (distribution/level shift/unit = high; sampling/volume/freshness = medium; others = low). No duplicate
  incident while the same finding persists. An incident closes when two consecutive windows are clean.
- Workbench (`apps/local/plant.py` + routes): a background thread advances the simulator in real time × speed. Routes:
  `GET /api/plant/state` (series, KPIs, incidents, faults, status), `POST /api/plant/control`
  {action: start|pause|reset|speed, speed?}, `POST /api/plant/inject` {fault, sensor}, `POST /api/plant/clear`
  {fault_id}, and `POST /api/plant/incidents/<id>/investigate` (starts an agent run through the existing run manager with
  the incident window, the plant baseline and as_of = window end, and returns run_id). Session auth, Host/Origin checks
  and body caps, as with the other routes. The UI uses polling once per second (simple and robust); no SSE is needed here.

## Visual quality bar

Dark operations dashboard consistent with the existing tokens. A clear grid: status bar, then KPIs, then charts (2/3)
with incidents (1/3), then the fault console and agent activity. Charts are inline SVG with proper axes, gridlines, units,
legends and accessible text alternatives. Animations are subtle (value tick, new-incident highlight) and respect
`prefers-reduced-motion`. EN/TR. Keyboard operable, with 44 px targets. Works at 375 px (the grid stacks). Nothing in
any view is decorative.

## Acceptance (what "done" means)

The operator opens the app, presses Start, and sees the charts move. They inject "unit change ×10" on pressure, and
within about 15–30 s a high-severity incident appears with a distribution-shift finding and a marker on the chart. They
press "Investigate with agents", and the Agent flow page shows the run live. Screenshots on desktop and mobile, EN and
TR, are delivered to the operator.
