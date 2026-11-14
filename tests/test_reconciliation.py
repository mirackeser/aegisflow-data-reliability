# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_recovery_authority
from aegisflow_dr.advisory.contracts import AdvisoryError,decode,encode
from aegisflow_dr.advisory.reconciliation import reconcile_usage,reconciliation_history
from aegisflow_dr.advisory.recovery import assess_recovery
from aegisflow_dr.advisory.routing import execute_route
from aegisflow_dr.advisory.usage import initialize_usage,UsageLedger
from aegisflow_dr.storage.store import sha


class ReconciliationTests(unittest.TestCase):
    bind=test_recovery_authority.RecoveryAuthorityTests.bind
    reopen=test_recovery_authority.RecoveryAuthorityTests.reopen
    open_route=test_recovery_authority.RecoveryAuthorityTests.open_route
    candidate=test_recovery_authority.RecoveryAuthorityTests.candidate
    sign=test_recovery_authority.RecoveryAuthorityTests.sign

    def setUp(self):
        def initialize(*args,**kwargs):
            if kwargs.get('routing'):kwargs['reconciliation']=True
            return initialize_usage(*args,**kwargs)
        with patch('test_routing.initialize_usage',side_effect=initialize):
            test_recovery_authority.RecoveryAuthorityTests.setUp(self)
        self.now=1500
        self.operator_grant=replace(self.grant,purpose='reconcile-usage')
        self.attestation_signature=self.sign(self.payload,self.issuer_grant,self.issuer_key)
        self.approval_value={'version':'1','action':'ACCOUNT_KNOWN_USAGE','approval_id':str(uuid4()),
            'operator_id':self.operator,'operation_sha256':self.op,
            'snapshot_sha256':self.value['snapshot_sha256'],'assessment_sha256':self.value['assessment_sha256'],
            'attempt_id':self.value['attempt_id'],'attestation_sha256':sha(self.payload),
            'attestation_signature_sha256':sha(self.attestation_signature)}
        self.approval=encode('usage-reconciliation',self.approval_value)

    def apply(self,**changes):
        args=dict(grant=self.operator_grant,issuer_grant=self.issuer_grant,now_ms=1500);args.update(changes)
        return reconcile_usage(self.route,self.approval,self.sign(self.approval,self.operator_grant),
                               self.payload,self.attestation_signature,**args)

    def sql(self,statement,args=()):
        with closing(sqlite3.connect(self.route_path)) as db,db:db.execute(statement,args)

    def test_exact_accounting_commits_receipt_and_keeps_delivery_blocked(self):
        before=self.evidence.read_bytes();calls=len(self.calls)
        digest=self.apply();snapshot=self.open_route().snapshot()
        self.assertEqual((snapshot['held_tokens'],snapshot['charged_tokens'],snapshot['charged_cost_nusd']),(0,10,22))
        self.assertEqual(reconciliation_history(self.open_route())[0]['digest'],digest)
        assessment=assess_recovery(self.open_route())['assessment']
        self.assertEqual(assessment['route_status'],'USAGE_UNKNOWN')
        self.assertIn('USAGE_UNRESOLVED',assessment['reasons'])
        self.assertFalse(assessment['automatic_resend_allowed'])
        with self.assertRaises(AdvisoryError):self.route.reserve(self.candidates[1].prepared,self.candidates[1].quote,attempt_key='retry',deadline_ms=2000)
        for action in ('unknown','cancel','settle'):
            args={'input_tokens':8,'output_tokens':2} if action=='settle' else {}
            with self.assertRaises(AdvisoryError):self.route.transition(self.value['attempt_id'],action,**args)
        self.assertEqual(len(self.calls),calls);self.assertEqual(before,self.evidence.read_bytes())

    def test_exact_replay_and_concurrent_execution_charge_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:self.apply(),range(2)))
        self.assertEqual(values[0],values[1]);self.assertEqual(self.apply(),values[0])
        self.assertEqual(len(reconciliation_history(self.route)),1)
        self.assertEqual(self.route.snapshot()['charged_tokens'],10)

    def test_old_profiles_and_invalid_initializer_are_rejected(self):
        for ledger in ({},self.bound):
            with self.assertRaises(AdvisoryError):reconcile_usage(ledger,self.approval,b'{}',self.payload,b'{}',grant=self.grant,issuer_grant=self.issuer_grant,now_ms=1500)
        for kwargs in ({'reconciliation':True},{'reconciliation':1}):
            with self.assertRaises(AdvisoryError):initialize_usage(self.root/'invalid.db',**kwargs)
        self.assertFalse((self.root/'invalid.db').exists())

    def test_read_only_review_permission_cannot_settle(self):
        with self.assertRaises(AdvisoryError):self.apply(grant=self.grant)
        self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def test_changed_approval_bindings_and_shared_issuer_are_rejected(self):
        for key,value in (('operator_id',str(uuid4())),('operation_sha256','0'*64),
                ('attestation_sha256','0'*64),('attestation_signature_sha256','0'*64),
                ('attempt_id',str(uuid4())),('snapshot_sha256','0'*64),('assessment_sha256','0'*64)):
            self.approval=encode('usage-reconciliation',{**self.approval_value,key:value})
            with self.assertRaises(AdvisoryError):self.apply()
        self.approval=encode('usage-reconciliation',self.approval_value)
        with self.assertRaises(AdvisoryError):self.apply(issuer_grant=replace(self.issuer_grant,public_key=self.operator_grant.public_key))
        self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def test_stale_revoked_expired_and_clock_mismatch_do_not_release_holds(self):
        for kwargs in ({'grant':replace(self.operator_grant,revoked=True)},{'now_ms':4000},{'now_ms':1600}):
            before=self.route_path.read_bytes()
            with self.assertRaises(AdvisoryError):self.apply(**kwargs)
            self.assertEqual(before,self.route_path.read_bytes())
        self.sql('UPDATE metadata SET observed_ms=observed_ms+1')
        with self.assertRaises(AdvisoryError):self.apply()
        self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def test_conflicting_approval_cannot_rewrite_committed_accounting(self):
        self.apply();before=self.route_path.read_bytes()
        self.approval=encode('usage-reconciliation',{**self.approval_value,'approval_id':str(uuid4())})
        with self.assertRaises(AdvisoryError):self.apply()
        self.assertEqual(before,self.route_path.read_bytes())

    def test_database_failure_rolls_back_receipt_and_observed_clock(self):
        self.sql("CREATE TRIGGER fail BEFORE INSERT ON reconciliations BEGIN SELECT RAISE(ABORT,'private detail'); END")
        before=self.route_path.read_bytes()
        with self.assertRaisesRegex(AdvisoryError,'^Usage ledger unavailable$'):self.apply()
        self.assertEqual(before,self.route_path.read_bytes());self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def crash_worker(self, after_commit):
        from dataclasses import asdict
        grants=[]
        for grant in (self.operator_grant,self.issuer_grant):
            value=asdict(grant);value['public_key']=value['public_key'].hex();grants.append(value)
        arguments={'approval':self.approval.hex(),'signature':self.sign(self.approval,self.operator_grant).hex(),
            'attestation':self.payload.hex(),'attestation_signature':self.attestation_signature.hex(),
            'grants':grants,'operation_id':decode('operation',self.binding.payload)['operation_id'],
            'after_commit':after_commit}
        code="""
import json,os,sqlite3,sys
from contextlib import contextmanager
import aegisflow_dr.advisory.reconciliation as module
from aegisflow_dr.advisory.usage import UsageLedger
from aegisflow_dr.advisory.recovery_auth import RecoverySigner
value=json.loads(sys.argv[2]);original=sqlite3.connect
if not value['after_commit']:
    def connect(*args,**kwargs):
        db=original(*args,**kwargs);db.create_function('crash_worker',0,lambda:os._exit(37));return db
    sqlite3.connect=connect
ledger=UsageLedger(sys.argv[1],operation_id=value['operation_id'],clock_ms=lambda:1500)
if value['after_commit']:
    database=module.database
    @contextmanager
    def crash_database(*args,**kwargs):
        with database(*args,**kwargs) as db:yield db
        os._exit(37)
    module.database=crash_database
grants=[RecoverySigner(**{**g,'public_key':bytes.fromhex(g['public_key'])}) for g in value['grants']]
module.reconcile_usage(ledger,*[bytes.fromhex(value[k]) for k in ('approval','signature','attestation','attestation_signature')],grant=grants[0],issuer_grant=grants[1],now_ms=1500)
"""
        result=subprocess.run([sys.executable,'-c',code,str(self.route_path),json.dumps(arguments)],capture_output=True)
        self.assertEqual(result.returncode,37,result.stderr.decode())

    def test_real_process_exit_before_commit_preserves_hold_and_allows_retry(self):
        self.sql("CREATE TRIGGER crash AFTER INSERT ON reconciliations BEGIN SELECT crash_worker(); END")
        self.crash_worker(False)
        self.assertEqual(self.open_route().snapshot()['held_tokens'],15)
        self.sql('DROP TRIGGER crash')
        self.apply();self.assertEqual(self.open_route().snapshot()['charged_tokens'],10)

    def test_real_process_exit_after_commit_recovers_without_double_charge(self):
        self.crash_worker(True)
        self.assertEqual(self.open_route().snapshot()['charged_tokens'],10)
        self.apply();self.assertEqual(len(reconciliation_history(self.open_route())),1)
        self.assertEqual(self.open_route().snapshot()['charged_cost_nusd'],22)

    def test_missing_schema_and_tampered_receipts_fail_closed(self):
        self.apply()
        with closing(sqlite3.connect(self.route_path)) as db,db:
            for statement in ('DELETE FROM reconciliations','UPDATE reconciliations SET digest=\'x\''):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(statement)
            db.execute('DROP TRIGGER reconciliations_update');db.execute("UPDATE reconciliations SET digest='x'")
        with self.assertRaises(AdvisoryError):self.route.snapshot()
        self.sql('DROP TABLE reconciliations')
        with self.assertRaises(AdvisoryError):self.open_route()

    def test_receipt_binding_caps_and_history_limits(self):
        digest=self.apply()
        with closing(sqlite3.connect(self.route_path)) as db,db:
            raw=db.execute('SELECT payload FROM reconciliations').fetchone()[0]
            db.execute('DROP TRIGGER reconciliations_update')
        original=decode('usage-reconciliation-record',raw)
        for field,value in (('request_sha256','0'*64),('input_tokens',11),('attempt_id',str(uuid4()))):
            evidence={**self.value,field:value};e=encode('usage-attestation',evidence)
            a=encode('usage-reconciliation',{**self.approval_value,'attestation_sha256':sha(e)})
            changed=encode('usage-reconciliation-record',{**original,'approval':a.hex(),'attestation':e.hex()})
            self.sql('UPDATE reconciliations SET payload=?,digest=?',(changed,sha(changed)))
            with self.assertRaises(AdvisoryError):self.route.snapshot()
        self.sql('UPDATE reconciliations SET payload=?,digest=?',(raw,digest))
        self.assertEqual(reconciliation_history(self.route,after=1),[])
        for kwargs in ({'after':None},{'after':'x'*37},{'limit':101}):
            with self.assertRaises(AdvisoryError):reconciliation_history(self.route,**kwargs)
        with self.assertRaises(AdvisoryError):reconciliation_history(self.bound)

    def test_independently_valid_shared_signer_and_invalid_bytes_are_rejected(self):
        issuer=replace(self.issuer_grant,principal_id=self.operator_grant.principal_id,public_key=self.operator_grant.public_key)
        self.attestation_signature=self.sign(self.payload,issuer,self.key)
        self.approval=encode('usage-reconciliation',{**self.approval_value,'attestation_signature_sha256':sha(self.attestation_signature)})
        with self.assertRaisesRegex(AdvisoryError,'Independent reconciliation issuer'):self.apply(issuer_grant=issuer)
        with self.assertRaises(AdvisoryError):
            reconcile_usage(self.route,self.approval,b'{}',None,b'{}',grant=self.operator_grant,issuer_grant=issuer,now_ms=1500)

    def test_orphan_receipt_is_rejected_before_accounting_projection(self):
        self.apply();self.sql('DELETE FROM attempts')
        with self.assertRaisesRegex(AdvisoryError,'history rejected'):self.route.snapshot()
