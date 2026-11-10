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

The local two-task dependency/reservation/retry/cancellation slice is implemented in increment 08. Certificate/resource/egress foundations are implemented in increment 09. Increment 10 adds official A2A 1.0 stateless review interoperability over that boundary. Next add one official MCP read-only adapter behind the existing tool gateway, then production protocol hosting/operations and model-provider/per-specialist contracts, semantic evidence verification, independent model evaluation and authenticated API/access boundaries. Do not advance to the web interface merely because the deterministic demo passes its development suite.


## Multi-agent integration sequence

Increment 07 adds local task/proposal/verdict/receipt schemas, controlled capability routing, a bounded DAG and an independent deterministic Judge on retained runs (ADR-0008). Increment 08 implements local reservation/retry/cancellation/recovery for the A26→A27 review in a separate queue with fenced commits and bounded backoff. The queue remains trusted-host only; external idempotency, outbox/inbox, retention/quotas and distributed operations remain future gates.


Increment 09 implements mutual TLS, exact certificate/resource grants and bounded pinned-IP HTTPS for a private read-only review binding. Increment 10 adds a version-pinned official SDK adapter and generated models, strict A2A 1.0 HTTP+JSON stateless consultation and actual SDK/TLS tests. It supplies a host callback, not a production HTTP server, remote Task service or public discovery. Source/run/queue schemas and original architecture/PDF are unchanged. See ADR-0010/0011 and the increment delivery records.


Next implement one version-pinned official MCP read-only adapter with exact tool grants and interoperability/negative-access tests. Production HTTP framing/error mapping, workload issuer/secrets delivery, revocation/rotation, authenticated audit/rate controls, tenant isolation and task lifecycle remain deployment gates. Model routing, retrieval/cache and independent held-out evaluation follow their own contracts. Agree data residency, cost and operational ownership before external provisioning. Keep interface work deferred; do not equate a tested stateless profile with a deployed Zero Trust platform.
