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
