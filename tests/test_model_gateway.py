# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from dataclasses import replace
import sqlite3
import time
import unittest
from unittest.mock import patch

import test_recovery_authority
from tls_support import TestCertificates,review_server
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError,decode,encode
from aegisflow_dr.advisory.dispatch import AdapterRequest,dispatch
from aegisflow_dr.advisory.gateway import gateway_adapter,fetch_usage_attestation
from aegisflow_dr.advisory.operation import bind_operation
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.security.policy import AccessPolicy
from aegisflow_dr.storage.store import canonical,sha


class GatewayTests(unittest.TestCase):
    bind=test_recovery_authority.RecoveryAuthorityTests.bind
    reopen=test_recovery_authority.RecoveryAuthorityTests.reopen
    open_route=test_recovery_authority.RecoveryAuthorityTests.open_route
    candidate=test_recovery_authority.RecoveryAuthorityTests.candidate
    sign=test_recovery_authority.RecoveryAuthorityTests.sign

    def setUp(self):
        test_recovery_authority.RecoveryAuthorityTests.setUp(self)
        self.certs=TestCertificates(self.root)
        self.gateway_grant=replace(self.grant,purpose='model-gateway-result')
        self.prepared=self.candidates[0].prepared;self.quote=self.candidates[0].quote
        self.request=AdapterRequest(canonical(self.prepared.messages),sha(self.prepared.request),
            self.quote.model_id,1000,self.quote.output_limit,16384)
        metadata=decode('request',self.prepared.request)
        self.response=encode('response',{'version':'1','request_sha256':sha(self.prepared.request),
            'decision':'PROPOSE','assessment':self.record['trace']['assessment'],
            'evidence_sha256':metadata['evidence_sha256']})
        self.queries=[]

    def model_reply(self,query,**changes):
        result={**{k:query[k] for k in ('version','operation_sha256','request_sha256','input_sha256','quote_sha256','model_id')},
                'payload_hex':self.response.hex(),'input_tokens':8,'output_tokens':2,'receipt_sha256':'1'*64,**changes}
        payload=encode('gateway-result',result)
        signature=self.sign(payload,self.gateway_grant)
        return encode('gateway-response',{'result':result,'signature_hex':signature.hex()})

    def handler(self,peer,body,headers,path,policy):
        query=decode('gateway-request',body);self.queries.append(query)
        return 200,self.model_reply(query)

    def adapter(self,destination,**changes):
        args=dict(endpoint=destination,material=self.certs.client,grant=self.gateway_grant,clock_ms=lambda:1500)
        args.update(changes)
        return gateway_adapter(self.prepared,self.quote,self.binding,**args)

    def test_real_pinned_mtls_gateway_binds_exact_input_and_judge(self):
        before=self.evidence.read_bytes()
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.handler) as (server,endpoint):
            with patch('socket.getaddrinfo',side_effect=AssertionError('DNS forbidden')):
                result=self.adapter(endpoint).send(self.request)
            self.assertEqual(server.requests,1)
        self.assertEqual(result.payload,self.response)
        self.assertEqual((result.input_tokens,result.output_tokens),(8,2))
        self.assertEqual(bytes.fromhex(self.queries[0]['messages_hex']),self.request.messages)
        self.assertEqual(self.prepared.review_response(result.payload)['status'],'VERIFIED_ADVISORY')
        self.assertEqual(before,self.evidence.read_bytes())

    def test_dispatch_settles_trusted_usage_then_judge_checks_claim(self):
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.handler) as (_,endpoint):
            result=dispatch(self.prepared,self.quote,self.bound,self.adapter(endpoint),attempt_key='gateway',deadline_ms=2000)
        self.assertEqual(result['review']['status'],'VERIFIED_ADVISORY')
        self.assertEqual(self.bound.snapshot()['charged_cost_nusd'],22)

    def test_unknown_http_failure_retains_hold_and_never_retries(self):
        def failure(*args):return 503,b'{"private":"provider detail"}'
        with review_server(self.certs,self.runs,AccessPolicy(),handler=failure) as (server,endpoint):
            result=dispatch(self.prepared,self.quote,self.bound,self.adapter(endpoint),attempt_key='failed',deadline_ms=2000)
            self.assertEqual(server.requests,1)
            with self.assertRaises(AdvisoryError):dispatch(self.prepared,self.quote,self.bound,self.adapter(endpoint),attempt_key='again',deadline_ms=2000)
        self.assertEqual(result['status'],'USAGE_UNKNOWN');self.assertEqual(self.bound.snapshot()['held_tokens'],15)

    def test_signed_but_mismatched_model_quote_context_and_usage_rejected(self):
        for field,value in (('model_id','offline/wrong'),('request_sha256','0'*64),('input_sha256','0'*64),
                ('quote_sha256','0'*64),('operation_sha256','0'*64),('input_tokens',11),('output_tokens',6)):
            def handler(peer,body,*_):return 200,self.model_reply(decode('gateway-request',body),**{field:value})
            with review_server(self.certs,self.runs,AccessPolicy(),handler=handler) as (_,endpoint):
                with self.assertRaises(AdvisoryError):self.adapter(endpoint).send(self.request)

    def test_tampered_signature_unstructured_json_and_duplicate_keys_rejected(self):
        for body in (b'{}',b'{"result":{},"result":{}}'):
            with review_server(self.certs,self.runs,AccessPolicy(),handler=lambda *_:(200,body)) as (_,endpoint):
                with self.assertRaises(AdvisoryError):self.adapter(endpoint).send(self.request)
        def handler(peer,body,*_):
            value=decode('gateway-response',self.model_reply(decode('gateway-request',body)))
            proof=decode('recovery-signature',bytes.fromhex(value['signature_hex']));proof['signature']='0'*128
            return 200,encode('gateway-response',{**value,'signature_hex':encode('recovery-signature',proof).hex()})
        with review_server(self.certs,self.runs,AccessPolicy(),handler=handler) as (_,endpoint):
            with self.assertRaises(AdvisoryError):self.adapter(endpoint).send(self.request)

    def test_wrong_pin_and_invalid_or_expired_grants_send_nothing(self):
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.handler) as (server,endpoint):
            for grant,clock in ((replace(self.gateway_grant,revoked=True),lambda:1500),
                    (self.gateway_grant,lambda:5000)):
                with self.assertRaises(AdvisoryError):self.adapter(endpoint,grant=grant,clock_ms=clock).send(self.request)
            with self.assertRaises(AdvisoryError):self.adapter(replace(endpoint,server_sha256='0'*64)).send(self.request)
            self.assertEqual(server.requests,0)
            for changes in ({'endpoint':{}},{'material':{}},{'grant':{}},{'grant':self.grant},{'clock_ms':None}):
                with self.assertRaises(AdvisoryError):self.adapter(endpoint,**changes)

    def test_mutated_dispatch_and_response_byte_caps_reject(self):
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.handler) as (server,endpoint):
            adapter=self.adapter(endpoint)
            for changes in ({'messages':b'changed'},{'model_id':'offline/wrong'},{'output_limit':1},
                            {'request_sha256':'0'*64},{'remaining_ms':False}):
                with self.assertRaises(AdvisoryError):adapter.send(replace(self.request,**changes))
            with self.assertRaises(AdvisoryError):adapter.send({})
            self.assertEqual(server.requests,0)
            with self.assertRaises(AdvisoryError):adapter.send(replace(self.request,max_response_bytes=1))

    def test_original_timeout_stops_stalled_response(self):
        def stalled(peer,body):
            time.sleep(.15)
        with review_server(self.certs,self.runs,AccessPolicy(),response=stalled) as (_,endpoint):
            started=time.monotonic()
            with self.assertRaisesRegex(AdvisoryError,'^Gateway exchange unavailable$'):
                self.adapter(endpoint).send(replace(self.request,remaining_ms=40))
            self.assertLess(time.monotonic()-started,1)

    def usage_handler(self,peer,body,*_):
        query=decode('usage-query',body);self.queries.append(query)
        payload=encode('usage-attestation',{**query,'receipt_sha256':'2'*64,'input_tokens':8,'output_tokens':2})
        return 200,encode('usage-reply',{'attestation_hex':payload.hex(),
                           'signature_hex':self.sign(payload,self.issuer_grant,self.issuer_key).hex()})

    def fetch(self,endpoint,**changes):
        args=dict(endpoint=endpoint,material=self.certs.client,grant=self.issuer_grant,now_ms=lambda:1500)
        args.update(changes)
        return fetch_usage_attestation(self.route,self.value['attempt_id'],**args)

    def test_independent_signed_usage_inquiry_is_read_only(self):
        before=self.route_path.read_bytes()
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.usage_handler) as (server,endpoint):
            result=self.fetch(endpoint);self.assertEqual(server.requests,1)
        self.assertEqual(result['verification']['charged_cost_nusd'],22)
        self.assertEqual(before,self.route_path.read_bytes());self.assertEqual(self.route.snapshot()['held_tokens'],15)
        self.assertNotIn('messages_hex',self.queries[0])

    def test_usage_query_releases_ledger_lock_and_rejects_concurrent_change(self):
        def handler(peer,body,*args):
            with closing(sqlite3.connect(self.route_path,timeout=.2)) as db,db:
                db.execute('UPDATE metadata SET observed_ms=observed_ms+1')
            return self.usage_handler(peer,body,*args)
        with review_server(self.certs,self.runs,AccessPolicy(),handler=handler) as (_,endpoint):
            with self.assertRaisesRegex(AdvisoryError,'Stale usage'):self.fetch(endpoint)
        self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def test_usage_query_scope_status_and_configuration_preflight(self):
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.usage_handler) as (server,endpoint):
            for changes in ({'grant':self.grant},{'grant':replace(self.issuer_grant,operation_sha256='0'*64)},
                    {'grant':replace(self.issuer_grant,revoked=True)},{'now_ms':None}):
                with self.assertRaises(AdvisoryError):self.fetch(endpoint,**changes)
            for ledger in ({},self.bound):
                with self.assertRaises(AdvisoryError):fetch_usage_attestation(ledger,'bad',endpoint=endpoint,material=self.certs.client,grant=self.issuer_grant,now_ms=lambda:1500)
            with self.assertRaises(AdvisoryError):fetch_usage_attestation(self.route,'missing',endpoint=endpoint,material=self.certs.client,grant=self.issuer_grant,now_ms=lambda:1500)
            self.assertEqual(server.requests,0)

    def test_bound_quote_and_operation_deadline_cannot_be_expanded(self):
        with review_server(self.certs,self.runs,AccessPolicy(),handler=self.handler) as (server,endpoint):
            for prepared,quote,operation in (({},self.quote,self.binding),
                    (self.prepared,{},self.binding),(self.prepared,self.quote,{}),
                    (self.prepared,replace(self.quote,input_sha256='0'*64),self.binding),
                    (self.prepared,replace(self.quote,model_id='offline/other'),self.binding)):
                with self.assertRaises(AdvisoryError):
                    gateway_adapter(prepared,quote,operation,endpoint=endpoint,material=self.certs.client,
                                    grant=self.gateway_grant,clock_ms=lambda:1500)
            with self.assertRaises(AdvisoryError):self.adapter(endpoint,clock_ms=lambda:2000).send(self.request)
            self.assertEqual(server.requests,0)
            self.adapter(endpoint).send(replace(self.request,remaining_ms=600000))
            self.assertEqual(self.queries[-1]['remaining_ms'],500)
