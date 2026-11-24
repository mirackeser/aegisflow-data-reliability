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

from ..pipeline import InputRejected
from .registry import role

STATUSES = ("COMPLETED", "NEEDS_EVIDENCE", "POLICY_DENIED", "SKIPPED", "FAILED")
TRANSPORTS = ("in_process", "mcp_local", "a2a_mtls")
MAX_ADVISORY_CHARS = 600


def _offline(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=2)
def _validator(name):
    schema = json.loads(files("aegisflow_dr").joinpath("data", name + ".json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=Registry(retrieve=_offline))


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
