# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import os
import sqlite3
import unittest

from aegisflow_dr.benchmark.core import BenchmarkError, canonical, parse
from aegisflow_dr.benchmark.encrypted_curation_store import HEADER, retain_encrypted_curation, read_encrypted_curation
from aegisflow_dr.benchmark.signed_curation_store import read_signed_curation
import test_signed_curation_store


class EncryptedCurationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_signed_curation_store.SignedCurationStoreTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.key = os.urandom(32)

    def retain(self, **changes):
        f = self.fixture
        options = dict(grants=f.grants, policy_revision='policy-1', now_ms=3000, key=self.key, key_id='key-1')
        return retain_encrypted_curation(f.path, f.development, f.candidate, f.signed.annotations,
                                         f.signed.envelopes, **{**options, **changes})

    def read(self, digest, **changes):
        f = self.fixture
        options = dict(expected_sha256=digest, grants=f.grants, policy_revision='policy-1',
                       now_ms=4000, key=self.key, key_id='key-1')
        return read_encrypted_curation(f.path, **{**options, **changes})

    def rehash(self, name, raw):
        header = self.fixture.header(); header['artifacts'][name] = sha256(raw).hexdigest()
        self.fixture.mutate('UPDATE artifacts SET value=? WHERE name=?', (raw, name))
        encoded = canonical(header)
        self.fixture.mutate("UPDATE artifacts SET value=? WHERE name='header'", (encoded,))
        return sha256(encoded).hexdigest()

    def test_roundtrip_never_writes_plaintext_source_labels_policy_or_signatures(self):
        digest = self.retain(); result = self.read(digest)
        self.assertEqual(result['status'], 'AGREED')
        self.assertEqual(result['encryption']['snapshot_sha256'], digest)
        self.assertEqual(result['authentication']['verified_at_ms'], 4000)
        disk = self.fixture.path.read_bytes()
        for raw in (self.fixture.development, self.fixture.candidate, *self.fixture.signed.annotations,
                    *self.fixture.signed.envelopes, self.key, b'public_key_hex', b'csv_text'):
            self.assertNotIn(raw, disk)
        self.assertEqual(self.fixture.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.read(digest), result)

    def test_fresh_snapshots_have_independent_random_ciphertexts(self):
        first = self.retain(); first_header = self.fixture.header()
        self.fixture.path = self.fixture.path.parent/'second.db'
        second = self.retain()
        self.assertNotEqual(first, second)
        self.assertNotEqual(first_header['snapshot_id'], self.fixture.header()['snapshot_id'])
        self.assertNotEqual(first_header['artifacts'], self.fixture.header()['artifacts'])

    def test_wrong_missing_key_and_wrong_key_id_fail_closed(self):
        digest = self.retain()
        for key in (None, b'x'*31, 'private', os.urandom(32)):
            with self.assertRaises(BenchmarkError): self.read(digest, key=key)
        for key_id in ('other-key', 'Bad ID'):
            with self.assertRaises(BenchmarkError): self.read(digest, key_id=key_id)
        with self.assertRaises(BenchmarkError): self.read('0'*64)

    def test_current_signing_policy_expiry_and_time_still_apply_after_decryption(self):
        digest = self.retain()
        for changes in ({'policy_revision':'policy-2'}, {'now_ms':8000}, {'now_ms':2999},
                        {'grants':(replace(self.fixture.grants[0], revoked=True), self.fixture.grants[1])}):
            with self.assertRaises(BenchmarkError): self.read(digest, **changes)

    def test_changed_ciphertext_detected_before_decryption(self):
        digest = self.retain()
        self.fixture.mutate("UPDATE artifacts SET value=? WHERE name='candidate'", (os.urandom(40),))
        with self.assertRaisesRegex(BenchmarkError, 'integrity rejected'): self.read(digest)

    def test_rehashed_ciphertext_and_truncation_cannot_forge_aead(self):
        for index, raw in enumerate((b'x', os.urandom(40))):
            self.fixture.path = self.fixture.path.parent/(str(index)+'.db'); self.retain()
            digest = self.rehash('candidate', raw)
            with self.assertRaises(BenchmarkError): self.read(digest)

    def test_artifact_swap_rejected_even_with_recomputed_public_header(self):
        self.retain()
        with closing(sqlite3.connect(self.fixture.path)) as connection:
            raw = connection.execute("SELECT value FROM artifacts WHERE name='annotation_a'").fetchone()[0]
        digest = self.rehash('annotation_b', raw)
        with self.assertRaisesRegex(BenchmarkError, 'decryption rejected'): self.read(digest)

    def test_snapshot_aad_and_header_schema_are_enforced(self):
        for index, changes in enumerate(({'snapshot_id':'0'*32}, {'version':'other'}, {'extra':True})):
            self.fixture.path = self.fixture.path.parent/(str(index)+'.db'); self.retain()
            raw = canonical({**self.fixture.header(), **changes})
            self.fixture.mutate("UPDATE artifacts SET value=? WHERE name='header'", (raw,))
            with self.assertRaises(BenchmarkError): self.read(sha256(raw).hexdigest())

    def test_invalid_key_or_signatures_do_not_create_file(self):
        for changes in ({'key':None}, {'key_id':'Bad ID'}, {'now_ms':8000}):
            with self.assertRaises(BenchmarkError): self.retain(**changes)
            self.assertFalse(self.fixture.path.exists())

    def test_existing_plaintext_and_encrypted_formats_never_overwrite_or_cross_read(self):
        digest = self.retain(); original = self.fixture.path.read_bytes()
        with self.assertRaises(BenchmarkError): self.retain()
        self.assertEqual(self.fixture.path.read_bytes(), original)
        with self.assertRaises(BenchmarkError): self.fixture.read(digest)
        self.fixture.path = self.fixture.path.parent/'plaintext.db'; signed = self.fixture.retain()
        with self.assertRaises(BenchmarkError): self.read(signed)

    def test_signed_disagreement_stays_blocked_after_encryption(self):
        signed = self.fixture.signed
        annotation = parse(signed.annotations[1]); annotation['labels'][0]['label'] = annotation['labels'][1]['label']
        signed.annotations = (signed.annotations[0], canonical(annotation))
        signed.envelopes = (signed.envelopes[0], signed.envelope(1))
        result = self.read(self.retain())
        self.assertEqual(result['status'], 'DISAGREEMENT'); self.assertEqual(result['cases'], [])

    def test_exported_header_schema_matches_runtime(self):
        self.assertEqual(parse(Path('docs/contracts/encrypted-curation-header-v1.json').read_bytes()), HEADER)
