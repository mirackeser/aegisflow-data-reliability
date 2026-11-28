# SPDX-License-Identifier: Apache-2.0
"""Task and result contracts shared by every agent role (offline JSON Schema, Draft 2020-12).

A result carries claims as message keys with bounded parameters, each bound to evidence references (id plus
SHA-256). Free model text may appear only in ``advisory_text`` (at most 600 characters); it is advisory, never
evidence, and the Judge does not accept it as such. Proposed actions are recorded as proposals and are never executed.
"""
from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

from ..pipeline import InputRejected
from .registry import role

STATUSES = ("COMPLETED", "NEEDS_EVIDENCE", "POLICY_DENIED", "SKIPPED", "FAILED")
# The closed set of error codes the executors, the model adapter and the runtime produce. The Judge accepts an
# upper-case claim parameter only from this set, the statuses or the module vocabulary, never an arbitrary token.
ERROR_CODES = frozenset({
    "MODEL_UNAVAILABLE", "INVALID_OUTPUT", "TIMEOUT", "LLM_BUDGET_EXHAUSTED", "TOKEN_BUDGET_EXCEEDED", "UNMAPPED_GOAL",
    "DEADLINE_EXCEEDED", "A24_NOT_RUN", "NOT_ORDER_EXTRACT", "NO_ACCEPTED_FINDINGS", "NO_BACKFILL_TARGET",
    "NO_BASELINE", "NO_CDC_SOURCE", "NO_HISTORY", "NO_HISTORY_OR_RETRIEVER", "NO_LOG_SOURCE", "NO_OBSERVATIONS",
    "NO_PROPOSAL", "NO_REMEDIATION_OPTIONS", "NO_SECOND_SOURCE", "NO_TIME_COLUMN", "NO_TYPE_SIGNAL",
    "SANDBOX_WRITES_DISABLED", "RAW_VALUE_IN_CONTEXT", "TOOL_NOT_ALLOWED", "NO_FAILED_AGENT", "NO_PROPOSALS",
    "INPUT_REJECTED", "RESULT_REJECTED", "TOOL_ERROR", "TOOL_BUDGET_EXCEEDED", "BUDGET_EXCEEDED", "NOT_SELECTED",
    "INTAKE_REJECTED", "EXECUTOR_ERROR", "DEPENDENCY_UNMET"})
TRANSPORTS = ("in_process", "mcp_local", "a2a_mtls")
MAX_ADVISORY_CHARS = 600


def _offline(uri):
    raise NoSuchResource(ref=uri)


def _schema(name):
    schema = json.loads(files("aegisflow_dr").joinpath("data", name + ".json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@lru_cache(maxsize=4)
def _validator(name):
    # The run record embeds tasks and results by their $id; every schema is packaged, nothing is fetched.
    schemas = [_schema(n) for n in ("agent-task-v1", "agent-result-v1", "agent-run-v1")]
    registry = Registry(retrieve=_offline).with_resources(
        (schema["$id"], DRAFT202012.create_resource(schema)) for schema in schemas)
    root = {"$ref": "urn:aegisflow:agents:run:1#/$defs/event"} if name == "event" else _schema(name)
    return Draft202012Validator(root, registry=registry)


def _string_keys(value):
    # json.dumps would coerce non-string keys and propertyNames ignores them, so check keys explicitly.
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("non-string key")
            _string_keys(item)
    elif isinstance(value, list):
        for item in value:
            _string_keys(item)


def _validate(name, label, value, extra=None):
    try:
        _string_keys(value)
        json.dumps(value, allow_nan=False)
        _validator(name).validate(value)
        if extra is not None and not extra(value):
            raise ValueError("semantic check")
    except (ValueError, TypeError, RecursionError, ValidationError):
        raise InputRejected("Agent %s contract rejected" % label) from None
    return value


def validate_task(value):
    """Return ``value`` unchanged when it satisfies ``agent-task-v1`` and its tools are within the role's allowlist."""
    return _validate("agent-task-v1", "task", value,
                     lambda task: set(task["allowed_tools"]) <= set(role(task["agent_id"]).allowed_tools))


def validate_result(value):
    """Return ``value`` unchanged when it satisfies ``agent-result-v1``; else raise InputRejected."""
    return _validate("agent-result-v1", "result", value)


def validate_run(value):
    """Return ``value`` unchanged when it satisfies ``agent-run-v1`` (tasks and results included); else raise."""
    return _validate("agent-run-v1", "run", value)


def validate_event(value):
    """Return ``value`` unchanged when it is a run event whose ``data`` matches its type's schema; else raise."""
    return _validate("event", "event", value)
