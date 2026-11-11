# SPDX-License-Identifier: Apache-2.0
import unittest
from unittest.mock import patch
import test_dispatch
from aegisflow_dr.advisory.dispatch import AdapterFailure
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.context import PreparedAdvisory


class FailureTests(unittest.TestCase):
    setUp = test_dispatch.DispatchTests.setUp
    run_dispatch = test_dispatch.DispatchTests.run_dispatch

    def test_known_zero_usage_releases_hold_without_review(self):
        with patch.object(PreparedAdvisory,'review_response',side_effect=AssertionError):
            result=self.run_dispatch(lambda _:AdapterFailure('RETRYABLE',0,0))
        self.assertEqual(result['status'],'KNOWN_RETRYABLE_FAILURE')
        self.assertIsNone(result['review'])
        self.assertEqual(self.ledger.snapshot()['held_tokens'],0)
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],0)

    def test_terminal_failure_still_charges_known_usage(self):
        result=self.run_dispatch(lambda _:AdapterFailure('TERMINAL',10,2))
        self.assertEqual(result['status'],'KNOWN_TERMINAL_FAILURE')
        self.assertEqual(self.ledger.snapshot()['charged_cost_nusd'],26)

    def test_unknown_failure_kind_retains_full_hold(self):
        result=self.run_dispatch(lambda _:AdapterFailure('http-429',0,0))
        self.assertEqual(result['status'],'USAGE_UNKNOWN')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_invalid_usage_never_refunds_known_failure(self):
        result=self.run_dispatch(lambda _:AdapterFailure('RETRYABLE',False,0))
        self.assertEqual(result['status'],'USAGE_UNKNOWN')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_late_known_failure_charges_but_cannot_request_retry(self):
        times=iter([0,1])
        result=self.run_dispatch(lambda _:AdapterFailure('RETRYABLE',10,2),clock=lambda:next(times))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],12)

    def test_retryable_label_never_automatically_resends(self):
        calls=[]
        def send(request):
            calls.append(request)
            return AdapterFailure('RETRYABLE',0,0)
        self.run_dispatch(send)
        with self.assertRaises(AdvisoryError):self.run_dispatch(send)
        self.assertEqual(len(calls),1)

    def test_settlement_failure_retains_hold(self):
        original=self.ledger.transition
        def transition(attempt,action,**kwargs):
            if action=='settle':raise AdvisoryError('unavailable')
            return original(attempt,action,**kwargs)
        with patch.object(self.ledger,'transition',side_effect=transition):
            result=self.run_dispatch(lambda _:AdapterFailure('TERMINAL',0,0))
        self.assertEqual(result['status'],'USAGE_UNKNOWN')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)
