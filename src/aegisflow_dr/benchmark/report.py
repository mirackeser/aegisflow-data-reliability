# SPDX-License-Identifier: Apache-2.0
"""Versioned report envelope with explicit counts and undefined metric values."""
from .core import LABELS, PREDICTIONS, PREDICTION_SCHEMA, closed, validate

COUNT = {'type': 'integer', 'minimum': 0, 'maximum': 64}
HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
RATE = {'type': ['number', 'null'], 'minimum': 0, 'maximum': 1}
PER_CLASS = closed({**{key: COUNT for key in ('support', 'true_positive', 'false_positive', 'false_negative')},
                    **{key: RATE for key in ('precision', 'recall', 'f1')}})
METRICS = closed({**{key: COUNT for key in ('case_count', 'correct', 'abstentions', 'errors', 'tool_sequence_matches')},
    **{key: RATE for key in ('coverage', 'exact_match', 'selective_accuracy')},
    'confusion': closed({label: closed({prediction: COUNT for prediction in PREDICTIONS}) for label in LABELS}),
    'per_class': closed({label: PER_CLASS for label in LABELS}),
    'failure_detection': closed({key: COUNT for key in ('true_positive', 'false_positive', 'false_negative',
                                                       'abstentions', 'errors')})})
PART = closed({'metrics': METRICS, 'families': {'type': 'object', 'additionalProperties': False,
    'patternProperties': {'^[a-z0-9-]{1,64}$': METRICS}, 'minProperties': 1, 'maxProperties': 64}})
REPORT_SCHEMA = closed({'version': {'const': '1'}, 'suite_id': {'const': 'public-validation-v1'},
    'suite_sha256': HASH, 'scorer_sha256': HASH,
    'implementation_sha256': {'type': 'array', 'items': HASH, 'maxItems': 64, 'uniqueItems': True},
    'policy_sha256': {'type': 'array', 'items': HASH, 'maxItems': 64, 'uniqueItems': True},
    'model_calls': {'const': 0}, 'blind_holdout': {'const': False},
    'scope': {'const': 'public_synthetic_deterministic_validation'},
    'splits': closed({split: PART for split in ('development', 'validation')}),
    'predictions': {'type': 'array', 'items': PREDICTION_SCHEMA, 'minItems': 2, 'maxItems': 64},
    'regression_gate_passed': {'type': 'boolean'}})


def validate_report(report):
    validate(REPORT_SCHEMA, report)
    return report
