# ADR-0003: Execute a bounded batch pipeline before adding orchestration

Status: accepted for the local synthetic baseline. Date: 2026-11-10.

The first diagnostic tool validates source CSV only. The second increment executes source validation, deterministic staging and a packaged SQL customer-sales aggregate in an in-memory SQLite database. Monetary values are integer cents throughout SQL processing; source validation constrains each amount and the record count so SQLite integer aggregation stays within signed 64-bit bounds.

Staging preserves source logical record order, trims order/customer identifiers and converts validated decimal amounts to cents. The mart groups by normalized customer ID and sorts results explicitly. Reconciliation compares staging and mart order counts and total cents. A packaged `exclude_first` fault drops the first record during aggregation to demonstrate a transformation regression. No arbitrary SQL, external database, writes to disk or automatic fix is accepted.

Invalid-quality source data returns BLOCKED before transformations; malformed or over-budget input remains rejected with CLI exit 2. A reconciliation failure returns FAIL. Potential downstream consumers are traversed in a fixed, declared dataset DAG: source_orders → staging_orders → customer_sales → sales_dashboard. The dashboard is metadata only. Impact is not inferred causality, a proof of root cause or column-level lineage.

Artifacts bind exact source bytes, canonical staging/mart CSV bytes and upstream hashes. SQL transforms have content hashes. The staging normalization contract has a separately versioned hash. Hashes bind observations but are not immutable storage or source authenticity. Byte snapshots are ephemeral in this increment; durable evidence storage is later work.

Reconciliation covers counts and monetary totals only. It does not prove correct per-customer attribution: a balanced reassignment can pass. Test scenarios demonstrate this boundary rather than claiming general transformation correctness. Timestamp scheduling, dbt, external connectors, observed OpenLineage events, incidents and agent execution remain planned.
