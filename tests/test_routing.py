# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_operation

from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.advisory.dispatch import Adapter, AdapterFailure, AdapterResult, dispatch
from aegisflow_dr.advisory.route_store import RouteJournal, admit_route
from aegisflow_dr.advisory.routing import RouteCandidate, execute_route, plan_route
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, database, initialize_usage
from aegisflow_dr.storage.store import sha


class RoutingTests(unittest.TestCase):
    def setUp(self):
        test_operation.OperationTests.setUp(self)
        self.route_path=self.root/'route.db'
        initialize_usage(self.route_path,UsagePolicy(max_total_attempts=2),operation=self.binding,routing=True)
        self.route=self.open_route()
        self.journal=RouteJournal(self.route)
        self.calls=[]
        self.candidates=(self.candidate('offline/test','retry'),self.candidate('offline/secondary','good'))

    bind=test_operation.OperationTests.bind
    reopen=test_operation.OperationTests.reopen

    def open_route(self):
        return UsageLedger(self.route_path,operation_id=self.operation_id,clock_ms=lambda:self.now)

    def candidate(self,model,kind):
        prepared=PreparedAdvisory(self.runs,self.record['run_id'],model_id=model)
        quote=replace(self.quote,input_sha256=prepared.manifest['input_sha256'],model_id=model)
        def send(request):
            self.calls.append(model)
            if kind=='retry':return AdapterFailure('RETRYABLE',2,0)
            if kind=='terminal':return AdapterFailure('TERMINAL',2,0)
            if kind=='unknown':raise TimeoutError('private-provider-error')
            if kind=='cancel':raise KeyboardInterrupt()
            if kind=='invalid':return AdapterResult(b'not-json',8,2)
            request_data=decode('request',prepared.request)
            payload=encode('response',{'version':'1','request_sha256':sha(prepared.request),
                'decision':'ABSTAIN' if kind=='abstain' else 'PROPOSE',
                'assessment':None if kind=='abstain' else ('SOURCE_QUALITY_FAILURE' if kind=='wrong' else self.record['trace']['assessment']),
                'evidence_sha256':[] if kind=='abstain' else request_data['evidence_sha256']})
            return AdapterResult(payload,8,2)
        return RouteCandidate(prepared,quote,Adapter(quote.adapter_id,send))

    def event(self,result,index=0):
        return {'index':index,'model_id':self.candidates[index].quote.model_id,
                'request_sha256':result['request_sha256'],'attempt_id':result['attempt_id'],
                'status':result['status'],'review_status':result['review']['status'] if result['review'] else None}

    def claim_dispatch(self):
        token=self.journal.claim(plan_route(self.route,self.candidates))
        first=self.candidates[0]
        result=dispatch(first.prepared,first.quote,self.route,first.adapter,
                        attempt_key='manual',deadline_ms=2000,route_token=token)
        return token,result

    def test_retryable_failure_switches_once_to_verified_model_and_persists(self):
        before=self.evidence.read_bytes()
        result=execute_route(self.route,self.candidates)
        self.assertEqual(result['status'],'VERIFIED_ADVISORY')
        self.assertEqual(self.calls,['offline/test','offline/secondary'])
        self.assertEqual([e['status'] for e in result['events']],['KNOWN_RETRYABLE_FAILURE','REVIEWED'])
        self.assertEqual(RouteJournal(self.open_route()).snapshot()['events'],result['events'])
        self.assertEqual(self.route.snapshot()['charged_tokens'],12)
        self.assertEqual(self.evidence.read_bytes(),before)
        text=json.dumps(result)
        self.assertNotIn('messages',text)
        self.assertNotIn('private-provider-error',text)

    def test_completed_exact_replay_never_resends(self):
        first=execute_route(self.route,self.candidates)
        result=execute_route(self.open_route(),self.candidates)
        self.assertTrue(result['replayed'])
        self.assertEqual(result['events'],first['events'])
        self.assertEqual(len(self.calls),2)

    def test_conflicting_plan_denied_after_completion(self):
        execute_route(self.route,self.candidates)
        changed=(self.candidate('offline/test','retry'),self.candidates[1])
        with self.assertRaises(AdvisoryError):execute_route(self.open_route(),changed)
        self.assertEqual(len(self.calls),2)

    def test_terminal_wrong_abstained_invalid_and_unknown_results_never_fallback(self):
        for index,(kind,status) in enumerate((('terminal','KNOWN_TERMINAL_FAILURE'),
                ('wrong','REJECTED_ADVISORY'),('abstain','ABSTAIN'),('invalid','RESPONSE_REJECTED'),
                ('unknown','USAGE_UNKNOWN'),('good','VERIFIED_ADVISORY'))):
            with self.subTest(kind=kind):
                path=self.root/f'case-{index}.db'
                initialize_usage(path,UsagePolicy(max_total_attempts=2),operation=self.binding,routing=True)
                ledger=UsageLedger(path,operation_id=self.operation_id,clock_ms=lambda:1000)
                self.calls.clear()
                result=execute_route(ledger,(self.candidate('offline/test',kind),self.candidates[1]))
                self.assertEqual(result['status'],status)
                self.assertEqual(self.calls,['offline/test'])
                self.assertEqual(ledger.snapshot()['held_tokens'],15 if kind=='unknown' else 0)

    def test_retryable_plan_exhaustion_has_no_wraparound(self):
        result=execute_route(self.route,(self.candidates[0],self.candidate('offline/secondary','retry')))
        self.assertEqual(result['status'],'EXHAUSTED')
        self.assertEqual(len(self.calls),2)

    def test_shared_budget_denies_second_call_and_persists_reason(self):
        path=self.root/'small.db'
        initialize_usage(path,UsagePolicy(max_tokens=16,max_total_attempts=2),operation=self.binding,routing=True)
        ledger=UsageLedger(path,operation_id=self.operation_id,clock_ms=lambda:1000)
        result=execute_route(ledger,self.candidates)
        self.assertEqual(result['status'],'ADMISSION_DENIED')
        self.assertEqual(len(result['events']),1)
        self.assertEqual(self.calls,['offline/test'])

    def test_deadline_expired_before_first_call_is_durable(self):
        self.now=2000
        result=execute_route(self.route,self.candidates)
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['events'],[])
        self.assertEqual(self.calls,[])

    def test_shared_elapsed_deadline_between_calls_blocks_fallback(self):
        times=iter((0.0,0.0,0.0,0.1,0.9,1.1))
        result=execute_route(self.route,self.candidates,clock=lambda:next(times))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(result['events']),1)

    def test_elapsed_deadline_after_settlement_overrides_review(self):
        times=iter((0.0,0.0,0.0,0.1,1.1))
        result=execute_route(self.route,(self.candidate('offline/test','good'),),clock=lambda:next(times))
        self.assertEqual(result['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(result['events'][0]['review_status'],'VERIFIED_ADVISORY')
        self.assertEqual(self.route.snapshot()['charged_tokens'],10)

    def test_dispatch_deadline_status_is_retained_without_switch(self):
        times=iter((0.0,0.0,0.0,1.1,1.1))
        result=execute_route(self.route,self.candidates,clock=lambda:next(times))
        self.assertEqual(result['events'][0]['status'],'DEADLINE_EXCEEDED')
        self.assertEqual(len(self.calls),1)

    def test_cancellation_leaves_claim_and_unknown_hold_without_resume(self):
        candidates=(self.candidate('offline/test','cancel'),self.candidates[1])
        with self.assertRaises(KeyboardInterrupt):execute_route(self.route,candidates)
        self.assertEqual(self.journal.snapshot()['status'],'RUNNING')
        self.assertEqual(self.open_route().snapshot()['held_tokens'],15)
        with self.assertRaises(AdvisoryError):execute_route(self.open_route(),candidates)
        self.assertEqual(len(self.calls),1)

    def test_post_dispatch_journal_failure_never_retries_or_resumes(self):
        with patch.object(RouteJournal,'record',side_effect=AdvisoryError('storage unavailable')):
            with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates)
        self.assertEqual(self.route.snapshot()['charged_tokens'],2)
        self.assertEqual(self.journal.snapshot()['status'],'RUNNING')
        with self.assertRaises(AdvisoryError):execute_route(self.open_route(),self.candidates)
        self.assertEqual(len(self.calls),1)

    def test_concurrent_hosts_cannot_dispatch_the_same_route_twice(self):
        entered,release=threading.Event(),threading.Event()
        candidate=self.candidate('offline/test','good')
        original=candidate.adapter.send
        def send(request):
            entered.set()
            if not release.wait(5):raise RuntimeError('Test synchronization failed')
            return original(request)
        candidates=(replace(candidate,adapter=Adapter(candidate.quote.adapter_id,send)),)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(execute_route,self.route,candidates)
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaises(AdvisoryError):execute_route(self.open_route(),candidates)
            finally:release.set()
            self.assertEqual(future.result()['status'],'VERIFIED_ADVISORY')
        self.assertEqual(len(self.calls),1)

    def test_all_candidates_are_validated_before_any_call(self):
        invalid=(self.candidates[0],self.candidate('offline/not-approved','good'))
        with self.assertRaises(AdvisoryError):execute_route(self.route,invalid)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.journal.snapshot()['status'],'UNCLAIMED')

    def test_bad_configuration_quotes_and_duplicate_models_fail_closed(self):
        first=self.candidates[0]
        cases=([],(),(first,)*3,(first,first),({},),
            (replace(first,prepared={}),),(replace(first,quote={}),),(replace(first,adapter={}),),
            (replace(first,adapter=Adapter('wrong',lambda _:None)),),
            (replace(first,adapter=Adapter(first.quote.adapter_id,None)),),
            (replace(first,quote=replace(first.quote,model_id='offline/secondary')),),
            (replace(first,quote=replace(first.quote,input_sha256='0'*64)),))
        for candidates in cases:
            with self.subTest(candidates=candidates),self.assertRaises(AdvisoryError):plan_route(self.route,candidates)
        with self.assertRaises(AdvisoryError):plan_route(self.bound,self.candidates)
        with self.assertRaises(AdvisoryError):plan_route({},self.candidates)
        with self.assertRaises(AdvisoryError):RouteJournal(self.bound)
        self.assertEqual(self.calls,[])

    def test_invalid_clocks_deny_and_interrupted_clock_never_resumes(self):
        for value in (True,float('nan'),float('inf'),'0'):
            with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates,clock=lambda:value)
        times=iter((1.0,0.9))
        with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates,clock=lambda:next(times))
        self.assertEqual(self.journal.snapshot()['status'],'RUNNING')
        self.assertEqual(self.calls,[])

    def test_invalid_wall_clock_is_rejected_before_claim(self):
        self.now=True
        with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates)
        self.assertEqual(self.journal.snapshot()['status'],'UNCLAIMED')

    def test_direct_dispatch_and_wrong_token_or_candidate_cannot_bypass_plan(self):
        first=self.candidates[0]
        for token in (None,'wrong'):
            with self.assertRaises(AdvisoryError):dispatch(first.prepared,first.quote,self.route,first.adapter,
                attempt_key='direct',deadline_ms=2000,route_token=token)
        token=self.journal.claim(plan_route(self.route,self.candidates))
        with database(self.route_path) as connection:
            with self.assertRaises(AdvisoryError):admit_route(connection,'wrong',sha(first.prepared.request),'0'*64)
            with self.assertRaises(AdvisoryError):admit_route(connection,token,sha(first.prepared.request),'0'*64)
        with self.assertRaises(AdvisoryError):self.bound.reserve(first.prepared,first.quote,
            attempt_key='direct',deadline_ms=2000,route_token=token)
        self.assertEqual(self.calls,[])

    def test_version_downgrade_and_missing_route_tables_are_rejected(self):
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute('UPDATE metadata SET version=2')
        with self.assertRaises(AdvisoryError):self.open_route()
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute('UPDATE metadata SET version=3')
            connection.execute('DROP TABLE route_events')
        with self.assertRaises(AdvisoryError):self.open_route()
        for kwargs in ({'routing':True},{'routing':1,'operation':self.binding}):
            with self.assertRaises(AdvisoryError):initialize_usage(self.root/'invalid-route.db',**kwargs)

    def test_claim_requires_pristine_ledger_and_valid_plan(self):
        with self.assertRaises(AdvisoryError):self.journal.claim(b'{}')
        # Simulate a preexisting attempt to verify admission fails even if no route was claimed.
        token=self.journal.claim(plan_route(self.route,self.candidates))
        first=self.candidates[0]
        self.route.reserve(first.prepared,first.quote,attempt_key='existing',deadline_ms=2000,route_token=token)
        with database(self.route_path) as connection:
            connection.execute('DELETE FROM route')
        with self.assertRaises(AdvisoryError):self.journal.claim(plan_route(self.route,self.candidates))

    def test_bad_event_order_identity_or_unsettled_retry_is_rejected(self):
        token,result=self.claim_dispatch()
        event=self.event(result)
        for changes in ({'index':1},{'model_id':'offline/secondary'},
                        {'request_sha256':'0'*64},{'attempt_id':str(uuid4())}):
            with self.assertRaises(AdvisoryError):self.journal.record(token,{**event,**changes})
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute("UPDATE attempts SET request_sha256=?",('0'*64,))
        with self.assertRaises(AdvisoryError):self.journal.record(token,event)
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute("UPDATE attempts SET request_sha256=?,status='UNKNOWN',actual_input=NULL,actual_output=NULL,charged_tokens=0,charged_cost_nusd=0",(event['request_sha256'],))
        with self.assertRaises(AdvisoryError):self.journal.record(token,event)
        with self.assertRaises(AdvisoryError):self.journal.stop(token,'invented')
        with self.assertRaises(AdvisoryError):self.journal.stop('wrong','ADMISSION_DENIED')
        self.assertEqual(self.journal.snapshot()['events'],[])

    def test_durable_event_is_required_before_advancing_to_next_model(self):
        token,result=self.claim_dispatch()
        second=self.candidates[1]
        with self.assertRaises(AdvisoryError):dispatch(second.prepared,second.quote,self.route,second.adapter,
            attempt_key='early',deadline_ms=2000,route_token=token)
        self.journal.record(token,self.event(result))
        result=dispatch(second.prepared,second.quote,self.route,second.adapter,
            attempt_key='second',deadline_ms=2000,route_token=token)
        self.journal.record(token,self.event(result,1))
        with self.assertRaises(AdvisoryError):self.journal.record(token,self.event(result,1))
        self.assertEqual(len(self.calls),2)

    def test_corrupted_progression_cannot_skip_terminal_or_exhausted_steps(self):
        token,result=self.claim_dispatch()
        self.journal.record(token,self.event(result))
        event=self.event(result)
        event['status']='KNOWN_TERMINAL_FAILURE'
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute('UPDATE route_events SET event=?',(encode('route-event',event),))
        with database(self.route_path) as connection:
            with self.assertRaises(AdvisoryError):admit_route(connection,token,'0'*64,'0'*64)
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            event['index']=1
            connection.execute('INSERT INTO route_events VALUES (1,?)',(encode('route-event',event),))
        with database(self.route_path) as connection:
            with self.assertRaises(AdvisoryError):admit_route(connection,token,'0'*64,'0'*64)
        with self.assertRaises(AdvisoryError):self.journal.record(token,self.event(result))

    def test_wrong_operation_plan_rejected_before_claim(self):
        plan=decode('route-plan',plan_route(self.route,self.candidates))
        plan['operation_sha256']='0'*64
        with self.assertRaises(AdvisoryError):self.journal.claim(encode('route-plan',plan))
        self.assertEqual(self.journal.snapshot()['status'],'UNCLAIMED')

    def test_event_and_final_status_commit_atomically_on_storage_failure(self):
        with closing(sqlite3.connect(self.route_path)) as connection,connection:
            connection.execute("CREATE TRIGGER deny_finish BEFORE UPDATE ON route BEGIN SELECT RAISE(ABORT, 'private-storage-error'); END")
        with self.assertRaisesRegex(AdvisoryError,'^Usage ledger unavailable$'):
            execute_route(self.route,self.candidates)
        self.assertEqual(self.journal.snapshot(),{'version':'1','status':'RUNNING','events':[]})
        self.assertEqual(self.route.snapshot()['charged_tokens'],2)
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(AdvisoryError):execute_route(self.open_route(),self.candidates)

    def test_wall_clock_rollback_after_claim_blocks_dispatch(self):
        wall=iter((1000,999))
        self.route.clock_ms=lambda:next(wall)
        with self.assertRaises(AdvisoryError):execute_route(self.route,self.candidates)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.journal.snapshot()['status'],'RUNNING')
