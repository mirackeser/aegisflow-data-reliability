# SPDX-License-Identifier: Apache-2.0
"""Bounded provider-neutral metadata and response contracts."""
import json
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

MAX_BYTES = 16_384
LABELS = ['NO_FAILURE_OBSERVED', 'SOURCE_QUALITY_FAILURE', 'TRANSFORMATION_RECONCILIATION_FAILURE']
HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$', 'minLength': 64, 'maxLength': 64}
UUID = {'type': 'string', 'pattern': '^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$',
        'minLength': 36, 'maxLength': 36}
REFERENCES = {'type': 'array', 'items': HASH, 'uniqueItems': True, 'maxItems': 4}


def closed(properties):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}


REQUEST = closed({'version': {'const': '1'}, 'request_id': UUID, 'run_id': UUID,
    'incident_id': UUID, 'record_sha256': HASH, 'prompt_sha256': HASH,
    'model_id': {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9._/-]{0,63}$',
                 'maxLength': 64, 'not': {'pattern': '\\s'}},
    'evidence_sha256': {**REFERENCES, 'minItems': 1}})
RESPONSE = closed({'version': {'const': '1'}, 'request_sha256': HASH,
    'decision': {'enum': ['PROPOSE', 'ABSTAIN']},
    'assessment': {'enum': LABELS + [None]}, 'evidence_sha256': REFERENCES})
RESPONSE.update({'if': {'properties': {'decision': {'const': 'ABSTAIN'}}},
    'then': {'properties': {'assessment': {'type': 'null'}, 'evidence_sha256': {'maxItems': 0}}},
    'else': {'properties': {'assessment': {'enum': LABELS}, 'evidence_sha256': {'minItems': 1}}}})
SCHEMAS = {'request': REQUEST, 'response': RESPONSE}


class AdvisoryError(ValueError):
    """Sanitized metadata/response rejection."""


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AdvisoryError('Advisory contract rejected')
        value[key] = item
    return value


def _constant(value):
    raise AdvisoryError('Advisory contract rejected')


def decode(name, payload):
    if type(name) is not str or name not in SCHEMAS or type(payload) is not bytes or len(payload) > MAX_BYTES:
        raise AdvisoryError('Advisory contract rejected')
    try:
        value = json.loads(payload.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
        Draft202012Validator(SCHEMAS[name]).validate(value)
        # Reject escaped lone surrogates even where a schema allows a string.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        return value
    except (ValueError, TypeError, RecursionError, ValidationError):
        raise AdvisoryError('Advisory contract rejected') from None


def encode(name, value):
    try:
        payload = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError):
        raise AdvisoryError('Advisory contract rejected') from None
    decode(name, payload)
    return payload
