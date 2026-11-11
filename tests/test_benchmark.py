# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from contextlib import redirect_stdout
import io
from importlib.resources import files
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jsonschema import Draft202012Validator
from aegisflow_dr.benchmark.core import (BenchmarkError, LABELS, SUITE_SCHEMA, PREDICTION_SCHEMA,
    canonical, load_suite, parse, ratio, score, signature, validate_suite)
from aegisflow_dr.benchmark.report import REPORT_SCHEMA, validate_report
from aegisflow_dr.benchmark.runner import _execute, evaluate_baseline


def predictions(suite):
    return [{'case_id': case['case_id'], 'assessment': case['expected_assessment'],
             'tools': list(case['expected_tools'])} for case in suite['cases']]


class BenchmarkContractsTests(unittest.TestCase):
    def setUp(self):
        self.suite, self.digest = load_suite()

    def test_frozen_public_suite_and_exported_schemas_are_packaged(self):
        root = files('aegisflow_dr.benchmark').joinpath('data')
        for suffix in ('json', 'sha256'):
            self.assertEqual(root.joinpath('public-validation-v1.' + suffix).read_bytes(),
                Path('fixtures/evaluations/public-validation-v1.' + suffix).read_bytes())
        for name, schema in [('suite', SUITE_SCHEMA), ('prediction', PREDICTION_SCHEMA), ('report', REPORT_SCHEMA)]:
            Draft202012Validator.check_schema(schema)
            self.assertEqual(json.loads(Path('docs/contracts/benchmark-' + name + '-v1.json').read_text()), schema)
        self.assertEqual(len(self.suite['cases']), 18)
        self.assertEqual(len(self.digest), 64)

    def test_original_development_cases_remain_exactly_represented(self):
        original = json.loads(Path('fixtures/evaluations/investigation-development-v1.json').read_text())['cases']
        actual = [{key: value for key, value in case.items() if key not in ('split', 'family', 'group_id')}
                  for case in self.suite['cases'] if case['split'] == 'development']
        self.assertEqual(actual, original)

    def test_digest_change_is_rejected_before_execution(self):
        with patch('aegisflow_dr.benchmark.core.files') as resource:
            resource.return_value.joinpath.return_value.joinpath.return_value.read_bytes.return_value = b'{}'
            resource.return_value.joinpath.return_value.joinpath.return_value.read_text.return_value = 'a' * 64
            with self.assertRaises(BenchmarkError):
                load_suite()

    def test_malformed_duplicate_unknown_and_nonfinite_contracts_reject(self):
        for value in [None, b'x' * 1_000_001, b'\xff', b'{', b'{"x":1,"x":2}', b'[' * 1100, b'NaN', b'Infinity']:
            with self.assertRaises(BenchmarkError):
                parse(value)
        for value in [float('nan'), float('inf'), {'x': '\ud800'}, object()]:
            with self.assertRaises(BenchmarkError):
                canonical(value)
        for change in [{'extra': True}, {'version': '2'}, {'visibility': 'blind'}, {'cases': []}]:
            with self.assertRaises(BenchmarkError):
                validate_suite(self.suite | change)
        suite = deepcopy(self.suite)
        suite['cases'][0]['csv_text'] = '\ud800'
        with self.assertRaises(BenchmarkError):
            validate_suite(suite)

    def test_duplicate_case_missing_split_and_invalid_case_reject(self):
        for mutation in ('duplicate', 'split', 'label', 'tool', 'boolean', 'field'):
            suite = deepcopy(self.suite)
            if mutation == 'duplicate': suite['cases'].append(suite['cases'][0])
            elif mutation == 'split': suite['cases'] = suite['cases'][:10]
            elif mutation == 'label': suite['cases'][0]['expected_assessment'] = 'CERTAIN'
            elif mutation == 'tool': suite['cases'][0]['expected_tools'] = ['write']
            elif mutation == 'boolean': suite['cases'][0]['csv_text'] = True
            else: suite['cases'][0]['policy'] = 'admin'
            with self.assertRaises(BenchmarkError): validate_suite(suite)

    def test_group_family_and_near_copy_leakage_reject(self):
        for field in ('group_id', 'family', 'csv_text'):
            suite = deepcopy(self.suite)
            suite['cases'][-1][field] = suite['cases'][0][field]
            with self.assertRaises(BenchmarkError): validate_suite(suite)
        self.assertEqual(signature('\ufeffb,a\n 2 ,1\n'), signature('a,b\n1,2\n'))
        with self.assertRaises(BenchmarkError): signature('a,b\n"unterminated')

    def test_prediction_shape_coverage_duplicates_and_unknown_ids_reject(self):
        base = predictions(self.suite)
        variants = [None, [], base * 5, base[:-1], base + [base[0]],
                    [dict(base[0], assessment='unknown')] + base[1:],
                    [dict(base[0], case_id='unknown')] + base[1:],
                    [dict(base[0], confidence=1)] + base[1:]]
        for value in variants:
            with self.assertRaises(BenchmarkError): score(self.suite, value)

    def test_perfect_scores_have_explicit_denominators_and_undefined_rates(self):
        result = score(self.suite, predictions(self.suite))
        for split, count in [('development', 10), ('validation', 8)]:
            self.assertEqual(result[split]['metrics']['case_count'], count)
            self.assertEqual(result[split]['metrics']['correct'], count)
            self.assertEqual(result[split]['metrics']['exact_match'], 1)
        self.assertIsNone(ratio(0, 0))
        family = result['validation']['families']['quoted-records']
        self.assertEqual(family['per_class'][LABELS[1]]['support'], 0)
        self.assertIsNone(family['per_class'][LABELS[1]]['recall'])

    def test_wrong_labels_false_positives_and_false_negatives_count(self):
        value = predictions(self.suite)
        value[0]['assessment'] = LABELS[1]  # healthy -> failure
        value[1]['assessment'] = LABELS[0]  # failure -> healthy
        result = score(self.suite, value)['development']['metrics']
        self.assertEqual(result['correct'], 8)
        self.assertEqual(result['failure_detection']['false_positive'], 1)
        self.assertEqual(result['failure_detection']['false_negative'], 1)
        self.assertEqual(result['per_class'][LABELS[1]]['false_positive'], 1)
        self.assertEqual(result['confusion'][LABELS[0]][LABELS[1]], 1)

    def test_abstentions_errors_and_selective_accuracy_do_not_inflate_exact_match(self):
        value = predictions(self.suite)
        value[1]['assessment'] = 'ABSTAIN'
        value[2]['assessment'] = 'ERROR'
        result = score(self.suite, value)['development']['metrics']
        self.assertEqual(result['exact_match'], .8)
        self.assertEqual(result['coverage'], .8)
        self.assertEqual(result['selective_accuracy'], 1)
        self.assertEqual(result['abstentions'], 1)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['failure_detection']['abstentions'], 1)
        self.assertEqual(result['failure_detection']['errors'], 1)
        for prediction in value: prediction['assessment'] = 'ABSTAIN'
        result = score(self.suite, value)['validation']['metrics']
        self.assertEqual(result['exact_match'], 0)
        self.assertEqual(result['coverage'], 0)
        self.assertIsNone(result['selective_accuracy'])

    def test_tool_order_scored_independently_of_assessment(self):
        value = predictions(self.suite)
        value[0]['tools'].reverse()
        result = score(self.suite, value)['development']['metrics']
        self.assertEqual(result['correct'], 10)
        self.assertEqual(result['tool_sequence_matches'], 9)


