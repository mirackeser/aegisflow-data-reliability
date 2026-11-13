# SPDX-License-Identifier: Apache-2.0
import json
import unittest
from unittest.mock import patch

from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.qualification import qualify_operations
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.advisory.routing import execute_route


class OperationalQualificationTests(unittest.TestCase):
    def test_integrated_scenarios_accounting_recovery_and_no_activation(self):
        report = qualify_operations()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(report['scenarios']), 7)
        self.assertEqual(sum(case['adapter_invocations'] for case in report['scenarios']), 7)
        self.assertEqual(report['interrupted_worker'], 'BLOCKED_WITH_HOLD')
        self.assertFalse(report['live_activation_authorized'])
        self.assertEqual(report['live_provider_calls'], 0)
        text = json.dumps(report)
        for forbidden in ('messages', 'attempt_id', 'operator_id', 'synthetic ambiguity', 'Bearer'):
            self.assertNotIn(forbidden, text)
        self.assertIn('independent_model_quality', report['unverified_live_boundaries'])

    def test_repeated_execution_isolated_and_report_reproducible(self):
        self.assertEqual(qualify_operations(), qualify_operations())

    def test_incorrect_totals_cannot_receive_pass_report(self):
        def corrupt(ledger):
            result = assess_recovery(ledger)
            result['assessment']['usage']['charged_cost_nusd'] = 0
            return result
        with patch('aegisflow_dr.advisory.qualification.assess_recovery', side_effect=corrupt):
            with self.assertRaisesRegex(AdvisoryError, 'qualification failed'): qualify_operations()

    def test_unexpected_resume_cannot_receive_pass_report(self):
        def unsafe(ledger, candidates, **kwargs):
            if ledger.path.name == 'interrupted.db': return {'status':'RUNNING'}
            return execute_route(ledger,candidates,**kwargs)
        with patch('aegisflow_dr.advisory.qualification.execute_route', side_effect=unsafe):
            with self.assertRaisesRegex(AdvisoryError, 'Interrupted route was resumed'): qualify_operations()
