# Baseline Comparison (D05c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare a current CSV with a stored, digest-protected baseline (sampling interval, volume, freshness, empty share, distribution shift by PSI), measure it on a synthetic corpus with development / validation / held-out splits, and expose it in the bilingual local workbench.

**Architecture:** A pure deterministic module `aegisflow_dr.baseline` (build, verify, compare) reusing `profiling.read_table`, `profiling._column` and `profiling.parse_timestamp`; an evaluation module `aegisflow_dr.baseline_eval` mirroring `profiling_eval`; a local store plus four HTTP endpoints in `apps/local`; one new browser script `baseline.js`.

**Tech Stack:** Python 3.11+ standard library only (no new dependency), `unittest`, `coverage` branch mode; vanilla JS with the existing `h()`/`t()` helpers; Node assertion scripts.

**Spec:** `docs/superpowers/specs/2026-11-24-baseline-comparison-design.md` — the binding authority for every value below.

## Global Constraints

- Run tests with `PYTHONPATH=src .venv/bin/python -m unittest ...` from the repository root; the full gate is `PYTHONPATH=src .venv/bin/python -m coverage run --branch --source=aegisflow_dr -m unittest discover -s tests` then `.venv/bin/python -m coverage report --fail-under=100`. Package branch coverage must stay at 100% with no `pragma: no cover` except the existing `if __name__ == "__main__"` idiom.
- Local app tests: `.venv/bin/python -m unittest discover -s apps/local`; JS: `node apps/local/test_presentation.cjs && node apps/local/test_workspace.cjs && node apps/local/test_strings.cjs`.
- Every new source file starts with `# SPDX-License-Identifier: Apache-2.0` (Python) or `// SPDX-License-Identifier: Apache-2.0` (JS).
- Code, comments, docs and commit messages are English. UI strings are `[English, Turkish]` pairs in `apps/local/strings.js`, no markup, matching placeholders.
- No new runtime dependency. Python 3.11 compatible (no 3.12+ only syntax).
- Constants (module `baseline`): `FORMAT = "1"`, `ENGINE = "deterministic-baseline-v1"`, `MAX_REFERENCES = 5`, `MIN_DELTAS = 10`, `MIN_VALUES = 50`, `FRESHNESS_INTERVALS = 3`, `SAMPLING_RATIO = 1.5`, `VOLUME_RATIO = 1.5`, `EMPTY_RATE_DELTA = 0.10`, `PSI_SHIFT = 0.25`, `PSI_SMOOTH = 0.5`, `CHECKS = ("column_missing", "column_added", "role_change", "sampling_interval_change", "volume_change", "freshness", "empty_rate_change", "distribution_shift")`. Decile edges are rounded to 6 places before de-duplication.
- Thresholds are fixed by the spec. Do not change any threshold in response to evaluation results.
- **Held-out discipline:** implementers never run `baseline_eval` with `--include-heldout` and never generate `docs/evaluation/baseline.md`; the controller does that once at the end.
- Never claim root cause, model accuracy, live operation or production connection in code, docs or UI.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A reference CSV whose header differs from another reference only by column order → must be rejected (`InputRejected`), not silently merged.
- A stored baseline edited by hand (one edge changed, one count changed, digest left alone) → `load_baseline` rejects; the workbench store moves the file aside instead of using it.
- A current file without any timestamp column compared with a time-based baseline → no crash; sampling/freshness appear in `not_evaluated` with reasons.
- `as_of` with a timezone against naive data (or the reverse) → `not_evaluated` reason `timezone_mismatch`, never an exception from datetime subtraction.
- Comparing a baseline with one of its own reference files → `NO_DRIFT` with PSI exactly 0 for every numeric column.

---

### Task 1: Baseline record — build and verify

**Files:**
- Create: `src/aegisflow_dr/baseline.py`
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: `profiling.read_table(payload) -> (header, rows)`, `profiling._column(name, values) -> (profile, kinds)`, `profiling.parse_timestamp(text) -> datetime | None`, `pipeline.InputRejected`.
- Produces: `build_baseline(payloads: list[bytes], *, freshness_sla_seconds: int | None = None) -> dict`; `load_baseline(obj: object) -> dict` (returns the validated dict); `canonical_digest(record: dict) -> str` (SHA-256 of the canonical JSON of `record` minus `digest`); helper `bin_counts(edges: list[float], values: list[float]) -> list[int]`; helper `interval_median(timestamps: list[datetime]) -> float | None` (median positive gap between sorted distinct timestamps, `None` if fewer than `MIN_DELTAS` gaps); all constants listed in Global Constraints.

