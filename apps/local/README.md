# Local investigation workbench

Zero external spending. This local pilot connects a disposable PostgreSQL source, existing retained deterministic investigations, lexical source retrieval, revision-bound references and an authenticated loopback observation screen. No paid API, model download, inference, production exposure or source repair is enabled.

From the repository root with the package installed:

```sh
python apps/local/workbench.py --state-dir /tmp/aegis-local-private --postgres-bindir /path/to/postgresql/bin
```

Open the printed loopback address. Read `access-token` from the private state directory and paste it into the access field. It is kept only in page memory, never localStorage or a URL. Do not commit the state directory. The server binds only 127.0.0.1, checks Host/Origin and requires a bearer token for state and execution; assets are public but contain no investigation data. Restart rotates the token. This is a trusted single-user local process boundary, not production authentication, tenant hosting, distributed rate limiting or hardened Internet service.

Run investigation creates a separate temporary PostgreSQL cluster, never accesses existing servers, and checks clean/missing/duplicate data through the existing evidence engine. Database writes are limited to fixture setup using the fixture owner; the inspected reader has SELECT only and three denied write operations are verified. Temporary server shutdown is attempted in finally. Unexpected process termination may require manual cleanup of a leftover temporary cluster; no automatic uncertain worker restart is permitted.

The four displayed roles are narrow deterministic capability slices, not full autonomous specialist agents. A10 completion reflects the quality checks executed inside source qualification. Events represent actual execution boundaries, not simulated LLM progress. Knowledge retrieval is lexical, not vector/semantic RAG. Its text is untrusted reference material and never grants tool access. Cache entries are bound to tenant, grants, query and document revision; replacement/deletion invalidates entries. No local LLM is installed/configured, and the screen reports that explicitly. Model inference and calibrated quality, vector retrieval, full specialist orchestration and production operations remain separate acceptance work.

The workbench retains sanitized results and events for the current run and up to 20 prior runs, not a full enterprise audit archive. An interrupted state is reported after restart without automatic rerun. Existing core evidence, campaign and accounting APIs remain unchanged. PostgreSQL qualification creates temporary evidence that is removed with its fixture; the screen retains summaries and reference digests, not source evidence files. Do not treat these pilot summaries as enterprise audit retention.

Validation: local retrieval/cache tests, HTTP authorization/origin/Host/body rejection, single-owner admission, sanitized failure and interrupted-state recovery. `tools/check_postgres_local.py --bindir ...` performs actual isolated PostgreSQL qualification. Existing application regression and security/hygiene checks remain required. No model accuracy or production readiness is claimed.

## Investigation workspace update

The workspace now offers a full source suite or individual healthy, missing-total, duplicate-order and transformation-reconciliation scenarios. Requests select a host-owned route; no raw SQL, filesystem path or arbitrary scenario reaches PostgreSQL. The original zero-body `/api/run` route remains compatible. Reports expose sanitized findings, logical record numbers, content digests and actual reconciliation expected/observed values. Role events describe performed checks without claiming that every run detected a violation.

A bounded history of 20 prior runs is retained atomically with current state; historical views do not execute queries. Older summary-only records remain readable and explain their missing detail. This remains a single-user local summary archive, not complete enterprise audit retention. Authorization, Host/Origin checks and source write denials still apply. The UI uses local assets, text-only rendering of evidence, desktop/mobile layouts and reduced-motion support. Model inference remains unconfigured.

## Turkish/English routes and local CSV inspection

The default language is Turkish; TR/EN persists only a language preference in localStorage. Credentials remain in memory. Distinct routes `/overview`, `/investigations`, `/activity`, `/knowledge` and `/history` render separate screens, support browser history and direct navigation. Direct page reload requires local authentication again. Overview counts and bars derive only from actual retained observations; they are not model accuracy or invented telemetry.

Authenticated `POST /api/inspect` accepts UTF-8 CSV bytes (`Content-Type: text/csv`, exactly one Content-Length, 1–1,000,000 bytes, no transfer encoding). The existing engine inspects `order_id,customer_id,order_total`; arbitrary SQL, URLs and file paths are not accepted. Files and actual investigation evidence are retained in private `evidence.db` under the host-owned state directory. Uploaded input never goes to an external service or model. A27 independently rechecks the retained record and must accept its evidence binding before the upload can complete. Failures are sanitized; unknown/invalid encodings and exceeded engine row budgets cannot yield success. Uploaded inputs are not declared synthetic and do not report PostgreSQL write-denial checks that were never performed. Retention/deletion and disk quota management remain operator responsibilities; this is a local single-user tool.

