# Repository hygiene and credential response

Only project source, reviewed documentation and synthetic fixtures belong in Git. Never commit live API keys, credentials, sessions, environment-specific configuration, raw enterprise data, logs, research databases or local build/install output. Use runtime secret injection or the deployment platform's secret store when model providers are introduced. No provider key is currently required by this deterministic baseline.

Run Gitleaks with redaction enabled before publishing. CI fetches full history, scans all fetched Git refs, checks tracked-file hygiene and scans extracted text from reachable historical PDF blobs. Findings must not be printed as raw credential values. The pinned Gitleaks container runs with network disabled and read-only source mounts; it does not need a provider token or external scan account. Checkout does not persist its temporary authentication credential.

If a live secret is found: stop using it, revoke/rotate at the issuing provider, inspect usage, replace it with runtime configuration and rerun redacted scans. Removing a current file does not remove past exposure. Any history rewrite requires a separate coordinated decision; never silently rewrite shared history or delete the architecture archive to hide evidence.

Cleanup scope: redundant chat-interface and print HTML were removed from the current repository; internal conversation/message identifiers were removed from shareable provenance and the PDF appendix; SVG renderer IDs were normalized. Original architecture text, six Mermaid sources, readable diagrams and PDF remain. The original conversation and Git history are preserved. These identifiers were not provider credentials.

Limits: pattern-based scans do not prove that every possible credential is absent. The checks do not inspect account-side secret settings, unreachable Git objects, external repositories or previously downloaded copies. Historical renderer metadata remains recoverable in prior commits; no credential was detected that required rotation or a history rewrite. Legitimate AI product terminology and original design content are retained.

Tool reference: https://github.com/gitleaks/gitleaks


Runtime dependencies are now audited with pinned pip-audit 2.10.1: `python -m pip_audit . --strict --progress-spinner off`. The audit resolves the declared runtime dependency graph and queries the public advisory service; it does not scan project behavior or provisioned credentials, and a clean result is limited to known advisories at scan time. CI fails when collection/auditing fails or a known vulnerability is found. The JSON Schema runtime validator is pinned in pyproject.toml. Transitive dependencies are resolved by pip; a cross-platform lockfile and full build-tool supply-chain hardening remain future delivery work.
