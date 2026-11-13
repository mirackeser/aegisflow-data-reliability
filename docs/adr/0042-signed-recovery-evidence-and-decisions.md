# ADR-0042 — Signed recovery evidence and durable decisions

Status: Accepted for the trusted-host local profile.

B08 previously provided read-only recovery assessments and unsigned advisory review packets. This increment adds operation/purpose-scoped Ed25519 grants, signed current-snapshot usage assertions and operator decisions that bind both the review and any exact attached usage proof. Separate issuer/operator principals and keys are required when attaching evidence.

Decisions persist in a separate operation-scoped SQLite log under usage → decision lock ordering. Snapshot freshness and authority are checked while the usage lock is held; the decision commits before its digest is returned. Exact replay is idempotent, conflicting review IDs reject, history is bounded and updates/deletes reject for normal clients. Existing usage/route schemas and budgets are unchanged. No receipt or review can release a hold or authorize a resend.

Validation: 745 application + 13 security/hygiene methods = 758 distinct tests, fourteen new methods. Python 3.12 statement/branch coverage: 4,374 / 1,302; Python 3.14: 4,311 / 1,302; 100%, no exclusions. Negative cases include altered signatures/payloads, role/operation/time/key mismatches, stale snapshots, wrong attempts/quotes, over-cap/floating counts, attachment substitution, shared issuer/operator keys, conflicting IDs, append-only/capacity limits, database write failures and concurrent identical submissions. Twelve installed checks, dependency/secret/hygiene scans and PR/main CI are delivery gates; final links are in the PR.

Current grants and time remain host supplied; managed issuer/revocation distribution is not deployed. A signature proves possession under an approved grant, not authenticity/completeness of an external billing receipt. File ownership and independent audit custody remain required. See the [contract](../contracts/recovery-authority-v1.md).

Next: define and qualify explicit reconciliation transitions and failure atomicity under operator authorization, before any actual UNKNOWN resolution. Independent real-model quality evaluation, approved provider/data-region/retention/spending and production identity remain separate gates.
