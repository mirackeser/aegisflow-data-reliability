# SPDX-License-Identifier: Apache-2.0
"""A23-A28: candidate mechanisms, competitors, probes, evidence collection, the Judge and ranking.

Nothing here determines a root cause. A23's model output is stored as ``llm_suggestion`` evidence and summarised in
an advisory claim; the Judge (A27) labels such claims "advisory" and never accepts them as findings. A24/A25/A28
report the deterministic probe loop of ``hypotheses.investigate``, whose "supported" means only "consistent with
fixed probes".
"""
from hashlib import sha256
import re

from ...hypotheses import CATALOG, MECHANISMS, investigate, verify_investigation
from ...pipeline import InputRejected
from ..contracts import validate_result
from ..prompts import hypothesis_schema
from ..registry import ROLES
from ._base import MAX_LIST, NeedsEvidence, bounded, executor
from .orchestration import triage

_HEX = re.compile(r"[0-9a-f]{64}")
_AGENT_IDS = frozenset(spec.agent_id for spec in ROLES)
CITATION_KINDS = ("retrieval", "similar_runs")


@executor("A23")
def hypothesis_generator(run):
    observations = triage(run.ctx)["observations"][:MAX_LIST]
    if not observations:
        raise NeedsEvidence("NO_OBSERVATIONS")
    ids = [o["id"] for o in observations]
    observations_ref = run.put("observations", {"observations": observations})
    catalog = [{"mechanism": m, "explains": sorted({check for check, _ in CATALOG[m][1]})} for m in MECHANISMS]
    data, suggestion = run.ask("a23", {"observations": observations, "catalog": catalog}, hypothesis_schema(ids),
                               observations=ids)
    candidates = data["candidates"]
    proposed = [c["mechanism"] for c in candidates]
    explained = sorted({i for c in candidates for i in c["explains"]}, key=ids.index)
    run.claim("a23.suggested", {"mechanisms": proposed, "explains": explained}, suggestion, observations_ref)
    run.advise("Model-suggested candidate mechanisms (advisory, to be tested, not a cause): "
               + (", ".join(proposed) or "none"))
    investigation_ref, investigation = run.prior_evidence("A24", "investigation")
    if investigation is not None:
        supported = sorted({h["mechanism"] for h in investigation["hypotheses"] if h["status"] == "supported"})
        considered = {h["mechanism"] for h in investigation["hypotheses"] if h["status"] != "refuted"}
        run.claim("a23.compared", {"agreed": sorted(set(proposed) & set(supported)),
                                   "model_only": sorted(set(proposed) - considered), "rule_supported": supported},
                  suggestion, investigation_ref)


def _investigation(run):
    if run.ctx.baseline is None:
        raise NeedsEvidence("NO_BASELINE")
    record = run.ctx.tool("investigate_hypotheses", investigate, run.ctx.baseline, run.ctx.payload, as_of=run.ctx.as_of)
    ref = run.put("investigation", record)
    if not record["observations"]:
        raise NeedsEvidence("NO_OBSERVATIONS")
    run.uncertainty = ("medium", "candidate_mechanisms_only")
    return record, ref


@executor("A24")
def counter_hypothesis(run):
    record, ref = _investigation(run)
    hypotheses = record["hypotheses"]
    run.claim("a24.summary", {"hypotheses": len(hypotheses),
                              "with_competitors": sum(bool(h["competitors"]) for h in hypotheses),
                              "verdict": record["verdict"]}, ref)
    for h in hypotheses[:24]:
        run.claim("a24.hypothesis", {"hypothesis": h["id"], "mechanism": h["mechanism"], "column": h["column"],
                                     "status": h["status"], "explains": bounded(h["explains"]),
                                     "competitors": bounded(h["competitors"])}, ref)


@executor("A25")
def active_probe_planner(run):
    record, ref = _investigation(run)
    run.claim("a25.stop", {"stop_reason": record["stop_reason"], "used": record["budget"]["used"],
                           "max_probes": record["budget"]["max_probes"]}, ref)
    for probe in record["probes"][:24]:
        outcomes = list(probe["outcomes"].values())
        run.claim("a25.probe", {"probe_id": probe["id"], "probe": probe["probe"], "column": probe["column"],
                                "round": probe["round"], "supports": outcomes.count("supports"),
                                "refutes": outcomes.count("refutes"), "neutral": outcomes.count("neutral")}, ref)


def _digest(value):
    return value if type(value) is str and _HEX.fullmatch(value) else None


