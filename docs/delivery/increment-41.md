# Increment 41 — Cross-system regression and route-result integrity

Re-ran the existing 719-test application baseline, reviewed routing/accounting/recovery authority and reproduced unsupported success without a terminal event. Shared history validation now prevents contradictory historical replay and clean recovery reports; proposed events require matching usage before commit.

Validation: 731 application + 13 security/hygiene methods = 744 distinct tests; twelve new methods. Local Python 3.12/3.14 full statement/branch coverage is 100% with no exclusions. Eleven installed checks, fresh dependency/secret/hygiene scans and PR/main CI are delivery gates. Final run links are recorded in the PR. Original architecture and core execution artifacts remain preserved.

See [ADR-0041](../adr/0041-route-outcome-integrity.md). Next: authenticated provider usage evidence and durable recovery decisions, with real model acceptance still dependent on independently measured quality.
