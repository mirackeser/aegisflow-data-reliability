# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.pipeline import generate_orders, InputRejected
from aegisflow_dr.storage import IncidentStore, IntegrityFailure, StoreError, VersionMismatch, initialize
from aegisflow_dr.__main__ import main


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'research.db'
        initialize(self.path)
        self.store = IncidentStore(self.path)
        self.payload = generate_orders(fault='null_total')

    def record(self, key='case-1'):
        return self.store.record(self.payload, request_key=key)

    def test_snapshot_report_and_many_to_many_links_survive_reopen(self):
        record = self.record()
        restored = IncidentStore(self.path).read(record['incident_id'])
        self.assertEqual(restored, record)
        self.assertEqual(record['state'], 'DIAGNOSED')
        self.assertEqual(record['report']['status'], 'FAIL')
        claims = record['manifest']['claims']
        self.assertEqual(len(claims), 2)
        self.assertEqual(len(record['manifest']['links']), 4)
        with closing(sqlite3.connect(self.path)) as connection:
            source = connection.execute("SELECT content FROM evidence WHERE id='source'").fetchone()[0]
        self.assertEqual(source, self.payload)
        self.assertNotIn('ORD-', json.dumps(record))

    def test_clean_summary_is_not_a_causal_claim(self):
        record = self.store.record(generate_orders(), request_key='clean')
        self.assertEqual(record['manifest']['claims'][0]['kind'], 'source_quality_summary')
        self.assertEqual(record['report']['status'], 'PASS')
        self.assertEqual(self.store.replay(record['incident_id'])['outcome'], 'MATCH')

    def test_idempotency_returns_original_record_without_rediagnosis(self):
        first = self.record()
        with patch('aegisflow_dr.storage.store.diagnose_csv', side_effect=RuntimeError):
            again = self.record()
        self.assertEqual(first, again)

    def test_idempotency_conflict_does_not_change_original(self):
        first = self.record()
        with self.assertRaises(StoreError):
            self.store.record(generate_orders(), request_key='case-1')
        self.assertEqual(self.store.read(first['incident_id']), first)

    def test_concurrent_identical_keys_create_one_incident(self):
        with ThreadPoolExecutor(max_workers=8) as workers:
            records = list(workers.map(lambda _: self.record(), range(16)))
        self.assertEqual(len({r['incident_id'] for r in records}), 1)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM incidents').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_concurrent_conflicting_payloads_only_commit_one(self):
        def attempt(payload):
            try:
                return self.store.record(payload, request_key='race')['manifest']['source_sha256']
            except StoreError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(attempt, [self.payload, generate_orders()]))
        self.assertEqual(results.count('conflict'), 1)

    def test_malformed_input_does_not_create_partial_case(self):
        with self.assertRaises(InputRejected):
            self.store.record(b'a,a\n1,2', request_key='bad')
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM incidents').fetchone()[0], 0)

    def test_mid_transaction_failure_rolls_back_all_tables(self):
        with patch.object(IncidentStore, '_append', side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError): self.record()
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ['incidents', 'evidence', 'claims', 'claim_evidence', 'events']:
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_bad_keys_and_payloads_are_rejected(self):
        for key in ['', 'x'*65, 'space key', '../escape', None]:
            with self.subTest(key=key), self.assertRaises(StoreError): self.record(key)
        for payload in ['text', b'x'*1000001]:
            with self.assertRaises(StoreError): self.store.record(payload, request_key='x')

    def test_initialization_never_overwrites_an_existing_file(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError): initialize(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        other = Path(self.temp.name) / 'foreign.db'
        other.write_bytes(b'not ours')
        with self.assertRaises(FileExistsError): initialize(other)
        self.assertEqual(other.read_bytes(), b'not ours')

    def test_missing_store_not_implicitly_created(self):
        missing = Path(self.temp.name) / 'absent.db'
        with self.assertRaises(sqlite3.OperationalError): IncidentStore(missing)
        self.assertFalse(missing.exists())

    def test_store_file_is_private_on_posix(self):
        if os.name == 'posix': self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_wrong_schema_version_and_missing_triggers_fail_closed(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('PRAGMA user_version=3')
        with self.assertRaises(StoreError): self.store.read('anything')
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('PRAGMA user_version=2')
            connection.execute('DROP TRIGGER immutable_events_update')
        with self.assertRaises(StoreError): IncidentStore(self.path)

    def test_all_persisted_entities_reject_update_and_delete(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ['incidents', 'evidence', 'claims', 'claim_evidence', 'events']:
                for operation in [f'UPDATE {table} SET rowid=rowid', f'DELETE FROM {table}']:
                    with self.subTest(operation=operation), self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(operation)
                    connection.rollback()

    def tamper(self, table, sql, parameters=()):
        # File owners can remove SQL triggers. Restore the original DDL so the
        # subsequent failure specifically exercises content/chain verification.
        with closing(sqlite3.connect(self.path)) as connection:
            trigger = f'immutable_{table}_update'
            ddl = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (trigger,)).fetchone()[0]
            connection.execute(f'DROP TRIGGER {trigger}')
            connection.execute(sql, parameters)
            connection.execute(ddl)
            connection.commit()

    def test_source_tampering_detected_on_read_replay_and_retry(self):
        record = self.record()
        self.tamper('evidence', "UPDATE evidence SET content=? WHERE id='source'", (b'tampered',))
        for operation in [lambda: self.store.read(record['incident_id']),
                          lambda: self.store.replay(record['incident_id']), self.record]:
            with self.assertRaises(IntegrityFailure): operation()

    def test_claim_content_corruption_detected(self):
        record = self.record()
        self.tamper('claims', "UPDATE claims SET content=? WHERE id='summary'", (b'{}',))
        with self.assertRaises(IntegrityFailure): self.store.read(record['incident_id'])

    def test_event_chain_tampering_detected(self):
        record = self.record()
        self.tamper('events', 'UPDATE events SET content=? WHERE revision=2', (b'{}',))
        with self.assertRaises(IntegrityFailure): self.store.read(record['incident_id'])

    def test_cross_incident_claim_links_are_rejected_by_foreign_keys(self):
        first = self.record()
        second = self.store.record(generate_orders(), request_key='second')
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            # The second clean case has no finding-000 claim.
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO claim_evidence VALUES (?,?,?)',
                                   (second['incident_id'], 'finding-000', 'source'))

    def test_replay_refuses_changed_implementation_but_history_remains_readable(self):
        record = self.record()
        with patch('aegisflow_dr.storage.store.engine_fingerprint', return_value='a'*64):
            self.assertEqual(self.store.read(record['incident_id']), record)
            with self.assertRaises(VersionMismatch): self.store.replay(record['incident_id'])

    def test_replay_detects_nondeterministic_diagnostic_result(self):
        record = self.record()
        from aegisflow_dr.pipeline import diagnose_csv
        changed = diagnose_csv(generate_orders())
        with patch('aegisflow_dr.storage.store.diagnose_csv', return_value=changed):
            self.assertEqual(self.store.replay(record['incident_id'])['outcome'], 'MISMATCH')
        self.assertEqual(self.store.read(record['incident_id']), record)

    def test_closure_requires_revision_and_is_append_only(self):
        record = self.record()
        case_id = record['incident_id']
        with self.assertRaises(StoreError): self.store.close(case_id, expected_revision=1, actor='local')
        closed = self.store.close(case_id, expected_revision=2, actor='local')
        self.assertEqual((closed['state'], closed['revision']), ('CLOSED', 3))
        self.assertEqual(closed['manifest'], record['manifest'])
        self.assertEqual(self.record(), closed)
        with self.assertRaises(StoreError): self.store.close(case_id, expected_revision=2, actor='local')
        with self.assertRaises(StoreError): self.store.close(case_id, expected_revision=3, actor='local')
        self.assertEqual(self.store.replay(case_id)['outcome'], 'MATCH')

    def test_competing_closures_only_append_one_event(self):
        record = self.record()
        def close(_):
            try: return self.store.close(record['incident_id'], expected_revision=2, actor='local')['state']
            except StoreError: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(close, range(2)))
        self.assertCountEqual(results, ['CLOSED', 'conflict'])

    def test_unknown_incident_and_invalid_closure_are_rejected(self):
        with self.assertRaises(StoreError): self.store.read('missing')
        for options in [dict(expected_revision=True, actor='local'),
                        dict(expected_revision=2, actor='bad actor')]:
            with self.assertRaises(StoreError): self.store.close('missing', **options)

    def test_cli_round_trip_and_sanitized_failures(self):
        source = Path(self.temp.name) / 'synthetic.csv'
        source.write_bytes(self.payload)
        def invoke(args):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err): code = main(args)
            return code, out.getvalue(), err.getvalue()
        code, out, _ = invoke(['record-source', '--db', str(self.path), '--source', str(source), '--key', 'cli'])
        self.assertEqual(code, 0)
        case_id = json.loads(out)['incident_id']
        code, out, _ = invoke(['replay-incident', '--db', str(self.path), '--incident', case_id])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)['outcome'], 'MATCH')
        code, out, err = invoke(['store-init', '--db', str(self.path)])
        self.assertEqual(code, 2)
        self.assertEqual(out, '')
        self.assertNotIn(str(self.path), err)

    def test_report_and_manifest_checksum_corruption_are_detected(self):
        for target in ['report', 'manifest']:
            with self.subTest(target=target):
                record = self.record(key=target)
                if target == 'report':
                    self.tamper('evidence', "UPDATE evidence SET content=? WHERE incident_id=? AND id='report'",
                                (b'{}', record['incident_id']))
                else:
                    self.tamper('incidents', 'UPDATE incidents SET manifest=? WHERE id=?',
                                (b'{}', record['incident_id']))
                with self.assertRaises(IntegrityFailure): self.store.read(record['incident_id'])

    def test_deleted_claim_link_is_detected(self):
        record = self.record()
        with closing(sqlite3.connect(self.path)) as connection:
            ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name='immutable_claim_evidence_delete'").fetchone()[0]
            connection.execute('DROP TRIGGER immutable_claim_evidence_delete')
            connection.execute("DELETE FROM claim_evidence WHERE claim_id='summary' AND evidence_id='source'")
            connection.execute(ddl)
            connection.commit()
        with self.assertRaises(IntegrityFailure): self.store.read(record['incident_id'])

    def test_key_substitution_is_detected(self):
        record = self.record()
        self.tamper('incidents', "UPDATE incidents SET request_key='substituted'")
        with self.assertRaises(IntegrityFailure): self.store.read(record['incident_id'])

    def test_backup_and_restore_preserve_replayable_history(self):
        record = self.record()
        backup = Path(self.temp.name) / 'backup.db'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        restored = IncidentStore(backup)
        self.assertEqual(restored.read(record['incident_id']), record)
        self.assertEqual(restored.replay(record['incident_id'])['outcome'], 'MATCH')

    def test_process_exit_before_commit_leaves_no_partial_incident(self):
        import subprocess
        record = self.record()
        program = '''import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute("BEGIN IMMEDIATE")
c.execute("INSERT INTO incidents VALUES ('partial','crash',?,?)", (b'{}','fake'))
os._exit(17)
'''
        child = subprocess.run([sys.executable, '-c', program, str(self.path)],
                               capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 17, child.stderr)
        self.assertEqual(self.store.read(record['incident_id']), record)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM incidents WHERE id='partial'").fetchone()[0], 0)

    def test_truncated_report_does_not_invent_omitted_claims(self):
        payload = b'order_id,customer_id,order_total\n' + b',,\n' * 101
        record = self.store.record(payload, request_key='truncated')
        self.assertEqual(record['report']['finding_count'], 303)
        self.assertTrue(record['report']['findings_truncated'])
        self.assertEqual(len(record['manifest']['claims']), 101)
        self.assertEqual(self.store.replay(record['incident_id'])['outcome'], 'MATCH')
