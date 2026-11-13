# ADR-0039 — Record intent before policy mutation and publish exact successors

Status: accepted for local trusted-host orchestration.

Increment 38 requires an external current checkpoint but leaves publication/recovery to the host. Add a separate control store and managed entry points. Commit an exact intended disable before changing policy; block evaluations until the exact successor is verified and published. Recovery may finish the recorded transition from the previous state or recognize it already committed, but never adopt an arbitrary policy tip.

Reuse key-policy event construction to avoid mismatched successor hashes. Preserve the independent policy chain and existing identity/access/evidence checks. Serialize control, policy, binding and grant locks in that order. Unknown keys reject before persistent intent to avoid unnecessarily blocking service. Concurrent recovery is idempotent.

Fifteen new tests cover normal publication, scope/state corruption, unknown keys, intent/publication write failures, old restores, divergent successors, concurrent recovery and read/disable ordering. A subprocess exits after actual policy commit and before control publication; restart verifies pending state, blocked reads and exact recovery without a duplicate event. Installed distribution verification covers publication and idempotent recovery.

A local private control file is not a privileged-owner or distributed anti-rollback guarantee. Independent custody of control state remains required. Document the joint-restore boundary and absence of a provisioned external service. No key material or enterprise data is added. See the [contract](../contracts/checkpoint-control-v1.md).
