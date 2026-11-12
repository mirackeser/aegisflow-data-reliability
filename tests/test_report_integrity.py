# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest

from aegisflow_dr.benchmark.core import BenchmarkError, LABELS, load_suite, score
from aegisflow_dr.benchmark.report import validate_report
from aegisflow_dr.benchmark.runner import evaluate_baseline


class ReportIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline=evaluate_baseline()

    def test_overall_counts_and_rates_cannot_be_forged(self):
        for key,value in (('correct',0),('case_count',7),('coverage',0.5),('exact_match',0.1),('errors',1)):
            report=deepcopy(self.baseline);report['splits']['validation']['metrics'][key]=value
            with self.subTest(key=key),self.assertRaises(BenchmarkError):validate_report(report)

    def test_family_and_class_results_are_recomputed(self):
        report=deepcopy(self.baseline)
        report['splits']['validation']['metrics']['per_class'][LABELS[0]]['precision']=0
        with self.assertRaises(BenchmarkError):validate_report(report)
        report=deepcopy(self.baseline)
        family=next(iter(report['splits']['validation']['families'].values()))
        family['correct']=0
        with self.assertRaises(BenchmarkError):validate_report(report)

    def test_gate_cannot_be_flipped_independently(self):
        report=deepcopy(self.baseline);report['regression_gate_passed']=False
        with self.assertRaises(BenchmarkError):validate_report(report)

    def test_dataset_digest_and_prediction_coverage_are_bound(self):
        report=deepcopy(self.baseline);report['suite_sha256']='a'*64
        with self.assertRaises(BenchmarkError):validate_report(report)
        for mutation in ('missing','duplicate','unknown'):
            report=deepcopy(self.baseline)
            if mutation=='missing':report['predictions'].pop()
            if mutation=='duplicate':report['predictions'][-1]=report['predictions'][0]
            if mutation=='unknown':report['predictions'][0]['case_id']='unknown'
            with self.subTest(mutation=mutation),self.assertRaises(BenchmarkError):validate_report(report)

    def test_changed_predictions_require_updated_metrics_and_gate(self):
        report=deepcopy(self.baseline);report['predictions'][0]['assessment']='ABSTAIN'
        with self.assertRaises(BenchmarkError):validate_report(report)
        suite,_=load_suite();report['splits']=score(suite,report['predictions']);report['regression_gate_passed']=False
        self.assertEqual(validate_report(report),report)

    def test_valid_report_validation_does_not_mutate_input(self):
        report=deepcopy(self.baseline);before=deepcopy(report)
        validate_report(report);self.assertEqual(before,report)
