# Security policy

This repository currently provides a research baseline, not a supported production service. Security tests do not constitute a security certification. Review the documented trust boundaries and deployment gates before integrating it with real enterprise data or external agents.

Report suspected vulnerabilities privately through GitHub's Security tab when private reporting is available. If it is unavailable, request a private reporting channel without posting exploit details, credentials or sensitive data in a public issue. Never include real API keys, certificates, private keys, customer datasets or unredacted logs in reports.

Project dependencies and secret/file hygiene are checked in CI. Runtime and all optional profile dependency audits use the project manifest; full fetched Git history and extracted historical PDF text are scanned for secrets. See docs/security/repository-hygiene.md and the accepted architecture decisions for the exact scope and remaining limits.

The optional A2A 1.0 stateless review profile reuses mutual TLS, pinned egress and exact leaf/incident/run grants. Caller role labels and Agent Cards do not establish authorization. Its host callback requires the actual verified TLS socket and does not supply a production HTTP server, public discovery endpoint or remote task administration. See docs/contracts/a2a-review-v1.md for the deliberately restricted surface and deployment gates.

The optional MCP profile is a trusted in-process integration with host-owned immutable grants and budgets, not remote identity enforcement. Do not publish its SDK Server over HTTP/stdio to untrusted callers without a separate admission/authentication/transport design. Tool annotations and client metadata are not authorization. No provider credentials, sampling, external resources or implicit server telemetry middleware are enabled. See docs/contracts/mcp-local-tools-v1.md.
