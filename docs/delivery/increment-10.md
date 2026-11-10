# Increment 10 — Official A2A stateless review interoperability

Goal: attach the first normative protocol adapter to the verified certificate/resource boundary without changing retained evidence or local workflow behavior.

## Delivered

- Optional pinned official `a2a-sdk==1.3.0` integration using generated A2A 1.0 protobuf messages, HTTP+JSON RestTransport and one stateless synchronous review skill. Base installation is SDK-independent.
- Strict codec/profile and business-schema validation before SDK lenient decoding: exact fields/roles/context, one JSON data part, duplicate/unknown/alias/nonfinite rejection, version/path and byte bounds.
- Isolated HTTPX transport over the existing bounded mTLS channel, fixed host-owned routing, exact leaf/resource authorization, no DNS/proxy/redirect/fallback, sanitized errors and bounded async collection/cancellation behavior.
- Host callback and descriptive Agent Card, with no production listener, public discovery, remote Tasks, files, streaming, push, tenant metadata or tool administration.
- Real SDK/TLS interoperability and negative tests, installed-wheel A2A check, CI matrix extension and manifest-derived auditing of every optional dependency group.
- ADR-0011, profile/sequence/flow diagrams, security/licensing documentation and current backlog. Original architecture/PDF, persisted schemas/fingerprints and old repository are preserved.

## Measured validation (2026-11-11)

276 application unit/integration/simulation methods and 13 security/hygiene methods passed: **289 distinct tests**. This increment adds 23 A2A/transport tests and two dependency-audit tests. Repeated runs, subtests, installed smoke checks and CI matrix executions are not counted again.

Coverage.py 7.17.2 reports 330/330 statements and 58/58 branch exits in security/integration (100% each). Existing coordination and workflow gates remain 100%. Whole-application combined coverage rounds to 97% (2,117 statements, 676 branch exits; 40 statements and 32 branch exits remain uncovered in older modules). These are test coverage measurements, not security certification or model accuracy.

Cases include native generated-model round trips, direct official SDK calls, real mTLS acceptance, false assessments/citations, default denial before evidence reads, cross-context isolation, no DNS resolution, unsupported versions/operations, response validation before lenient SDK parsing, malformed/oversized messages, forbidden metadata/files/URLs, cancellation before connection, shared deadlines and sanitized failures. Existing TLS, queue recovery, schema and replay tests remain green.

The built wheel is checked outside the source checkout for existing license/catalog/data/evidence/queue behavior, real mTLS and official A2A acceptance/Judge rejection/default denial, with evidence bytes unchanged. Dependency auditing includes runtime, SDK and test profiles and reports no known vulnerabilities at scan time. Redacted candidate secret/file hygiene checks run before publishing; CI additionally scans full fetched history and extracted historical PDF text.

## Scope and next step

This is tested A2A 1.0 stateless-profile interoperability, not a deployed or certified general A2A task server. Local queue execution and deterministic Judge remain unchanged. Ten labeled development scenarios remain matched with zero model calls; no held-out/model accuracy is claimed.

Next: one official MCP read-only adapter behind existing tool grants, followed by production hosting/error/lifecycle and operational identity/audit/tenant gates before external deployment. Provider/model routing, RAG/CAG, advisory LLM Judge and held-out evaluation precede interface work. External issuer/provider/deployment choices need data-residency, cost and operational ownership decisions; no such provisioning is performed here.
