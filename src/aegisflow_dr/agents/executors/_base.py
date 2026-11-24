# SPDX-License-Identifier: Apache-2.0
"""Shared scaffolding: every executor is ``execute(task, ctx) -> result`` built by the ``executor`` decorator.

The decorator validates the task against ``agent-task-v1`` and the role, binds the context to the task, runs the
body with a ``Run`` (which collects claims, evidence, proposals, model and retrieval records), maps typed outcomes
to statuses and validates the result against ``agent-result-v1``:

- ``NeedsEvidence(code)`` and model failures -> NEEDS_EVIDENCE, ``Skip(code)`` -> SKIPPED,
- ``PolicyDenied(code)`` -> POLICY_DENIED,
- InputRejected -> FAILED/INPUT_REJECTED, ToolError -> FAILED/TOOL_ERROR,
  ToolBudgetExceeded -> FAILED/TOOL_BUDGET_EXCEEDED, a completed result the schema rejects -> FAILED/RESULT_REJECTED.

Anything else is a programming error and propagates. A non-COMPLETED result keeps its evidence references and model
record but carries no claims and no proposals (the result schema requires this).
"""
from functools import wraps
from time import perf_counter

from ...pipeline import InputRejected
from ..context import PolicyDenied, ToolBudgetExceeded, ToolError
from ..contracts import MAX_ADVISORY_CHARS, validate_result, validate_task
from ..llm import MAX_OUTPUT_TOKENS, PROVIDER, SEED, TEMPERATURE
from ..prompts import PROMPT_VERSION, TEMPLATES, case_vocabulary, safe_context
from ...advisory.context_cache import CacheIdentity

MAX_CLAIMS, MAX_LIST = 32, 16


