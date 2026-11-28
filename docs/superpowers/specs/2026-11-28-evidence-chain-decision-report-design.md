# Design: evidence chain, human decision and incident report (step 3 of the new direction)

Goal: an incident ends in a verifiable case file. A reviewer can see exactly which data, which evidence, which agent run and
which human decision a conclusion rests on. Anyone can check that none of it was changed afterwards, and print it as a
report.

## Evidence chain

A hash chain of links, built server-side for one incident from records that already exist. Each link is
`{"kind", "digest", "at", "summary", "prev", "link_sha256"}`. `link_sha256` is the SHA-256 of the canonical JSON of the
link without itself, and `prev` is the previous link's `link_sha256` (`null` for the first link). The links, in order:

1. **baseline:** the plant baseline digest and the number of commissioning readings.
2. **evidence:** the frozen evidence window: its SHA-256, bounds, `as_of`, the onset method and the statistic.
3. **probes:** the probe-loop record on that evidence: `trace_sha256`, and the evidence reference that must equal
   the run's A24 evidence.
4. **agent_run:** the sealed run record: `trace_sha256`, status, agents completed, and Judge accepted/advisory/rejected.
5. **decision:** the human decision record, when one exists.

**Verification** recomputes every link from its source and checks the chain:

- the evidence bytes hash to the evidence digest;
- the probe record's trace digest is valid and its reference equals the run's A24 evidence reference;
- the run record passes `verify_record`;
- the decision record's digest matches;
- every `prev` and `link_sha256` matches.

The result is one status per link (`verified`, `mismatch` or `missing`, the last for a step that has not happened). A
chain is complete only when all five links are verified. The digest is an integrity check and anyone can recompute it,
so it is not a signature.

## Human decision (A33 records, a person decides)

On the Incident page, after the agent run has finished, a reviewer records one decision for the incident:

- `accepted`: accept one supported candidate as the working explanation.
- `rejected`: none of the candidates is accepted.
- `more_evidence`: keep the incident open for more evidence.

The record also holds the reviewer name (1–60 printable characters), a note (0–500 characters), the run id and the
evidence digest it applies to. A decision can be replaced, and every version is kept. The latest one is the chain's
decision link.

`accepted` needs a candidate that the probe loop supports on the frozen evidence. The server refuses anything else,
because a person cannot accept what the evidence does not support. Nothing is executed: the decision is recorded, never
acted on.

Decisions are stored in the state folder (`incident-decisions.json`, atomic write, mode 0600, a digest per record). The
store keeps at most 200 incidents and 20 versions each. They are keyed by the evidence digest, so a plant reset never
attaches an old decision to a new incident.

## Incident report

`/report?incident=INC-0001` is a print-ready A4 report in the page language. It contains:

- the summary and a simulation notice;
- the timeline, the onset chart and the findings;
- the candidate explanations with measured probe values and fixed thresholds;
- the advisory model suggestion, the Judge counts and the human decision;
- the full evidence chain with its verification;
- the limits.

"Save as PDF" uses the browser's print dialog. This keeps every character (Turkish included), needs no new dependency
and costs USD 0. The chain head and the case file's content digest (canonical JSON of the chain, its checks and every decision
version, computed by the server) are printed in the footer.

## Constraints

- Every number comes from the API, and wording never claims a root cause.
- EN/TR, keyboard operable, works at 375 px, and the report has a clean print layout.
- 100% branch coverage. No new dependencies.
