# SPDX-License-Identifier: Apache-2.0
"""One investigation run over the 36 contract-bound roles: lifecycle, waves, budgets, recovery, Judge and record.

``run_case`` runs a case through the binding role table (docs/superpowers/specs/2026-11-24-agent-runtime-roles.md):

1. A01 opens the run and the case intake runs once (its profile, comparison and contract calls are ``tool_call``
   events of A10 and A01). An unreadable case ends the run as ``input_rejected``.
2. A02 plans, A03 routes (at most 8 specialists; every other role gets a SKIPPED row with its reason), A04 turns the
   selection into dependency waves of at most 4, whose agents run concurrently, each in its own thread.
3. A27 (the Judge) gates the claim set, over A2A with mutual TLS when available; only accepted specialist claims feed
   A29. A30, A31 and A32 follow the proposals; A33 records a pending approval; A34, A05, A35, A36 and A26 review,
   account, evaluate and store; A01 closes the run. A closing Judge pass covers the claims made after the gate.

Dependencies gate (role table): an agent whose selected prerequisite did not complete (FAILED after recovery,
NEEDS_EVIDENCE, POLICY_DENIED or SKIPPED, a budget skip included) is SKIPPED with ``DEPENDENCY_UNMET`` and the unmet
prerequisites are named; a prerequisite that was never selected does not block.

A05's limits are enforced here. Before a wave starts, specialists over the specialist limit, model roles without
model calls or tokens left, and every non-closing role once the wall time is used are SKIPPED with
``BUDGET_EXCEEDED``, so no new wave is scheduled after the wall limit. Each agent runs in its own daemon thread and is
waited for at most its ``deadline_ms`` (the agent deadline, capped by the run time left; closing controls get the
run time left plus ``CLOSING_GRACE_MS``), measured in real time: an agent still running then is FAILED with
``DEADLINE_EXCEEDED`` and listed in ``abandoned``. Everything that attempt did or still does (buffered events,
staged evidence, its result) is discarded, so the record never depends on how far the thread got (a Python thread
cannot be killed; a daemon thread never blocks process exit). This bounds
tool calls and injected retrievers too. Model calls are bounded before that by their own timeout, which is the time
left of the task's deadline (at most 30 s). The case intake and rule tools are bounded by their input limits. An agent
whose injected-clock latency exceeds its deadline is also FAILED with ``DEADLINE_EXCEEDED``. A06 decides on every
FAILED agent and the runtime retries the ones it marks ``retry_once_same_input`` once with the same task, if the
time, model-call and token budgets still allow it (POLICY_DENIED and NEEDS_EVIDENCE are not failures and are never
retried). Latencies are measured on the injected ``clock``; results, events and the record are deterministic for a
fixed clock, model, ``now`` and ``run_id``. Nothing here executes a proposal or simulates a human decision, and model
text never becomes evidence.
"""
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from threading import Condition, Lock, Thread, local
from time import monotonic, perf_counter
from typing import Any
from uuid import uuid4

from ..advisory.context_cache import ContextCache
from ..pipeline import InputRejected
from . import transport as transports
from .context import AgentContext, PolicyDenied
from .contracts import validate_result, validate_run, validate_task
from .events import EventLog
from .executors import resolve
from .executors.governance import USAGE_KEYS
from .executors.orchestration import BUDGET_EXCEEDED, LIMITS, REASONING_DEPENDS, SPECIALISTS, triage
from .executors._base import Run
from .executors.reasoning import judge
from .executors.remediation import accepted_findings
from .llm import LocalModel
from .prompts import PROMPT_VERSION, case_vocabulary
from .registry import ROLES, role

