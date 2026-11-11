# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, PropertyMock
import unittest
import test_usage
from aegisflow_dr.advisory.dispatch import Adapter, AdapterRequest, AdapterResult, dispatch
from aegisflow_dr.advisory.contracts import AdvisoryError, MAX_BYTES, decode, encode
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.usage import UsageLedger
from aegisflow_dr.storage.store import canonical, sha


class DispatchTests(unittest.TestCase):
    setUp = test_usage.UsageTests.setUp

    def response(self, assessment='NO_FAILURE_OBSERVED'):
        request = decode('request', self.prepared.request)
        return encode('response', {'version':'1', 'request_sha256':sha(self.prepared.request),
            'decision':'PROPOSE', 'assessment':assessment, 'evidence_sha256':request['evidence_sha256']})

    def run_dispatch(self, send=None, **kwargs):
        adapter = Adapter(self.quote.adapter_id, send or (lambda request: AdapterResult(self.response(), 10, 3)))
        return dispatch(self.prepared, self.quote, self.ledger, adapter,
                        attempt_key='dispatch', deadline_ms=2000, **kwargs)

    def test_exact_immutable_request_limits_and_success(self):
        before = self.evidence.read_bytes()
        def send(request):
            self.assertIs(type(request), AdapterRequest)
            self.assertEqual(request.messages, canonical(self.prepared.messages))
            self.assertEqual((request.remaining_ms,request.output_limit,request.max_response_bytes),(1000,5,MAX_BYTES))
            self.assertEqual(request.request_sha256, sha(self.prepared.request))
            self.assertEqual(request.model_id, self.quote.model_id)
            return AdapterResult(self.response(),10,3)
        result = self.run_dispatch(send)
        self.assertEqual(result['review']['status'], 'VERIFIED_ADVISORY')
        self.assertEqual(self.ledger.snapshot()['charged_cost_nusd'],29)
        self.assertEqual(before,self.evidence.read_bytes())

    def test_wrong_assessment_is_charged_but_judge_rejects(self):
        result=self.run_dispatch(lambda _:AdapterResult(self.response('SOURCE_QUALITY_FAILURE'),10,3))
        self.assertEqual(result['review']['status'],'REJECTED_ADVISORY')
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],13)

    def test_duplicate_after_restart_never_resends(self):
        self.run_dispatch()
        self.ledger=UsageLedger(self.path,clock_ms=lambda:1000)
        with self.assertRaises(AdvisoryError): self.run_dispatch(lambda _:self.fail('duplicate send'))

    def test_parallel_same_key_sends_once(self):
        calls=[]
        def send(request):
            calls.append(request)
            return AdapterResult(self.response(),10,3)
        def execute(_):
            try:return self.run_dispatch(send)['status']
            except AdvisoryError:return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(execute,(0,1))),['DENIED','REVIEWED'])
        self.assertEqual(len(calls),1)

    def test_bad_config_and_revision_never_reserve(self):
        values=[({},self.quote,self.ledger,Adapter(self.quote.adapter_id,lambda _:None)),
                (self.prepared,{},self.ledger,Adapter(self.quote.adapter_id,lambda _:None)),
                (self.prepared,self.quote,{},Adapter(self.quote.adapter_id,lambda _:None)),
                (self.prepared,self.quote,self.ledger,{}),
                (self.prepared,self.quote,self.ledger,Adapter('wrong',lambda _:None)),
                (self.prepared,self.quote,self.ledger,Adapter(self.quote.adapter_id,None))]
        for args in values:
            with self.assertRaises(AdvisoryError):dispatch(*args,attempt_key='x',deadline_ms=2000)
        self.assertEqual(self.ledger.snapshot()['attempts'],0)

    def test_changed_input_is_rejected(self):
        with patch.object(PreparedAdvisory,'messages',new_callable=PropertyMock,return_value=[]):
            with self.assertRaises(AdvisoryError):self.run_dispatch()
        self.assertEqual(self.ledger.snapshot()['attempts'],0)

    def test_exception_is_sanitized_and_retains_hold(self):
        def send(_):raise RuntimeError('private-adapter-detail')
        result=self.run_dispatch(send)
        self.assertEqual(result['status'],'USAGE_UNKNOWN')
        self.assertNotIn('private-adapter-detail',str(result))
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_cancellation_propagates_and_retains_hold(self):
        def send(_):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_dispatch(send)
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_invalid_result_and_invalid_usage_retain_full_hold(self):
        for value in (None,{},AdapterResult(b'{}',True,0),AdapterResult(b'{}',11,0),AdapterResult(b'{}',10,6)):
            with self.subTest(value=type(value).__name__):
                # Independent ledger/request scope for each invalid adapter outcome.
                path=self.root/('case-'+str(len(list(self.root.iterdir())))+'.db')
                from aegisflow_dr.advisory.usage import initialize_usage
                initialize_usage(path)
                self.ledger=UsageLedger(path,clock_ms=lambda:1000)
                self.assertEqual(self.run_dispatch(lambda _:value)['status'],'USAGE_UNKNOWN')
                self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_malformed_oversized_and_wrong_type_payloads_are_charged_rejections(self):
        for i,payload in enumerate((b'{', b'x'*(MAX_BYTES+1),'{}')):
            from aegisflow_dr.advisory.usage import initialize_usage
            path=self.root/f'response-{i}.db'
            initialize_usage(path)
            self.ledger=UsageLedger(path,clock_ms=lambda:1000)
            self.assertEqual(self.run_dispatch(lambda _:AdapterResult(payload,10,3))['status'],'RESPONSE_REJECTED')
            self.assertEqual(self.ledger.snapshot()['charged_tokens'],13)

    def test_late_result_is_charged_without_review(self):
        with patch.object(PreparedAdvisory,'review_response',side_effect=AssertionError):
            times=iter([0,1])
            result=self.run_dispatch(clock=lambda:next(times))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],13)

    def test_wall_deadline_rejects_result(self):
        def send(_):
            self.now=2000
            return AdapterResult(self.response(),10,3)
        self.assertEqual(self.run_dispatch(send)['status'],'DEADLINE_EXCEEDED')
        # The wall deadline branch is independent of the elapsed-clock check.

    def test_expiry_between_start_and_send_never_calls_adapter(self):
        ticks=iter([1000,1000,2000,2000])
        self.ledger.clock_ms=lambda:next(ticks)
        result=self.run_dispatch(lambda _:self.fail('expired call'))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_storage_failure_during_unknown_keeps_inflight_hold(self):
        original=self.ledger.transition
        def transition(attempt,action,**kwargs):
            if action=='unknown':raise AdvisoryError('ledger unavailable')
            return original(attempt,action,**kwargs)
        with patch.object(self.ledger,'transition',side_effect=transition):
            result=self.run_dispatch(lambda _:None)
        self.assertEqual(result['status'],'USAGE_UNKNOWN')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_admission_denial_never_calls_adapter(self):
        self.now=2000
        with self.assertRaises(AdvisoryError):self.run_dispatch(lambda _:self.fail('denied call'))
