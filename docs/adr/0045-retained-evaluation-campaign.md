# ADR-0045: Retained public evaluation campaigns

Status: Accepted for the public synthetic trusted-host profile.

## Problem and decision

Individual investigation, dispatch, signed gateway, accounting and quality components were tested separately. They did not provide one retained multi-case result joining raw model predictions, independently accepted advice, cumulative expenditure and latency. This increment integrates those boundaries as a single campaign rather than adding another isolated control.

`run_campaign` freezes the existing public suite and statistical protocol before dispatch. Each case executes the real source/investigation/retention path, prepares minimized evidence and binds a fresh operation. A trusted factory receives only the prepared evidence and operation, never case identifiers, family, split or labels. Its adapter must defer all I/O until the existing one-shot dispatcher admits the call. Factories are trusted Python, not isolated plugins.

Each case receives only the remaining aggregate token/cost allowance. Known charges and unresolved holds reduce that allowance. Unknown usage stops subsequent cases; skipped cases remain in the denominator as errors. This profile deliberately uses one candidate and one attempt per case. Existing multi-model routing remains available separately; this campaign cannot search for a better Judge verdict by retrying a case.

## Retention and reporting

An exclusive 0700 directory owns 0600 files. Completed case observations and existing SQLite ledgers are committed before proceeding. The manifest is written last and synchronized; only a completed manifest permits historical reading. Existing directories, including interrupted ones, are never resumed or overwritten. Actual process-exit and concurrent-start tests verify this boundary. An interrupted campaign requires explicit operator review of its retained ledgers, not an automatic restart under a new identity.

The separately retained manifest digest binds exact artifacts. Readback validates file digests, rejects missing/extra/symlinked artifacts and recomputes the report from observations. It verifies the fixed public protocol, so editing provenance flags cannot promote these fixtures into a sealed evaluation. Each artifact is limited to 16 MB and total readback to 64 MB. The directory and digest require trusted custody: this is neither a signature nor protection against a host replacing both records and external digest. Filesystem parent directories and concurrent writers must remain host controlled. Historical reading does not refresh model authorization or rerun a Judge against changed evidence.

Raw predictions and accepted advice are distinct outputs. A signed wrong assertion remains a wrong assertion even when the deterministic Judge rejects it. Malformed/uncorrelated/late/failed responses become errors, abstentions retain their denominator, and rejected claims block quality acceptance. Closed response projections are retained; arbitrary model text, exception contents, credentials and private keys are not copied into reports.

## Scope and consequences

The built-in fixture derives answers from diagnostic summaries without a model or external network. Integration/installed checks additionally exercise all 18 public cases through an ephemeral signed loopback mTLS gateway. Its sample token counts and nano-dollar rates are test values, not measured provider usage. An operational PASS means this campaign's cases were verified within its configured latency/budget limits. The independent statistical quality decision remains BLOCK because these 18 public, inspected cases do not meet the sealed provenance and sample-support requirements.

The current model revision hash is a trusted host declaration. Exact vendor identity, tokenizer/framing, all billable categories, independent sealed evaluation, credential delivery, data region/retention and spend approval remain provider activation prerequisites. No CLI option enables a live provider. Campaign budgets are scoped to one directory, not a cross-process or cross-campaign organization quota. A new campaign is a new host-authorized scope; copied/recreated directories do not provide global replay protection. Socket limits come from the gateway; arbitrary host Python and local preparation are not hard-preempted. Latency covers local investigation, preparation and dispatch per case; it is not a production SLO measurement.

Next delivery should integrate one selected provider and its usage qualification with the evaluation entry point, rather than expanding the public fixture suite into a claimed model benchmark. Independent held-out execution needs a separate protected runner and registered protocol, not an override to the public campaign.