RECORD_VERSION, POLICY_VERSION, MAX_TOOL_CALLS = "1", "1", 8
# Closing controls run after a budget stop too, but within the wall limit plus this fixed grace (their deadline is
# min(agent deadline, run time left + grace)); they are deterministic bookkeeping that takes milliseconds.
CLOSING_GRACE_MS = 2_000
NOT_SELECTED, INTAKE_REJECTED = "NOT_SELECTED", "INTAKE_REJECTED"
DEADLINE_EXCEEDED, EXECUTOR_ERROR, DEPENDENCY_UNMET = "DEADLINE_EXCEEDED", "EXECUTOR_ERROR", "DEPENDENCY_UNMET"
AGENT_IDS = tuple(spec.agent_id for spec in ROLES)
ALWAYS = ("A01", "A02", "A03", "A04", "A05", "A26", "A27", "A34", "A35", "A36")
# Closing controls make no model call and run even after a budget stop, so the run is closed and accounted honestly.
CLOSING = frozenset({"A01", "A05", "A26", "A27", "A33", "A34", "A35", "A36"})
MODEL_ROLES = frozenset(spec.agent_id for spec in ROLES if "local_llm" in spec.allowed_tools)
LLM_ONLY = frozenset(spec.agent_id for spec in ROLES if spec.kind == "llm")
# Prerequisites per role (role table): specialists read the profile (A10); A24/A25 follow A11/A20; A23 compares with
# A24/A25 and A28 ranks A24; the remediation chain follows the Judge. A33 reads every proposal and has none.
DEPENDS = {**{a: ("A10",) for a in SPECIALISTS if a != "A10"}, "A24": ("A11", "A20"), "A25": ("A11", "A20"),
           **REASONING_DEPENDS, "A04": ("A03",), "A29": ("A27",), "A30": ("A29",), "A31": ("A30",), "A32": ("A30",)}
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,55}")


@dataclass(frozen=True)
class Case:
    """The case inputs of the binding role table (see ``AgentContext`` for their checks)."""
    payload: bytes
    case_id: str
    tenant_id: str = "local"
    baseline: Any = None
    as_of: Any = None
    second_payload: Any = None
    retriever: Any = None
    history: Any = None
    prompt_version: str = PROMPT_VERSION  # the model prompts; an earlier version replays an earlier recording


@dataclass(frozen=True)
class Budget:
    """Per-run limits (A05). Defaults are the catalog limits; an operator may only lower them."""
    specialists: int = LIMITS["specialists"]
    llm_calls: int = LIMITS["llm_calls"]
    tokens: int = LIMITS["tokens"]
    wall_ms: int = LIMITS["elapsed_ms"]
    agent_deadline_ms: int = 60_000

    def __post_init__(self):
        bounds = {"specialists": (0, LIMITS["specialists"]), "llm_calls": (0, LIMITS["llm_calls"]),
                  "tokens": (0, LIMITS["tokens"]), "wall_ms": (1, LIMITS["elapsed_ms"]),
                  "agent_deadline_ms": (1, LIMITS["elapsed_ms"])}
        for name, (low, high) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise InputRejected("Invalid run budget")

    def limits(self):
        return {"specialists": self.specialists, "llm_calls": self.llm_calls, "tokens": self.tokens,
                "elapsed_ms": self.wall_ms}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def trace_digest(record):
    """SHA-256 of the canonical record without its ``trace_sha256`` field."""
    return sha256(canonical({k: v for k, v in record.items() if k != "trace_sha256"})).hexdigest()


def verify_record(record):
    """Return ``record`` when it satisfies ``agent-run-v1`` and its trace digest matches; else raise InputRejected."""
    validate_run(record)
    if record["trace_sha256"] != trace_digest(record):
        raise InputRejected("Agent run trace digest mismatch")
    return record


def _typed(agent, task_id, status, code, usage=None, refs=()):
    """A runtime-produced outcome (a role that did not run, or a typed failure around its execution)."""
    level, reason = ("low", "not_applicable") if status == "SKIPPED" else ("high", "typed_failure")
    return validate_result({
        "task_id": task_id, "agent_id": agent, "status": status, "claims": [], "evidence_refs": list(refs)[:64],
        "uncertainty": {"level": level, "reason": reason}, "proposed_actions": [],
        "usage": usage or {key: 0 for key in USAGE_KEYS}, "transport": "in_process", "llm": None, "retrieval": None,
        "error_code": code, "advisory_text": None})


