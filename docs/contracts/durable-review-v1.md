# Durable review execution v1

This is a trusted local operator interface over the coordination-v1 proposal contract. It does not add network protocols or agent-supplied tool grants. See ADR-0009 for state, timing, limits and recovery guarantees.

## Operator flow

Use separate paths for the immutable evidence store and mutable execution queue. After recording a source/run and preparing a valid proposal:

```sh
python -m aegisflow_dr queue-init --queue work/reviews.db
python -m aegisflow_dr submit-review --queue work/reviews.db --db work/incidents.db --proposal work/proposal.json --key review-001
python -m aegisflow_dr work-once --queue work/reviews.db --db work/incidents.db --owner local-worker
python -m aegisflow_dr work-once --queue work/reviews.db --db work/incidents.db --owner local-worker
python -m aegisflow_dr read-job --queue work/reviews.db --job JOB_ID
```

Each work-once call reserves at most one eligible task. The first normally completes collect and the second Judge. IDLE means nothing is eligible now; a future retry may still be waiting. Read the job status and nested Judge verdict before interpreting success. submit-review optionally accepts --max-attempts (1–5); other retry settings are host API configuration. Repeated --key with an equivalent proposal returns the original verified job.

```sh
python -m aegisflow_dr cancel-job --queue work/reviews.db --job JOB_ID
python -m aegisflow_dr recover-job --queue work/reviews.db --job JOB_ID
```

Recovery handles expired reservations only; it does not bypass retry delays or revive terminal tasks. Reservation scans also recover eligible expired work. There is no daemon, polling automation or network listener.

If an evidence writer was interrupted during disk writes, stop writers and explicitly run `python -m aegisflow_dr store-recover --db work/incidents.db` before reopening the evidence store. Recovery checks the known schema and SQLite pages, preserves committed records and never creates a missing store. It does not repair checksum-invalid committed evidence.

## Results and API boundaries

CLI exit 0 means the operation applied or returned a valid current state (including IDLE or a recorded task failure); 1 means the worker lost its lease; 2 means rejected input, unsupported/corrupt state or an operational error. A job can be SUCCEEDED while its verdict is REJECT/ABSTAIN. Work-once never prints reservation tokens or raw exception messages.

Host APIs: workflow.schema.initialize(path), ReviewQueue.read/submit/reserve/context/complete/fail/renew/recover/cancel, enqueue_review and work_once. Use enqueue_review rather than accepting client-supplied metadata checksums: it loads and binds the evidence first. Direct queue mutation APIs are for trusted host code, not exposed as agent tools. A lease is an opaque in-process handle. Renew requires a still-valid reservation and is bounded to three calls per attempt.

Public job metadata includes job/request identity, version fingerprint, normalized proposal/retry policy, bounded task states/results, update time and immutable event summaries. Internal event snapshots contain hashed lease tokens; raw tokens are never stored. The queue file remains private and unencrypted. Read operations require a writable queue file for SQLite crash-journal recovery; they do not alter application history.

Historical jobs remain readable independently of evidence availability. New submissions and worker tasks require verified evidence. If evidence disappears or changes between submission and execution, execution fails closed. Metadata hashes and owner labels do not provide authenticated provenance or cross-tenant authorization.
