# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
import subprocess
import sys
import unittest
import test_usage
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, initialize_usage


class SharedUsageTests(unittest.TestCase):
    setUp = test_usage.UsageTests.setUp

    def scope(self, limit=2):
        path=self.root/'scope.db'
        initialize_usage(path,UsagePolicy(max_total_attempts=limit))
        self.ledger=UsageLedger(path,clock_ms=lambda:1000)
        return path

    def reserve(self,key,deadline=2000):
        prepared=PreparedAdvisory(self.runs,self.record['run_id'],model_id='fixture/'+key)
        quote=replace(self.quote,input_sha256=prepared.manifest['input_sha256'],model_id='fixture/'+key)
        return self.ledger.reserve(prepared,quote,attempt_key=key,deadline_ms=deadline)

    def settle(self,row):
        self.ledger.transition(row['attempt_id'],'start')
        self.ledger.transition(row['attempt_id'],'settle',input_tokens=2,output_tokens=0)

    def test_total_attempts_shared_across_new_model_requests_and_restart(self):
        path=self.scope()
        self.settle(self.reserve('first'))
        self.settle(self.reserve('second'))
        self.ledger=UsageLedger(path,clock_ms=lambda:1000)
        with self.assertRaises(AdvisoryError):self.reserve('third')
        self.assertEqual(self.ledger.snapshot()['charged_tokens'],4)
        self.assertEqual(self.ledger.snapshot()['attempts'],2)

    def test_unknown_usage_blocks_switch_to_new_model(self):
        self.scope()
        row=self.reserve('first')
        self.ledger.transition(row['attempt_id'],'start')
        self.ledger.transition(row['attempt_id'],'unknown')
        with self.assertRaises(AdvisoryError):self.reserve('second')
        self.assertEqual(self.ledger.snapshot()['held_tokens'],15)

    def test_cancel_counts_and_deadline_cannot_reset(self):
        self.scope()
        row=self.reserve('first')
        self.ledger.transition(row['attempt_id'],'cancel')
        with self.assertRaises(AdvisoryError):self.reserve('second',2100)
        self.settle(self.reserve('second'))
        with self.assertRaises(AdvisoryError):self.reserve('third')

    def test_concurrent_distinct_models_share_one_cap(self):
        self.scope(1)
        def reserve(key):
            try:return self.reserve(key)['status']
            except AdvisoryError:return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,('first','second')))
        self.assertEqual(sorted(results),['DENIED','RESERVED'])

    def test_idempotent_receipt_still_available_at_cap(self):
        self.scope(1)
        prepared=self.prepared
        row=self.ledger.reserve(prepared,self.quote,attempt_key='same',deadline_ms=2000)
        self.assertEqual(row,self.ledger.reserve(prepared,self.quote,attempt_key='same',deadline_ms=2000))
        self.assertEqual(self.ledger.snapshot()['attempts'],1)

    def test_invalid_total_limit_rejected(self):
        for value in (True,0,-1,100001,'2',float('nan')):
            with self.assertRaises(AdvisoryError):UsagePolicy(max_total_attempts=value)

    def test_legacy_policy_opens_without_rewriting_metadata(self):
        with sqlite3.connect(self.path) as connection:
            raw=connection.execute('SELECT policy FROM metadata').fetchone()[0]
            policy=json.loads(raw)
            del policy['max_total_attempts']
            legacy=json.dumps(policy).encode()
            connection.execute('UPDATE metadata SET policy=?',(legacy,))
        before=self.path.read_bytes()
        ledger=UsageLedger(self.path)
        self.assertIsNone(ledger.policy.max_total_attempts)
        self.assertEqual(before,self.path.read_bytes())

    def test_demo_real_entrypoint_shows_shared_guard(self):
        import os
        result=subprocess.run([sys.executable,'-m','aegisflow_dr.advisory.demo'],
            env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True,check=True)
        import contextlib, io, runpy
        from unittest.mock import patch
        output=io.StringIO()
        with patch.dict(sys.modules), contextlib.redirect_stdout(output):
            sys.modules.pop('aegisflow_dr.advisory.demo',None)
            runpy.run_module('aegisflow_dr.advisory.demo',run_name='__main__')
        self.assertEqual(json.loads(output.getvalue()),json.loads(result.stdout))
        value=json.loads(result.stdout)
        self.assertEqual(value['events'][-1]['event'],'ADMISSION_DENIED')
        self.assertEqual(value['usage']['attempts'],2)
        self.assertEqual(value['usage']['charged_cost_nusd'],26)
        self.assertEqual(value['model_calls'],0)
        self.assertEqual(value['routing_status'],'VERIFIED_ADVISORY')
        self.assertTrue(value['replayed_without_dispatch'])
        self.assertEqual(value['usage']['version'],'3')
        self.assertTrue(value['evidence_unchanged'])

    def test_demo_is_repeatable_without_operational_ids(self):
        from aegisflow_dr.advisory.demo import run_demo
        first=run_demo()
        self.assertEqual(first,run_demo())
        self.assertEqual(first['events'][3]['review'],'VERIFIED_ADVISORY')
