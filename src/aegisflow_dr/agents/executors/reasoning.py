# SPDX-License-Identifier: Apache-2.0
"""A23-A28: candidate mechanisms, competitors, probes, evidence collection, the Judge and ranking.

Nothing here determines a root cause. A23's model output is stored as ``llm_suggestion`` evidence and summarised in
an advisory claim; the Judge (A27) labels such claims "advisory" and never accepts them as findings. A24/A25/A28
report the deterministic probe loop of ``hypotheses.investigate``, whose "supported" means only "consistent with
fixed probes".
"""
from hashlib import sha256
import re

from ...batch import DATASETS
from ...hypotheses import CATALOG, MECHANISMS, investigate, verify_investigation
from ...pipeline import InputRejected
from ..contracts import ERROR_CODES, STATUSES, validate_result
from ..prompts import VOCABULARY, hypothesis_schema
from ..registry import ROLES
from ._base import MAX_LIST, NeedsEvidence, bounded, executor
from .orchestration import readings, triage, unmapped

_HEX = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"(?:obs|hyp|prb|sig)-[0-9]{1,4}|(?:g|c|f|opt)[0-9]{1,3}|A(?:0[1-9]|[12][0-9]|3[0-6])")
# Claims that may rest on a model suggestion; they are labelled advisory and never accepted as findings.
ADVISORY_CLAIMS = {"A02": ("a02.worded",), "A22": ("a22.relevance",), "A23": ("a23.suggested", "a23.compared"),
                   "A29": ("a29.options",), "A30": ("a30.proposal",)}
# Words a claim parameter may carry besides column names and ids: the prompt vocabulary (checks, mechanisms, probes,
# roles, statuses, reason codes) plus the fixed words the executors and the modules they wrap emit.
# Upper-case parameters: agent statuses and the declared error codes only (an arbitrary upper-case token is free text).
CODE_WORDS = frozenset(STATUSES) | ERROR_CODES | frozenset({"UNKNOWN"})
CLAIM_WORDS = VOCABULARY | frozenset(DATASETS) | frozenset({
    "declared_dataset_dag", "specialists", "reasoning", "first", "second", "one_to_one", "one_to_many", "many_to_one",
    "many_to_many", "resolved", "no_informative_probe", "probe_budget_exhausted", "completed", "completed_with_gaps",
    "failed_agents", "pending", "safe_stop", "retry_once_same_input", "policy_denied", "llm_calls", "tokens",
    "elapsed_ms"})
_AGENT_IDS = frozenset(spec.agent_id for spec in ROLES)
CITATION_KINDS = ("retrieval", "similar_runs")


@executor("A23")
def hypothesis_generator(run):
    observations = triage(run.ctx)["observations"][:MAX_LIST]
    if not observations:
        raise NeedsEvidence("NO_OBSERVATIONS")
    ids = [o["id"] for o in observations]
    observations_ref = run.put("observations", {"observations": observations})
    if run.ctx.prompt_version == "2":
        catalog = [{"mechanism": m, "explains": sorted({check for check, _ in CATALOG[m][1]})} for m in MECHANISMS]
        context = {"observations": observations, "catalog": catalog}
    else:  # version 3: each observation with its qualitative reading; the signatures are in the prompt
        context = {"observations": [{**o, "reading": r} for o, r in zip(observations, readings(run.ctx))]}
    data, suggestion = run.ask("a23", context, hypothesis_schema(ids), observations=ids)
    candidates = data["candidates"]
    proposed = [c["mechanism"] for c in candidates]
    if run.ctx.prompt_version != "2":
        proposed = list(dict.fromkeys(proposed))  # a mechanism the model repeats keeps its first place
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


