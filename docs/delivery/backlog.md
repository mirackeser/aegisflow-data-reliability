# Delivery backlog

Work in short, acceptance-driven increments. Estimate the next item after reviewing the previous increment; the architectural 16-week roadmap is a target, not a delivery guarantee.

1. **DR-001 — Deterministic diagnostic baseline:** implemented in increment 01. Reproducible synthetic orders; schema/null/duplicate injection; evidence-linked checks; bounded input; stable CLI outcomes; automated regression coverage.
2. **DR-002 — Real batch transformations and lineage:** implemented in increment 02. Introduce an explicit source/staging/mart fixture and lineage edges; identify downstream impact without pretending that a failing check proves its root cause.
3. **DR-003 — Tool contracts and enforcement:** implemented in increment 03 for local trusted-host sessions; enterprise identity, hard isolation and durable quotas remain planned. Typed requests/results, allowed tool catalog, read-only policy, time/call budgets and negative authorization tests.
4. **DR-004 — Incident and evidence persistence:** source diagnosis implemented in increment 04; versioned runs and exact batch artifacts implemented in increment 06. Model-claim verification and enterprise storage remain planned. Incident lifecycle, immutable snapshots, claim/evidence junctions, reproducible replay and version checks.
5. **DR-005 — Bounded orchestration:** deterministic baseline implemented in increment 05; retained source evidence, one policy session, conditional tool routing and development regressions are working. Durable workflow/batch evidence is implemented in increment 06. Contract/TAG/local verification slices are implemented in increment 07; the two-task local durable reservation/retry/cancellation path is implemented in increment 08; remote delivery and model planning remain planned. Implement deterministic baseline first, then optional model planning behind the same enforcement boundary; track each specialist's tested capability separately.
6. **DR-006 — Investigation interface:** planned. Build the first premium, accessible investigation workspace on working API contracts.
7. **DR-007 — Research evaluation:** planned. Separate development and held-out failure families; compare B0-B4 with controlled tools and budgets.

## Infrastructure gates before interface work

The local two-task dependency/reservation/retry/cancellation slice is implemented in increment 08. Certificate/resource/egress foundations are implemented in increment 09. Next integrate one version-pinned official protocol adapter before remote deployment, then add model-provider and per-specialist contracts, semantic evidence verification, independent model evaluation and authenticated API/access boundaries. Do not advance to the web interface merely because the deterministic demo passes its development suite.


## Multi-agent integration sequence

Increment 07 adds local task/proposal/verdict/receipt schemas, controlled capability routing, a bounded DAG and an independent deterministic Judge on retained runs (ADR-0008). Increment 08 implements the bounded local reservation/retry/cancellation/recovery gate for the A26→A27 review. Follow with authenticated identity and one protocol adapter, then provider/model, retrieval/cache and independent held-out evaluation gates. Choose external providers and deployment only after data-residency/cost constraints are agreed. Keep the interface deferred.


Increment 08 implements a separate durable queue for the A26→A27 retained-run review, bounded reservations/renewals, fenced result commits, retry/backoff, cancellation and crash recovery. Next: workload identity/authorization and one protocol adapter, with negative certificate/token/egress tests before remote enablement. The current queue is local and trusted-host only; external idempotency, outbox/inbox, retention/quotas and distributed operations remain future gates. Model services and interface work remain deferred.


Increment 09 implements mutual TLS, exact certificate/resource grants and bounded pinned-IP HTTPS for the private read-only review binding. Production identity/issuer deployment, revocation/audit/rate controls, tenant isolation and official MCP/A2A interoperability remain gated. Next implement a version-pinned adapter from official generated models and test interoperability over the verified boundary. Do not call the private JSON binding A2A/MCP compatible or equate it with a deployed Zero Trust system.