Report download exports the selected sanitized result to JSON without token or raw source CSV. The UI uses textContent for evidence text, with no third-party scripts/fonts/assets. Byte limits, unauthorized uploads, content types, cross-origin requests, malformed payloads, exact record findings and retained run references are tested. Actual source hashes and references remain language invariant; known UI labels/messages are translated while original reference documents retain their source language.

## Product clarity and operations layout

The workspace explains its current purpose before asking for input: inspect order-data schema, required values, duplicate IDs, amount formats and transformation reconciliation, then review findings with record numbers and evidence. My-file and example modes are explicit and separate. Selecting a file shows its name/size without submitting it. Example execution is labeled in results/history; simply opening pages never starts work. Completed local actions move focus to the result summary; failures stay visible in the status region.

The operations overview contains source readiness, an actual execution path, counts by diagnostic category, observed history and review guidance. It deliberately uses no invented ingestion rate or model accuracy. Chart categories count diagnostic violations, while the attention summary separately deduplicates affected record references. A duplicate violation can reference more than one record. Source charts exclude transformation reconciliation violations, which are shown in the report. Truncated findings show a lower-bound notice. Older summary-only reports show an unavailable-detail state. A history trend requires at least two detailed reports. Suggested reviews are fixed check-specific guidance, never executed changes or proven causal root causes.

Technical hashes are progressively disclosed. The primary screen names human-readable stages rather than displaying only role codes. The interface retains TR/EN, distinct routes and keyboard focus. Diagram and bar states have text equivalents; reduced motion and responsive layouts apply. `node apps/local/test_presentation.cjs` verifies grouping/count/truncation/provenance/reconciliation behavior without extra dependencies. Visual QA uses a separate local state directory and synthetic data; it must not populate the user's working history automatically.

Connecting does not auto-select the last uploaded file as a new investigation. Saved results, including the most recent completed run, are explicitly opened from Reports/recent investigations; an ongoing run can still be observed. No original record/history is deleted by this UI change.

### Guided use and readable reports

The overview includes a collapsible product guide with links to sources, inspections,
execution and saved reports. Every page explains its purpose and next action.
Current local capabilities and future production/model capabilities are explicitly
separated in the guide. A completed task is not presented as proof of data accuracy.

Users can download a three-order synthetic CSV template without submitting data.
Completed or saved inspections can be exported as a standalone, printable HTML
report in the selected TR/EN language; JSON remains available for technical review.
The HTML preserves source identity, run ID, timestamps, grouped record references,
truncation warnings and reconciliation values. It escapes all interpolated values
and forbids scripts and network resources via a restrictive content policy.

## Investigation workspace (current interface)

The interface is a multi-page dark operations workspace (Overview, Investigations, Data sources, Execution flow, Reports, Evidence references) in Turkish and English. Every page opens with a four-part guide: what it is for, what you can do, what happened, and what to do next.

- **Data sources** validates a CSV against the order contract before any investigation (`POST /api/discover`): record/column counts, inferred column types, exact contract match, and *suggested* column mappings for renamed fields (alias or similar name; mostly-numeric amount columns only). Suggestions are never applied silently; a mapping is sent only after the person ticks it (`X-Column-Mapping`) and only renames the header of a copy. Labelled synthetic samples (`POST /api/sample/<fault>`) and the isolated PostgreSQL example remain separate, clearly labelled sources. Company databases and warehouses are shown as *not connected*.
- **Connected folder** (opt-in, `--source-dir FOLDER`) exposes CSV and SQLite files placed directly in that one folder, read-only. Names are matched against the folder listing, so path separators, symbolic links and other directories are unreachable. SQLite files open with `mode=ro` plus `query_only`, an authorizer that permits only reads, and a 5-second deadline; tables are listed with row counts (`GET /api/sources`, `POST /api/source/tables|discover|inspect`). Exports are capped at 1 MB and 10,000 rows, a larger table is inspected as a labelled sample, and binary cells become the word `binary`. Runs are labelled "Connected source". This is a local-file connector, not a production-database or enterprise connector: no network database, credential store or scheduler is involved.
- **Investigations** groups findings by rule-based priority (schema, then findings that change totals, then the rest — not a model score). For each finding it shows the affected record numbers with masked identifiers, observed duplicate patterns (identical repeat vs. conflicting values, labelled as observations, never as confirmed causes), exact decimal amount exposure, declared downstream blocking, retained-evidence hashes, the revision-bound reference retrieved for that finding class, and read-only proposed actions. A person can accept, defer or dismiss each action (`POST /api/review`); the decision is stored for audit and changes no data.
- **Execution flow** is derived from the executed tool trace (`aegisflow_dr.execution_view`): completed, needs-you, skipped/blocked and unavailable steps, each with dependencies and a reason code. Root-cause inference is shown as unavailable (no model configured) and remediation as disabled (read-only policy). Role IDs refer to the design catalog; no autonomous agent or model call occurs.
- **Overview** charts only observed values: exact quality-dimension counts, a column×check problem map, a valid-amount histogram, saved-run trend and source readiness. Nothing is simulated.

