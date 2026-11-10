# Private secure review binding v1

This host integration API carries the existing proposal-v1 and verdict-v1 contracts over authenticated HTTPS. It is not an MCP/A2A wire schema and does not start a production HTTP service. See ADR-0010 for threat boundaries and requirements.

## Configuration and use

The application host constructs TLSFiles(ca_file, certificate_file, private_key_file), client_context/server_context, Grant(peer_sha256, incident_id, run_id), AccessPolicy(frozenset_of_grants) and EgressPolicy(hostname, port, literal_address, server_sha256). Configuration belongs to trusted host code, never proposal JSON. TLSFiles expects Path objects and existing readable files. POSIX keys require owner-only permissions; encrypted keys need a future approved secret-provider integration and currently reject without a prompt.

The client calls review_https(proposal_bytes, endpoint=egress_policy, material=tls_files, timeout=5.0). The default private path is /review. It connects to the literal approved IP with the named service as SNI and verifies the server leaf pin before transmitting the proposal. Loopback requires explicit host allow_loopback=True for local tests; it is denied by default. No DNS resolution or URL-based fallback occurs.

A TLS-aware host routes the private POST operation to handle_review(actual_ssl_socket, proposal_bytes, investigation_runs, access_policy), returning the encoded verdict with application/json and a single exact Content-Length. The gate accepts only an actual verified server-side mutual-TLS socket. Do not turn forwarded headers into a principal or expose queue/tool-admin operations through this handler. Incoming bodies must be bounded by the production host before reading; the contract parser also rejects values over 16,384 bytes.

Only a verified client leaf explicitly granted the exact incident/run can trigger evidence reads. Empty policy denies all. Host policy updates can overlap old/new pins for rotation, then remove old pins. Pinning complements CA verification; it does not replace it. Role catalog IDs and queue lease tokens remain unrelated to certificate identity.

## Results and errors

The result is a validated verdict dictionary. ACCEPT means the scoped assessment/evidence agree, REJECT identifies contradiction/bad citations, and ABSTAIN identifies insufficient/unavailable evidence. The response run must equal the requested run. Neither certificate identity nor TLS implies model truth.

SecurityError identifies sanitized TLS/configuration/authorization rejection in host APIs; TransportError identifies a rejected HTTPS exchange. Malformed proposal JSON remains ContractError before connection. Do not log raw payloads, private-key paths or underlying exceptions. The binding does not define public error bodies or an authenticated audit store; production hosting must map sanitized errors and implement rate/audit controls.

No persistent network session, cookie store, proxy, redirect or automatic retry is used. Response framing must have status 200, application/json, one numeric bounded Content-Length, no Transfer-Encoding or Content-Encoding, a <=16,384-byte verdict and <=32,768-byte total receive budget. Shared network deadlines remain bounded to ten seconds. All resources close on rejection and success.

## Operational limits

There is no production listener, certificate authority, OAuth/JWT exchange, SPIFFE integration, automatic revocation distribution, distributed tenant registry or full remote agent runtime. Python hosts, local configuration and OpenSSL remain trusted/maintained deployment components. Tests use temporary leaf/root keys and loopback only. Existing local CLI and durable queue behavior are unchanged; connecting authenticated external queue mutation remains a future design decision.
