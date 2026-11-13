# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import os
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.identity_keys import initialize_binding
from aegisflow_dr.benchmark.key_policy import initialize_key_policy, disable_key, key_history, evaluate_with_key_policy
import test_identity_keys


class KeyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=test_identity_keys.IdentityKeyTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.root/'keys.db'
        self.keys={'key-1':self.f.binding.key_material_sha256,'key-2':sha256(os.urandom(32)).hexdigest()}
        self.checkpoint=initialize_key_policy(self.path,self.keys)

    def evaluate(self,peer,**changes):
        options=dict(expected_binding_sha256=self.f.digest,peer=peer,expected_sha256=self.f.access.f.digest,
                     policy_revision='policy-1',now_ms=4000,grants=self.f.access.f.fixture.fixture.grants,
                     resolve_key=self.f.access.f.resolver,checkpoint=self.checkpoint)
        return evaluate_with_key_policy(self.path,self.f.path,self.f.access.path,
                                        self.f.access.f.fixture.fixture.path,**{**options,**changes})

    def call(self,**changes):
        with patch.object(self.f,'evaluate',side_effect=self.evaluate): return self.f.call(**changes)

    def disable(self,key='key-1',**changes):
        return disable_key(self.path,checkpoint=self.checkpoint,key_id=key,now_ms=4000,**changes)

    def history(self): return key_history(self.path,checkpoint=self.checkpoint)

    def sql(self,statement,args=()):
        with closing(sqlite3.connect(self.path)) as db,db: db.execute(statement,args)

    def test_real_peer_read_is_allowed_and_history_starts_empty(self):
        self.assertEqual(self.call()['status'],'AGREED');self.assertEqual(self.history(),[])
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertNotIn(self.f.access.f.fixture.key,self.path.read_bytes())

    def test_disable_blocks_all_bindings_and_preserves_lifecycle(self):
        self.checkpoint=self.disable()
        self.f.access.f.resolver.reset_mock()
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.path=self.f.root/'second-binding.db';self.f.digest=initialize_binding(self.f.path,self.f.binding)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.access.f.resolver.assert_not_called()
        self.assertEqual(self.history()[0]['action'],'DISABLED')
        self.assertEqual(self.disable(),self.checkpoint)
        self.assertEqual(len(self.history()),1)

    def test_unrelated_key_disable_keeps_allowed_key_usable(self):
        self.checkpoint=self.disable('key-2')
        self.assertEqual(self.call()['status'],'AGREED')

    def test_restored_old_database_rejects_current_external_checkpoint(self):
        before=self.path.read_bytes();self.checkpoint=self.disable()
        self.path.write_bytes(before)
        with self.assertRaisesRegex(BenchmarkError,'Current external'): self.history()
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.access.f.resolver.assert_not_called()

    def test_stale_checkpoint_and_wrong_catalog_reject(self):
        old=deepcopy(self.checkpoint);self.checkpoint=self.disable()
        for checkpoint in (old,{**self.checkpoint,'catalog_sha256':'0'*64},
                           {**self.checkpoint,'event_sha256':'0'*64},{**self.checkpoint,'sequence':True},{**self.checkpoint,'sequence':0.0}):
            self.assertIsInstance(self.call(checkpoint=checkpoint),BenchmarkError)
        self.f.access.f.resolver.assert_not_called()

    def test_unknown_key_and_wrong_material_reject_before_snapshot_export(self):
        with self.assertRaises(BenchmarkError): self.disable('unknown')
        self.path=self.f.root/'unknown-key.db'
        self.checkpoint=initialize_key_policy(self.path,{'other':sha256(os.urandom(32)).hexdigest()})
        self.assertIsInstance(self.call(),BenchmarkError);self.f.access.f.resolver.assert_not_called()
        self.path=self.f.root/'wrong-material.db'
        self.checkpoint=initialize_key_policy(self.path,{'key-1':sha256(os.urandom(32)).hexdigest()})
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.access.f.resolver.return_value=None
        self.assertIsInstance(self.call(),BenchmarkError)

    def test_catalog_contract_and_no_overwrite(self):
        for keys in (None,{},[],{'Bad key':'a'*64},{'key':'bad'}, {'a':'a'*64,'b':'a'*64},
                     {str(i):'a'*64 for i in range(65)}):
            with self.assertRaises(BenchmarkError): initialize_key_policy(self.f.root/'invalid.db',keys)
        self.assertFalse((self.f.root/'invalid.db').exists())
        before=self.path.read_bytes()
        with self.assertRaises(BenchmarkError): initialize_key_policy(self.path,self.keys)
        self.assertEqual(before,self.path.read_bytes())

    def test_catalog_and_event_mutations_blocked_by_normal_sql(self):
        self.checkpoint=self.disable()
        for sql in ('DELETE FROM events','UPDATE events SET payload=payload','DELETE FROM catalog','UPDATE catalog SET payload=payload'):
            with self.assertRaises(sqlite3.IntegrityError): self.sql(sql)

    def test_changed_chain_with_recomputed_tip_still_rejects_semantic_forgery(self):
        self.checkpoint=self.disable();event=self.history()[0]
        self.sql('DROP TRIGGER events_update')
        for changes in ({'previous_sha256':'0'*64},{'catalog_sha256':'0'*64},{'sequence':2},
                        {'sequence':1.0},{'key_id':'unknown'},{'action':'ENABLED'},{'time_ms':True}):
            raw=canonical({**event,**changes});self.sql('UPDATE events SET payload=?',(raw,))
            checkpoint={**self.checkpoint,'event_sha256':sha256(raw).hexdigest()}
            with self.assertRaises(BenchmarkError): key_history(self.path,checkpoint=checkpoint)

    def test_duplicate_disable_and_sequence_gap_reject(self):
        self.checkpoint=self.disable();event=self.history()[0]
        raw=canonical({**event,'sequence':2,'previous_sha256':self.checkpoint['event_sha256']})
        self.sql('INSERT INTO events VALUES (2,?)',(raw,))
        checkpoint={**self.checkpoint,'sequence':2,'event_sha256':sha256(raw).hexdigest()}
        with self.assertRaises(BenchmarkError): key_history(self.path,checkpoint=checkpoint)
        self.sql('DROP TRIGGER events_delete');self.sql('DELETE FROM events WHERE sequence=2')
        self.sql('INSERT INTO events VALUES (3,?)',(raw,))
        with self.assertRaises(BenchmarkError): key_history(self.path,checkpoint=checkpoint)

    def test_corrupt_history_resource_limit_rejects_before_parsing(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executemany('INSERT INTO events VALUES (?,?)',((i,b'{}') for i in range(1,10002)))
        with self.assertRaisesRegex(BenchmarkError,'capacity exceeded'): self.history()

    def test_creation_and_event_write_failure_are_fail_closed(self):
        path=self.f.root/'broken.db'
        with patch('aegisflow_dr.benchmark.access_registry.sqlite3.connect',side_effect=sqlite3.OperationalError('private')):
            with self.assertRaises(BenchmarkError): initialize_key_policy(path,self.keys)
        with self.assertRaises(BenchmarkError): initialize_key_policy(path,self.keys)
        self.sql("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'private'); END")
        with self.assertRaises(BenchmarkError): self.disable()
        self.assertEqual(self.history(),[])

    def test_shared_registry_path_rejects(self):
        self.path=self.f.path
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.access.f.resolver.assert_not_called()

    def test_disable_serializes_with_entire_authenticated_read(self):
        entered,release,disabling=Event(),Event(),Event()
        def resolver(access):
            entered.set()
            if not release.wait(3): raise RuntimeError('test timeout')
            return self.f.access.f.fixture.key
        def disable():
            disabling.set();return self.disable()
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading=pool.submit(self.call,resolve_key=resolver)
            self.assertTrue(entered.wait(3));pending=pool.submit(disable)
            self.assertTrue(disabling.wait(3));release.set()
            self.assertEqual(reading.result(timeout=5)['status'],'AGREED')
            self.checkpoint=pending.result(timeout=5)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.access.f.resolver.assert_not_called()