def _suggestion_problem(evidence, refs, claim, observations, signals):
    by_id = {o["id"]: o for o in observations}
    explains = claim["params"].get("explains", [])
    if type(explains) is not list or any(item not in by_id for item in explains):
        return "unknown_observation"
    known = set(by_id) | {s["id"] for s in signals}
    for ref in refs:
        suggestion = evidence.get(ref) if evidence.kind(ref) == "llm_suggestion" else {}
        if suggestion.get("agent") == "A02":
            goals = suggestion.get("goals")
            goal_ids = [g.get("id") for g in goals if type(g) is dict] if type(goals) is list else []
            if (len(goal_ids) != len(goals or []) or unmapped(goals, goal_ids, known)
                    or unmapped(suggestion["data"]["questions"], goal_ids, known)):
                return "goal_not_mapped"
        if suggestion.get("agent") != "A23":
            continue
        for candidate in suggestion["data"]["candidates"]:
            if any(i not in by_id or not _explains(candidate["mechanism"], by_id[i]) for i in candidate["explains"]):
                return "mechanism_does_not_explain"
    return None


def _token(value, names):
    if type(value) is not str:
        return True  # numbers, booleans and null
    return (value in CLAIM_WORDS or value in names or bool(_RUN_ID.fullmatch(value) or _HEX.fullmatch(value)
                                                           or value in CODE_WORDS))


def free_text_params(params, names):
    """True when any string parameter is not a known word, column name, run id, digest or declared code."""
    return not all(_token(item, names) for value in params.values()
                   for item in (value if type(value) is list else [value]))


def _check_claim(agent, claim, own, evidence, observations, signals, names):
    refs = claim["evidence_refs"]
    if any(ref not in own for ref in refs):
        return "rejected", "ref_not_in_result"
    if any(not evidence.has(ref) for ref in refs):
        return "rejected", "evidence_missing_or_altered"
    if free_text_params(claim["params"], names):
        return "rejected", "free_text_in_params"
    if all(evidence.kind(ref) != "llm_suggestion" for ref in refs):
        return "accepted", "evidence_verified"
    if claim["text_key"] not in ADVISORY_CLAIMS.get(agent, ()):
        return "rejected", "model_suggestion_as_support"
    problem = _suggestion_problem(evidence, refs, claim, observations, signals)
    return ("rejected", problem) if problem else ("advisory", "model_suggestion")


def _known_citations(evidence, refs):
    known = []
    for ref in refs:
        if evidence.kind(ref) in CITATION_KINDS:
            known += [{k: c[k] for k in ("source", "revision", "citation")} for c in evidence.get(ref)["citations"]]
    return known


def judge(results, evidence, observations, signals=(), *, names):
    """Per-claim verdicts for every completed result, each with a reason:

    - rejected: a reference outside the result, missing from the store or not matching its digest; a string parameter
      that is not a known word, a column name in ``names`` (required: the case's column names), a run id, a digest
      or a declared status or error code (model free text belongs in ``advisory_text`` only); a model suggestion
      cited by a claim that is not one of the model roles'
      advisory claims; or a suggestion whose ids or mechanisms do not hold (see below);
    - advisory: an advisory claim resting on a model suggestion whose observation ids exist, whose A23 mechanisms
      explain them per the catalog and whose A02 goals and questions each rest on known signal/observation ids;
    - accepted: every reference resolves and matches its digest, and no model suggestion is cited.

    Every retrieval citation must appear in that result's own retrieval evidence."""
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
            verdict, reason = _check_claim(agent, claim, own, evidence, observations, signals, names)
            verdicts.append({"agent": agent, "claim": index, "text_key": claim["text_key"], "verdict": verdict,
                             "reason": reason})
        known = _known_citations(evidence, [ref for ref in own if evidence.has(ref)])
        for citation in (result["retrieval"] or {"citations": []})["citations"]:
            if citation not in known:
                verdicts.append({"agent": agent, "claim": None, "verdict": "rejected", "reason": "unverified_citation"})
    return verdicts


@executor("A27")
def evidence_verification(run):
    t = triage(run.ctx)
    verdicts = judge(run.ctx.prior, run.ctx.evidence, t["observations"], t["signals"], names=run.vocabulary()[0])
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
