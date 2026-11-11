# Increment 13 — Repository review, advisory contracts and agent visibility

Delivered: source/security-boundary review; dependency and repository hygiene scans; provider-neutral offline advisory metadata/response schemas; exact request/evidence binding; deterministic Judge revalidation; installed-package check; and a rendered agent connection/state map with current CLI snapshot and future live-observer requirements.

Measured locally on 2026-11-11: 328 application tests plus 13 security/hygiene tests passed, **341 distinct methods**, including 14 new advisory tests. New advisory code covers 78/78 statements and 14/14 branch exits. Existing critical coverage gates remain green; benchmark/public fixture agreement remains 10/10 development and 8/8 validation with zero model calls.

Cases include contradictory assessments, forged/partial citations, cross-session/stale responses, model abstention, unavailable/changed records, unverified initialization, forbidden authority/confidence/rationale fields, invalid model/prompt metadata, malformed/oversized/duplicate/nonfinite JSON, reference uniqueness and unchanged evidence bytes. Installed checks run outside checkout. Dependency audit reported no known vulnerabilities; candidate/history/PDF security checks remain enforced by CI.

The advisory request is metadata-only, not a complete prompt or provider adapter. No model call, budget accounting, calibrated confidence, remote authentication or execution authority is claimed. The map describes A26/A27 capabilities and queue snapshots; it is not a live UI. Other catalog roles remain planned. No persisted workflow fingerprints, evidence schema or original architecture archive is changed.

Next: bounded evidence context/redaction and prompt assembly, provider-neutral usage/timeout/cost admission and predeclared acceptance/sealed-evaluation rules before model activation. Operator-facing live graph follows authenticated observer/API and event/heartbeat freshness requirements.
