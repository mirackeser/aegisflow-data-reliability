# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
import unittest
import test_dispatch
from aegisflow_dr.advisory.retry import RetryPolicy, retry_dispatch
from aegisflow_dr.advisory.dispatch import Adapter, AdapterResult, AdapterFailure
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, initialize_usage


class RetryTests(unittest.TestCase):
    setUp = test_dispatch.DispatchTests.setUp
    response = test_dispatch.DispatchTests.response

    def run_retry(self, send, **kwargs):
        return retry_dispatch(self.prepared,self.quote,self.ledger,Adapter(self.quote.adapter_id,send),
            operation_key='retry',deadline_ms=2000,clock=lambda:self.now/1000,
            wait=kwargs.pop('wait',lambda seconds:setattr(self,'now',self.now+round(seconds*1000))),**kwargs)

    def test_known_failure_then_verified_result_preserves_input_and_deadline(self):
        requests=[]
        before=self.evidence.read_bytes()
        def send(request):
            requests.append(request)
            return AdapterFailure('RETRYABLE',0,0) if len(requests)==1 else AdapterResult(self.response(),10,3)
        result=self.run_retry(send)
        self.assertEqual(result['status'],'FINISHED')
        self.assertEqual(result['attempts_started'],2)
        self.assertEqual(result['last_result']['review']['status'],'VERIFIED_ADVISORY')
        self.assertEqual([r.remaining_ms for r in requests],[1000,900])
        self.assertEqual(requests[0].messages,requests[1].messages)
        self.assertEqual(before,self.evidence.read_bytes())

    def test_attempt_limit_is_exact(self):
        result=self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0))
        self.assertEqual((result['status'],result['attempts_started']),('ATTEMPT_LIMIT',2))

    def test_unknown_usage_never_retries_or_refunds(self):
        result=self.run_retry(lambda _:None)
        self.assertEqual(result['attempts_started'],1)
        self.assertEqual(result['last_result']['status'],'USAGE_UNKNOWN')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_terminal_failure_never_retries(self):
        result=self.run_retry(lambda _:AdapterFailure('TERMINAL',10,0))
        self.assertEqual(result['attempts_started'],1)
        self.assertEqual(result['last_result']['status'],'KNOWN_TERMINAL_FAILURE')

    def test_restart_repeat_operation_cannot_resend(self):
        self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0))
        self.ledger=UsageLedger(self.path,clock_ms=lambda:self.now)
        result=self.run_retry(lambda _:self.fail('duplicate'))
        self.assertEqual(result['status'],'ADMISSION_DENIED')
        self.assertEqual(result['attempts_started'],0)

    def test_no_sleep_when_backoff_does_not_fit(self):
        self.now=1950
        result=self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0),wait=lambda _:self.fail('sleep'))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['attempts_started'],1)

    def test_overslept_deadline_stops_before_new_call(self):
        result=self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0),wait=lambda _:setattr(self,'now',2000))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['attempts_started'],1)

    def test_expired_before_first_attempt(self):
        self.now=2000
        result=self.run_retry(lambda _:self.fail('expired'))
        self.assertEqual(result['attempts_started'],0)

    def test_billed_failure_consumes_shared_budget(self):
        path=self.root/'tight.db'
        initialize_usage(path,UsagePolicy(max_tokens=20,max_cost_nusd=40))
        self.ledger=UsageLedger(path,clock_ms=lambda:self.now)
        result=self.run_retry(lambda _:AdapterFailure('RETRYABLE',10,5))
        self.assertEqual(result['status'],'ADMISSION_DENIED')
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],15)
        self.assertEqual(result['attempts_started'],1)

    def test_exponential_delay_is_capped(self):
        path=self.root/'many.db'
        initialize_usage(path,UsagePolicy(max_attempts=4))
        self.ledger=UsageLedger(path,clock_ms=lambda:self.now)
        waits=[]
        result=self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0),
            policy=RetryPolicy(4,10,15),wait=lambda s:waits.append(s))
        self.assertEqual(waits,[.01,.015,.015])
        self.assertEqual(result['attempts_started'],4)

    def test_policy_rejects_invalid_bounds_types(self):
        for kwargs in ({'max_attempts':True},{'max_attempts':0},{'max_attempts':9},
                       {'base_delay_ms':0},{'base_delay_ms':60001},{'max_delay_ms':99}):
            with self.assertRaises(AdvisoryError):RetryPolicy(**kwargs)
        with self.assertRaises(AdvisoryError):self.run_retry(lambda _:None,policy=RetryPolicy(3))

    def test_invalid_operation_and_host_objects_rejected(self):
        adapter=Adapter(self.quote.adapter_id,lambda _:None)
        for key in ('','x'*65,'private key',None):
            with self.assertRaises(AdvisoryError):retry_dispatch(self.prepared,self.quote,self.ledger,adapter,operation_key=key,deadline_ms=2000)
        for args in (({},self.quote,self.ledger,adapter),(self.prepared,{},self.ledger,adapter),
                     (self.prepared,self.quote,{},adapter),(self.prepared,self.quote,self.ledger,{})):
            with self.assertRaises(AdvisoryError):retry_dispatch(*args,operation_key='x',deadline_ms=2000)

    def test_clock_invalid_or_rollback_never_sends(self):
        adapter=Adapter(self.quote.adapter_id,lambda _:self.fail('clock'))
        for ticks in ([float('nan')],[1,.9],[1,float('inf')]):
            iterator=iter(ticks)
            with self.assertRaises(AdvisoryError):retry_dispatch(self.prepared,self.quote,self.ledger,adapter,
                operation_key='clock',deadline_ms=2000,clock=lambda:next(iterator))

    def test_wait_cancellation_never_starts_next_attempt(self):
        def wait(_):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_retry(lambda _:AdapterFailure('RETRYABLE',0,0),wait=wait)
        self.assertEqual(self.ledger.snapshot()['attempts'],1)
        self.assertEqual(self.ledger.snapshot()['held_tokens'],0)

    def test_concurrent_same_operation_sends_once(self):
        calls=[]
        def send(_):
            calls.append(True)
            return AdapterFailure('TERMINAL',0,0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.run_retry(send),(0,1)))
        self.assertEqual(sorted(r['status'] for r in results),['ADMISSION_DENIED','FINISHED'])
        self.assertEqual(len(calls),1)

    def test_schema_rejection_never_retried(self):
        result=self.run_retry(lambda _:AdapterResult(b'{',0,0))
        self.assertEqual(result['last_result']['status'],'RESPONSE_REJECTED')
        self.assertEqual(result['attempts_started'],1)

    def test_monotonic_expiry_stops_even_when_wall_clock_is_unchanged(self):
        timer=[1.0]
        adapter=Adapter(self.quote.adapter_id,lambda _:AdapterFailure('RETRYABLE',0,0))
        result=retry_dispatch(self.prepared,self.quote,self.ledger,adapter,operation_key='timer',deadline_ms=2000,
            clock=lambda:timer[0],wait=lambda _:timer.__setitem__(0,3.0))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['attempts_started'],1)

    def test_late_final_result_reports_operation_deadline(self):
        def send(_):
            self.now=2000
            return AdapterResult(self.response(),10,3)
        result=self.run_retry(send)
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['attempts_started'],1)
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],13)