class _Hooks:
    """The runtime side of ``AgentContext.hooks``: tool transport, intake accounting and per-agent event buffers."""

    def __init__(self, run, mcp, reason):
        self._run, self._mcp, self._reason = run, mcp, reason
        self._buffers, self._lock, self._abandoned, self.local = {}, Lock(), set(), local()
        self.intake = []
        self.discarded = 0  # events of abandoned agents, which arrive after their deadline

    def begin(self, agent):
        with self._lock:
            self._buffers[agent] = []

    def flush(self, agent):
        with self._lock:
            pending = self._buffers.pop(agent, [])
        for item in pending:
            self._run.log.publish(item)

    def abandon(self, agent, token):
        """Drop what an abandoned attempt did and will do: its buffered events now, its later events on arrival.

        Discarding the partial work (like its staged evidence) keeps the record independent of how far the thread
        got before its deadline. ``token`` identifies the attempt, so a later attempt of the same role is unaffected.
        """
        with self._lock:
            self.discarded += len(self._buffers.pop(agent, []))
            self._abandoned.add(token)

    def event(self, agent_id, kind, data):
        pending = self._run.log.stamp(agent_id, kind, data)
        with self._lock:
            if getattr(self.local, "token", None) in self._abandoned:
                self.discarded += 1
                return
            buffer = self._buffers.get(agent_id)
            if buffer is not None:
                buffer.append(pending)
                return
        self._run.log.publish(pending)

    def _timed(self, agent, data, call):
        started, outcome = self._run.clock(), "ok"
        try:
            return call()
        except InputRejected:
            outcome = "input_rejected"
            raise
        except PolicyDenied:
            outcome = "denied"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            data.update(outcome=outcome, latency_ms=max(0, round((self._run.clock() - started) * 1000)))
            self.event(agent, "tool_call", data)

    def intake_tool(self, agent, name, fn, args, kwargs):
        data = {"tool": name, "phase": "intake", "transport": transports.IN_PROCESS, "reason": "case_intake"}
        try:
            return self._timed(agent, data, lambda: fn(*args, **kwargs))
        finally:
            self.intake.append({"agent": agent, "tool": name, "outcome": data["outcome"],
                                "latency_ms": data["latency_ms"]})

    def call_tool(self, ctx, name, fn, args, kwargs):
        data = {"tool": name, "phase": "agent", "transport": transports.IN_PROCESS, "reason": self._reason}
        arguments = None
        if self._mcp is not None:
            arguments, data["reason"] = self._mcp.route(name, fn, args, kwargs)

        def call():
            if arguments is None:
                return fn(*args, **kwargs)
            data["transport"], data["reason"] = transports.MCP_LOCAL, None
            value, data["transport"], data["reason"] = self._mcp.invoke(name, arguments, fn, args)
            return value

        try:
            return self._timed(ctx.agent_id, data, call)
        finally:
            if data["transport"] == transports.MCP_LOCAL:
                ctx.usage.mcp_calls += 1


