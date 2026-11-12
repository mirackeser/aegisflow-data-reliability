# Signed curation retention v1

`benchmark.signed_curation_store` extends the optional `curation` profile with a separate signed snapshot format. Legacy unsigned snapshots and APIs are unchanged; neither reader accepts the other format.

## Trusted inputs and API

`retain_signed_curation(path, development, candidate, annotations, envelopes, *, grants, policy_revision, now_ms)` recomputes the source manifest, checks two detached signatures under the supplied grants, and reconciles all labels before reserving a new file. It returns the SHA-256 digest of the canonical header. The host must keep that digest independently from the snapshot. `policy_revision` is a host-assigned ID, not an issuer signature or a globally ordered revision.

`read_signed_curation(path, *, expected_sha256, grants, policy_revision, now_ms)` requires the external digest, current grants, current revision and trusted clock on every read. It first bounds the database structure and payload sizes, checks the header digest, and matches retained policy bytes against the current externally supplied policy. It reconstructs the original signed result at retention time and compares the full header, then verifies the signatures again at current time. Reads before retention time, at/after signature expiry, with revoked grants or any changed grant/revision fail closed. Policy changes require deliberate re-review/re-retention into a new file; no silent migration or stale-policy fallback exists. Host freshness of grants, revision and clock remains a prerequisite.

## Persistent contract

The private local SQLite file contains exactly eight rows: `development`, `candidate`, `annotation_a`, `annotation_b`, `envelope_a`, `envelope_b`, `trust_policy`, `header`. Raw source, annotation and envelope bytes are preserved. `trust_policy` is canonical JSON with version `1`, revision and two ordered grant records: reviewer ID, public key hex, manifest hash, validity interval and revocation flag. It is evidence, never a source of runtime authority. No private key is persisted by these APIs.

The closed [header schema](signed-curation-header-v1.json) binds the format, exact retention time, hashes of all seven artifacts, manifest hash and original authenticated result hash. The returned result includes current authentication proofs and a `retention` record with snapshot hash, policy hash/revision and original retention time. It excludes raw source data and public-key records. Disagreements remain retained but export no quality labels.

Creation uses exclusive file reservation with mode 0600 and one transaction. Normal insert/update/delete mutations are rejected by triggers. Failed initialization may leave a reserved empty file; it is never automatically overwritten. Readers enforce the physical table definition, bounded row count and blob sizes before loading data, with SQLite limits and trusted schema disabled. Existing symlinks cannot be overwritten; reads follow symlinks and still require the external digest. Deployment hosts must control the parent directory. The shared reader/writer is used by both formats to keep these checks consistent.

```mermaid
sequenceDiagram
    participant H as Trusted host
    participant V as Signature and consensus verification
    participant S as Private local snapshot
    H->>V: Sources, annotations, envelopes, grants, policy revision, clock
    V->>V: Check manifest, distinct keys, scope, time, consensus
    V->>S: Transaction: exact evidence + policy + bound header
    V-->>H: External snapshot digest
    H->>S: Reopen with external digest and current authority
    S->>V: Bounded artifacts; stored policy grants no authority
    V->>V: Recompute original evidence and recheck current signatures
    V-->>H: Current verified result or rejection
```

## Security and evaluation limits

This is local durable integrity and provenance, not encrypted or access-separated enterprise storage. Sources and labels are plaintext; public keys and reviewer IDs are also retained. Use only synthetic fixtures until storage confidentiality and authorization are implemented. OS owners can replace files and remove triggers; the externally controlled digest and cryptographic checks detect substitution under the documented trust boundary. The format is not a sandbox for malicious native SQLite inputs, independent timestamp service, organizational identity enrollment or proof of reviewer independence. It is not an archival label-export API after expiry. Authentication never approves sampling, provenance, model quality, deployment or remediation.

Next: encrypted storage and managed key delivery, curator/evaluator access separation, organizational enrollment/revocation, independent sealed-data governance and live model acceptance. Historical evidence must not be promoted to current authority when these services are added.
