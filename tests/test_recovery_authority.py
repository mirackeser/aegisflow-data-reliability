# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import test_routing
from aegisflow_dr.advisory.contracts import AdvisoryError,decode,encode
from aegisflow_dr.advisory.recovery import assess_recovery,prepare_recovery_review
from aegisflow_dr.advisory.recovery_auth import RecoverySigner,signing_bytes,verify_signature,verify_usage_attestation
from aegisflow_dr.advisory.recovery_decisions import initialize_decisions,record_decision,decision_history,decision_payload
from aegisflow_dr.advisory.routing import execute_route
from aegisflow_dr.storage.store import sha


class RecoveryAuthorityTests(unittest.TestCase):
    bind=test_routing.RoutingTests.bind
    reopen=test_routing.RoutingTests.reopen
    open_route=test_routing.RoutingTests.open_route
    candidate=test_routing.RoutingTests.candidate

    def setUp(self):
        test_routing.RoutingTests.setUp(self)
        execute_route(self.route,(self.candidate('offline/test','unknown'),))
        self.report=assess_recovery(self.route)
        self.op=self.report['assessment']['operation_sha256']
        self.operator=str(uuid4());self.issuer=str(uuid4())
        self.key=Ed25519PrivateKey.generate();self.issuer_key=Ed25519PrivateKey.generate()
        self.grant=RecoverySigner(self.operator,'recovery-decision',self.op,self.key.public_key().public_bytes_raw(),900,5000)
        self.issuer_grant=RecoverySigner(self.issuer,'usage-attestation',self.op,self.issuer_key.public_key().public_bytes_raw(),900,5000)
        self.review=prepare_recovery_review(self.route,review_id=str(uuid4()),operator_id=self.operator,action='KEEP_BLOCKED')
        with closing(sqlite3.connect(self.route_path)) as db:
            db.row_factory=sqlite3.Row;self.attempt=dict(db.execute('SELECT * FROM attempts').fetchone())
        self.value={'version':'1','operation_sha256':self.op,
            'snapshot_sha256':self.report['assessment']['snapshot_sha256'],
            'assessment_sha256':self.report['assessment_sha256'],
            **{k:self.attempt[k] for k in ('attempt_id','request_sha256','input_sha256','quote_sha256')},
            'receipt_sha256':'1'*64,'input_tokens':8,'output_tokens':2}
        self.payload=encode('usage-attestation',self.value)
        self.log=self.root/'decisions.db';initialize_decisions(self.log,operation_sha256=self.op)

    def sign(self,payload,grant=None,key=None,**changes):
        grant=self.grant if grant is None else grant;key=self.key if key is None else key
        metadata={'version':'1','purpose':grant.purpose,'principal_id':grant.principal_id,
            'operation_sha256':grant.operation_sha256,'key_sha256':sha(grant.public_key),
            'payload_sha256':sha(payload),'issued_at_ms':1000,'expires_at_ms':4000,**changes}
        return encode('recovery-signature',{**metadata,'signature':key.sign(signing_bytes(metadata)).hex()})

    def save_decision(self,**changes):
        args=dict(grant=self.grant,now_ms=1500)
        args.update(changes)
        return record_decision(self.log,self.route,self.review,self.sign(decision_payload(self.review,args.get('attestation'),args.get('attestation_envelope'))),**args)

    def usage(self,payload=None,**changes):
        payload=self.payload if payload is None else payload
        args=dict(grant=self.issuer_grant,now_ms=1500);args.update(changes)
        return verify_usage_attestation(self.route,payload,self.sign(payload,self.issuer_grant,self.issuer_key),**args)

    def history(self,**changes):
        return decision_history(self.log,operation_sha256=self.op,**changes)

    def test_signed_usage_and_durable_decision_keep_hold_unchanged(self):
        before=self.route_path.read_bytes()
        result=self.usage();self.assertEqual((result['charged_tokens'],result['charged_cost_nusd']),(10,22))
        digest=self.save_decision(attestation=self.payload,attestation_envelope=self.sign(self.payload,self.issuer_grant,self.issuer_key),issuer_grant=self.issuer_grant)
        self.assertEqual(self.history()[0]['digest'],digest)
        self.assertEqual(bytes.fromhex(self.history()[0]['record']['attestation']),self.payload)
        self.assertEqual(before,self.route_path.read_bytes())
        self.assertEqual(self.route.snapshot()['held_tokens'],15)

    def test_duplicate_decision_is_idempotent_and_conflicting_id_rejected(self):
        first=self.save_decision();self.assertEqual(self.save_decision(),first);self.assertEqual(len(self.history()),1)
        self.assertEqual(self.history()[0]['recorded_at_ms'],1500)
        self.assertEqual(self.save_decision(now_ms=1600),first)
        packet=decode('recovery-review',self.review);self.review=encode('recovery-review',{**packet,'action':'REQUEST_USAGE_ATTESTATION'})
        with self.assertRaises(AdvisoryError):self.save_decision()
        self.assertEqual(len(self.history()),1)

    def test_signature_scope_key_payload_and_expiry_fail_closed(self):
        envelope=self.sign(self.review)
        for grant,now,purpose in ((replace(self.grant,revoked=True),1500,'recovery-decision'),
                (replace(self.grant,principal_id=str(uuid4())),1500,'recovery-decision'),
                (replace(self.grant,operation_sha256='0'*64),1500,'recovery-decision'),
                (self.grant,4000,'recovery-decision'),(self.grant,999,'recovery-decision'),
                (self.grant,1500,'usage-attestation'),({},1500,'recovery-decision'),(self.grant,1500,'unknown')):
            with self.assertRaises(AdvisoryError):verify_signature(self.review,envelope,grant=grant,now_ms=now,purpose=purpose)
        for payload in (b'wrong',None,b'x'*16385):
            with self.assertRaises(AdvisoryError):verify_signature(payload,envelope,grant=self.grant,now_ms=1500,purpose='recovery-decision')
        bad=decode('recovery-signature',envelope);bad['signature']='0'*128
        with self.assertRaises(AdvisoryError):verify_signature(self.review,encode('recovery-signature',bad),grant=self.grant,now_ms=1500,purpose='recovery-decision')
        with self.assertRaises(AdvisoryError):verify_signature(self.review,b'{}',grant=self.grant,now_ms=1500,purpose='recovery-decision')

    def test_strict_grant_and_signature_intervals(self):
        for changes in ({'public_key':b'x'},{'public_key':bytearray(32)},{'revoked':1},
                {'not_before_ms':True},{'expires_at_ms':900},{'purpose':'unknown'},{'principal_id':'invalid'}):
            with self.assertRaises(AdvisoryError):replace(self.grant,**changes)
        metadata=decode('recovery-signature',self.sign(self.review));metadata.pop('signature')
        for changes in ({'issued_at_ms':1000.0},{'expires_at_ms':1000},{'expires_at_ms':True}):
            with self.assertRaises(AdvisoryError):signing_bytes({**metadata,**changes})

    def test_attestation_binding_caps_and_exact_integer_counts(self):
        for key,value in (('operation_sha256','0'*64),('snapshot_sha256','0'*64),('assessment_sha256','0'*64),
                ('attempt_id',str(uuid4())),('request_sha256','0'*64),('input_sha256','0'*64),
                ('quote_sha256','0'*64),('input_tokens',11),('output_tokens',6),('input_tokens',8.0)):
            with self.subTest(key=key):
                with self.assertRaises(AdvisoryError):self.usage(encode('usage-attestation',{**self.value,key:value}))
        self.assertEqual(self.usage(encode('usage-attestation',{**self.value,'input_tokens':0,'output_tokens':0}))['charged_tokens'],0)
        for ledger in ({},self.bound):
            with self.assertRaises(AdvisoryError):verify_usage_attestation(ledger,self.payload,b'{}',grant=self.issuer_grant,now_ms=1500)

    def test_stale_evidence_and_operator_mismatch_leave_log_empty(self):
        other=replace(self.grant,principal_id=str(uuid4()))
        with self.assertRaises(AdvisoryError):record_decision(self.log,self.route,self.review,self.sign(decision_payload(self.review),other),grant=other,now_ms=1500)
        with closing(sqlite3.connect(self.route_path)) as db,db:db.execute('UPDATE metadata SET observed_ms=observed_ms+1')
        with self.assertRaises(AdvisoryError):self.save_decision()
        with self.assertRaises(AdvisoryError):self.usage()
        self.assertEqual(self.history(),[])

    def test_invalid_paths_scope_and_incomplete_evidence(self):
        with self.assertRaises(AdvisoryError):initialize_decisions(self.log,operation_sha256=self.op)
        with self.assertRaises(AdvisoryError):initialize_decisions(self.root/'invalid.db',operation_sha256='wrong')
        self.assertFalse((self.root/'invalid.db').exists())
        for ledger,path in (({},self.log),(self.route,self.route_path)):
            with self.assertRaises(AdvisoryError):record_decision(path,ledger,self.review,b'{}',grant=self.grant,now_ms=1500)
        with self.assertRaises(AdvisoryError):self.save_decision(attestation=self.payload)
        with self.assertRaisesRegex(AdvisoryError,'Complete usage evidence'):
            record_decision(self.log,self.route,self.review,b'{}',grant=self.grant,now_ms=1500,attestation=self.payload)
        with self.assertRaises(AdvisoryError):decision_history(self.log,operation_sha256='0'*64)
        with self.assertRaises(AdvisoryError):decision_history(self.root/'missing.db',operation_sha256=self.op)
        self.assertFalse((self.root/'missing.db').exists())
        for kwargs in ({'after':-1},{'limit':101},{'limit':True}):
            with self.assertRaises(AdvisoryError):self.history(**kwargs)

    def test_log_failure_rolls_back_without_releasing_usage(self):
        with closing(sqlite3.connect(self.log)) as db,db:
            db.execute("CREATE TRIGGER fail BEFORE INSERT ON decisions BEGIN SELECT RAISE(ABORT,'private detail'); END")
        before=self.route_path.read_bytes()
        with self.assertRaisesRegex(AdvisoryError,'^Recovery decision log unavailable$'):self.save_decision()
        self.assertEqual(self.history(),[]);self.assertEqual(before,self.route_path.read_bytes())

    def test_append_only_history_and_pagination(self):
        self.save_decision()
        with closing(sqlite3.connect(self.log)) as db,db:
            for statement in ('DELETE FROM decisions','UPDATE decisions SET digest=\'x\'','DELETE FROM scope'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(statement)
        self.assertEqual(self.history(after=1),[])
        with closing(sqlite3.connect(self.log)) as db,db:
            db.execute('DROP TRIGGER decisions_update');db.execute("UPDATE decisions SET digest='x'")
        with self.assertRaises(AdvisoryError):self.history()

    def test_concurrent_identical_records_commit_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            digests=list(pool.map(lambda _:self.save_decision(),range(2)))
        self.assertEqual(digests[0],digests[1]);self.assertEqual(len(self.history()),1)

    def test_attached_usage_is_bound_to_operator_signature(self):
        proof=self.sign(self.payload,self.issuer_grant,self.issuer_key)
        unsigned=self.sign(decision_payload(self.review))
        with self.assertRaises(AdvisoryError):
            record_decision(self.log,self.route,self.review,unsigned,grant=self.grant,now_ms=1500,
                            attestation=self.payload,attestation_envelope=proof,issuer_grant=self.issuer_grant)
        self.assertEqual(self.history(),[])
        for args in ((None,), (self.review,self.payload), (self.review,'text',b'proof')):
            with self.assertRaises(AdvisoryError):decision_payload(*args)

    def test_operator_and_issuer_must_be_independent(self):
        issuer=replace(self.issuer_grant,public_key=self.grant.public_key)
        with self.assertRaisesRegex(AdvisoryError,'Independent usage issuer'):
            self.save_decision(attestation=self.payload,attestation_envelope=self.sign(self.payload,issuer,self.key),issuer_grant=issuer)
        self.assertEqual(self.history(),[])

    def test_capacity_blocks_new_ids_but_preserves_exact_replay(self):
        digest=self.save_decision()
        with closing(sqlite3.connect(self.log)) as db,db:
            raw=db.execute('SELECT payload FROM decisions').fetchone()[0]
            db.executemany('INSERT INTO decisions(review_id,recorded_at_ms,payload,digest) VALUES (?,1500,?,?)',
                           [(str(uuid4()),raw,digest) for _ in range(9999)])
        self.assertEqual(self.save_decision(),digest)
        value=decode('recovery-review',self.review)
        self.review=encode('recovery-review',{**value,'review_id':str(uuid4())})
        with self.assertRaisesRegex(AdvisoryError,'capacity'):self.save_decision()
        self.assertEqual(len(self.history(limit=100)),100)

    def test_final_usage_and_wrong_issuer_operation_are_rejected(self):
        wrong=replace(self.issuer_grant,operation_sha256='0'*64)
        with self.assertRaisesRegex(AdvisoryError,'Stale usage attestation'):
            verify_usage_attestation(self.route,self.payload,self.sign(self.payload,wrong,self.issuer_key),grant=wrong,now_ms=1500)
        with closing(sqlite3.connect(self.route_path)) as db,db:
            db.execute('DELETE FROM route_events')
            db.execute('UPDATE route SET final_status=NULL')
            db.execute("UPDATE attempts SET status='SETTLED',actual_input=8,actual_output=2,charged_tokens=10,charged_cost_nusd=22")
        report=assess_recovery(self.route)
        payload=encode('usage-attestation',{**self.value,'snapshot_sha256':report['assessment']['snapshot_sha256'],
                                          'assessment_sha256':report['assessment_sha256']})
        with self.assertRaisesRegex(AdvisoryError,'attempt rejected'):self.usage(payload)
