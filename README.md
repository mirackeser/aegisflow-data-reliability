# AegisFlow AI — Agentic Data Reliability

Evidence-led investigation of batch data pipelines, with bounded tools and human-reviewed remediation as the target architecture.

## Current increment

The batch demo now executes source validation → normalized staging → SQL customer-sales aggregation in an in-memory SQLite database. It checks count/amount conservation and traverses a fixed declared lineage graph for potential downstream impact. Packaged SQL and canonical stage/mart datasets have linked content hashes. Dashboard execution, durable snapshots and inferred root cause remain outside this increment.


The executable baseline generates synthetic orders and checks a CSV data contract. It detects renamed columns, missing values, duplicate order IDs and invalid amounts. Every report identifies the exact input with SHA-256 and uses logical CSV record numbers as evidence locators. Invalid input and exhausted input budgets fail explicitly.

**This is a deterministic diagnostic foundation, not an agent runtime or root-cause inference system.** All 36 specialist roles remain planned. No model calls, external connectors, automatic repair or production writes are implemented.

## Try locally

Python 3.11+; no runtime dependencies:

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m aegisflow_dr catalog
PYTHONPATH=src python3 -m aegisflow_dr demo
PYTHONPATH=src python3 -m aegisflow_dr demo --fault schema_drift
PYTHONPATH=src python3 -m aegisflow_dr demo --fault null_total
PYTHONPATH=src python3 -m aegisflow_dr demo --fault duplicate_order
PYTHONPATH=src python3 -m aegisflow_dr inspect fixtures/orders-clean.csv
PYTHONPATH=src python3 -m aegisflow_dr batch-demo
PYTHONPATH=src python3 -m aegisflow_dr batch-demo --transform exclude_first
PYTHONPATH=src python3 -m aegisflow_dr batch-demo --fault schema_drift
```

Exit codes: `0` = checks pass; `1` = quality/reconciliation failure or blocked batch; `2` = input rejected. A failed-quality demo intentionally returns `1`. Reports never expose raw order IDs or customer values. Use synthetic data only; local file inspection has no enterprise access policy.

## Documents

- [Architecture PDF](docs/AegisFlow-AI-Mimari-v1.0.pdf) and [original Turkish architecture](docs/architecture.md)
- [Planned role catalog](docs/agent-catalog.json) and [original diagrams](docs/diagrams/)
- [Engineering workflow](CONTRIBUTING.md), [active backlog](docs/delivery/backlog.md) and [source diagnostic evidence](docs/delivery/increment-01.md) and [batch evidence](docs/delivery/increment-02.md)
- [Baseline design decision](docs/adr/0002-deterministic-diagnostics.md) and [batch/lineage decision](docs/adr/0003-batch-transforms-and-lineage.md)
- [Source provenance](docs/source/provenance.json)

The original Turkish design is an immutable reference archive. New engineering documentation, code and GitHub collaboration use English. Its roadmap and experimental targets are not measured results.

## History preservation

The previous supply/SLA prototype remains separate and unchanged at https://github.com/aegisflow-ai-labs/Aegisflow-ai. This repository starts a distinct Data Reliability implementation; role identifiers must not be interpreted using the old catalog.

## License

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) and [licensing scope](docs/licensing.md). Third-party materials retain their original terms.

## Local tool gateway

`PYTHONPATH=src python3 -m aegisflow_dr gateway-demo` executes one synthetic batch through an exact host-configured tool/dataset grant. The closed request contract cannot supply policies, file paths or arbitrary SQL. Calls and UTF-8 input bytes are bounded; deadlines are checked before/after dispatch. See [ADR-0004](docs/adr/0004-local-tool-policy-and-budgets.md). This local control layer does not provide authentication, OS isolation, hard cancellation or durable quotas.
