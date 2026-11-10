# AegisFlow AI — Agentic Data Reliability

Evidence-led investigation of batch data pipelines, with bounded tools and human-reviewed remediation as the target architecture.

## Current increment

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
```

Exit codes: `0` = checks pass; `1` = quality violations found; `2` = input rejected. A failed-quality demo intentionally returns `1`. Reports never expose raw order IDs or customer values. Use synthetic data only; local file inspection has no enterprise access policy.

## Documents

- [Architecture PDF](docs/AegisFlow-AI-Mimari-v1.0.pdf) and [original Turkish architecture](docs/architecture.md)
- [Planned role catalog](docs/agent-catalog.json) and [original diagrams](docs/diagrams/)
- [Engineering workflow](CONTRIBUTING.md), [active backlog](docs/delivery/backlog.md) and [increment evidence](docs/delivery/increment-01.md)
- [Baseline design decision](docs/adr/0002-deterministic-diagnostics.md)
- [Source provenance](docs/source/provenance.json)

The original Turkish design is an immutable reference archive. New engineering documentation, code and GitHub collaboration use English. Its roadmap and experimental targets are not measured results.

## History preservation

The previous supply/SLA prototype remains separate and unchanged at https://github.com/aegisflow-ai-labs/Aegisflow-ai. This repository starts a distinct Data Reliability implementation; role identifiers must not be interpreted using the old catalog.
