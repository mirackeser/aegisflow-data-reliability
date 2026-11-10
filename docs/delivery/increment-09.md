# Increment 09 — Certificate identity, exact resource grants and bounded HTTPS

Goal: establish the verified network boundary before attaching official MCP/A2A adapters, while keeping existing local coordination/evidence behavior stable.

## Delivered

- TLS 1.3 client/server contexts with explicit CA material, mandatory certificates, strict X.509 checks and SAN-only client hostname validation.
- Actual TLS peer leaf extraction; immutable exact leaf/incident/run grants with default denial before evidence lookup. Queue owner labels, roles and forwarded identity headers cannot establish a remote identity.
- Host-owned literal-IP egress with named SNI, server pin verification before proposal bytes, no DNS/proxy/redirect/fallback and explicit local-test loopback opt-in.
- Private read-only HTTPS review binding with closed proposal/verdict contracts, framing/body/header budgets, shared network deadline, fragmented-body-safe resource lifetime and sanitized errors.
- Temporary ECDSA certificate fixtures and real handshake/integration tests; an installed-wheel TLS check outside the checkout. No production server or external service was provisioned.
- Runtime plus optional test dependency auditing from pyproject.toml, with temporary requirements/cache cleanup; new audit-tool negative tests.
- Public repository visibility confirmed and licensing text updated without changing license terms. Checkout/setup-python actions are pinned to verified release commits (v7.0.1/v7.1.0, Node 24), with read-only workflow permissions and credential persistence disabled. SECURITY.md, ADR-0010, secure-review-v1, diagrams and backlog document implemented boundaries and deployment gates.

## Measured validation (2026-11-10)

253 application unit/integration/simulation tests plus 11 security/hygiene tests passed: 264 distinct methods. This includes 26 new certificate/transport tests and three new dependency-audit tests. Repeated runs, subtests and CI matrix executions are not counted again.

Coverage.py 7.17.2 measured 181/181 statements and 40/40 branch exits in the new security/integration packages (100% each). Existing coordination/workflow coverage remains 100%; the whole application combined report is approximately 97%, with legacy uncovered paths still visible. CI enforces package gates across Python 3.11/3.12/3.14. These are test coverage measurements, not model accuracy or security certification.

Tests include expired/unknown-CA/wrong-EKU/missing certificates, server SAN/name/pin mismatch, TLS downgrade, same-CA unknown clients, rotation, exact resource isolation, default denial, endpoint injection, missing/duplicate/invalid framing, redirects, encodings, byte/deadline bounds, truncation, cross-run verdicts and fragmented responses. Missing certificate extraction and sanitized configuration/network failures also use fault injection. Production code contains no custom certificate-chain validator.

The installed wheel passed existing license/catalog/data/evidence/queue checks and a real loopback mTLS acceptance/denial check without source-package imports or evidence mutation. All 10 packaged development scenarios remain matched; no model calls are made. Runtime and test dependency auditing reported no known vulnerabilities at scan time. Redacted local secret scanning and candidate/PDF hygiene are required before merge; CI additionally scans reachable Git history and historical PDF extraction.

## Scope and next gate

This is a private JSON review binding, not MCP/A2A interoperability or a deployed Zero Trust platform. Production hosting, issuer/workload identity, automatic revocation/rotation, audit/rate controls, token exchange and tenant boundaries remain deployment gates. The test-only HTTP server is not shipped as a production entry point. Keys/certificates are generated under temporary directories and not retained in Git.

Next: integrate one version-pinned official protocol adapter using normative generated models, then interoperability/negative-access validation over this boundary. Deployment/data-residency/identity provider decisions precede external provisioning. Model/provider routing, RAG/CAG, advisory LLM Judge, held-out evaluation and UI remain separately gated.
