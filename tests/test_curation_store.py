# SPDX-License-Identifier: Apache-2.0
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.curation_store import retain_curation, read_curation
import test_curation


class CurationStoreTests(unittest.TestCase):
    def setUp(self):
        fixture=test_curation.CurationTests();fixture.setUp()
        self.dev=canonical(fixture.development);self.candidate=canonical(fixture.candidates)
        self.annotations=fixture.annotations;self.reviewers=fixture.reviewers
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'curation.db'

    def retain(self):
        return retain_curation(self.path,self.dev,self.candidate,tuple(map(canonical,self.annotations)),reviewer_ids=self.reviewers)

    def read(self,digest):
        return read_curation(self.path,expected_sha256=digest,reviewer_ids=self.reviewers)

    def mutate(self,sql,parameters=()):
        with closing(sqlite3.connect(self.path)) as connection,connection:
            for action in ('insert','update','delete'):connection.execute('DROP TRIGGER immutable_'+action)
            connection.execute(sql,parameters)

    def test_agreement_reopens_privately_without_source_in_result(self):
        digest=self.retain();result=self.read(digest)
        self.assertEqual(result['status'],'AGREED');self.assertEqual(len(result['cases']),3)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.read(digest),result)
        self.assertNotIn('csv_text',str(result))

    def test_disagreement_is_retained_without_exported_labels(self):
        self.annotations[1]['labels'][0]['label']=self.annotations[1]['labels'][1]['label']
        result=self.read(self.retain())
        self.assertEqual(result['status'],'DISAGREEMENT');self.assertEqual(result['cases'],[])

    def test_existing_file_and_symlink_are_never_overwritten(self):
        digest=self.retain();before=self.path.read_bytes()
        with self.assertRaises(BenchmarkError):self.retain()
        self.assertEqual(before,self.path.read_bytes())
        link=self.path.parent/'link.db';link.symlink_to(self.path);self.path=link
        with self.assertRaises(BenchmarkError):self.retain()
        self.assertEqual(self.read(digest)['status'],'AGREED')

    def test_invalid_source_or_review_is_rejected_before_creation(self):
        self.annotations[1]['labels'].pop()
        with self.assertRaises(BenchmarkError):self.retain()
        self.assertFalse(self.path.exists())

    def test_untrusted_digest_and_reviewers_fail_closed(self):
        digest=self.retain()
        with self.assertRaises(BenchmarkError):self.read('0'*64)
        self.reviewers=('outsider','reviewer-b')
        with self.assertRaises(BenchmarkError):self.read(digest)

    def test_all_mutations_blocked_by_normal_sql_access(self):
        digest=self.retain()
        for sql in ("DELETE FROM artifacts", "UPDATE artifacts SET value=value", "INSERT INTO artifacts VALUES ('extra',x'00')"):
            with closing(sqlite3.connect(self.path)) as connection,connection:
                with self.assertRaises(sqlite3.IntegrityError):connection.execute(sql)
        self.assertEqual(self.read(digest)['status'],'AGREED')

    def test_byte_changes_detected_even_when_normalized_meaning_matches(self):
        digest=self.retain()
        self.mutate("UPDATE artifacts SET value=? WHERE name='annotation_a'",(canonical(self.annotations[0])+b' ',))
        with self.assertRaises(BenchmarkError):self.read(digest)

    def test_consistent_source_substitution_cannot_replace_external_digest(self):
        digest=self.retain()
        self.mutate("UPDATE artifacts SET value=? WHERE name='header'",(b'{}',))
        with self.assertRaises(BenchmarkError):self.read(digest)

    def test_missing_extra_oversized_and_wrong_type_artifacts_reject(self):
        mutations=[("DELETE FROM artifacts WHERE name='candidate'",()),
                   ("INSERT INTO artifacts VALUES ('extra',?)",(b'x',)),
                   ("UPDATE artifacts SET value=? WHERE name='candidate'",(b'x'*1_000_001,)),
                   ("UPDATE artifacts SET value=? WHERE name='candidate'",('text',))]
        for index,(sql,parameters) in enumerate(mutations):
            self.path=self.path.parent/('bad'+str(index)+'.db');digest=self.retain()
            self.mutate(sql,parameters)
            with self.assertRaises(BenchmarkError):self.read(digest)

    def test_missing_or_corrupt_database_has_sanitized_failure(self):
        with self.assertRaisesRegex(BenchmarkError,'^Curation snapshot unavailable$'):self.read('0'*64)
        self.path.write_bytes(b'private corrupt bytes')
        with self.assertRaisesRegex(BenchmarkError,'^Curation snapshot unavailable$'):self.read('0'*64)

    def test_failed_initialization_never_produces_readable_snapshot(self):
        with patch('aegisflow_dr.benchmark.curation_store.sqlite3.connect',side_effect=sqlite3.OperationalError('private detail')):
            with self.assertRaisesRegex(BenchmarkError,'^Curation snapshot unavailable$'):self.retain()
        with self.assertRaises(BenchmarkError):self.read('0'*64)
        with self.assertRaises(BenchmarkError):self.retain()
