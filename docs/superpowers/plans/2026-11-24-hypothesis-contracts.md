# Hypothesis Contracts (F04) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Versioned observation / hypothesis / probe / investigation contracts and a deterministic, budgeted investigation loop over a fixed catalog of simulated mechanisms, measured on simulated scenarios with held-out, and shown in the bilingual workbench.

**Architecture:** `aegisflow_dr.hypotheses` (catalog, observations, probes, loop, schema validation) on top of `baseline.compare` and `profiling.profile_csv`; `aegisflow_dr.hypotheses_eval` reusing `baseline_eval`'s generator; one workbench endpoint and a "Candidate explanations" section in `apps/local/baseline.js`.

**Tech Stack:** Python 3.11+ standard library plus the existing `jsonschema` dependency; unittest + coverage; vanilla JS.

**Spec:** `docs/superpowers/specs/2026-11-24-hypothesis-contracts-design.md` — binding for every value below.

## Global Constraints

- Same gates as before: `PYTHONPATH=src .venv/bin/python -m coverage run --branch --source=aegisflow_dr -m unittest discover -s tests && .venv/bin/python -m coverage report --fail-under=100`; `PYTHONPATH=src .venv/bin/python -m unittest discover -s apps/local`; `node apps/local/test_presentation.cjs && node apps/local/test_workspace.cjs && node apps/local/test_strings.cjs`.
- SPDX headers; English code/docs; `[English, Turkish]` UI strings (Turkish term for baseline: "taban çizgisi"; hypothesis: "hipotez"; counter-hypothesis: "karşı hipotez"; probe: "sınama").
- Constants in `hypotheses`: `FORMAT = "1"`, `ENGINE = "deterministic-hypotheses-v1"`, `CATALOG_VERSION = "1"`, `MAX_PROBES_DEFAULT = 6`, `MAX_PROBES_LIMIT = 20`, `MECHANISMS` and `PROBES` in spec table order, `STATEMENT` = the spec's fixed text.
- Probe thresholds exactly as the spec tables; never tuned on evaluation output.
- Held-out discipline: implementers never run `--include-heldout` and never create `docs/evaluation/hypotheses.md`.
- Never claim root cause, model accuracy, live agents or production connection. "supported" never becomes "confirmed".
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; explicit `git add`, never `.coverage`.

## Review Focus

- A comparison with findings no catalog mechanism explains (e.g. `column_added`) → those observations are listed but produce no hypothesis; no crash.
- `max_probes` of 0, 21, `True` or a float → `InputRejected`.
- Two numeric columns both shifted → independent hypothesis sets per column; probes chosen per (probe, column).
- An investigation record edited after creation → schema-valid but `trace_sha256` mismatch is detectable with `verify_investigation`.
- A probe whose input is undefined (baseline median 0, baseline sd 0, no freshness measurement) → `null` measured value and neutral outcomes, never ZeroDivisionError.

---

### Task 1: Contracts, catalog and hypothesis generation

**Files:** Create `src/aegisflow_dr/data/hypothesis-contracts-v1.json`, `src/aegisflow_dr/hypotheses.py`; Test `tests/test_hypotheses.py`.

**Interfaces — Produces:** `observations_from(comparison: dict, profile: dict) -> list[dict]`; `generate(observations: list[dict]) -> list[dict]` (hypotheses with competitors, all `open`); `validate(kind: str, value: dict) -> dict` (kind in `observation|hypothesis|probe_result|investigation`, raises `InputRejected`); `verify_investigation(record: dict) -> dict` (schema + trace digest, raises `InputRejected`); `trace_digest(record) -> str`; constants.

- [ ] Tests: schema file loads offline and is Draft 2020-12 valid; each `$defs` kind accepts a minimal valid example and rejects an extra key and a wrong enum; `observations_from` maps every catalog-relevant baseline finding and the three profile checks with `evidence_sha256` = comparison `source_sha256`, ignores other checks; `volume_change` direction routes to `partial_load`/`source_outage` (drop) or `duplicate_delivery` (increase); per-column mechanisms are generated per column; `genuine_change` generated for every distribution_shift column; competitors are symmetric and exclude self; a comparison with only `column_added` gives one observation and no hypotheses.
- [ ] Implement per spec "Contracts" and "Mechanism catalog". Package data: ensure `pyproject.toml` package-data already covers `data/*.json` (it does) and add the new file to `tools/check_installed.py` only if that script enumerates data files.
- [ ] Gate, commit `feat: hypothesis contracts, catalog and generation (F04)`.