- [ ] **Step 1: Write failing tests** in `tests/test_baseline.py`, class `BuildBaselineTests`:
  - `test_record_shape_and_digest`: three 400-record references (ts every 60 s, one numeric `v`, one text `tag`) → keys exactly `{"format_version","engine","columns","time_column","references","volume","sampling","freshness_sla_seconds","empty_share","numeric","digest"}`; `sampling["median_interval_seconds"] == 60`; `freshness_sla_seconds == 180`; `volume == {"min_records":400,"max_records":400,"median_records":400}`; `digest == canonical_digest(record)`; `"tag" not in record["numeric"]`.
  - `test_explicit_sla_wins`: `freshness_sla_seconds=900` → 900; `0`, `-5`, `True`, `1.5` → `InputRejected`.
  - `test_reference_count_bounds`: `[]` and six payloads → `InputRejected`; non-list → `InputRejected`.
  - `test_headers_must_match_in_name_and_order`: references `a,b` and `b,a` → `InputRejected`.
  - `test_mixed_timezone_awareness_rejected`: one reference with `Z` timestamps, one naive → `InputRejected`.
  - `test_edges_counts_and_constant_column`: values 1..100 → 9 strictly increasing edges, `sum(counts) == 100`, `len(counts) == 10`; a constant column of 60 values → `edges == []`, `counts == [60]`; a numeric column with 49 values → `edges is None and counts is None`.
  - `test_no_raw_values_stored`: a text column containing the marker `SECRET-TAG-123` → marker absent from `json.dumps(record)`.
  - `test_interval_median_needs_ten_gaps`: 10 timestamps → `None`; 11 → median.
  - Class `LoadBaselineTests`: `test_round_trip` (`load_baseline(json.loads(json.dumps(r))) == r`); `test_every_single_field_edit_is_rejected` (for each top-level key, and for one edge, one count, one reference sha, change the value without touching `digest` → `InputRejected`); `test_digest_recomputed_after_valid_edit_still_checks_bounds` (set `edges` non-increasing and recompute digest → `InputRejected`); `test_wrong_types_rejected` (`None`, list, extra key, missing key → `InputRejected`).
