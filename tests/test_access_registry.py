# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from dataclasses import replace, asdict
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from hashlib import sha256
import sqlite3
import unittest
from unittest.mock import patch
from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.access_registry import initialize_access, evaluate_registered, revoke_access, access_history
import test_curation_access


class AccessRegistryTests(unittest.TestCase):
    def setUp(self):
        self.f = test_curation_access.CurationAccessTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.path = self.f.fixture.fixture.path.parent/'access.db'
        self.digest = initialize_access(self.path, self.f.access)

    def read(self, **changes):
        options = dict(expected_grant_sha256=self.digest, principal_id='evaluator-a', role='evaluator',
                       expected_sha256=self.f.digest, key_id='key-1', policy_revision='policy-1',
                       now_ms=4000, grants=self.f.fixture.fixture.grants, resolve_key=self.f.resolver)
        return evaluate_registered(self.path, self.f.fixture.fixture.path, **{**options, **changes})

    def history(self, **changes):
        return access_history(self.path, expected_sha256=self.digest, **changes)

    def sql(self, sql, args=()):
        with closing(sqlite3.connect(self.path)) as db, db: db.execute(sql,args)

    def test_durable_read_and_audit_reopen(self):
        self.assertEqual(self.read()['status'], 'AGREED')
        self.assertEqual([x['outcome'] for x in self.history()], ['STARTED','VERIFIED'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.f.fixture.key, self.path.read_bytes())
        self.assertEqual(self.history(after=1,limit=1)[0]['outcome'], 'VERIFIED')
        self.assertEqual(self.history(after=2), [])

    def test_denied_scope_is_audited_before_any_key_resolution(self):
        for changes in ({'role':'curator'}, {'principal_id':'outsider'}, {'key_id':'other'}, {'now_ms':7000}):
            with self.assertRaises(BenchmarkError): self.read(**changes)
        self.f.resolver.assert_not_called()
        self.assertEqual([x['outcome'] for x in self.history()][1::2], ['REJECTED']*4)

    def test_revocation_survives_reopen_is_terminal_and_idempotent(self):
        revoke_access(self.path,expected_sha256=self.digest,now_ms=4000)
        revoke_access(self.path,expected_sha256=self.digest,now_ms=4001)
        with self.assertRaises(BenchmarkError): self.read()
        self.f.resolver.assert_not_called()
        self.assertEqual([x['outcome'] for x in self.history()], ['REVOKED','STARTED','REJECTED'])
        with self.assertRaises(sqlite3.IntegrityError): self.sql('UPDATE authority SET revoked=0')

    def test_wrong_binding_missing_and_corrupt_database_reject_without_resolver(self):
        with self.assertRaises(BenchmarkError): self.read(expected_grant_sha256='0'*64)
        self.path=self.path.parent/'missing.db'
        with self.assertRaises(BenchmarkError): self.read()
        self.assertFalse(self.path.exists())
        self.path.write_bytes(b'private corrupt bytes')
        with self.assertRaisesRegex(BenchmarkError,'^Access registry unavailable$'): self.read()
        self.f.resolver.assert_not_called()

    def test_invalid_grants_and_existing_files_are_not_overwritten(self):
        before=self.path.read_bytes()
        for access in (None, replace(self.f.access,revoked=True), self.f.access):
            with self.assertRaises(BenchmarkError): initialize_access(self.path,access)
        self.assertEqual(before,self.path.read_bytes())

    def test_history_is_bounded_and_audit_mutations_are_blocked(self):
        self.read()
        for kwargs in ({'after':True},{'after':-1},{'limit':0},{'limit':101},{'limit':1.0}):
            with self.assertRaises(BenchmarkError): self.history(**kwargs)
        for sql in ('DELETE FROM audit','UPDATE audit SET outcome=outcome','DELETE FROM authority',"UPDATE authority SET payload=x'00'"):
            with self.assertRaises(sqlite3.IntegrityError): self.sql(sql)

    def test_key_failure_is_sanitized_and_retained_as_rejection(self):
        self.f.resolver.side_effect=RuntimeError('private detail')
        with self.assertRaisesRegex(BenchmarkError,'^Registered evaluation rejected$'): self.read()
        self.assertEqual(self.history()[-1]['outcome'],'REJECTED')
        self.assertNotIn('private detail',str(self.history()))

    def test_audit_failure_blocks_key_resolution(self):
        self.sql("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'private detail'); END")
        with self.assertRaisesRegex(BenchmarkError,'^Access registry unavailable$'): self.read()
        self.f.resolver.assert_not_called()
        self.assertEqual(self.history(),[])

    def test_final_audit_failure_never_returns_labels(self):
        self.sql("CREATE TRIGGER fail_verified BEFORE INSERT ON audit WHEN NEW.outcome='VERIFIED' BEGIN SELECT RAISE(ABORT,'private detail'); END")
        with self.assertRaises(BenchmarkError): self.read()
        self.f.resolver.assert_called_once()
        self.assertEqual(self.history(),[])

    def test_malformed_rehashed_grant_and_revocation_reject(self):
        self.sql('DROP TRIGGER preserve_authority')
        raw=canonical({'unexpected':'value'})
        self.sql('UPDATE authority SET payload=?',(raw,))
        with self.assertRaisesRegex(BenchmarkError,'grant rejected'): self.read(expected_grant_sha256=sha256(raw).hexdigest())
        self.sql('PRAGMA ignore_check_constraints=ON')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA ignore_check_constraints=ON')
            db.execute('UPDATE authority SET payload=?,revoked=2',(canonical(asdict(self.f.access)),))
        with self.assertRaisesRegex(BenchmarkError,'revocation rejected'): self.read()

    def test_failure_during_creation_rolls_back_and_reserves_path(self):
        self.path=self.path.parent/'broken.db'
        with patch('aegisflow_dr.benchmark.access_registry.sqlite3.connect',side_effect=sqlite3.OperationalError('private')):
            with self.assertRaises(BenchmarkError): initialize_access(self.path,self.f.access)
        with self.assertRaises(BenchmarkError): initialize_access(self.path,self.f.access)

    def test_concurrent_revocation_serializes_after_inflight_read(self):
        entered, release, revoking = Event(), Event(), Event()
        def resolver(access):
            entered.set()
            if not release.wait(3): raise RuntimeError('test synchronization timeout')
            return self.f.fixture.key
        def revoke():
            revoking.set()
            revoke_access(self.path,expected_sha256=self.digest,now_ms=4001)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reading=pool.submit(self.read,resolve_key=resolver)
            self.assertTrue(entered.wait(3))
            revocation=pool.submit(revoke)
            self.assertTrue(revoking.wait(3))
            release.set()
            self.assertEqual(reading.result(timeout=5)['status'],'AGREED')
            revocation.result(timeout=5)
        with self.assertRaises(BenchmarkError): self.read()
        self.f.resolver.assert_not_called()
        self.assertEqual([x['outcome'] for x in self.history()],['STARTED','VERIFIED','REVOKED','STARTED','REJECTED'])