@executor("A26")
def evidence_collector(run):
    ctx = run.ctx
    inputs = {"payload_sha256": sha256(ctx.payload).hexdigest(), "payload_bytes": len(ctx.payload),
              "baseline_digest": _digest((ctx.baseline or {}).get("digest")),
              "second_payload_sha256": sha256(ctx.second_payload).hexdigest() if ctx.second_payload else None,
              "as_of_given": ctx.as_of is not None, "retriever_given": ctx.retriever is not None,
              "history_runs": len(ctx.history or [])}
    inputs_ref = run.put("case_inputs", inputs)
    stored, rejected = {}, []
    for agent, result in sorted(ctx.prior.items()):
        try:
            if agent not in _AGENT_IDS or type(result) is not dict or result.get("agent_id") != agent:
                raise InputRejected("result")
            stored[agent] = ctx.evidence.put("agent_result", validate_result(result))
        except InputRejected:
            rejected.append(agent if agent in _AGENT_IDS else "invalid")
    index_ref = run.put("evidence_index", {"inputs": inputs_ref, "results": stored, "rejected": rejected})
    run.claim("a26.stored", {"results": len(stored), "rejected": len(rejected), "inputs": len(inputs)},
              index_ref, inputs_ref)


def _explains(mechanism, observation):
    return any(check == observation["check"] and direction in (None, observation["direction"])
               for check, direction in CATALOG[mechanism][1])


def _suggestion_problem(evidence, refs, claim, observations):
    by_id = {o["id"]: o for o in observations}
    explains = claim["params"].get("explains", [])
    if type(explains) is not list or any(item not in by_id for item in explains):
        return "unknown_observation"
    for ref in refs:
        suggestion = evidence.get(ref) if evidence.kind(ref) == "llm_suggestion" else {}
        if suggestion.get("agent") != "A23":
            continue
        for candidate in suggestion["data"]["candidates"]:
            if any(i not in by_id or not _explains(candidate["mechanism"], by_id[i]) for i in candidate["explains"]):
                return "mechanism_does_not_explain"
    return None


def _check_claim(claim, own, evidence, observations):
    refs = claim["evidence_refs"]
    if any(ref not in own for ref in refs):
        return "rejected", "ref_not_in_result"
    if any(not evidence.has(ref) for ref in refs):
        return "rejected", "evidence_missing_or_altered"
    if all(evidence.kind(ref) != "llm_suggestion" for ref in refs):
        return "accepted", "evidence_verified"
    problem = _suggestion_problem(evidence, refs, claim, observations)
    return ("rejected", problem) if problem else ("advisory", "model_suggestion")


def _known_citations(evidence, refs):
    known = []
    for ref in refs:
        if evidence.kind(ref) in CITATION_KINDS:
            known += [{k: c[k] for k in ("source", "revision", "citation")} for c in evidence.get(ref)["citations"]]
    return known


def judge(results, evidence, observations):
    """Per-claim verdicts for every completed result: accepted (evidence resolves and matches its digest), advisory
    (it rests on a model suggestion whose observation ids exist and whose mechanisms explain them per the catalog)
    or rejected. Every retrieval citation must appear in that result's own retrieval evidence."""
    verdicts = []
    for agent, result in sorted(results.items()):
        if type(result) is not dict or result.get("status") != "COMPLETED":
            continue
        try:
            validate_result(result)
            if result["agent_id"] != agent:
                raise InputRejected("result")
        except InputRejected:
            verdicts.append({"agent": agent if agent in _AGENT_IDS else "invalid", "claim": None,
                             "verdict": "rejected", "reason": "invalid_result"})
            continue
        own = result["evidence_refs"]
        for index, claim in enumerate(result["claims"]):
            verdict, reason = _check_claim(claim, own, evidence, observations)
            verdicts.append({"agent": agent, "claim": index, "text_key": claim["text_key"], "verdict": verdict,
                             "reason": reason})
        known = _known_citations(evidence, [ref for ref in own if evidence.has(ref)])
        for citation in (result["retrieval"] or {"citations": []})["citations"]:
            if citation not in known:
                verdicts.append({"agent": agent, "claim": None, "verdict": "rejected", "reason": "unverified_citation"})
    return verdicts


@executor("A27")
def evidence_verification(run):
    verdicts = judge(run.ctx.prior, run.ctx.evidence, triage(run.ctx)["observations"])
    ref = run.put("judge_verdict", {"verdicts": verdicts})
    counts = {name: sum(v["verdict"] == name for v in verdicts) for name in ("accepted", "advisory", "rejected")}
    rejected = sorted({v["agent"] for v in verdicts if v["verdict"] == "rejected"})
    run.claim("a27.verdict", {**counts, "rejected_agents": bounded(rejected)}, ref)


@executor("A28")
def ranking_uncertainty_reviewer(run):
    ref, record = run.prior_evidence("A24", "investigation")
    if record is None:
        raise NeedsEvidence("A24_NOT_RUN")
    verify_investigation(record)
    statuses = [h["status"] for h in record["hypotheses"]]
    run.claim("a28.ranking", {"ranking": bounded(record["ranking"]), "verdict": record["verdict"],
                              "supported": statuses.count("supported"), "open": statuses.count("open"),
                              "refuted": statuses.count("refuted")}, ref)
    # A single consistent candidate is still not a determined cause, so uncertainty is never "low" here.
    run.uncertainty = ("medium", "single_candidate_consistent") if record["verdict"] == "single_supported" else (
        "high", record["verdict"])
