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
OPERATION = closed({'version': {'const': '1'}, 'operation_id': UUID,
    'run_id': UUID, 'incident_id': UUID, 'record_sha256': HASH,
    'prompt_sha256': HASH, 'context_sha256': HASH, 'response_schema_sha256': HASH,
    'evidence_sha256': {**REFERENCES, 'minItems': 1},
    'allowed_models': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                       'uniqueItems': True, 'items': REQUEST['properties']['model_id']},
    'deadline_ms': {'type': 'integer', 'minimum': 0, 'maximum': 10**18}})
ROUTE_STEP = closed({'model_id': REQUEST['properties']['model_id'],
    'request_sha256': HASH, 'input_sha256': HASH, 'quote_sha256': HASH})
ROUTE_PLAN = closed({'version': {'const': '1'}, 'operation_sha256': HASH,
    'steps': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': ROUTE_STEP}})
DISPATCH_STATUSES = ['KNOWN_RETRYABLE_FAILURE', 'KNOWN_TERMINAL_FAILURE', 'USAGE_UNKNOWN',
                     'DEADLINE_EXCEEDED', 'RESPONSE_REJECTED', 'REVIEWED']
REVIEW_STATUSES = ['VERIFIED_ADVISORY', 'REJECTED_ADVISORY', 'ABSTAIN']
ROUTE_EVENT = closed({'index': {'type': 'integer', 'minimum': 0, 'maximum': 7},
    'model_id': REQUEST['properties']['model_id'], 'request_sha256': HASH, 'attempt_id': UUID,
    'status': {'enum': DISPATCH_STATUSES}, 'review_status': {'enum': REVIEW_STATUSES + [None]}})
ROUTE_EVENT.update({'if': {'properties': {'status': {'const': 'REVIEWED'}}},
    'then': {'properties': {'review_status': {'enum': REVIEW_STATUSES}}},
    'else': {'properties': {'review_status': {'type': 'null'}}}})
RECOVERY_REVIEW = closed({'version': {'const': '1'}, 'review_id': UUID, 'operator_id': UUID,
    'operation_sha256': HASH, 'snapshot_sha256': HASH, 'assessment_sha256': HASH,
    'action': {'enum': ['KEEP_BLOCKED', 'REQUEST_USAGE_ATTESTATION']}})
TIME = {'type':'integer','minimum':0,'maximum':10**18}
PURPOSES = ('usage-attestation', 'recovery-decision')
SIGNED = closed({'version':{'const':'1'}, 'purpose':{'enum':list(PURPOSES)},
    'principal_id':UUID, 'operation_sha256':HASH, 'key_sha256':HASH, 'payload_sha256':HASH,
    'issued_at_ms':TIME, 'expires_at_ms':TIME})
ENVELOPE = closed({**SIGNED['properties'], 'signature':{'type':'string','pattern':'^[0-9a-f]{128}$',
                                                    'minLength':128,'maxLength':128}})
ATTESTATION = closed({'version':{'const':'1'}, 'operation_sha256':HASH, 'snapshot_sha256':HASH,
    'assessment_sha256':HASH, 'attempt_id':UUID, 'request_sha256':HASH,
    'input_sha256':HASH, 'quote_sha256':HASH, 'receipt_sha256':HASH,
    'input_tokens':{'type':'integer','minimum':0,'maximum':10**6},
    'output_tokens':{'type':'integer','minimum':0,'maximum':10**6}})
DECISION = closed({'version':{'const':'1'},'review_sha256':HASH,
    'attestation_sha256':{'anyOf':[HASH,{'type':'null'}]},
    'attestation_signature_sha256':{'anyOf':[HASH,{'type':'null'}]}})
DECISION_SCOPE = closed({'operation_sha256':HASH})
SCHEMAS = {'recovery-decision':DECISION,'recovery-signature-metadata':SIGNED,'recovery-signature':ENVELOPE,
           'usage-attestation':ATTESTATION,'recovery-decision-scope':DECISION_SCOPE,'recovery-review': RECOVERY_REVIEW, 'request': REQUEST, 'response': RESPONSE, 'operation': OPERATION,
           'route-plan': ROUTE_PLAN, 'route-event': ROUTE_EVENT}


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
