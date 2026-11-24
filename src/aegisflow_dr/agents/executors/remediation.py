# SPDX-License-Identifier: Apache-2.0
"""A29-A32: remediation proposals only. Nothing here changes data, and nothing proposed is executed.

A29 drafts options for Judge-accepted findings and A30 a patch text, both through the local model; their output is
advisory and is recorded as ``llm_suggestion`` evidence and proposals with ``executed: false``. A31 and A32 cannot
validate a proposal without a sandbox writer or a backfill target, which this deployment does not have, so they
return NEEDS_EVIDENCE with that reason instead of pretending to validate.
"""
from ...profiling import profile_csv
from ...pipeline import diagnose_csv
from ..prompts import VOCABULARY, patch_schema, remediation_schema
from ._base import MAX_LIST, NeedsEvidence, executor
from .orchestration import SPECIALISTS, triage

FINDING_PARAMS = ("check", "column", "count", "status", "direction", "findings", "records", "changed", "stale",
                  "shifted", "passed", "mechanism", "verdict")
# Only the specialists' measurements are remediation findings; control, reasoning, policy and governance claims
# (for example A34's review) are not.


def accepted_findings(run):
    """(judge reference, findings): Judge-accepted claims of specialists (A07-A22), reduced to whitelisted parameters
    whose text values are known names or column names (the A34 rule)."""
    ref, verdict = run.prior_evidence("A27", "judge_verdict")
    header = run.vocabulary()[0]
    findings = []
    for item in (verdict or {"verdicts": []})["verdicts"]:
        result = run.prior(item["agent"])
        if (item["verdict"] != "accepted" or item["agent"] not in SPECIALISTS or len(findings) == MAX_LIST
                or result is None or not 0 <= item["claim"] < len(result["claims"])):
            continue
        claim = result["claims"][item["claim"]]
        params = {k: v for k, v in claim["params"].items() if k in FINDING_PARAMS and type(v) is not list
                  and (type(v) is not str or v in VOCABULARY or v in header)}
        findings.append({"id": "f%d" % (len(findings) + 1), "agent": item["agent"], "text_key": claim["text_key"],
                         **params})
    return ref, findings


@executor("A29")
def remediation_strategy_planner(run):
    judge_ref, findings = accepted_findings(run)
    if not findings:
        raise NeedsEvidence("NO_ACCEPTED_FINDINGS")
    ids = [f["id"] for f in findings]
    data, suggestion = run.ask("a29", {"findings": findings}, remediation_schema(ids), findings=findings)
    options = data["options"]
    run.claim("a29.options", {"options": len(options), "risks": [o["risk"] for o in options],
                              "addresses": sorted({i for o in options for i in o["addresses"]}, key=ids.index)},
              suggestion, judge_ref)
    for number, option in enumerate(options, 1):
        run.propose("a29.option", {"option": "opt%d" % number, "risk": option["risk"], "addresses": option["addresses"]})
    run.advise(" ".join("opt%d (%s risk): %s" % (n, o["risk"], o["title"]) for n, o in enumerate(options, 1)))


@executor("A30")
def patch_proposal(run):
    options_ref, suggestion = run.prior_evidence("A29", "llm_suggestion")
    if suggestion is None:
        raise NeedsEvidence("NO_REMEDIATION_OPTIONS")
    if not triage(run.ctx)["order_extract"]:
        raise NeedsEvidence("NOT_ORDER_EXTRACT")
    options = [{"id": "opt%d" % n, "risk": o["risk"], "addresses": o["addresses"], "option_title": o["title"],
                "option_rollback": o["rollback"]} for n, o in enumerate(suggestion["data"]["options"], 1)]
    columns = [c["name"] for c in triage(run.ctx)["columns"]][:MAX_LIST]
    data, ref = run.ask("a30", {"options": options, "columns": columns}, patch_schema([o["id"] for o in options]),
                        options=[o["id"] for o in options])
    proposal = data["proposal"]
    run.claim("a30.proposal", {"kind": proposal["kind"], "addresses": proposal["addresses"], "executed": False},
              ref, options_ref)
    run.propose("a30.patch", {"kind": proposal["kind"], "addresses": proposal["addresses"]})
    run.advise("Proposal for human review, not applied: " + proposal["text"])


@executor("A31")
def sandbox_validation(run):
    if run.prior("A30") is None:
        raise NeedsEvidence("NO_PROPOSAL")
    profile = run.ctx.tool("profile_csv", profile_csv, run.ctx.payload)
    report = run.ctx.tool("diagnose_csv", diagnose_csv, run.ctx.payload)
    run.put("unchanged_payload_check", {"applied": False, "profile_status": profile["status"],
                                        "profile_findings": len(profile["findings"]),
                                        "contract_status": report.status, "contract_findings": report.finding_count})
    raise NeedsEvidence("SANDBOX_WRITES_DISABLED")


@executor("A32")
def regression_backfill_validator(run):
    raise NeedsEvidence("NO_BACKFILL_TARGET" if run.prior("A30") is not None else "NO_PROPOSAL")

