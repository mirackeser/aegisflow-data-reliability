# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
import unittest
from unittest.mock import Mock
from aegisflow_dr.benchmark.core import BenchmarkError
from aegisflow_dr.benchmark.curation_access import EvaluationAccess, read_for_evaluation
import test_encrypted_curation_store


class CurationAccessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_encrypted_curation_store.EncryptedCurationTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.digest = self.fixture.retain()
        self.access = EvaluationAccess('evaluator-a', self.digest, 'key-1', 'policy-1', 3000, 7000)
        self.resolver = Mock(return_value=self.fixture.key)

    def read(self, **changes):
        options = dict(access=self.access, principal_id='evaluator-a', role='evaluator',
                       expected_sha256=self.digest, key_id='key-1', policy_revision='policy-1',
                       now_ms=4000, grants=self.fixture.fixture.grants, resolve_key=self.resolver)
        return read_for_evaluation(self.fixture.fixture.path, **{**options, **changes})

    def test_authorized_read_returns_verified_result_without_key(self):
        result = self.read()
        self.assertEqual(result['status'], 'AGREED')
        self.resolver.assert_called_once_with(self.access)
        self.assertNotIn(self.fixture.key.hex(), str(result))

    def test_every_scope_mismatch_denies_before_key_resolution(self):
        for changes in ({'principal_id':'other'}, {'role':'curator'}, {'role':'admin'},
                        {'expected_sha256':'0'*64}, {'key_id':'other'}, {'policy_revision':'other'},
                        {'now_ms':2999}, {'now_ms':7000}, {'access':None},
                        {'access':replace(self.access, revoked=True)}, {'now_ms':True}):
            with self.subTest(changes=changes), self.assertRaises(BenchmarkError): self.read(**changes)
        self.resolver.assert_not_called()

    def test_interval_start_is_inclusive_end_is_exclusive(self):
        self.assertEqual(self.read(now_ms=3000)['status'], 'AGREED')
        self.assertEqual(self.read(now_ms=6999)['status'], 'AGREED')

    def test_key_failure_is_sanitized_without_fallback(self):
        self.resolver.side_effect = RuntimeError('private credential detail')
        with self.assertRaisesRegex(BenchmarkError, '^Evaluation key unavailable$'): self.read()
        self.resolver.assert_called_once()

    def test_wrong_key_and_expired_signatures_still_block(self):
        self.resolver.return_value = b'x'*32
        with self.assertRaises(BenchmarkError): self.read()
        self.resolver.return_value = self.fixture.key
        with self.assertRaises(BenchmarkError): self.read(access=replace(self.access, expires_at_ms=9000), now_ms=8000)

    def test_invalid_grant_contract_rejects(self):
        for changes in ({'principal_id':'Bad ID'}, {'snapshot_sha256':'bad'}, {'key_id':'bad key'},
                        {'policy_revision':'bad revision'}, {'revoked':1}, {'not_before_ms':True},
                        {'not_before_ms':7000}, {'expires_at_ms':0}):
            with self.subTest(changes=changes), self.assertRaises(BenchmarkError): replace(self.access, **changes)
