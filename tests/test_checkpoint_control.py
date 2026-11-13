# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
import subprocess
import sys
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.checkpoint_control import initialize_checkpoint, checkpoint_status, managed_disable, recover_checkpoint, evaluate_managed
from aegisflow_dr.benchmark.key_policy import disable_key, key_history
import test_key_policy


class CheckpointControlTests(unittest.TestCase):
    def setUp(self):
        self.f=test_key_policy.KeyPolicyTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.f.root/'checkpoint.db'
        self.catalog=initialize_checkpoint(self.path,self.f.path,checkpoint=self.f.checkpoint)

    def status(self): return checkpoint_status(self.path,catalog_sha256=self.catalog)
    def disable(self,key='key-1'): return managed_disable(self.path,self.f.path,catalog_sha256=self.catalog,key_id=key,now_ms=4000)
    def recover(self): return recover_checkpoint(self.path,self.f.path,catalog_sha256=self.catalog)

    def evaluate(self,peer,**changes):
        f=self.f.f
        options=dict(catalog_sha256=self.catalog,expected_binding_sha256=f.digest,peer=peer,
                     expected_sha256=f.access.f.digest,policy_revision='policy-1',now_ms=4000,
                     grants=f.access.f.fixture.fixture.grants,resolve_key=f.access.f.resolver)
        return evaluate_managed(self.path,self.f.path,f.path,f.access.path,f.access.f.fixture.fixture.path,**{**options,**changes})

    def call(self,**changes):
        with patch.object(self.f.f,'evaluate',side_effect=self.evaluate): return self.f.f.call(**changes)

    def pending(self):
        with patch('aegisflow_dr.benchmark.checkpoint_control.recover_checkpoint',side_effect=RuntimeError('crash after intent')):
            with self.assertRaises(RuntimeError): self.disable()

    def sql(self,statement,args=()):
        with closing(sqlite3.connect(self.path)) as db,db: db.execute(statement,args)

    def test_managed_peer_read_then_disable_publish_and_replay(self):
        self.assertEqual(self.call()['status'],'AGREED')
        checkpoint=self.disable()
        self.assertEqual(self.status(),{'version':'1','current':checkpoint,'pending':None})
        self.assertEqual(self.disable(),checkpoint);self.assertEqual(self.recover(),checkpoint)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.assertEqual(len(key_history(self.f.path,checkpoint=checkpoint)),1)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_durable_intent_blocks_reads_and_other_mutations_before_policy_write(self):
        self.pending()
        self.assertIsNotNone(self.status()['pending'])
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.f.access.f.resolver.assert_not_called()
        with self.assertRaisesRegex(BenchmarkError,'recovery required'): self.disable('key-2')
        self.assertEqual(key_history(self.f.path,checkpoint=self.f.checkpoint),[])
        checkpoint=self.recover()
        self.assertEqual(checkpoint['sequence'],1)
        self.assertIsNone(self.status()['pending'])

    def test_recover_after_policy_commit_before_checkpoint_publication(self):
        self.pending();state=self.status()
        actual=disable_key(self.f.path,checkpoint=state['current'],key_id='key-1',now_ms=4000)
        self.assertEqual(actual,state['pending']['next'])
        self.assertIsInstance(self.call(),BenchmarkError)
        self.assertEqual(self.recover(),actual)
        self.assertEqual(self.recover(),actual)
        self.assertEqual(len(key_history(self.f.path,checkpoint=actual)),1)

    def test_publication_write_failure_keeps_intent_and_blocks_until_recovery(self):
        self.pending()
        self.sql("CREATE TRIGGER fail_publish BEFORE UPDATE ON checkpoint BEGIN SELECT RAISE(ABORT,'private'); END")
        with self.assertRaises(BenchmarkError): self.recover()
        state=self.status();self.assertIsNotNone(state['pending'])
        self.assertEqual(len(key_history(self.f.path,checkpoint=state['pending']['next'])),1)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.sql('DROP TRIGGER fail_publish')
        self.assertEqual(self.recover(),state['pending']['next'])

    def test_intent_write_failure_never_changes_policy(self):
        self.sql("CREATE TRIGGER fail_intent BEFORE UPDATE ON checkpoint BEGIN SELECT RAISE(ABORT,'private'); END")
        with self.assertRaises(BenchmarkError): self.disable()
        self.assertEqual(key_history(self.f.path,checkpoint=self.f.checkpoint),[])
        self.assertIsNone(self.status()['pending'])

    def test_old_policy_restore_is_rejected_and_never_auto_trusted(self):
        backup=self.f.path.read_bytes();self.disable();self.f.path.write_bytes(backup)
        self.assertIsInstance(self.call(),BenchmarkError)
        with self.assertRaises(BenchmarkError): self.recover()
        self.f.f.access.f.resolver.assert_not_called()

    def test_divergent_policy_successor_cannot_clear_intent(self):
        self.pending()
        disable_key(self.f.path,checkpoint=self.f.checkpoint,key_id='key-2',now_ms=4000)
        with self.assertRaises(BenchmarkError): self.recover()
        self.assertIsNotNone(self.status()['pending'])
        self.assertIsInstance(self.call(),BenchmarkError)

    def test_unknown_key_is_rejected_without_persistent_intent(self):
        with self.assertRaises(BenchmarkError): self.disable('unknown')
        self.assertIsNone(self.status()['pending']);self.assertEqual(self.recover(),self.f.checkpoint)

    def test_expected_catalog_and_closed_state_contract_are_required(self):
        with self.assertRaises(BenchmarkError): checkpoint_status(self.path,catalog_sha256='0'*64)
        state=self.status()
        for altered in ({**state,'extra':True},{**state,'current':{**state['current'],'sequence':0.0}}):
            self.sql('UPDATE checkpoint SET payload=?',(canonical(altered),))
            with self.assertRaises(BenchmarkError): self.status()
        self.sql('UPDATE checkpoint SET payload=?',(canonical(state),))
        self.pending();pending=self.status()
        for altered in ({**pending['pending'],'time_ms':4000.0},
                        {**pending['pending'],'next':{**pending['pending']['next'],'sequence':1.0}},
                        {**pending['pending'],'next':{**pending['pending']['next'],'event_sha256':'0'*64}}):
            self.sql('UPDATE checkpoint SET payload=?',(canonical({**pending,'pending':altered}),))
            with self.assertRaises(BenchmarkError): self.recover()

    def test_missing_corrupt_and_existing_control_files_fail_closed(self):
        before=self.path.read_bytes()
        with self.assertRaises(BenchmarkError): initialize_checkpoint(self.path,self.f.path,checkpoint=self.f.checkpoint)
        self.assertEqual(before,self.path.read_bytes())
        self.sql('DELETE FROM checkpoint')
        with self.assertRaises(BenchmarkError): self.status()
        self.path=self.path.parent/'missing.db'
        with self.assertRaises(BenchmarkError): self.status()
        self.assertFalse(self.path.exists())

    def test_shared_paths_rejected_and_bad_initial_checkpoint_creates_nothing(self):
        with self.assertRaises(BenchmarkError): initialize_checkpoint(self.f.path,self.f.path,checkpoint=self.f.checkpoint)
        target=self.path.parent/'new.db'
        with self.assertRaises(BenchmarkError): initialize_checkpoint(target,self.f.path,checkpoint={})
        self.assertFalse(target.exists())
        self.path=self.f.path
        self.assertIsInstance(self.call(),BenchmarkError)

    def test_unexpected_disable_result_keeps_recovery_pending(self):
        self.pending()
        with patch('aegisflow_dr.benchmark.checkpoint_control.disable_key',return_value=self.f.checkpoint):
            with self.assertRaisesRegex(BenchmarkError,'Unexpected policy successor'): self.recover()
        self.assertIsNotNone(self.status()['pending'])

    def test_concurrent_publish_requests_never_lose_a_disable(self):
        self.pending()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.recover(),range(2)))
        self.assertEqual(results[0],results[1])
        self.assertEqual(len(key_history(self.f.path,checkpoint=results[0])),1)

    def test_read_and_disable_follow_anchor_first_lock_order(self):
        entered,release,disabling=Event(),Event(),Event()
        def resolver(access):
            entered.set()
            if not release.wait(3): raise RuntimeError('test timeout')
            return self.f.f.access.f.fixture.key
        def disable():
            disabling.set();return self.disable()
        with ThreadPoolExecutor(max_workers=2) as pool:
            read=pool.submit(self.call,resolve_key=resolver)
            self.assertTrue(entered.wait(3));change=pool.submit(disable)
            self.assertTrue(disabling.wait(3));release.set()
            self.assertEqual(read.result(timeout=5)['status'],'AGREED')
            self.assertEqual(change.result(timeout=5)['sequence'],1)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.f.f.access.f.resolver.assert_not_called()

    def test_process_exit_after_policy_commit_recovers_exact_persisted_intent(self):
        self.pending();expected=self.status()['pending']['next']
        script="""import os,sys
from unittest.mock import patch
from aegisflow_dr.benchmark.checkpoint_control import recover_checkpoint
with patch('aegisflow_dr.benchmark.checkpoint_control._save',side_effect=lambda *args:os._exit(37)):
    recover_checkpoint(sys.argv[1],sys.argv[2],catalog_sha256=sys.argv[3])
"""
        result=subprocess.run([sys.executable,'-c',script,str(self.path),str(self.f.path),self.catalog],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,37,result.stderr)
        self.assertIsNotNone(self.status()['pending'])
        self.assertEqual(len(key_history(self.f.path,checkpoint=expected)),1)
        self.assertIsInstance(self.call(),BenchmarkError)
        self.assertEqual(self.recover(),expected)
        self.assertIsNone(self.status()['pending'])