class _Run:
    def __init__(self, case, model, cache, budget, clock, on_event, plan, now, run_id):
        self.case, self.budget, self.clock, self.plan, self.run_id = case, budget, clock, plan, run_id
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.started_at = self._stamp()
        self.started = clock()
        self.log = EventLog(clock, self.started, on_event)
        mcp = transports.McpTools() if plan["tools"]["mode"] == transports.MCP_LOCAL else None
        self.hooks = _Hooks(self, mcp, plan["tools"]["reason"] or "not_in_mcp_profile")
        self.ctx = AgentContext(case.payload, case.tenant_id, case.case_id, baseline=case.baseline, as_of=case.as_of,
                                second_payload=case.second_payload, retriever=case.retriever, history=case.history,
                                model=model, cache=cache, clock=clock, started=self.started, hooks=self.hooks,
                                limits=budget.limits(), prompt_version=case.prompt_version)
        self.limits = budget.limits()
        self.results, self.tasks, self.attempts, self.waves_run = {}, {}, {}, []
        self.selection = {}
        self.wave_of, self.recovery, self.exceeded, self.gate = {}, [], [], []
        self.judge_transport = dict(plan["judge"])
        self.pki, self.unmet, self.abandoned = None, {}, []
        self.specialists = set()  # specialists admitted so far (counted at admission, before a wave starts)

    # -- helpers ----------------------------------------------------------------------------------------------------
    def _stamp(self):
        value = self.now()
        if type(value) is not datetime or value.tzinfo is None:
            raise InputRejected("The run clock must return an aware datetime")
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def elapsed_ms(self):
        return max(0, round((self.clock() - self.started) * 1000))

    def emit(self, agent, kind, data):
        self.log.emit(agent, kind, data)

    def task_id(self, agent):
        return "%s.%s" % (self.run_id, agent.lower())

    def select(self, agent, reason):
        self.selection[agent] = {"selected": True, "reason": reason}
        self.emit(agent, "agent_selected", {"reason": reason})

    def skip(self, agent, reason, code=NOT_SELECTED, selected=False, unmet=()):
        if not selected:
            self.selection[agent] = {"selected": False, "reason": reason}
        self.unmet[agent] = list(unmet)
        self.results[agent] = _typed(agent, self.task_id(agent), "SKIPPED", code)
        self.emit(agent, "agent_skipped", {"reason": reason, "error_code": code, "unmet": list(unmet)})

    def unmet_prerequisites(self, agent):
        """Selected prerequisites of ``agent`` whose final result is not COMPLETED."""
        return [d for d in DEPENDS.get(agent, ()) if self.selection.get(d, {}).get("selected")
                and self.results[d]["status"] != "COMPLETED"]

    def used(self):
        results = list(self.results.values())
        return {"specialists": sum(r["agent_id"] in SPECIALISTS and r["status"] != "SKIPPED" for r in results),
                "llm_calls": sum(r["usage"]["llm_calls"] for r in results),
                "tokens": sum(r["usage"]["tokens_in"] + r["usage"]["tokens_out"] for r in results),
                "elapsed_ms": self.elapsed_ms()}

    def stop(self, limit):
        if limit not in self.exceeded:
            self.exceeded.append(limit)

    def refs_of(self, agents):
        refs = []
        for agent in agents:
            for ref in (self.results.get(agent) or {}).get("evidence_refs", []):
                if ref not in refs:
                    refs.append(ref)
        return refs[:64]

    def task(self, agent, llm_calls=0, tokens=0, closing=False):
        remaining = max(0, self.limits["elapsed_ms"] - self.elapsed_ms()) + (CLOSING_GRACE_MS if closing else 0)
        deadline = max(1, min(self.budget.agent_deadline_ms, remaining))
        return validate_task({
            "task_id": self.task_id(agent), "run_id": self.run_id, "tenant_id": self.case.tenant_id,
            "case_id": self.case.case_id, "agent_id": agent, "goal": role(agent).name[:300],
            "input_refs": self.refs_of(DEPENDS.get(agent, ())), "allowed_tools": list(role(agent).allowed_tools),
            "budget": {"max_tool_calls": MAX_TOOL_CALLS if role(agent).allowed_tools else 0,
                       "max_llm_calls": llm_calls, "max_tokens": tokens, "deadline_ms": deadline},
            "policy_version": POLICY_VERSION})

    # -- execution --------------------------------------------------------------------------------------------------
    def _execute(self, agent, task, ctx):
        started = self.clock()
        try:
            if agent == "A27" and self.judge_transport["mode"] == transports.A2A_MTLS:
                result = self._judge_a2a(task, ctx)
            else:
                result = resolve(agent)(task, ctx)
        except Exception:  # a programming error in an executor becomes a typed failure, never a crashed run
            result = _typed(agent, task["task_id"], "FAILED", EXECUTOR_ERROR)
        latency = max(0, round((self.clock() - started) * 1000))
        result = validate_result({**result, "usage": {**result["usage"], "latency_ms": latency}})
        if latency > task["budget"]["deadline_ms"]:
            result = _typed(agent, task["task_id"], "FAILED", DEADLINE_EXCEEDED, result["usage"],
                            result["evidence_refs"])
        return result

    def _judge_a2a(self, task, ctx):
        try:
            self.pki = self.pki or self.stack.enter_context(transports.ephemeral_pki())  # one CA per run
            timeout = min(transports.A2A_TIMEOUT_S, task["budget"]["deadline_ms"] / 1000)
            received = transports.a2a_review(task, lambda t: resolve("A27")(t, ctx), pki=self.pki, timeout=timeout)
            result = validate_result(received)
            if (result["task_id"] != task["task_id"] or result["agent_id"] != "A27"
                    or any(not ctx.evidence.has(ref) for ref in result["evidence_refs"])):
                raise InputRejected("Judge result does not match its task")
        except (ValueError, OSError):  # PKI, TLS, A2A or contract failure (TransportError, ProtocolError, SSLError
            # and InputRejected are among them); any other error is an executor error, not a transport failure
            self.judge_transport = {"mode": transports.IN_PROCESS, "reason": "a2a_exchange_failed"}
            return resolve("A27")(task, ctx)
        self.judge_transport.update(self.pki.fingerprints(), tls="TLSv1.3", address="127.0.0.1")
        return {**result, "transport": transports.A2A_MTLS}

    def run_wave(self, stage, agents, *, closing=False, retry=None):
        """Run ``agents`` (at most 4) concurrently; record each one as soon as it completes or reaches its deadline.

        Each agent writes to its own staged evidence view, committed on completion and dropped on abandonment. Its
        events and ``agent_finished`` are published at its completion (live order); the wave's span of the log is then
        sealed into agent-id order for the record.
        """
        agents = sorted(agents)
        number = len(self.waves_run) + 1
        self.waves_run.append({"wave": number, "stage": stage, "agents": agents})
        runnable = []
        for agent in agents:
            self.wave_of[agent] = number
            task = retry[agent] if retry else self.admit(agent, closing)
            if task is not None:
                runnable.append((agent, task))
        if not runnable:
            return
        ctx = replace(self.ctx, prior=dict(self.results))
        done, completed, pending = Condition(), {}, {}
        for agent, task in runnable:
            self.tasks[agent] = task
            self.attempts[agent] = self.attempts.get(agent, 0) + 1
            self.hooks.begin(agent)
            self.emit(agent, "agent_started", {"wave": number, "stage": stage, "attempt": self.attempts[agent],
                                               "depends_on": [d for d in DEPENDS.get(agent, ())
                                                              if self.selection.get(d, {}).get("selected")],
                                               "budget": task["budget"]})
            view, token = self.ctx.evidence.stage(), object()
            pending[agent] = (task, view, token, perf_counter() + task["budget"]["deadline_ms"] / 1000)
            self._spawn(agent, task, replace(ctx, evidence=view), token, done, completed)
        mark = self.log.mark()
        while pending:
            due = min(item[3] for item in pending.values())
            with done:
                done.wait_for(lambda: completed.keys() & pending.keys(), timeout=max(0.0, due - perf_counter()))
                ready = sorted(completed.keys() & pending.keys())
            for agent in ready:
                pending.pop(agent)[1].commit()
                self.hooks.flush(agent)
                self._record(agent, *completed[agent], retry)
            now = perf_counter()
            for agent in sorted(a for a, item in pending.items() if now >= item[3]):
                task, _, token, _ = pending.pop(agent)  # still running: its staged evidence is never committed
                self.hooks.abandon(agent, token)
                self.abandoned.append(agent)
                self._record(agent, _typed(agent, task["task_id"], "FAILED", DEADLINE_EXCEEDED), self.clock(), retry,
                             abandoned=True)
        self.log.seal(mark)

    def _record(self, agent, result, at, retry, *, abandoned=False):
        if retry:
            result = self._merge_attempts(self.results[agent], result)
        self.results[agent] = result
        data = self._finished(agent, result, abandoned=abandoned)
        self.log.publish(self.log.stamp(agent, "agent_finished", data, at))

    def _spawn(self, agent, task, ctx, token, done, completed):
        """Run one agent attempt in a daemon thread that reports (result, completion time) to ``completed``."""
        def work():
            self.hooks.local.token = token
            result = self._execute(agent, task, ctx)  # _execute never raises
            at = self.clock()
            with done:
                completed[agent] = (result, at)
                done.notify_all()

        Thread(target=work, name="agent-" + agent, daemon=True).start()

    def _finished(self, agent, result, *, abandoned=False, runtime=False):
        data = {"status": result["status"], "error_code": result["error_code"], "transport": result["transport"],
                "claims": len(result["claims"]), "evidence_refs": len(result["evidence_refs"]),
                "proposals": len(result["proposed_actions"]), "usage": result["usage"],
                "attempt": self.attempts.get(agent, 0)}
        if agent == "A27" and result["transport"] == transports.A2A_MTLS:
            data["certificates"] = self.pki.fingerprints()
        if abandoned:
            data["abandoned"] = True
        if runtime:  # an outcome the runtime recorded without running the agent's executor
            data["runtime"] = True
        return data

    @staticmethod
    def _merge_attempts(first, second):
        usage = {key: first["usage"][key] + second["usage"][key] for key in USAGE_KEYS}
        return validate_result({**second, "usage": usage})

    def admit(self, agent, closing):
        """The task for ``agent`` within the run budget and with its prerequisites met, or None after a skip."""
        if not closing and self.elapsed_ms() >= self.limits["elapsed_ms"]:
            self.stop("elapsed_ms")
            return self.skip(agent, "time_limit", BUDGET_EXCEEDED, selected=True)
        unmet = self.unmet_prerequisites(agent)
        if unmet:
            return self.skip(agent, "dependency_unmet", DEPENDENCY_UNMET, selected=True, unmet=unmet)
        if agent in SPECIALISTS:
            if len(self.specialists) >= self.limits["specialists"]:
                self.stop("specialists")
                return self.skip(agent, "specialist_limit", BUDGET_EXCEEDED, selected=True)
            self.specialists.add(agent)
        if agent not in MODEL_ROLES or self.ctx.model is None:
            return self.task(agent, closing=closing)
        used = self.used()
        calls, tokens = self.limits["llm_calls"] - used["llm_calls"], self.limits["tokens"] - used["tokens"]
        if calls < 1 or tokens < 1:
            limit = "llm_calls" if calls < 1 else "tokens"
            self.stop(limit)
            if agent in LLM_ONLY:
                return self.skip(agent, limit + "_limit", BUDGET_EXCEEDED, selected=True)
            return self.task(agent)  # a hybrid keeps its rule part and makes no model call
        return self.task(agent, llm_calls=1, tokens=min(tokens, LIMITS["tokens"]))

    def recover(self, failed):
        """A06 decides on the agents that failed in this wave; the runtime retries its retry_once decisions once."""
        if "A06" not in self.selection or not self.selection["A06"]["selected"]:
            self.select("A06", "failed_agent")
        self.run_wave("recovery", ["A06"], closing=True)
        decision = self.evidence_of("A06", "recovery_decision") or {"decisions": []}
        retry = {}
        for item in decision["decisions"]:
            if item["agent"] not in failed:
                continue
            retried = (item["decision"] == "retry_once_same_input" and self.within_budget(self.tasks[item["agent"]]))
            self.recovery.append({"agent": item["agent"], "error_code": item["error_code"],
                                  "decision": item["decision"], "retried": retried})
            if retried:
                retry[item["agent"]] = self.tasks[item["agent"]]
        if retry:
            self.run_wave("retry", list(retry), retry=retry)

    def within_budget(self, task):
        """A retry repeats the same task, so it must still fit the remaining time, model-call and token budget."""
        used, calls = self.used(), task["budget"]["max_llm_calls"]
        return (used["elapsed_ms"] < self.limits["elapsed_ms"]
                and used["llm_calls"] + calls <= self.limits["llm_calls"]
                and (calls == 0 or used["tokens"] < self.limits["tokens"]))

    def stage(self, stage, agents, *, closing=False):
        self.run_wave(stage, agents, closing=closing)
        failed = [a for a in sorted(agents) if self.results[a]["status"] == "FAILED" and self.attempts.get(a) == 1]
        if failed:
            self.recover(failed)

    def evidence_of(self, agent, kind):
        result = self.results.get(agent)
        if result is None or result["status"] != "COMPLETED":
            return None
        return next((self.ctx.evidence.get(ref) for ref in result["evidence_refs"]
                     if self.ctx.evidence.kind(ref) == kind), None)

    # -- the run ----------------------------------------------------------------------------------------------------
    def execute(self):
        self.emit("A01", "run_started", {"run_id": self.run_id, "tenant_id": self.case.tenant_id,
                                         "case_id": self.case.case_id, "transport_plan": self.plan,
                                         "limits": self.limits})
        self.select("A01", "always")
        with ExitStack() as stack:
            self.stack = stack
            try:
                intake = triage(self.ctx)
            except InputRejected:
                intake = None
                self.rejected()
            else:
                self.investigate(intake)
                self.remediate()
                self.close()
        if self.pki is not None:  # the run's certificate directory must be gone; a failure is reported, not hidden
            self.judge_transport["certificates_removed"] = not self.pki.root.exists()
        return self.record(intake)

    def investigate(self, intake):
        for agent in ("A02", "A03"):
            self.select(agent, "always")
            self.stage({"A02": "plan", "A03": "route"}[agent], [agent])
        routing = self.evidence_of("A03", "routing")
        if routing is None:  # without A03's routing nothing is selected and A04 has nothing to schedule
            for agent in SPECIALISTS + ("A23", "A24", "A25", "A28"):
                self.skip(agent, "router_unavailable")
            self.select("A04", "always")
            self.skip("A04", "dependency_unmet", DEPENDENCY_UNMET, selected=True, unmet=["A03"])
            return
        for item in routing["selected"]:
            self.select(item["agent"], item["reason"])
        for item in routing["skipped"]:
            self.skip(item["agent"], item["reason"])
        if self.selection["A24"]["selected"]:
            self.select("A28", "a24_selected")
        else:
            self.skip("A28", "a24_not_selected")
        self.select("A04", "always")
        self.stage("schedule", ["A04"])
        plan = self.evidence_of("A04", "wave_plan")
        if plan is None:
            for agent in sorted(item["agent"] for item in routing["selected"]) + (["A28"] if self.selection["A28"][
                    "selected"] else []):
                self.skip(agent, "dependency_unmet", DEPENDENCY_UNMET, selected=True, unmet=["A04"])
            return
        for item in plan["stages"]:
            self.stage(item["stage"], item["agents"])

    def remediate(self):
        self.select("A27", "always")
        self.stage("judge", ["A27"], closing=True)
        self.gate = [{**v, "pass": "gate"} for v in (self.evidence_of("A27", "judge_verdict") or {"verdicts": []})[
            "verdicts"]]
        self.publish_verdicts(self.gate)
        view = Run({"task_id": "view", "agent_id": "A27"}, replace(self.ctx, prior=dict(self.results)))
        if not accepted_findings(view)[1]:
            self.skip("A29", "no_accepted_findings")
        else:
            self.select("A29", "accepted_findings")
            self.stage("remediation", ["A29"])
        # Selection follows the role table; whether a selected step may run is the dependency gate in admit().
        if not self.selection["A29"]["selected"]:
            self.skip("A30", "no_remediation_options")
        elif not triage(self.ctx)["order_extract"]:
            self.skip("A30", "not_order_extract")
        else:
            self.select("A30", "options_for_order_extract")
            self.stage("remediation", ["A30"])
        if not self.selection["A30"]["selected"]:
            for agent in ("A31", "A32"):
                self.skip(agent, "no_patch_proposal")
            return
        for agent in ("A31", "A32"):
            self.select(agent, "patch_proposal")
        self.stage("validation", ["A31", "A32"])

    def publish_verdicts(self, verdicts):
        for agent in sorted({v["agent"] for v in verdicts}):
            own = [v for v in verdicts if v["agent"] == agent]
            self.emit("A27", "judge_verdict", {"subject": agent, "pass": own[0]["pass"],
                                               **{n: sum(v["verdict"] == n for v in own)
                                                  for n in ("accepted", "advisory", "rejected")},
                                               "verdicts": [{"claim": v["claim"], "verdict": v["verdict"],
                                                             "reason": v["reason"]} for v in own]})

    def close(self):
        proposals = any(r["status"] == "COMPLETED" and r["proposed_actions"] for r in self.results.values())
        if proposals:
            self.select("A33", "proposals_exist")
            self.stage("governance", ["A33"], closing=True)
            approval = self.evidence_of("A33", "approval_request")
            if approval is not None:
                self.emit("A33", "approval_requested", {"items": len(approval["items"]), "decision": "pending",
                                                        "executed": False})
        else:
            self.skip("A33", "no_proposals")
        if "A06" not in self.selection:
            self.skip("A06", "no_failed_agent")
        for agent in ("A34", "A05", "A35", "A36", "A26"):
            self.select(agent, "always")
            self.stage({"A34": "governance", "A05": "budget", "A35": "governance", "A36": "governance",
                        "A26": "collect"}[agent], [agent], closing=True)
        self.stage("close", ["A01"], closing=True)

    def rejected(self):
        for agent in AGENT_IDS[1:]:
            self.skip(agent, "intake_rejected", INTAKE_REJECTED)
        self.wave_of["A01"] = 1
        self.waves_run.append({"wave": 1, "stage": "close", "agents": ["A01"]})
        self.results["A01"] = _typed("A01", self.task_id("A01"), "FAILED", "INPUT_REJECTED")
        self.emit("A01", "agent_finished", self._finished("A01", self.results["A01"], runtime=True))

    # -- the record -------------------------------------------------------------------------------------------------
    def closing_verdicts(self):
        """The same Judge over the results completed after the gate (remediation, governance and close)."""
        later = {a: r for a, r in self.results.items() if self.wave_of.get(a, 0) > self.wave_of["A27"]}
        t = triage(self.ctx)
        names = case_vocabulary(self.case.payload, self.case.second_payload, baseline=self.case.baseline)[0]
        verdicts = [{**v, "pass": "closing"} for v in judge(later, self.ctx.evidence, t["observations"], t["signals"],
                                                            names=names)]
        self.publish_verdicts(verdicts)
        return verdicts

    def record(self, intake):
        verdicts = [] if intake is None else self.gate + self.closing_verdicts()
        statuses = {a: self.results[a]["status"] for a in AGENT_IDS}
        status = ("input_rejected" if intake is None else "budget_exceeded" if self.exceeded else
                  "failed_agents" if "FAILED" in statuses.values() else
                  "completed_with_gaps" if {"NEEDS_EVIDENCE", "POLICY_DENIED"} & set(statuses.values())
                  else "completed")
        usage_rows = {a: self.results[a]["usage"] for a in AGENT_IDS}
        intake_usage = {"tool_calls": len(self.hooks.intake),
                        "latency_ms": sum(c["latency_ms"] for c in self.hooks.intake), "calls": self.hooks.intake}
        totals = {k: sum(u[k] for u in usage_rows.values()) for k in USAGE_KEYS}
        totals["tool_calls"] += intake_usage["tool_calls"]
        used = self.used()
        self.emit("A01", "run_finished", {"status": status, "duration_ms": used["elapsed_ms"],
                                          "budget_exceeded": list(self.exceeded)})
        proposals = [{"agent": a, **action} for a in AGENT_IDS if self.results[a]["status"] == "COMPLETED"
                     for action in self.results[a]["proposed_actions"]]
        approval = self.evidence_of("A33", "approval_request")
        evaluation = self.evidence_of("A36", "evaluation_record")
        record = {
            "version": RECORD_VERSION, "run_id": self.run_id, "tenant_id": self.case.tenant_id,
            "case_id": self.case.case_id, "started_at": self.started_at, "finished_at": self._stamp(),
            "duration_ms": used["elapsed_ms"], "status": status,
            "intake": None if intake is None else {**intake, "tool_calls": self.hooks.intake},
            "plan": self.evidence_of("A02", "investigation_plan"),
            "selection": [{"agent_id": a, **self.selection.get(a, {"selected": False, "reason": "intake_rejected"}),
                           "error_code": self.results[a]["error_code"] if statuses[a] == "SKIPPED" else None,
                           "unmet": self.unmet.get(a, [])}
                          for a in AGENT_IDS],
            "waves": self.waves_run,
            "agents": [{"agent_id": a, "name": role(a).name, "layer": role(a).layer, "kind": role(a).kind,
                        "selected": self.selection.get(a, {"selected": False})["selected"],
                        "wave": self.wave_of.get(a), "attempts": self.attempts.get(a, 0),
                        "task": self.tasks.get(a), "result": self.results[a]} for a in AGENT_IDS],
            "events": [],
            "judge": {"transport": self.judge_transport, "verdicts": verdicts,
                      **{n: sum(v["verdict"] == n for v in verdicts) for n in ("accepted", "advisory", "rejected")},
                      "accepted_findings": [{"agent": v["agent"], "claim": v["claim"]} for v in verdicts
                                            if v["verdict"] == "accepted" and v["agent"] in SPECIALISTS]},
            "proposals": proposals,
            "approvals": [] if approval is None else [{"agent": "A33", "decision": "pending", "executed": False,
                                                       "items": approval["items"]}],
            "usage": {"agents": usage_rows, "intake": intake_usage, "totals": totals, "external_spend_usd": 0},
            "evaluation": evaluation,
            "transports": {"requested": self.plan["requested"], "tools": self.plan["tools"],
                           "judge": self.judge_transport,
                           "agents": {a: self.results[a]["transport"] for a in AGENT_IDS}},
            "budget": {"limits": self.limits, "used": used, "exceeded": list(self.exceeded)},
            "recovery": self.recovery,
            "abandoned": self.abandoned,
            "evidence": sorted(({**ref, "kind": self.ctx.evidence.kind(ref)} for ref in self.ctx.evidence.refs()),
                               key=lambda ref: ref["id"]),
        }
        record["events"] = self.log.events()
        record["event_log"] = {"dropped": self.log.dropped, "callback_errors": self.log.callback_errors}
        record["trace_sha256"] = trace_digest(record)
        return verify_record(record)


