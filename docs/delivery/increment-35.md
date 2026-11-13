# Increment 35 — Scoped evaluator key access

A trusted-host evaluator gateway now requires an immutable EvaluationAccess grant binding principal, exact encrypted snapshot digest, key ID, policy revision and validity interval. Curator/unknown roles, revoked/expired grants and any mismatched scope fail before the key resolver is called. Resolver failures are sanitized; existing cryptographic and current signing-policy checks remain mandatory. No secret is returned by the gateway.

Six new methods cover actual encrypted snapshot reads, scope/role denial before resolution, time boundaries, malformed grants, wrong keys, expired signatures and sanitized resolver failure. Full regression, 100% statement/branch coverage, installed package checks and security/CI gates apply.

Trust boundary: principal, role and grant come from the trusted host, not client/model claims. This local API does not authenticate a human or provide an OS boundary against a host that already possesses the key. The key resolver must apply current external key policy. Existing low-level APIs remain host-only. Managed identity, durable authorization policy, key lifecycle and process/access separation are the next gate; real enterprise data remains deferred. This is the first evaluator authorization slice, not completed enterprise role separation.
