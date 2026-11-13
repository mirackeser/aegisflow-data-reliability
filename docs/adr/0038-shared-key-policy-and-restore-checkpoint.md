# ADR-0038 — Share key disable decisions and anchor their lifecycle externally

Status: accepted for local trusted-host integration.

Increment 37 disables individual identity/key bindings. Introduce a catalog-backed shared key policy so one terminal disable affects every binding routed through it. Preserve an append-only hash-linked lifecycle and require an externally retained current checkpoint on every operation. Validate the entire small history before key resolution; hold the policy lock across peer evaluation so concurrent disabling has defined ordering.

This combines shared key control, lifecycle records and old-backup rejection. Do not claim a hash chain alone prevents rollback. The external checkpoint must be monotonic and separately governed; database/checkpoint publication is not atomic, and mismatches block until explicit recovery. The API never reconstructs trusted authority from a restored file. Independent copied policies remain outside the scope.

General pre-change qualification: 674 application methods plus security/hygiene checks and whole-application coverage passed. Fourteen new tests cover actual TLS/encrypted reads across bindings, unrelated-key behavior, restored databases/current checkpoints, malformed/stale chains, alias rejection, no-overwrite/mutation controls, event-write failure, corrupt-history resource bounds, wrong key material and concurrent disable/read ordering. Installed verification repeats lifecycle persistence, idempotence and restored-old-file rejection. Review documented publication/crash and copied-policy limits instead of asserting distributed rollback protection.

Next: trusted checkpoint publication/reconciliation and restore exercises, issuer/key-service operations and ingress audit. Existing public model/enterprise data activation gates remain unchanged. See [contract](../contracts/shared-key-policy-v1.md).
