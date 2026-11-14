# ADR-0043 — Explicit atomic usage reconciliation

Status: Accepted for the trusted-host local profile.

Signed review/evidence records previously retained all ambiguous usage holds. Add a new opt-in version 4 scope with operation-bound ACCOUNT_KNOWN_USAGE approvals under a distinct reconcile-usage purpose. Original routing scopes retain their formats; existing unsigned/ordinary signed reviews grant no settlement authority.

Keep delivery state immutable and record accounting in an append-only receipt within the same usage transaction. Project aggregate accounting from validated original rows plus receipts, so signature evidence and budget effects commit or roll back together. A late worker cannot transition a reconciled attempt. Unresolved delivery continues to block admission/resend; no successful answer or delivery is inferred from token evidence.

Qualification: 759 application + 13 security/hygiene methods = 772 distinct tests, fourteen new. Python 3.12 has 4,457 statements / 1,340 branch exits; Python 3.14 has 4,394 / 1,340; both 100%, zero exclusions. Actual child processes terminate through the public API before and after commit. Reopen/replay/concurrency prove holds are retained or charges are applied exactly once. Twelve installed checks, fresh security scans and PR/main CI remain delivery gates; final evidence is recorded in the PR.

A signature authenticates an approved host issuer's claim, not every external billing category. Current grants/clocks and single-scope custody are trusted host responsibilities. Persistent audit/history is bounded and uses increasing sequence cursors. A consistent privileged rewrite/rollback remains outside the local boundary. See [contract](../contracts/usage-reconciliation-v1.md).

Next: consolidate provider transport, independent usage acquisition and managed identity/custody acceptance before live activation; independently sealed model-quality measurement remains required. Do not interpret local coverage or simulated provider behavior as measured real-model accuracy.