### Task 2: Probes and the bounded loop

**Files:** Modify `src/aegisflow_dr/hypotheses.py`; Test `tests/test_hypotheses.py`.

**Interfaces — Consumes:** Task 1; `baseline.compare`, `baseline.load_baseline`, `profiling.profile_csv`, `profiling.read_table`, `profiling.parse_timestamp`. **Produces:** `investigate(baseline: dict, payload: bytes, *, as_of: str | None = None, max_probes: int = 6) -> dict` (validated investigation record); one private function per probe returning `(measured, outcomes)`.

- [ ] Tests: each probe's support/refute/neutral boundaries from the spec table on small constructed inputs (e.g. scale_ratio r = 10 with sd_ratio 10 supports unit_change; r = 1.9 refutes; r = −1 refutes; baseline median 0 gives null and neutral); status update rules; selection order (most unrefuted hypotheses concerned, ties by probe order then column); every stop reason reachable (`no_observations`, `resolved`, `no_informative_probe`, `probe_budget_exhausted` with `max_probes=1`); `max_probes` validation; ranking order; `genuine_change` never supported or refuted; record passes `verify_investigation` and an edited copy fails it; deterministic output for identical input; end-to-end on generated data for: pressure ×10 → unit_change sole supported; temp +1.5 sd → calibration_offset; last-160-records batch → partial_load supported, source_outage refuted by freshness_lag.
- [ ] Implement per spec "Probes" and "Bounded loop and replanning".
- [ ] Gate, commit `feat: deterministic probes and budgeted replanning loop (F04)`.

### Task 3: Simulated-scenario evaluation

**Files:** Create `src/aegisflow_dr/hypotheses_eval.py`, `tests/test_hypotheses_eval.py`.

**Interfaces — Consumes:** `hypotheses.investigate`, `baseline.build_baseline`, `baseline_eval` generator helpers (import, do not copy), `check_evaluation.wilson`. **Produces:** `split_of`, `scenario(group, name) -> (references, current, as_of, truth_mechanism | None)`, `evaluate(splits=("development","validation"))`, `render_markdown(report)`, `main(argv=())` with `--include-heldout`; `SCENARIOS` in spec order.

- [ ] Tests: split stability with pinned counts; scenario mechanics per spec table; metrics arithmetic on a constructed mini-report; zero denominators render `n/a`; mutants from the spec each exposed on development; held-out absent by default; report states its limits (simulated, same authors, unmodelled scenarios show misattribution, no root cause).
- [ ] Implement per spec "Evaluation". Runtime of the test module < 60 s (cache in setUpClass).
- [ ] Gate, commit `feat: simulated-scenario evaluation of the hypothesis loop (F04)`.

### Task 4: Workbench endpoint, panel section and capability map

**Files:** Modify `apps/local/baseline_store.py` (`investigate(name, payload, as_of=None)`), `apps/local/workbench.py` (`POST /api/baselines/investigate`, same body and caps as compare), `apps/local/baseline.js`, `apps/local/strings.js`, `apps/local/style.css`, `apps/local/test_baseline_store.py`, `apps/local/test_workbench.py`, `src/aegisflow_dr/capability_map.py`, `tests/test_capability_map.py`.

- [ ] Store/HTTP tests mirroring compare (auth, 404, 422, happy path validates with `verify_investigation`).
- [ ] UI per spec "Interface": an "Explain" button after a comparison with findings; verdict + statement; observation chips; hypothesis cards (status text + icon, competitors, probe evidence with measured values); probe timeline by round with budget and stop reason; EN/TR; accessible; no cause wording.
- [ ] Capability map per spec; counts test updated (A24, A25, A28 planned → partial); A23 limit text updated in both languages.
- [ ] Gates, commit `feat: candidate explanations in the workbench and capability map (F04)`.

### Task 5 (controller): held-out, docs, increment 63

- [ ] Whole-branch review, one fix wave, re-review; then generate `docs/evaluation/hypotheses.md` once with `--include-heldout`, add the sync test, update `docs/evaluation/README.md`, roadmap F04 line, `docs/delivery/status.md` (Increment 63); gates; PR; CI; merge.