- [ ] **Step 2: Run** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_baseline -v` — expect ImportError/failures.
- [ ] **Step 3: Implement** `build_baseline`, `load_baseline`, `canonical_digest`, `bin_counts`, `interval_median` in `src/aegisflow_dr/baseline.py` following the spec's "Baseline record" section exactly (pooled roles via `profiling._column` on concatenated column values; `statistics.quantiles(values, n=10, method="inclusive")`; edges rounded to 6 then sorted distinct; `bisect.bisect_right`). Module docstring states scope and the privacy note.
- [ ] **Step 4: Run** the test module, then the full gate; coverage for `baseline.py` must be 100% branch.
- [ ] **Step 5: Commit** `feat: digest-protected profile baseline record (D05c)`.

### Task 2: Comparison against a baseline

**Files:**
- Modify: `src/aegisflow_dr/baseline.py`
- Test: `tests/test_baseline.py` (new classes)

**Interfaces:**
- Consumes: Task 1 functions and constants.
- Produces: `compare(baseline: dict, payload: bytes, *, as_of: str | None = None) -> dict` with the spec's result shape; `psi(baseline_counts: list[int], current_counts: list[int]) -> float` (smoothed with `PSI_SMOOTH`, rounded to 6).

- [ ] **Step 1: Write failing tests**, class `CompareTests` (build fixtures with a small local generator: ts every 60 s, `v` = seeded Gaussian, `w` = second numeric, `tag` text):
  - `test_self_comparison_is_quiet`: baseline from one reference; compare the same bytes → `status == "NO_DRIFT"`, `findings == []`, and `psi(counts, counts) == 0.0`.
  - `test_psi_hand_computed`: `psi([50,50],[90,10])` equals the value computed in the test from the formula with 0.5 smoothing (to 6 places).
  - `test_distribution_shift_found_and_detail`: `v + 3 sd` → one `distribution_shift` on `v` with `detail["psi"] > 0.25`, `detail["threshold"] == 0.25`, proportions lists of equal length summing to 1 within 1e-6.
  - `test_sampling_ratio_boundaries`: current interval 90 s (ratio 1.5, not > 1.5) → no finding; 91 s → finding; 40 s (ratio 0.6667 ≥ 1/1.5) → none; 39 s → finding.
  - `test_volume_band`: baseline 400 records; 267 → none (267 ≥ 266.67); 266 → `drop`; 600 → none; 601 → `increase`.
  - `test_freshness`: SLA 180; as_of latest+180 s → none; +181 s → finding with `lag_seconds == 181`; no as_of → `not_evaluated` reason `no_as_of`; aware as_of vs naive data → reason `timezone_mismatch`; as_of before latest → `as_of_before_latest_record`; `as_of="yesterday"` → `InputRejected`.
  - `test_empty_rate_change`: baseline 0% empty; current 10% → none; 11% → finding.
  - `test_schema_changes`: drop `w`, add `z`, turn `tag` numeric → `column_missing/w`, `column_added/z`, `role_change/tag`; no distribution check for `w`; findings sorted by `CHECKS` order then column.
  - `test_not_evaluated_reasons`: current without timestamp column → sampling and freshness reasons; current with 30 numeric values → `too_few_values`; constant baseline column → `constant_in_baseline`; baseline column with 49 values → `too_few_values_in_baseline`; baseline without time column → `no_baseline_interval` and `no_time_column`.
  - `test_tampered_baseline_rejected_before_reading_payload`: edited baseline → `InputRejected` even with an invalid payload.
- [ ] **Step 2: Run** the module tests — expect failures.
- [ ] **Step 3: Implement** `compare` and `psi` per the spec's comparison table. Current timestamps are parsed only from the baseline's time column name when present in the current header; gaps use `interval_median`.
- [ ] **Step 4: Run** module tests and the full gate (100% branch).
- [ ] **Step 5: Commit** `feat: compare a profile with its baseline: sampling, volume, freshness, empty share and PSI (D05c)`.

### Task 3: Synthetic evaluation

**Files:**
- Create: `src/aegisflow_dr/baseline_eval.py`
- Test: `tests/test_baseline_eval.py`

**Interfaces:**
- Consumes: `baseline.build_baseline`, `baseline.compare`, `baseline.PSI_SHIFT`, `check_evaluation.wilson`.
- Produces: `split_of(group: int) -> str`; `generate(group: int, variant: str) -> (references: list[bytes], current: bytes, as_of: str, truth: set[tuple[str, str | None]])`; `evaluate(splits=("development", "validation")) -> dict`; `sensitivity() -> list[dict]` (development only); `render_markdown(report: dict, sweep: list[dict]) -> str`; `main(argv=()) -> str` (`--include-heldout` adds the held-out split); constants `VERSION = "1"`, `GROUPS = 60`, `VARIANTS` (the 14 spec variants in spec order), `SHIFTS = (0.25, 0.5, 0.75, 1.0, 1.5)`.

- [ ] **Step 1: Write failing tests** (`tests/test_baseline_eval.py`), all on development/validation only:
  - `test_split_assignment_is_stable_and_complete`: every group in exactly one split, all three splits non-empty.
  - `test_generation_is_deterministic_and_variants_share_references`: same bytes twice; all variants of one group share identical reference bytes.
  - `test_variant_mechanics`: for one group check each variant's mechanism from the spec table (record counts 350/160/1000, intervals 120/30 s, 25% empties in `flow_lpm`, `as_of` lags 60/150/1800 s, jitter within ±10 s and order kept, unit change ×10 on pressure).
  - `test_rates_without_denominator_are_none`: a constructed zero-trial rate renders `n/a`.
  - `test_unbroken_corpus_finds_large_kinds`: on development, `mean_shift_large`, `unit_change`, `sampling_slow`, `sampling_fast`, `volume_drop`, `volume_spike`, `stale`, `null_increase` are detected in every case.
  - Mutant tests, each patching `baseline` with `unittest.mock.patch` and requiring the development report to expose the defect (a drop in detected cases or a rise in unexpected cases for the named variant): `test_disabled_psi_is_exposed`, `test_psi_threshold_times_ten_is_exposed`, `test_disabled_sampling_is_exposed`, `test_inverted_volume_band_is_exposed`, `test_freshness_ignoring_as_of_is_exposed`, `test_disabled_empty_rate_is_exposed`.
  - `test_heldout_not_scored_by_default`: `"heldout" not in evaluate()["splits"]`; `main()` output contains no `Split: heldout`.
- [ ] **Step 2: Run** — expect failures.
- [ ] **Step 3: Implement** per the spec's Evaluation section. Report structure mirrors `profiling_eval` (`_rate`, `_show` style; reuse `check_evaluation.wilson`). Markdown sections: scope, corpus, thresholds and where they came from, sensitivity table (development), one section per scored split (variant table, per-check precision/recall, clean PSI summary, not-evaluated counts), "Reading these numbers" with the honesty bullets from the spec.
- [ ] **Step 4: Run** module tests and the full gate. Run time of `tests.test_baseline_eval` must stay under 60 s on the dev machine; report the time.
- [ ] **Step 5: Commit** `feat: synthetic evaluation of baseline comparison with split discipline (D05c)`.

### Task 4: Workbench store and endpoints

**Files:**
- Create: `apps/local/baseline_store.py`, `apps/local/test_baseline_store.py`
- Modify: `apps/local/workbench.py` (constructor creates `self.baselines = BaselineStore(self.root)`; routes), `apps/local/test_workbench.py`

**Interfaces:**
- Consumes: `baseline.build_baseline`, `baseline.load_baseline`, `baseline.compare`.
- Produces: `BaselineStore(directory)` with `.overview() -> {"baselines": [{"name","created","references","records","time_column","digest"}], "rejected_on_load": bool}`, `.save(name, references: list[str], freshness_sla_seconds=None, replace=False) -> dict`, `.compare(name, csv_text: str, as_of=None) -> dict`, `.remove(name) -> dict`, `.get(name) -> dict` (raises `KeyError` for unknown). HTTP: `GET /api/baselines`, `POST /api/baselines/save|compare|remove` per spec.

- [ ] **Step 1: Write failing tests**: store — slug rules (Turkish letters folded like `knowledge_base`, length 1–64, invalid → `InputRejected`), limit 50, `replace` required for an existing name, atomic 0600 file mode, edited file moved to `baselines.rejected.json` with `rejected_on_load` true, unknown name → `KeyError`, CSV text encoded UTF-8 before `build_baseline`; workbench — unauthorized 403 (follow existing tests' pattern), save/compare/remove happy path over HTTP, 422 with message for `InputRejected`, 400 for malformed JSON or non-object, 404 for unknown name, 413 for an oversized body.
- [ ] **Step 2: Run** `.venv/bin/python -m unittest discover -s apps/local` — expect failures.
- [ ] **Step 3: Implement** following `schema_store.py` patterns (lock, `_save` with `os.open(..., 0o600)`, `os.replace`) and the existing `do_GET`/`do_POST` structure.
- [ ] **Step 4: Run** local tests and the package gate.
- [ ] **Step 5: Commit** `feat: saved baselines and comparison endpoints in the local workbench (D05c)`.

### Task 5: Bilingual baseline panel

**Files:**
- Create: `apps/local/baseline.js`
- Modify: `apps/local/index.html` (script tag after `profile.js`), `apps/local/workbench.py` (static route for `/baseline.js`), `apps/local/app.js` (render the panel on the Data sources page next to `profilePanel()`), `apps/local/strings.js` (keys prefixed `bl.`), `apps/local/style.css`, `apps/local/test_strings.cjs` (add `baseline.js` to the scanned sources), `apps/local/test_workbench.py` (static route served).

**Interfaces:**
- Consumes: Task 4 endpoints; existing helpers `h`, `t`, `N`, `chip`, `request`, `requireSession`, `setNotice`, `render`, `selectedFile`; existing chart conventions in `charts.js`.
- Produces: `baselinePanel()` returning a section element or `null`.

- [ ] **Step 1: Design pass**: invoke the `ui-ux-pro-max:ui-ux-pro-max` skill for a data-dense dark dashboard panel (status tiles, horizontal bar with threshold marker, paired bar comparison, accessible chart text alternatives) and follow the existing `style.css` tokens; no new fonts or external assets.
- [ ] **Step 2: Implement** the panel per the spec's interface section: save form (name input, `multiple` file input for 1–5 references, optional SLA seconds, Replace confirmation when the name exists), compare form (saved-baseline select, optional `datetime-local` "as of" with a "Use now" button, Compare button disabled without a selected file), result view (status chip; four tiles sampling/volume/freshness/distribution with baseline vs current values and ok/changed/not evaluated; PSI bars per numeric column with the 0.25 marker and numeric value text; paired baseline/current bin-share bars for a selected column; findings list; not-evaluated list with translated reasons; scope note). Every chart has an `aria-label` sentence and the same numbers as text. All strings EN/TR.
- [ ] **Step 3: Run** the three JS test scripts and the local Python tests.
- [ ] **Step 4: Browser check** with the local workbench (desktop and 375 px mobile, EN and TR): save a baseline from a generated reference CSV, compare a clean and a shifted file, confirm no console errors and no horizontal overflow; attach screenshots paths to the report.
- [ ] **Step 5: Commit** `feat: bilingual baseline comparison panel with PSI and bin-share charts (D05c)`.

### Task 6 (controller): capability anchors, held-out run, docs

**Files:**
- Modify: `src/aegisflow_dr/capability_map.py` (A11 and A20 gain `"aegisflow_dr.baseline:compare"`), `tests/test_capability_map.py` if counts change (they must not: both stay `partial`), `docs/evaluation/README.md` (new section), `docs/delivery/implementation-and-roadmap.md` (D05 line), `docs/delivery/status.md` (Increment 62).
- Create: `docs/evaluation/baseline.md` (generated once with `--include-heldout`), sync test `test_committed_report_matches_code` in `tests/test_baseline_eval.py`.

- [ ] Generate the report with held-out once; record held-out numbers and weaknesses without touching thresholds.
- [ ] Full gate, local tests, JS tests; commit `docs: baseline comparison held-out report and increment 62`.