class BenchmarkRunnerTests(unittest.TestCase):
    def test_baseline_repeatable_and_not_model_or_blind_holdout_accuracy(self):
        first, second = evaluate_baseline(), evaluate_baseline()
        self.assertEqual(first, second)
        self.assertTrue(first['regression_gate_passed'])
        self.assertEqual(first['splits']['validation']['metrics']['correct'], 8)
        self.assertEqual(first['model_calls'], 0)
        self.assertFalse(first['blind_holdout'])
        self.assertEqual(first['scope'], 'public_synthetic_deterministic_validation')
        validate_report(first)

    def test_labels_are_not_execution_inputs(self):
        from aegisflow_dr.benchmark.runner import _execute as real_execute
        suite, digest = load_suite()
        suite['cases'][0]['expected_assessment'] = LABELS[1]
        with patch('aegisflow_dr.benchmark.runner.load_suite', return_value=(suite, digest)), \
             patch('aegisflow_dr.benchmark.runner._execute', wraps=real_execute) as execution:
            result = evaluate_baseline()
        self.assertFalse(result['regression_gate_passed'])
        self.assertEqual(result['predictions'][0]['assessment'], LABELS[0])
        self.assertEqual(execution.call_args_list[0].args,
                         (suite['cases'][0]['csv_text'], suite['cases'][0]['transform']))

    def test_unsupported_result_abstention_and_sanitized_failure(self):
        source = 'order_id,customer_id,order_total\nX,Y,1\n'
        for status, assessment, expected in [('COMPLETED', 'invalid', 'ERROR'),
                                             ('INCONCLUSIVE', None, 'ABSTAIN')]:
            fake = SimpleNamespace(status=status, assessment=assessment, steps=[],
                                   implementation_sha256='a' * 64, policy_sha256='b' * 64)
            with patch('aegisflow_dr.benchmark.runner.investigate', return_value=fake):
                self.assertEqual(_execute(source, 'clean')[0], expected)
        with patch('aegisflow_dr.benchmark.runner.initialize', side_effect=OSError('private-path')):
            self.assertEqual(_execute(source, 'clean'), ('ERROR', [], None, None))

    def test_all_errors_fail_regression_gate_without_fabricating_fingerprints(self):
        with patch('aegisflow_dr.benchmark.runner._execute', return_value=('ERROR', [], None, None)):
            report = evaluate_baseline()
        self.assertFalse(report['regression_gate_passed'])
        self.assertEqual(report['implementation_sha256'], [])
        self.assertEqual(report['splits']['validation']['metrics']['errors'], 8)

    def test_invalid_report_cannot_claim_model_or_blind_evaluation(self):
        report = evaluate_baseline()
        for mutation in ({'model_calls': 1}, {'blind_holdout': True}, {'unexpected': True}):
            with self.assertRaises(BenchmarkError): validate_report(report | mutation)

    def test_cli_emits_closed_report_and_success_exit(self):
        result = subprocess.run([sys.executable, '-m', 'aegisflow_dr.benchmark'],
            capture_output=True, text=True, timeout=20,
            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')})
        self.assertEqual(result.returncode, 0, result.stderr)
        validate_report(json.loads(result.stdout))

    def test_cli_failure_gate_returns_nonzero_exit(self):
        with patch('aegisflow_dr.benchmark.runner._execute', return_value=('ERROR', [], None, None)):
            report = evaluate_baseline()
        output = io.StringIO()
        with patch('aegisflow_dr.benchmark.runner.evaluate_baseline', return_value=report), \
             redirect_stdout(output), self.assertRaises(SystemExit) as exited:
            runpy.run_module('aegisflow_dr.benchmark', run_name='__main__')
        self.assertEqual(exited.exception.code, 1)
        self.assertFalse(json.loads(output.getvalue())['regression_gate_passed'])
