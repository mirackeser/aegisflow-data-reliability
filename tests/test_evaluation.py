# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.evaluation import evaluate_development_suite


class DevelopmentEvaluationTests(unittest.TestCase):
    def test_labeled_scenarios_agree_without_claiming_model_accuracy(self):
        report = evaluate_development_suite()
        self.assertEqual(report['matching_cases'], 10)
        self.assertEqual(report['case_count'], 10)
        self.assertTrue(report['all_matched'])
        self.assertEqual(report['model_calls'], 0)
        self.assertFalse(report['held_out_benchmark'])
        self.assertEqual(report['suite_kind'], 'development_regression')
        self.assertTrue(all(case['calls_used'] <= 3 for case in report['cases']))

    def test_packaged_and_reviewed_fixture_match(self):
        self.assertEqual(files('aegisflow_dr').joinpath('data/investigation-development-v1.json').read_bytes(),
                         Path('fixtures/evaluations/investigation-development-v1.json').read_bytes())

    def test_changed_expected_label_fails_instead_of_steering_the_workflow(self):
        suite = json.loads(Path('fixtures/evaluations/investigation-development-v1.json').read_text())
        suite['cases'][0]['expected_assessment'] = 'SOURCE_QUALITY_FAILURE'
        with patch('aegisflow_dr.evaluation.files') as resource:
            resource.return_value.joinpath.return_value.read_bytes.return_value = json.dumps(suite).encode()
            report = evaluate_development_suite()
        self.assertFalse(report['all_matched'])
        self.assertEqual(report['cases'][0]['actual_assessment'], 'NO_FAILURE_OBSERVED')
        self.assertEqual(report['matching_cases'], 9)

    def test_invalid_or_duplicate_cases_are_rejected_before_execution(self):
        original = json.loads(Path('fixtures/evaluations/investigation-development-v1.json').read_text())
        for mutation in ['duplicate', 'unknown_field', 'unknown_tool']:
            suite = deepcopy(original)
            if mutation == 'duplicate': suite['cases'].append(suite['cases'][0])
            elif mutation == 'unknown_field': suite['cases'][0]['policy'] = 'override'
            else: suite['cases'][0]['expected_tools'] = ['arbitrary']
            with self.subTest(mutation=mutation), patch('aegisflow_dr.evaluation.files') as resource, \
                 patch('aegisflow_dr.evaluation.investigate') as workflow:
                resource.return_value.joinpath.return_value.read_bytes.return_value = json.dumps(suite).encode()
                with self.assertRaises(ValueError): evaluate_development_suite()
                workflow.assert_not_called()
