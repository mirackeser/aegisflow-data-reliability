# ADR-0037 — Bind authenticated peers and exact key versions to evaluation

Status: accepted for local trusted-host integration.

The durable evaluator gateway previously relied on principal/role values supplied by the host. Reuse the established strict mTLS socket verifier to derive a client leaf identity, map it to an immutable host-approved principal/grant/key binding, and check the current persisted identity/key flags before invoking evaluator authorization. Bind actual resolver material to its version digest to reject wrong-secret delivery under a valid key ID.

Combine identity binding and key lifecycle into this increment: terminal binding-scoped disable, validity checks, explicit certificate renewal and explicit new-key/new-snapshot/new-grant transitions. Serialize disables and reads with a consistent lock order. Existing low-level APIs remain host-only; there is no new public listener or remote trust configuration.

Sixteen new tests use real ephemeral TLS sockets and real encrypted snapshots. They cover same-CA foreign certificates, unverified identity objects, persisted/idempotent disable, material mismatch, exact time boundaries, grant/principal/key mismatch, malformed policy, immutable records, initialization failures, distinct registry paths, explicit certificate/key rotation and concurrent disable/read ordering. No self-review defect was found in the existing scoped verifier; this adds the previously pending integration boundary.

Global certificate revocation, global key disable across bindings, enrollment/issuer operations, KMS custody, lifecycle event auditing, backup anti-rollback and process isolation remain separate gates. Do not describe binding-scoped flags as global revocation. See the [contract](../contracts/identity-key-binding-v1.md) for exact APIs and limits.
