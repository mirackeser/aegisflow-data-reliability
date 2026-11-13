# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from dataclasses import replace
from hashlib import sha256
import os
import sqlite3
import unittest
from unittest.mock import patch

from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.identity_keys import IdentityKeyBinding, initialize_binding, disable_binding, evaluate_peer
from aegisflow_dr.benchmark.access_registry import initialize_access
from aegisflow_dr.benchmark.encrypted_curation_store import retain_encrypted_curation
from aegisflow_dr.integration.secure_review import post_json
from tls_support import TestCertificates, review_server
import test_access_registry


class IdentityKeyTests(unittest.TestCase):
    def setUp(self):
        self.access = test_access_registry.AccessRegistryTests(); self.access.setUp()
        self.addCleanup(self.access.doCleanups)
        self.root = self.access.path.parent
        self.certs = TestCertificates(self.root)
        self.path = self.root/'binding.db'
        self.binding = IdentityKeyBinding(self.certs.client_pin, 'evaluator-a', self.access.digest,
                                          'key-1', sha256(self.access.f.fixture.key).hexdigest(), 3000, 7000)
        self.digest = initialize_binding(self.path, self.binding)

    def evaluate(self, peer, **changes):
        options = dict(expected_binding_sha256=self.digest, peer=peer, expected_sha256=self.access.f.digest,
                       policy_revision='policy-1', now_ms=4000, grants=self.access.f.fixture.fixture.grants,
                       resolve_key=self.access.f.resolver)
        return evaluate_peer(self.path, self.access.path, self.access.f.fixture.fixture.path, **{**options, **changes})

    def call(self, *, material=None, **changes):
        results = []
        def handler(peer, body, headers, path, policy):
            try:
                results.append(self.evaluate(peer, **changes))
            except BenchmarkError as error:
                results.append(error)
            return 200, b'{}'
        with review_server(self.certs, None, None, handler=handler) as (_, endpoint):
            post_json(b'{"principal_id":"administrator","role":"admin"}', endpoint=endpoint,
                      material=material or self.certs.client)
        self.assertEqual(len(results),1)
        return results[0]

    def disable(self, component):
        disable_binding(self.path, expected_sha256=self.digest, component=component)

    def sql(self, statement, args=()):
        with closing(sqlite3.connect(self.path)) as db, db: db.execute(statement,args)

    def test_real_verified_mtls_derives_principal_and_checks_material(self):
        result = self.call()
        self.assertEqual(result['status'],'AGREED')
        self.access.f.resolver.assert_called_once()
        self.assertEqual(self.access.history()[-1]['outcome'],'VERIFIED')
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertNotIn(self.access.f.fixture.key,self.path.read_bytes())

    def test_unverified_identity_text_and_objects_cannot_access_keys(self):
        for peer in (None, {'peer_sha256':self.certs.client_pin}, self.certs.client_pin):
            with self.assertRaisesRegex(BenchmarkError,'Authenticated evaluator channel required'): self.evaluate(peer)
        self.access.f.resolver.assert_not_called()

    def test_different_certificate_from_same_ca_is_denied(self):
        other,_ = self.certs.leaf('other',server=False)
        self.assertIsInstance(self.call(material=other),BenchmarkError)
        self.access.f.resolver.assert_not_called()

    def test_identity_and_key_disable_are_persistent_terminal_and_idempotent(self):
        for component in ('identity','key'):
            self.path=self.root/(component+'.db'); self.digest=initialize_binding(self.path,self.binding)
            self.disable(component); self.disable(component)
            self.assertIsInstance(self.call(),BenchmarkError)
            column='identity_revoked' if component=='identity' else 'key_disabled'
            with self.assertRaises(sqlite3.IntegrityError): self.sql('UPDATE binding SET '+column+'=0')
        self.access.f.resolver.assert_not_called()

    def test_wrong_secret_version_or_malformed_key_is_rejected_and_audited(self):
        for key in (None, 'secret', b'x'*31, os.urandom(32)):
            self.access.f.resolver.return_value=key
            self.assertIsInstance(self.call(),BenchmarkError)
        self.assertEqual([x['outcome'] for x in self.access.history()][1::2],['REJECTED']*4)

    def test_bound_time_limits_are_exact(self):
        for now in (2999,7000,True):
            self.assertIsInstance(self.call(now_ms=now),BenchmarkError)
        self.access.f.resolver.assert_not_called()
        self.assertEqual(self.call(now_ms=3000)['status'],'AGREED')
        self.assertEqual(self.call(now_ms=6999)['status'],'AGREED')

    def test_grant_principal_and_key_id_must_match_binding(self):
        for index, changes in enumerate(({'principal_id':'outsider'}, {'key_id':'other'}, {'grant_sha256':'0'*64})):
            self.path=self.root/(str(index)+'.db')
            self.digest=initialize_binding(self.path,replace(self.binding,**changes))
            self.assertIsInstance(self.call(),BenchmarkError)
        self.access.f.resolver.assert_not_called()

    def test_changed_external_digest_denies_before_resolution(self):
        self.assertIsInstance(self.call(expected_binding_sha256='0'*64),BenchmarkError)
        self.access.f.resolver.assert_not_called()

    def test_invalid_binding_and_disable_contracts(self):
        for changes in ({'peer_sha256':'bad'}, {'principal_id':'Bad ID'}, {'key_material_sha256':'bad'},
                        {'grant_sha256':'bad'}, {'key_id':'Bad ID'}, {'not_before_ms':True},
                        {'not_before_ms':7000}, {'expires_at_ms':3000}):
            with self.assertRaises(BenchmarkError): replace(self.binding,**changes)
        with self.assertRaises(BenchmarkError): initialize_binding(self.root/'invalid.db',None)
        with self.assertRaises(BenchmarkError): self.disable('both')
        self.assertFalse((self.root/'invalid.db').exists())

    def test_existing_file_cannot_be_overwritten_and_binding_cannot_be_mutated(self):
        before=self.path.read_bytes()
        with self.assertRaises(BenchmarkError): initialize_binding(self.path,self.binding)
        self.assertEqual(before,self.path.read_bytes())
        for statement in ('DELETE FROM binding',"UPDATE binding SET payload=x'00'"):
            with self.assertRaises(sqlite3.IntegrityError): self.sql(statement)

    def test_shared_registry_path_rejected_before_authentication(self):
        self.path=self.access.path
        with self.assertRaisesRegex(BenchmarkError,'Separate binding'): self.evaluate(None)

    def test_corrupt_flags_and_rehashed_invalid_payload_reject(self):
        self.sql('DROP TRIGGER preserve_binding')
        raw=canonical({'unexpected':1}); self.sql('UPDATE binding SET payload=?',(raw,))
        self.assertIsInstance(self.call(expected_binding_sha256=sha256(raw).hexdigest()),BenchmarkError)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA ignore_check_constraints=ON');db.execute('UPDATE binding SET key_disabled=2')
        self.assertIsInstance(self.call(expected_binding_sha256=sha256(raw).hexdigest()),BenchmarkError)
        self.access.f.resolver.assert_not_called()

    def test_creation_failure_leaves_no_reusable_policy(self):
        path=self.root/'broken.db'
        with patch('aegisflow_dr.benchmark.access_registry.sqlite3.connect',side_effect=sqlite3.OperationalError('private')):
            with self.assertRaises(BenchmarkError): initialize_binding(path,self.binding)
        with self.assertRaises(BenchmarkError): initialize_binding(path,self.binding)

    def test_certificate_renewal_requires_explicit_new_binding(self):
        renewed,pin=self.certs.leaf('renewed',server=False)
        self.assertIsInstance(self.call(material=renewed),BenchmarkError)
        self.disable('identity');old=self.path
        self.path=self.root/'renewed.db';self.digest=initialize_binding(self.path,replace(self.binding,peer_sha256=pin))
        self.assertEqual(self.call(material=renewed)['status'],'AGREED')
        self.assertIsInstance(self.call(),BenchmarkError)
        self.assertTrue(old.exists())

    def test_key_rotation_requires_new_snapshot_grant_and_binding(self):
        self.disable('key'); old=self.path
        encrypted=self.access.f.fixture
        signed=encrypted.fixture
        old_snapshot=signed.path
        key=os.urandom(32); signed.path=self.root/'rotated-snapshot.db'
        snapshot=retain_encrypted_curation(signed.path,signed.development,signed.candidate,
            signed.signed.annotations,signed.signed.envelopes,grants=signed.grants,policy_revision='policy-1',
            now_ms=3000,key=key,key_id='key-2')
        self.access.path=self.root/'rotated-access.db'
        grant=replace(self.access.f.access,snapshot_sha256=snapshot,key_id='key-2')
        grant_digest=initialize_access(self.access.path,grant)
        self.access.f.digest=snapshot;self.access.f.resolver.return_value=key
        self.path=self.root/'rotated-binding.db'
        self.digest=initialize_binding(self.path,replace(self.binding,grant_sha256=grant_digest,
            key_id='key-2',key_material_sha256=sha256(key).hexdigest()))
        self.assertEqual(self.call()['status'],'AGREED')
        self.assertTrue(old.exists());self.assertTrue(old_snapshot.exists())
        self.assertIsInstance(self.call(expected_sha256=self.binding.grant_sha256),BenchmarkError)

    def test_disable_serializes_with_inflight_authenticated_read(self):
        for component in ('identity','key'):
            self.path=self.root/('concurrent-'+component+'.db')
            self.digest=initialize_binding(self.path,self.binding)
            entered,release,disabling=Event(),Event(),Event()
            def resolver(access):
                entered.set()
                if not release.wait(3): raise RuntimeError('test timeout')
                return self.access.f.fixture.key
            def disable():
                disabling.set(); self.disable(component)
            with ThreadPoolExecutor(max_workers=2) as pool:
                reading=pool.submit(self.call,resolve_key=resolver)
                self.assertTrue(entered.wait(3))
                pending=pool.submit(disable)
                self.assertTrue(disabling.wait(3));release.set()
                self.assertEqual(reading.result(timeout=5)['status'],'AGREED')
                pending.result(timeout=5)
            self.assertIsInstance(self.call(),BenchmarkError)
        self.access.f.resolver.assert_not_called()
