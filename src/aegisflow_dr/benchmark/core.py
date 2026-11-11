# SPDX-License-Identifier: Apache-2.0
"""Strict split validation and denominator-explicit deterministic scoring."""
import csv
from hashlib import sha256
from importlib.resources import files
import io
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

LABELS = ('NO_FAILURE_OBSERVED', 'SOURCE_QUALITY_FAILURE', 'TRANSFORMATION_RECONCILIATION_FAILURE')
PREDICTIONS = (*LABELS, 'ABSTAIN', 'ERROR')
TOOLS = ['diagnose_csv', 'run_batch', 'query_lineage']
ID = {'type': 'string', 'pattern': '^[a-z0-9-]{1,64}$'}


class BenchmarkError(ValueError):
    """Constant failure message without raw data or parser detail."""


def closed(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


CASE_SCHEMA = closed({'case_id': ID, 'split': {'enum': ['development', 'validation']},
    'family': ID, 'group_id': ID, 'csv_text': {'type': 'string', 'maxLength': 16_384},
    'transform': {'enum': ['clean', 'exclude_first']}, 'expected_assessment': {'enum': list(LABELS)},
    'expected_tools': {'type': 'array', 'items': {'enum': TOOLS}, 'minItems': 1, 'maxItems': 3, 'uniqueItems': True}})
SUITE_SCHEMA = closed({'version': {'const': '1'}, 'suite_id': {'const': 'public-validation-v1'},
    'visibility': {'const': 'public_synthetic'},
    'cases': {'type': 'array', 'items': CASE_SCHEMA, 'minItems': 2, 'maxItems': 64}})
PREDICTION_SCHEMA = closed({'case_id': ID, 'assessment': {'enum': list(PREDICTIONS)},
    'tools': {'type': 'array', 'items': {'enum': TOOLS}, 'maxItems': 3, 'uniqueItems': True}})


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise BenchmarkError('Benchmark contract rejected') from None


def validate(schema, value):
    try:
        Draft202012Validator(schema).validate(value)
        canonical(value)
    except ValidationError:
        raise BenchmarkError('Benchmark contract rejected') from None


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BenchmarkError('Benchmark contract rejected')
        value[key] = item
    return value


def parse(raw):
    if type(raw) is not bytes or len(raw) > 1_000_000:
        raise BenchmarkError('Benchmark contract rejected')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        raise BenchmarkError('Benchmark contract rejected') from None


def _constant(value):
    raise BenchmarkError('Benchmark contract rejected')


def signature(text):
    """Conservative cross-split near-copy check; not a proof of independence."""
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff')), strict=True))
        # Ignore row order, surrounding whitespace and header column order.
        normalized = [sorted(cell.strip() for cell in row) for row in rows]
        return sha256(canonical(sorted(normalized))).hexdigest()
    except csv.Error:
        raise BenchmarkError('Benchmark CSV rejected') from None


def validate_suite(suite):
    validate(SUITE_SCHEMA, suite)
    seen, splits, groups, signatures, families = set(), set(), {}, {}, {}
    for case in suite['cases']:
        name, split = case['case_id'], case['split']
        if name in seen:
            raise BenchmarkError('Duplicate benchmark case')
        seen.add(name)
        splits.add(split)
        for mapping, key in ((groups, case['group_id']), (signatures, signature(case['csv_text'])),
                             (families, case['family'])):
            if key in mapping and mapping[key] != split:
                raise BenchmarkError('Cross-split leakage rejected')
            mapping[key] = split
    if splits != {'development', 'validation'}:
        raise BenchmarkError('Both benchmark splits required')
    return suite


def load_suite():
    root = files('aegisflow_dr.benchmark').joinpath('data')
    raw = root.joinpath('public-validation-v1.json').read_bytes()
    expected = root.joinpath('public-validation-v1.sha256').read_text().strip()
    if sha256(raw).hexdigest() != expected:
        raise BenchmarkError('Frozen suite digest mismatch')
    return validate_suite(parse(raw)), sha256(raw).hexdigest()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def metrics(cases, predictions):
    matrix = {label: {actual: 0 for actual in PREDICTIONS} for label in LABELS}
    matched_tools = 0
    for case in cases:
        prediction = predictions[case['case_id']]
        matrix[case['expected_assessment']][prediction['assessment']] += 1
        matched_tools += prediction['tools'] == case['expected_tools']
    total = len(cases)
    correct = sum(matrix[label][label] for label in LABELS)
    abstentions = sum(row['ABSTAIN'] for row in matrix.values())
    errors = sum(row['ERROR'] for row in matrix.values())
    per_class = {}
    for label in LABELS:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        predicted = sum(row[label] for row in matrix.values())
        per_class[label] = {'support': support, 'true_positive': tp,
            'false_positive': predicted - tp, 'false_negative': support - tp,
            'precision': ratio(tp, predicted), 'recall': ratio(tp, support),
            'f1': ratio(2 * tp, support + predicted)}
    failure_labels = LABELS[1:]
    return {'case_count': total, 'correct': correct, 'abstentions': abstentions, 'errors': errors,
        'coverage': ratio(total - abstentions - errors, total), 'exact_match': ratio(correct, total),
        'selective_accuracy': ratio(correct, total - abstentions - errors),
        'tool_sequence_matches': matched_tools, 'confusion': matrix, 'per_class': per_class,
        'failure_detection': {
            'true_positive': sum(matrix[e][a] for e in failure_labels for a in failure_labels),
            'false_positive': sum(matrix[LABELS[0]][a] for a in failure_labels),
            'false_negative': sum(matrix[e][LABELS[0]] for e in failure_labels),
            'abstentions': sum(matrix[e]['ABSTAIN'] for e in failure_labels),
            'errors': sum(matrix[e]['ERROR'] for e in failure_labels)}}


def score(suite, predictions):
    validate_suite(suite)
    if type(predictions) is not list or not 1 <= len(predictions) <= 64:
        raise BenchmarkError('Benchmark predictions rejected')
    indexed = {}
    for prediction in predictions:
        validate(PREDICTION_SCHEMA, prediction)
        if prediction['case_id'] in indexed:
            raise BenchmarkError('Duplicate benchmark prediction')
        indexed[prediction['case_id']] = prediction
    if set(indexed) != {case['case_id'] for case in suite['cases']}:
        raise BenchmarkError('Benchmark prediction coverage mismatch')
    result = {}
    for split in ('development', 'validation'):
        cases = [case for case in suite['cases'] if case['split'] == split]
        measured = metrics(cases, indexed)
        result[split] = {'metrics': measured, 'families': {
            family: metrics([case for case in cases if case['family'] == family], indexed)
            for family in sorted({case['family'] for case in cases})}}
    return result