class NeedsEvidence(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Skip(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class ModelFailure(Exception):
    """The model call could not produce usable output; ``code`` is the typed reason."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def bounded(values, limit=MAX_LIST):
    """A list of at most ``limit`` scalars, in the given order (the schema caps arrays at 16 items)."""
    return list(values)[:limit]


class Run:
    def __init__(self, task, ctx):
        self.task, self.ctx = task, ctx
        self.claims, self.refs, self.actions = [], [], []
        self.llm, self.retrieval, self.advisory = None, None, None
        self.uncertainty = ("low", "deterministic_rule")
        self.tokens_in = self.tokens_out = 0

    # -- evidence and claims --------------------------------------------------------------------------------------
    def put(self, kind, obj):
        ref = self.ctx.evidence.put(kind, obj)
        if ref not in self.refs:
            self.refs.append(ref)
        return ref

    def cite(self, ref):
        """Add an existing, resolvable reference (for example another agent's evidence) to this result."""
        if not self.ctx.evidence.has(ref):
            raise InputRejected("Unknown or altered evidence reference")
        ref = {"id": ref["id"], "sha256": ref["sha256"]}
        if ref not in self.refs:
            self.refs.append(ref)
        return ref

    def claim(self, text_key, params, *refs):
        if len(self.claims) < MAX_CLAIMS:
            self.claims.append({"text_key": text_key, "params": params, "evidence_refs": [self.cite(r) for r in refs]})

    def propose(self, text_key, params):
        self.actions.append({"text_key": text_key, "params": params, "executed": False})

    def advise(self, text):
        text = " ".join(text.split())[:MAX_ADVISORY_CHARS]
        self.advisory = text or None

    # -- prior results --------------------------------------------------------------------------------------------
    def prior(self, agent_id, status="COMPLETED"):
        """The earlier result of ``agent_id`` in this run when it has ``status``, else None."""
        result = self.ctx.prior.get(agent_id)
        if type(result) is not dict or result.get("status") != status:
            return None
        return result

    def prior_evidence(self, agent_id, kind):
        """(reference, object) of the first evidence of ``kind`` in ``agent_id``'s completed result, or (None, None)."""
        result = self.prior(agent_id)
        for ref in (result or {}).get("evidence_refs", []):
            if self.ctx.evidence.kind(ref) == kind:
                return self.cite(ref), self.ctx.evidence.get(ref)
        return None, None

    # -- the local model ------------------------------------------------------------------------------------------
    def vocabulary(self):
        """(column names, distinct cell values) of the case, for the A34 context rule."""
        ctx = self.ctx
        return ctx.remember("vocabulary", lambda: case_vocabulary(ctx.payload, ctx.second_payload))

    def ask(self, name, context, schema, **evidence):
        """One schema-constrained model call through the A34 guard; return (data, llm_suggestion reference).

        Raises PolicyDenied when the role may not use the model or the context breaks the A34 rule, and
        ModelFailure when there is no model, no model budget, or no valid output (the model record is kept).
        """
        ctx, template = self.ctx, TEMPLATES[name]
        if "local_llm" not in ctx.allowed_tools:
            raise PolicyDenied("TOOL_NOT_ALLOWED")
        header, cells = self.vocabulary()
        try:
            safe_context(context, header=header, cells=cells)
        except InputRejected:
            raise PolicyDenied("RAW_VALUE_IN_CONTEXT") from None
        if ctx.model is None:
            raise ModelFailure("MODEL_UNAVAILABLE")
        budget = self.task["budget"]
        max_tokens = min(template.max_tokens, MAX_OUTPUT_TOKENS, budget["max_tokens"])
        if ctx.usage.llm_calls >= budget["max_llm_calls"] or max_tokens < 1:
            raise ModelFailure("LLM_BUDGET_EXHAUSTED")
        context_ref = self.put("llm_context", {"agent": ctx.agent_id, "prompt_version": PROMPT_VERSION,
                                               "template": name, "context": context})
        options = {}
        if ctx.cache is not None:
            options = {"cache": ctx.cache, "agent_id": ctx.agent_id,
                       "identity": CacheIdentity(ctx.tenant_id, ctx.agent_id.lower(), PROMPT_VERSION,
                                                 context_ref["sha256"])}
        answer = ctx.model.complete(template.system, template.user(context), schema, max_tokens=max_tokens, **options)
        if answer.cache != "hit":
            ctx.usage.llm_calls += 1
        self.tokens_in += answer.tokens_in
        self.tokens_out += answer.tokens_out
        self.llm = {"provider": PROVIDER, "model": answer.model, "prompt_sha256": answer.prompt_sha256,
                    "temperature": TEMPERATURE, "seed": SEED}
        self.retrieval = {"citations": (self.retrieval or {}).get("citations", []), "cache": answer.cache}
        self.uncertainty = ("high", "model_advisory")
        if not answer.ok:
            raise ModelFailure(answer.error_code)
        if answer.tokens_in + answer.tokens_out > budget["max_tokens"]:
            raise ModelFailure("TOKEN_BUDGET_EXCEEDED")
        ref = self.put("llm_suggestion", {"agent": ctx.agent_id, "prompt_version": PROMPT_VERSION,
                                          "prompt_sha256": answer.prompt_sha256, "context": context_ref,
                                          "data": answer.data, **evidence})
        return answer.data, ref

    # -- the result -----------------------------------------------------------------------------------------------
    def result(self, status, error_code, started):
        completed = status == "COMPLETED"
        level, reason = self.uncertainty if completed else {
            "NEEDS_EVIDENCE": ("high", "missing_evidence"), "SKIPPED": ("low", "not_applicable"),
            "POLICY_DENIED": ("high", "policy_denied")}.get(status, ("high", "typed_failure"))
        return validate_result({
            "task_id": self.task["task_id"], "agent_id": self.task["agent_id"], "status": status,
            "claims": self.claims if completed else [], "evidence_refs": self.refs[:64],
            "uncertainty": {"level": level, "reason": reason},
            "proposed_actions": self.actions if completed else [],
            "usage": {"tool_calls": self.ctx.usage.tool_calls, "llm_calls": self.ctx.usage.llm_calls,
                      "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                      "latency_ms": max(0, round((perf_counter() - started) * 1000))},
            "transport": "in_process", "llm": self.llm, "retrieval": self.retrieval,
            "error_code": None if completed else error_code, "advisory_text": self.advisory if completed else None,
        })


def executor(agent_id):
    """Turn ``body(run)`` into the contract-bound ``execute(task, ctx)`` of role ``agent_id``."""
    def wrap(body):
        @wraps(body)
        def execute(task, ctx):
            validate_task(task)
            if task["agent_id"] != agent_id:
                raise InputRejected("Task is for another agent")
            run = Run(task, ctx.for_task(task))
            started = perf_counter()
            try:
                body(run)
            except NeedsEvidence as outcome:
                return run.result("NEEDS_EVIDENCE", outcome.code, started)
            except ModelFailure as outcome:
                return run.result("NEEDS_EVIDENCE", outcome.code, started)
            except Skip as outcome:
                return run.result("SKIPPED", outcome.code, started)
            except PolicyDenied as outcome:
                return run.result("POLICY_DENIED", outcome.code, started)
            except InputRejected:
                return run.result("FAILED", "INPUT_REJECTED", started)
            except ToolError:
                return run.result("FAILED", "TOOL_ERROR", started)
            except ToolBudgetExceeded:
                return run.result("FAILED", "TOOL_BUDGET_EXCEEDED", started)
            try:
                return run.result("COMPLETED", None, started)
            except InputRejected:  # e.g. a column name longer than a claim parameter may carry
                return run.result("FAILED", "RESULT_REJECTED", started)
        execute.agent_id = agent_id
        return execute
    return wrap
