# SPDX-License-Identifier: Apache-2.0
"""Versioned local JSON contracts with bounded parsing and offline references."""
from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

MAX_MESSAGE_BYTES = 16_384
CONTRACTS = frozenset({'task', 'proposal', 'verdict', 'receipt'})


class ContractError(ValueError):
    """A sanitized rejection; never include message values in errors."""


def _offline(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=4)
def _validator(name):
    if name not in CONTRACTS:
        raise ContractError('Unknown message contract')
    schema = json.loads(files('aegisflow_dr.coordination').joinpath('schemas', name + '-v1.json').read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=Registry(retrieve=_offline))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('Duplicate message field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ContractError('Nonfinite JSON value')


def parse(name: str, payload: bytes) -> dict:
    if type(name) is not str or name not in CONTRACTS:
        raise ContractError('Unknown message contract')
    if type(payload) is not bytes or len(payload) > MAX_MESSAGE_BYTES:
        raise ContractError('Message exceeds input contract')
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        _validator(name).validate(value)
        return value
    except (ValueError, TypeError, RecursionError, ValidationError):
        raise ContractError('Message contract rejected') from None


def encode(name: str, value: dict) -> bytes:
    """Validate outbound messages too; return a detached canonical byte sequence."""
    try:
        payload = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ContractError('Message contract rejected') from None
    parse(name, payload)
    return payload
