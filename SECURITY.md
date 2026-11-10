# Security policy

This repository currently provides a research baseline, not a supported production service. Security tests do not constitute a security certification. Review the documented trust boundaries and deployment gates before integrating it with real enterprise data or external agents.

Report suspected vulnerabilities privately through GitHub's Security tab when private reporting is available. If it is unavailable, request a private reporting channel without posting exploit details, credentials or sensitive data in a public issue. Never include real API keys, certificates, private keys, customer datasets or unredacted logs in reports.

Project dependencies and secret/file hygiene are checked in CI. Runtime and test dependency audits use the project manifest; full fetched Git history and extracted historical PDF text are scanned for secrets. See docs/security/repository-hygiene.md and the accepted architecture decisions for the exact scope and remaining limits.
