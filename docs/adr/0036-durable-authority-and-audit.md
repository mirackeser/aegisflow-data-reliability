# ADR-0036 — Couple current evaluator authority with decision audit

Status: accepted for local trusted-host operation.

The previous access gateway accepted an in-memory host grant. Deliver two related capabilities together: durable authority with terminal revocation, and transactional access-decision audit. Bind one grant to an external digest, prevent normal grant mutation, and serialize reads with revocation. Reuse the existing evaluator gateway and encrypted/signed validators rather than duplicating their authorization logic.

Write STARTED before key resolution, then a fixed outcome and commit before returning results. Denial is committed before its sanitized exception is raised. Final audit failure rolls back and suppresses label delivery. Independent crash auditing, privileged-owner tamper resistance and identity authentication remain explicit external boundaries; do not advertise these transactional records as proof that every attempted access was durably captured.

Twelve tests cover actual encrypted reads, persisted revocation and repetition, wrong bindings/missing/corrupt databases, normal mutation protection, malformed grants/state, bounded cursor reads, first/final audit failure, key-resolution sanitization, initialization failure and two-thread read/revocation ordering. Installed checks repeat valid access, revoke, deny and verify ordered audit. The increment combines related work without relaxing full regression, coverage, package or security gates.
