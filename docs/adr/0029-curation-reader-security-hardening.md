# ADR-0029: Bound curation reads before trusting storage schema

Status: Accepted. PR and post-merge CI evidence records delivery.

## Reproduced finding

A local curation database whose `artifacts` table was renamed and replaced by a view returning the same bytes was accepted by the previous reader. Hashes bound the returned content but did not constrain the database schema executing the read. The metadata query also materialized every row before checking for exactly five artifacts, and names were not covered by the application payload-length check. This is a local schema/resource-hardening gap for replaced or corrupted snapshot files; no remote intrusion, arbitrary-code execution or production breach was demonstrated.

## Change

Before reading artifacts require the exact supported physical table SQL, rejecting views, generated columns and altered definitions. Bound the metadata SELECT to six rows: five valid rows or enough to reject any excess. Apply connection-local SQLite length/row, SQL-text and expression-depth limits before schema use, and disable trusted schema behavior for reads. Preserve the read-only transaction, external digest, exact artifact names/types, payload limits and full curation recomputation. No automatic migration of unknown schemas is permitted.

The limits follow SQLite's [runtime limit guidance](https://www.sqlite.org/limits.html). This is bounded local SQLite use, not a complete sandbox for arbitrarily malicious native database files. Trusted host paths, maintained SQLite/Python, authenticated delivery and separate process/resource isolation remain relevant before accepting externally uploaded databases. Application read limits do not limit disk size, CPU spent in all SQLite startup paths or privileged-owner access.

## Adversarial validation and self-review

Add regression cases for view substitution, generated-expression schema, oversized metadata names, excess rows and byte-preserving legitimate reads. Test duplicate-key, non-finite, deeply nested, oversized, invalid UTF-8 and instruction-bearing advisory payloads, plus model-identity control characters. The identity checks already rejected the tested strings: no model-identity defect was reproduced, so that contract was not changed.

Existing complete suites exercise tool grants/budgets, evidence substitution, replay/correlation, unknown usage holds, invalid certificates/pins/identities and bounded transport. Current local LLM contracts do not constitute live prompt-injection red-teaming; no model is connected. Test execution is not proof of absence of all vulnerabilities. Preserve documented gaps in authenticated curator/operator identity, encryption/access separation, managed issuer/secrets operations, remote tenant API/rate limits, production denial-of-service and deployment-specific testing.

This increment prioritizes the reproduced storage issue before expanding curation authority. Next: authenticated curation identity and encrypted, access-separated storage; actual provider acceptance remains independently measured and gated.