Computation lives in `src/aegisflow_dr/analysis.py` (deterministic, bounded, 100% branch-covered). Verification: `python -m unittest discover -s apps/local`, `node apps/local/test_workspace.cjs`, `node apps/local/test_strings.cjs` (bilingual integrity) and the existing presentation tests.

## Change monitor and execution timeline

`monitoring.py` compares retained inspections of the same source (an uploaded file name, a connected folder table, or all labelled synthetic samples together) and `/api/state` returns the result as `monitoring`. Fixed rules over exact counts raise: `QUALITY_DEGRADED` (share of affected records up 5 points or more), `NEW_CHECK_FAILURE`, `SCHEMA_CHANGED` / `SCHEMA_RESTORED`, `ROW_COUNT_SHIFT` (50% or more), `AMOUNT_LEVEL_SHIFT` (average valid amount moves 50% or more) and `RECOVERED`. A source needs two inspections before it can be compared. These are prompts to look, not statistical tests, forecasts or causes; the Overview and Reports pages draw the retained ratios per inspection and mark the inspections where a rule fired.

The Execution flow page adds a timeline drawn from the real timestamps of the run's events: bar widths are measured spans, a step with a single recorded event is shown as a marker, and nothing is estimated. The capability graph gained stage headers and animated edges for steps that actually completed (disabled when the person prefers reduced motion). Role IDs still name design-catalog capabilities; no autonomous agent or model call is shown because none runs.

## Check accuracy page

`/evidence` (authenticated `GET /api/evaluation`, computed once per process on your machine) shows the record-level evaluation from `docs/evaluation/`: labelled corpus size, split sizes, leakage status, corpus fingerprint, and per-check recall and precision for `diagnose_csv` and `record_issues` across development, validation and held-out splits, each with exact counts and the lower bound of a 95% Wilson interval (an undefined rate is shown as n/a, never 100%). The page states what is not measured: real data, fault kinds nobody injected, and any language model.

## Capability map

`/agents` (authenticated `GET /api/capabilities`) separates the 36-role design catalog from the code that exists. `capability_map.py` states per role whether it is implemented (7), partly implemented (6), unavailable because it needs a model (1), disabled by the read-only policy (1) or only planned (21), and names the code behind each claim; a test imports every named anchor so a claim cannot outlive its code, and checks that unavailable and disabled roles agree with the execution plan. Partly implemented roles state their limit (for example, volume shifts are flagged but freshness is not measured). The page also marks which roles ran in the current inspection; a role never shows as running unless a plan step for it completed.

## Comparing two sources

With the Connected folder source selected, "Compare with a second source" (`POST /api/source/compare`, JSON `{first:{source,table?}, second:{source,table?}}`) matches two CSV or SQLite sources by `order_id` through `consistency.py`. It reports identical, differing (per column, with masked examples), only-in-first and only-in-second counts. Values are trimmed; ids match exactly including letter case; valid amounts compare numerically, anything else as text. A blank or repeated id in one source cannot be matched, so it is counted as ambiguous and excluded from both the value comparison and the one-sided counts. If either export was cut at the 10,000-row limit the response says `complete: false` and the page warns that one-sided counts may be sampling artifacts. Nothing is written and no inspection is created.

The same response carries `cardinality` from `cardinality.py` (the A18 role): how many shared order ids are one-to-one, one-to-many, many-to-one or many-to-many, the exact row count an inner join on `order_id` would return, how many extra rows that is, and how much each side's valid amount total would be inflated by the repeated keys (exact decimal arithmetic, checked in tests against a brute-force nested-loop join). Blank ids never join. It covers the two chosen extracts only, not other tables or foreign keys, and it changes nothing.

The state snapshot also carries `similar` from `similar.py` (the A22 role, partial): for each retained inspection that failed, up to three other retained inspections whose set of failing checks and schema issues overlaps by at least half (shared items divided by all items seen in either), with what is shared and what differs. The Investigations page shows them in a "Similar earlier inspections" panel. This is exact set matching over retained deterministic evidence: it is not embeddings, not retrieval-augmented generation, and it says nothing about cause. Only the 20 retained inspections are searched, and a clean inspection matches nothing.