def run_case(case, *, model=None, cache=None, budget=Budget(), clock=monotonic, on_event=None, transport="auto",
             now=None, run_id=None):
    """Run ``case`` through the 36 roles and return the validated, digest-sealed run record (``agent-run-v1``).

    ``clock`` (seconds, monotonic) times agents, budgets and events; ``now`` (an aware datetime factory) stamps
    ``started_at``/``finished_at``; ``run_id`` defaults to a fresh random id. ``on_event`` receives every recorded
    event synchronously, in order; its exceptions are counted and ignored. ``transport`` is "auto", "in_process",
    "mcp" or "a2a" (see ``agents.transport``).
    """
    if (type(case) is not Case or type(budget) is not Budget or not callable(clock)
            or (now is not None and not callable(now)) or (on_event is not None and not callable(on_event))
            or (model is not None and type(model) is not LocalModel)
            or (cache is not None and type(cache) is not ContextCache)):
        raise InputRejected("Invalid agent run request")
    if run_id is None:
        run_id = "run-" + uuid4().hex[:24]
    if type(run_id) is not str or not _RUN_ID.fullmatch(run_id):
        raise InputRejected("Invalid agent run id")
    return _Run(case, model, cache, budget, clock, on_event, transports.plan(transport), now, run_id).execute()
