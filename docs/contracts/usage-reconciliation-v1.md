# Explicit usage reconciliation v1

Module: `aegisflow_dr.advisory.reconciliation`; install `.[recovery]`. This local accounting authority is separate from dispatch, delivery success and ordinary review authority.

## New opt-in profile

`initialize_usage(path, policy, operation=binding, routing=True, reconciliation=True)` initializes **version 4** in a new empty scope. This is explicit opt-in; v1/v2/v3 formats and behavior remain supported without migration. Boolean/profile/table mismatches reject. The v4 database contains the existing route/usage tables plus an append-only reconciliation table. Missing/extra profile tables reject on reopen.

One approved scope file represents one logical operation. Independent copies do not coordinate budgets. Current host time, grants and filesystem custody remain deployment responsibilities.

## Authorization

The closed `usage-reconciliation` approval declares `ACCOUNT_KNOWN_USAGE` and binds approval/operator UUIDs, operation, current snapshot/assessment, attempt and exact usage-attestation/signature digests. The operator signs the approval using the existing domain-separated Ed25519 envelope and a **reconcile-usage** purpose grant. A `recovery-decision` grant cannot settle accounting. An independently granted issuer signs the usage assertion; principal and key must differ from the operator. Both current grants and signatures must be valid.

`reconcile_usage(ledger, approval, signature, attestation, attestation_signature, grant=..., issuer_grant=..., now_ms=...)` requires v4 and exact byte inputs. It verifies signature purposes, current grant scope/time, exact evidence and original attempt/input/request/quote bindings. Only UNKNOWN or crash-left IN_FLIGHT attempts qualify. Counts must be exact integers within original caps; costs use the originally reserved rates. All billable categories must fit the approved host quote; a signature does not independently prove external billing completeness.

On first application, `now_ms` must equal the ledger's trusted clock. The existing monotonic observation guard applies. No new deadline, model eligibility or attempt entitlement is created.

## Atomic accounting and history

One usage database transaction verifies current state and inserts the complete signed receipt with its timestamp and digest. Before commit it revalidates aggregate accounting. Any verification/write/commit failure rolls back both receipt and observed clock. A real process exit before commit leaves the hold intact; a process exit after commit leaves a discoverable receipt. Exact replay with current valid grants returns that receipt without charging again. A reused attempt or approval ID with different bytes rejects.

`UsageLedger.snapshot()` and recovery assessments project charges from validated receipts. They release the original full hold and count only the attested input/output usage. Example: original reservation 15 tokens / 35 nUSD, attested 8 input + 2 output at rates 2 / 3 nUSD gives held 0, charged 10 tokens / 22 nUSD. Zero usage is allowed only with the same signed, scoped approval and evidence checks.

The original attempt's delivery status and route events remain historical UNKNOWN/IN_FLIGHT. Raw SQL rows are not the public accounting API. Normal transitions are denied after a reconciliation receipt exists, so a late worker cannot overwrite the accounting. Ordinary admission and route ownership continue to see unresolved delivery and block reuse/resend. Recovery still reports unresolved delivery and grants no automatic refund/resend authority. Accounting certainty does not create a Judge verdict or prove delivery success.

`reconciliation_history(ledger, after=0, limit=100)` returns records by increasing database sequence. Pages include sequence, attempt ID, digest and exact signed artifacts encoded as hex. Limit is 1..100; original per-scope attempt bounds also bound receipts (one per attempt). Reads validate original reservation arithmetic, receipt digests/bindings, caps, operation and final aggregate budgets. Update/delete triggers protect normal clients. A privileged owner can consistently replace/roll back the database; hashes/triggers are not independent audit attestation or a KMS.

```mermaid
sequenceDiagram
  participant O as Authorized operator
  participant L as v4 usage ledger
  participant V as Signature and evidence verifier
  O->>L: Signed ACCOUNT_KNOWN_USAGE + issuer evidence
  L->>L: BEGIN IMMEDIATE; validate authority and accounting
  L->>V: Verify two purposes/identities and current snapshot
  V-->>L: Exact known counts within original caps
  L->>L: Insert immutable receipt; recompute aggregate budgets
  L->>L: COMMIT receipt and observed clock together
  L-->>O: Receipt digest
  Note over O,L: Delivery remains unknown; route cannot automatically resend
```

## Qualification and next gate

Tests include real process termination before/after commit through the public API, concurrent identical application, replay/conflict, stale/revoked/expired grants, wrong bindings, over-cap data, clock mismatch, write failure, missing/tampered/orphan receipts, history and delayed worker writes. Existing v1/v2/v3 tests remain enabled.

Next: operational recovery qualification across provider transport and independent usage acquisition, managed authority/revocation distribution and deployed custody. Actual provider activation and independently measured model-quality acceptance remain separately gated. No external financial transaction is performed by this API.
