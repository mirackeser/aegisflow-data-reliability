# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aegisflow_dr.benchmark.core import BenchmarkError, canonical, parse
from aegisflow_dr.benchmark.curation_store import read_curation, retain_curation
from aegisflow_dr.benchmark.signed_curation_store import (
    HEADER, read_signed_curation, retain_signed_curation,
)
import test_curation
import test_curation_auth


class SignedCurationStoreTests(unittest.TestCase):
    def setUp(self):
        self.signed = test_curation_auth.CurationAuthenticationTests(); self.signed.setUp()
        fixture = test_curation.CurationTests(); fixture.setUp()
        self.development = canonical(fixture.development)
        self.candidate = canonical(fixture.candidates)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'signed.db'
        self.grants = self.signed.grants

    def retain(self, **changes):
        options = {'grants': self.grants, 'policy_revision': 'policy-1', 'now_ms': 3000}
        return retain_signed_curation(self.path, self.development, self.candidate,
                                      self.signed.annotations, self.signed.envelopes, **{**options, **changes})

    def read(self, digest, **changes):
        options = {'expected_sha256': digest, 'grants': self.grants,
                   'policy_revision': 'policy-1', 'now_ms': 4000}
        return read_signed_curation(self.path, **{**options, **changes})

    def mutate(self, sql, parameters=()):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            for action in ('insert', 'update', 'delete'):
                connection.execute('DROP TRIGGER IF EXISTS immutable_'+action)
            connection.execute(sql, parameters)

    def header(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return parse(connection.execute("SELECT value FROM artifacts WHERE name='header'").fetchone()[0])

    def test_roundtrip_preserves_exact_signed_artifacts_and_policy(self):
        digest = self.retain(); result = self.read(digest)
        self.assertEqual(result['status'], 'AGREED')
        self.assertEqual(result['authentication']['verified_at_ms'], 4000)
        self.assertEqual(result['retention']['retained_at_ms'], 3000)
        self.assertEqual(result['retention']['snapshot_sha256'], digest)
        self.assertEqual(result, self.read(digest))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(self.path)) as connection:
            artifacts = dict(connection.execute('SELECT name,value FROM artifacts'))
        self.assertEqual(len(artifacts), 8)
        self.assertEqual(artifacts['envelope_a'], self.signed.envelopes[0])
        self.assertEqual(artifacts['envelope_b'], self.signed.envelopes[1])
        self.assertEqual(artifacts['annotation_a'], self.signed.annotations[0])
        policy = parse(artifacts['trust_policy'])
        self.assertEqual(policy['revision'], 'policy-1')
        self.assertEqual(policy['grants'][0]['public_key_hex'], self.grants[0].public_key.hex())
        self.assertEqual(result['retention']['policy_sha256'], sha256(artifacts['trust_policy']).hexdigest())
        self.assertNotIn('csv_text', str(result)); self.assertNotIn('public_key_hex', str(result))

    def test_disagreement_remains_retained_without_exporting_labels(self):
        annotation = parse(self.signed.annotations[1]); annotation['labels'][0]['label'] = annotation['labels'][1]['label']
        self.signed.annotations = (self.signed.annotations[0], canonical(annotation))
        self.signed.envelopes = (self.signed.envelopes[0], self.signed.envelope(1))
        result = self.read(self.retain())
        self.assertEqual(result['status'], 'DISAGREEMENT'); self.assertEqual(result['cases'], [])
        self.assertEqual(len(result['authentication']['proofs']), 2)

    def test_current_grants_revision_revocation_and_expiry_are_required(self):
        digest = self.retain()
        changes = ({'policy_revision': 'policy-2'}, {'grants': (replace(self.grants[0], revoked=True), self.grants[1])},
                   {'grants': (replace(self.grants[0], expires_at_ms=8500), self.grants[1])},
                   {'grants': tuple(reversed(self.grants))}, {'now_ms': 8000})
        for options in changes:
            with self.subTest(options=options), self.assertRaises(BenchmarkError): self.read(digest, **options)
        self.assertEqual(self.read(digest, now_ms=7999)['status'], 'AGREED')

    def test_missing_untrusted_policy_never_bootstraps_from_stored_keys(self):
        digest = self.retain()
        for grants in (None, [], (), (None, None), (self.grants[0],)):
            with self.assertRaises(BenchmarkError): self.read(digest, grants=grants)
        with self.assertRaises(BenchmarkError): self.read(digest, policy_revision='Bad revision')
        with self.assertRaises(BenchmarkError): self.read('0'*64)

    def test_time_cannot_precede_retention_or_use_bool_float(self):
        digest = self.retain()
        self.read(digest, now_ms=3000)
        for now in (2999, True, 4000.0, -1):
            with self.assertRaises(BenchmarkError): self.read(digest, now_ms=now)

    def test_invalid_evidence_fails_before_any_file_is_created(self):
        for options in ({'now_ms': 8000}, {'grants': None}, {'policy_revision': 'Bad revision'}):
            with self.assertRaises(BenchmarkError): self.retain(**options)
            self.assertFalse(self.path.exists())
        self.signed.envelopes = (b'{}', self.signed.envelopes[1])
        with self.assertRaises(BenchmarkError): self.retain()
        self.assertFalse(self.path.exists())

    def test_existing_file_and_symlink_cannot_be_overwritten(self):
        digest = self.retain(); before = self.path.read_bytes()
        with self.assertRaises(BenchmarkError): self.retain()
        self.assertEqual(self.path.read_bytes(), before)
        original = self.path; self.path = original.parent/'link.db'; self.path.symlink_to(original)
        with self.assertRaises(BenchmarkError): self.retain()
        self.assertEqual(self.read(digest)['status'], 'AGREED')

    def test_unsigned_and_signed_formats_cannot_be_confused(self):
        reviewers = tuple(g.reviewer_id for g in self.grants)
        digest = self.retain()
        with self.assertRaises(BenchmarkError): read_curation(self.path, expected_sha256=digest, reviewer_ids=reviewers)
        self.path = self.path.parent/'unsigned.db'
        digest = retain_curation(self.path, self.development, self.candidate, self.signed.annotations, reviewer_ids=reviewers)
        with self.assertRaises(BenchmarkError): self.read(digest)

    def test_normal_sql_mutations_remain_blocked(self):
        digest = self.retain()
        for sql in ('DELETE FROM artifacts', 'UPDATE artifacts SET value=value', "INSERT INTO artifacts VALUES ('extra',x'00')"):
            with closing(sqlite3.connect(self.path)) as connection, connection:
                with self.assertRaises(sqlite3.IntegrityError): connection.execute(sql)
        self.read(digest)

    def test_rehashed_invalid_signature_still_fails_cryptographic_verification(self):
        self.retain(); header = self.header()
        envelope = parse(self.signed.envelopes[0]); envelope['signature'] = '0'*128
        raw = canonical(envelope); header['artifacts']['envelope_a'] = sha256(raw).hexdigest()
        self.mutate("UPDATE artifacts SET value=? WHERE name='envelope_a'", (raw,))
        self.mutate("UPDATE artifacts SET value=? WHERE name='header'", (canonical(header),))
        with self.assertRaisesRegex(BenchmarkError, 'verification rejected'):
            self.read(sha256(canonical(header)).hexdigest())

    def test_source_policy_header_and_envelope_changes_are_detected(self):
        for name in ('development', 'trust_policy', 'header', 'envelope_a'):
            self.path = self.path.parent/(name+'.db'); digest = self.retain()
            self.mutate('UPDATE artifacts SET value=CAST(value || ? AS BLOB) WHERE name=?', (b' ', name))
            with self.subTest(name=name), self.assertRaises(BenchmarkError): self.read(digest)

    def test_recomputed_header_cannot_hide_wrong_artifact_or_result_hash(self):
        for field in ('result_sha256', 'manifest_sha256', 'artifacts'):
            self.path = self.path.parent/(field+'.db'); self.retain(); header = self.header()
            if field == 'artifacts': header[field]['candidate'] = '0'*64
            else: header[field] = '0'*64
            raw = canonical(header); self.mutate("UPDATE artifacts SET value=? WHERE name='header'", (raw,))
            with self.assertRaisesRegex(BenchmarkError, 'integrity rejected'): self.read(sha256(raw).hexdigest())

    def test_header_schema_and_exact_integer_time_are_validated(self):
        for index, changes in enumerate(({'version': '1'}, {'extra': True}, {'retained_at_ms': 3000.0},
                                         {'retained_at_ms': 8000})):
            self.path = self.path.parent/(str(index)+'.db'); self.retain()
            raw = canonical({**self.header(), **changes})
            self.mutate("UPDATE artifacts SET value=? WHERE name='header'", (raw,))
            with self.assertRaises(BenchmarkError): self.read(sha256(raw).hexdigest(), now_ms=8000)

    def test_schema_substitution_and_invalid_artifact_counts_reject(self):
        for index, sql in enumerate(("DELETE FROM artifacts WHERE name='envelope_a'",
                                    "INSERT INTO artifacts VALUES ('extra',x'00')",
                                    'ALTER TABLE artifacts RENAME TO source')):
            self.path = self.path.parent/(str(index)+'.db'); digest = self.retain(); self.mutate(sql)
            if index == 2:
                with closing(sqlite3.connect(self.path)) as connection, connection:
                    connection.execute('CREATE VIEW artifacts AS SELECT name,value FROM source')
            with self.assertRaises(BenchmarkError): self.read(digest)

    def test_partial_transaction_failure_never_exposes_a_snapshot(self):
        # Force failure after table creation and all INSERTs: no committed partial schema/data.
        original = sqlite3.connect
        with patch('aegisflow_dr.benchmark.curation_store.sqlite3.connect') as connect:
            # A SQLite authorizer rejects trigger creation, exercising real transactional rollback.
            def restricted(*args, **kwargs):
                connection = original(*args, **kwargs)
                connection.set_authorizer(lambda action, *rest: sqlite3.SQLITE_DENY
                                          if action == sqlite3.SQLITE_CREATE_TRIGGER else sqlite3.SQLITE_OK)
                return connection
            connect.side_effect = restricted
            with self.assertRaisesRegex(BenchmarkError, '^Curation snapshot unavailable$'): self.retain()
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT name FROM sqlite_schema').fetchall(), [])
        with self.assertRaises(BenchmarkError): self.read('0'*64)
        with self.assertRaises(BenchmarkError): self.retain()

    def test_exported_header_schema_matches_runtime(self):
        self.assertEqual(parse(Path('docs/contracts/signed-curation-header-v1.json').read_bytes()), HEADER)
