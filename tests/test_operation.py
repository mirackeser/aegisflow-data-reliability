# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import PropertyMock, patch
from uuid import uuid4
import test_usage

from aegisflow_dr.advisory.context import ContextPolicy, PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.advisory.dispatch import Adapter, AdapterResult, dispatch
from aegisflow_dr.advisory.operation import OperationBinding, bind_operation
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, initialize_usage
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage.store import sha


class OperationTests(unittest.TestCase):
    def setUp(self):
        test_usage.UsageTests.setUp(self)
        self.operation_id = str(uuid4())
        self.binding = self.bind()
        self.bound_path = self.root / 'bound.db'
        initialize_usage(self.bound_path, UsagePolicy(max_total_attempts=2), operation=self.binding)
        self.bound = self.reopen()

    def bind(self, **changes):
        values = dict(operation_id=self.operation_id,
                      allowed_models=('offline/test', 'offline/secondary'), deadline_ms=2000)
        values.update(changes)
        return bind_operation(self.prepared, **values)

    def reopen(self):
        return UsageLedger(self.bound_path, operation_id=self.operation_id, clock_ms=lambda:1000)

    def reserve(self, prepared=None, key='first', deadline=2000):
        prepared = self.prepared if prepared is None else prepared
        quote = replace(self.quote, input_sha256=prepared.manifest['input_sha256'],
                        model_id=decode('request', prepared.request)['model_id'])
        return self.bound.reserve(prepared, quote, attempt_key=key, deadline_ms=deadline)

    def settle(self, row):
        self.bound.transition(row['attempt_id'], 'start')
        self.bound.transition(row['attempt_id'], 'settle', input_tokens=0, output_tokens=0)

    def test_identity_and_grants_survive_restart_without_evidence_changes(self):
        evidence = self.evidence.read_bytes()
        self.settle(self.reserve())
        self.bound = self.reopen()
        secondary = PreparedAdvisory(self.runs, self.record['run_id'], model_id='offline/secondary')
        self.settle(self.reserve(secondary, 'second'))
        with self.assertRaises(AdvisoryError): self.reserve(secondary, 'third')
        self.assertEqual(self.bound.operation, self.binding)
        self.assertEqual(self.bound.snapshot()['version'], '2')
        self.assertEqual(self.bound.snapshot()['attempts'], 2)
        self.assertEqual(self.evidence.read_bytes(), evidence)

    def test_wrong_missing_or_unbound_operation_identity_rejected_without_rewrite(self):
        before = self.bound_path.read_bytes()
        for value in (None, str(uuid4()), True, ''):
            with self.assertRaises(AdvisoryError): UsageLedger(self.bound_path, operation_id=value)
        self.assertEqual(before, self.bound_path.read_bytes())
        with self.assertRaises(AdvisoryError): UsageLedger(self.path, operation_id=self.operation_id)

    def test_binding_requires_strict_metadata_and_closed_contract(self):
        for changes in ({'operation_id':'wrong'}, {'operation_id':None}, {'deadline_ms':True},
                        {'deadline_ms':-1}, {'allowed_models':[]}, {'allowed_models':()},
                        {'allowed_models':('offline/test',)*2}, {'allowed_models':('offline/other',)},
                        {'allowed_models':('offline/test', 'bad model')},
                        {'allowed_models':tuple('model/'+str(i) for i in range(17))}):
            with self.subTest(changes=changes), self.assertRaises(AdvisoryError): self.bind(**changes)
        for payload in (b'{}', b'[]', b'not-json', 'not-bytes', b'x'*16385):
            with self.assertRaises(AdvisoryError): OperationBinding(payload)
        value=decode('operation',self.binding.payload)
        value['extra']='rejected'
        with self.assertRaises(AdvisoryError): OperationBinding(json.dumps(value).encode())
        with self.assertRaises(AdvisoryError): bind_operation({}, operation_id=self.operation_id,
            allowed_models=('offline/test',), deadline_ms=2000)

    def test_untrusted_binding_or_missing_total_cap_creates_no_database(self):
        for operation,policy in (({},UsagePolicy(max_total_attempts=2)), (self.binding,UsagePolicy())):
            path=self.root/'invalid.db'
            with self.assertRaises(AdvisoryError): initialize_usage(path, policy, operation=operation)
            self.assertFalse(path.exists())

    def test_stored_binding_and_policy_corruption_fail_closed(self):
        for payload in (b'{}', b'not-json', b'[]'):
            with sqlite3.connect(self.bound_path) as connection:
                connection.execute('UPDATE metadata SET operation=?',(payload,))
            with self.assertRaises(AdvisoryError): self.reopen()
        with sqlite3.connect(self.bound_path) as connection:
            policy=json.loads(connection.execute('SELECT policy FROM metadata').fetchone()[0])
            policy['max_total_attempts']=None
            connection.execute('UPDATE metadata SET operation=?,policy=?',
                               (self.binding.payload,json.dumps(policy)))
        with self.assertRaises(AdvisoryError): self.reopen()

    def test_schema_downgrade_and_reinitialization_do_not_bypass_binding(self):
        before=self.bound_path.read_bytes()
        with self.assertRaises(AdvisoryError): initialize_usage(self.bound_path)
        self.assertEqual(before,self.bound_path.read_bytes())
        with sqlite3.connect(self.bound_path) as connection:
            connection.execute('UPDATE metadata SET version=1')
        with self.assertRaises(AdvisoryError): UsageLedger(self.bound_path)

    def test_wrong_model_and_changed_deadline_deny_before_first_reservation(self):
        other=PreparedAdvisory(self.runs,self.record['run_id'],model_id='offline/unapproved')
        for prepared,deadline in ((other,2000),(self.prepared,2001)):
            before=self.bound_path.read_bytes()
            with self.assertRaises(AdvisoryError): self.reserve(prepared,deadline=deadline)
            self.assertEqual(before,self.bound_path.read_bytes())
        self.assertEqual(self.bound.snapshot()['attempts'],0)

    def test_new_run_with_identical_source_is_not_same_operation(self):
        incident_id=decode('request',self.prepared.request)['incident_id']
        record=self.runs.execute(incident_id,default_policy(),request_key='different-run')
        prepared=PreparedAdvisory(self.runs,record['run_id'],model_id='offline/test')
        with self.assertRaises(AdvisoryError): self.reserve(prepared)
        self.assertEqual(self.bound.snapshot()['attempts'],0)

    def test_changed_prompt_policy_is_not_eligible(self):
        prepared=PreparedAdvisory(self.runs,self.record['run_id'],model_id='offline/test',
                                 policy=ContextPolicy(max_prompt_bytes=32767))
        with self.assertRaises(AdvisoryError): self.reserve(prepared)

    def test_different_incident_cannot_reuse_operation_budget(self):
        from aegisflow_dr.storage import IncidentStore
        incident=IncidentStore(self.evidence).record(generate_orders(),request_key='other-incident')
        record=self.runs.execute(incident['incident_id'],default_policy(),request_key='other-incident')
        prepared=PreparedAdvisory(self.runs,record['run_id'],model_id='offline/test')
        with self.assertRaises(AdvisoryError): self.reserve(prepared)
        self.assertEqual(self.bound.snapshot()['attempts'],0)

    def test_each_evidence_and_context_identity_field_is_enforced(self):
        request=decode('request',self.prepared.request)
        for field in ('run_id','incident_id','record_sha256','prompt_sha256','evidence_sha256'):
            changed=dict(request)
            changed[field] = [sha(b'different')] if field=='evidence_sha256' else (
                str(uuid4()) if field.endswith('_id') else sha(b'different'))
            with patch.object(PreparedAdvisory,'request',new_callable=PropertyMock,
                              return_value=encode('request',changed)):
                with self.assertRaises(AdvisoryError): self.reserve()
        manifest=self.prepared.manifest
        for field in ('context_sha256','response_schema_sha256'):
            with patch.object(PreparedAdvisory,'manifest',new_callable=PropertyMock,
                              return_value={**manifest,field:sha(b'different')}):
                with self.assertRaises(AdvisoryError): self.reserve()
        self.assertEqual(self.bound.snapshot()['attempts'],0)

    def test_binding_admission_precedes_idempotent_receipt_lookup(self):
        self.reserve()
        changed=decode('operation',self.binding.payload)
        changed['allowed_models']=['offline/secondary']
        self.bound.operation=OperationBinding(encode('operation',changed))
        with self.assertRaises(AdvisoryError): self.reserve()

    def test_unknown_usage_blocks_eligible_secondary_after_restart(self):
        row=self.reserve()
        self.bound.transition(row['attempt_id'],'start')
        self.bound.transition(row['attempt_id'],'unknown')
        self.bound=self.reopen()
        prepared=PreparedAdvisory(self.runs,self.record['run_id'],model_id='offline/secondary')
        with self.assertRaises(AdvisoryError): self.reserve(prepared,'secondary')
        self.assertEqual(self.bound.snapshot()['held_tokens'],15)

    def test_concurrent_connections_share_bound_admission(self):
        def reserve(index):
            prepared=PreparedAdvisory(self.runs,self.record['run_id'],model_id='offline/secondary')
            quote=replace(self.quote,input_sha256=prepared.manifest['input_sha256'],model_id='offline/secondary')
            try:
                return self.reopen().reserve(prepared,quote,attempt_key=str(index),deadline_ms=2000)['status']
            except AdvisoryError:return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reserve,(0,1))),['DENIED','RESERVED'])

    def test_dispatch_never_calls_ineligible_adapter_and_judge_rejects_wrong_answer(self):
        calls=[]
        def send(request):
            calls.append(request)
            metadata=decode('request',self.prepared.request)
            response=encode('response',{'version':'1','request_sha256':sha(self.prepared.request),
                'decision':'PROPOSE','assessment':'SOURCE_QUALITY_FAILURE',
                'evidence_sha256':metadata['evidence_sha256']})
            return AdapterResult(response,8,2)
        adapter=Adapter(self.quote.adapter_id,send)
        denied=PreparedAdvisory(self.runs,self.record['run_id'],model_id='offline/unapproved')
        quote=replace(self.quote,input_sha256=denied.manifest['input_sha256'],model_id='offline/unapproved')
        with self.assertRaises(AdvisoryError): dispatch(denied,quote,self.bound,adapter,
                                                       attempt_key='denied',deadline_ms=2000)
        self.assertEqual(calls,[])
        result=dispatch(self.prepared,self.quote,self.bound,adapter,attempt_key='allowed',deadline_ms=2000)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['review']['status'],'REJECTED_ADVISORY')
        self.assertEqual(self.bound.snapshot()['charged_tokens'],10)
