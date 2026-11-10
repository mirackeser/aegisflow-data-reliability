# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.__main__ import main
from aegisflow_dr.batch import execute_batch, BatchSnapshot
from aegisflow_dr.gateway import ToolGateway, ToolPolicy, ToolRequest
from aegisflow_dr.investigation import default_policy, investigate, validate_snapshots
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize, migrate, StoreError, IntegrityFailure, VersionMismatch
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.schema import APPLICATION_ID, schema_sql, signature, expected_schema, run_schema_sql
from aegisflow_dr.storage.store import canonical, sha


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'research.db'
        initialize(self.path)
        self.store = IncidentStore(self.path)
        self.incident = self.store.record(generate_orders(), request_key='source')
        self.runs = InvestigationRuns(self.store)

    def record(self, key='run', **options):
        return self.runs.execute(self.incident['incident_id'], default_policy(), request_key=key, **options)

    def tamper(self, table, operation, parameters=(), kind='update'):
        with closing(sqlite3.connect(self.path)) as connection:
            name = f'immutable_{table}_{kind}'
            ddl = connection.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()[0]
            connection.execute(f'DROP TRIGGER {name}')
            connection.execute(operation, parameters)
            connection.execute(ddl)
            connection.commit()

    def rewrite(self, record, *, trace=None, manifest=None):
        if manifest is None:
            manifest = record['manifest']
        if trace is None:
            trace = record['trace']
        manifest['trace_sha256'] = sha(canonical(trace))
        self.tamper('investigation_runs', 'UPDATE investigation_runs SET manifest=?,manifest_sha256=?,trace=? WHERE id=?',
                    (canonical(manifest), sha(canonical(manifest)), canonical(trace), record['run_id']))

    def test_exact_snapshots_survive_reopen_and_replay(self):
        record = self.record()
        fresh = InvestigationRuns(IncidentStore(self.path))
        self.assertEqual(fresh.read(record['run_id']), record)
        expected = execute_batch(generate_orders())
        for snapshot in expected.snapshots:
            self.assertEqual(fresh.artifact(record['run_id'], snapshot.name), snapshot.content)
        self.assertEqual(fresh.replay(record['run_id'])['outcome'], 'MATCH')
        self.assertEqual(self.store.read(self.incident['incident_id']), self.incident)
        self.assertNotIn('ORD-', json.dumps(record))

    def test_faulted_transform_retains_actual_executed_sql(self):
        record = self.record(transform='exclude_first')
        self.assertEqual(record['trace']['assessment'], 'TRANSFORMATION_RECONCILIATION_FAILURE')
        self.assertEqual(len(record['manifest']['artifacts']), 4)
        self.assertEqual(self.runs.replay(record['run_id'])['outcome'], 'MATCH')
        self.assertNotEqual(self.runs.artifact(record['run_id'], 'sql_transform'),
                            execute_batch(generate_orders()).snapshots[2].content)

    def test_source_failure_never_creates_batch_snapshots(self):
        incident = self.store.record(generate_orders(fault='null_total'), request_key='bad-source')
        record = self.runs.execute(incident['incident_id'], default_policy(), request_key='run')
        self.assertEqual(record['trace']['assessment'], 'SOURCE_QUALITY_FAILURE')
        self.assertEqual(record['manifest']['artifacts'], [])
        self.assertEqual(self.runs.replay(record['run_id'])['outcome'], 'MATCH')

    def test_denied_run_is_durable_and_inconclusive(self):
        record = self.runs.execute(self.incident['incident_id'], ToolPolicy(frozenset()), request_key='denied')
        self.assertEqual(record['trace']['status'], 'INCONCLUSIVE')
        self.assertEqual(record['manifest']['artifacts'], [])
        self.assertEqual(self.runs.replay(record['run_id'])['outcome'], 'MATCH')

    def test_late_denial_preserves_only_authorized_accepted_batch(self):
        policy = ToolPolicy(frozenset({('diagnose_csv', 'source_orders'), ('run_batch', 'source_orders')}))
        record = self.runs.execute(self.incident['incident_id'], policy, request_key='denied', transform='exclude_first')
        self.assertEqual(record['trace']['status'], 'INCONCLUSIVE')
        self.assertEqual(len(record['manifest']['artifacts']), 4)
        self.assertEqual(record['trace']['observations'], [])
        self.assertEqual(self.runs.replay(record['run_id'])['outcome'], 'MATCH')

    def test_retry_never_reexecutes_tools(self):
        record = self.record()
        with patch('aegisflow_dr.storage.runs.investigate', side_effect=AssertionError):
            self.assertEqual(self.record(), record)

    def test_conflicting_transform_or_policy_leaves_original(self):
        record = self.record()
        with self.assertRaises(StoreError): self.record(transform='exclude_first')
        with self.assertRaises(StoreError):
            self.runs.execute(self.incident['incident_id'], ToolPolicy(frozenset()), request_key='run')
        self.assertEqual(self.runs.read(record['run_id']), record)

    def test_concurrent_retry_commits_exactly_once(self):
        with patch('aegisflow_dr.storage.runs.investigate', wraps=investigate) as invocation:
            with ThreadPoolExecutor(max_workers=4) as workers:
                records = list(workers.map(lambda _: self.record(), range(8)))
            self.assertEqual(invocation.call_count, 1)
        self.assertEqual(len({record['run_id'] for record in records}), 1)

    def test_run_keys_are_scoped_to_incident(self):
        first = self.record()
        second = self.store.record(generate_orders(seed=2), request_key='other')
        other = self.runs.execute(second['incident_id'], default_policy(), request_key='run')
        self.assertNotEqual(first['run_id'], other['run_id'])

    def test_partial_insert_failure_rolls_back_run_and_artifacts(self):
        original = InvestigationRuns._insert_artifact
        count = 0
        def fail(connection, run_id, snapshot):
            nonlocal count
            count += 1
            original(connection, run_id, snapshot)
            if count == 2: raise RuntimeError('injected')
        with patch.object(InvestigationRuns, '_insert_artifact', side_effect=fail):
            with self.assertRaises(RuntimeError): self.record()
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ['investigation_runs', 'run_artifacts']:
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(self.store.read(self.incident['incident_id']), self.incident)

    def test_run_and_artifacts_are_append_only(self):
        self.record()
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ['investigation_runs', 'run_artifacts']:
                for query in [f'UPDATE {table} SET rowid=rowid', f'DELETE FROM {table}']:
                    with self.assertRaises(sqlite3.IntegrityError): connection.execute(query)
                    connection.rollback()

    def test_artifact_parent_foreign_key_enforced(self):
        with self.store._connect(write=True) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('INSERT INTO run_artifacts VALUES (?,?,?,?)', ('missing','stage',b'x',sha(b'x')))

    def test_unknown_ids_artifacts_and_invalid_requests_rejected(self):
        for run in ['', '../escape', '0'*36, '00000000-0000-0000-0000-000000000000']:
            with self.assertRaises(StoreError): self.runs.read(run)
        record = self.record()
        with self.assertRaises(StoreError): self.runs.artifact(record['run_id'], '../escape')
        for key in ['', None, 'x'*65, 'space key']:
            with self.assertRaises(StoreError): self.record(key=key)
        with self.assertRaises(StoreError): self.record(transform='sql')
        with self.assertRaises(StoreError): self.runs.execute('missing', default_policy(), request_key='valid')

    def test_manifest_corruption_rejected(self):
        record = self.record()
        self.tamper('investigation_runs', 'UPDATE investigation_runs SET manifest=?', (b'{}',))
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_trace_corruption_rejected(self):
        record = self.record()
        self.tamper('investigation_runs', 'UPDATE investigation_runs SET trace=?', (b'{}',))
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_corrupted_artifact_rejected_on_read_replay_retry(self):
        record = self.record()
        self.tamper('run_artifacts', "UPDATE run_artifacts SET content=? WHERE name='customer_sales'", (b'changed',))
        for operation in [lambda: self.runs.read(record['run_id']), lambda: self.runs.replay(record['run_id']), self.record]:
            with self.assertRaises(IntegrityFailure): operation()

    def test_missing_artifact_rejected(self):
        record = self.record()
        self.tamper('run_artifacts', "DELETE FROM run_artifacts WHERE name='sql_transform'", kind='delete')
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_rehashed_artifact_cannot_bypass_report_binding(self):
        record = self.record()
        self.tamper('run_artifacts', "UPDATE run_artifacts SET content=?,sha256=? WHERE name='customer_sales'", (b'x',sha(b'x')))
        for item in record['manifest']['artifacts']:
            if item['name'] == 'customer_sales': item.update(sha256=sha(b'x'), bytes=1)
        self.rewrite(record)
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_rehashed_trace_rejects_missing_observation_evidence(self):
        record = self.record()
        record['trace']['observations'][0]['evidence_sha256'][1] = 'a'*64
        self.rewrite(record)
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_rehashed_manifest_rejects_policy_substitution(self):
        record = self.record()
        record['manifest']['request']['policy']['max_calls'] = 1
        self.rewrite(record)
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_parent_source_corruption_invalidates_run(self):
        record = self.record()
        self.tamper('evidence', "UPDATE evidence SET content=? WHERE id='source'", (b'x',))
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_changed_implementation_keeps_readable_history_but_refuses_replay(self):
        record = self.record()
        with patch('aegisflow_dr.storage.runs.implementation_fingerprint', return_value='a'*64):
            self.assertEqual(self.runs.read(record['run_id']), record)
            with self.assertRaises(VersionMismatch): self.runs.replay(record['run_id'])

    def test_replay_mismatch_never_rewrites_history(self):
        record = self.record()
        changed = replace(investigate(self.store, self.incident['incident_id'], default_policy()), assessment='SOURCE_QUALITY_FAILURE')
        with patch('aegisflow_dr.storage.runs.investigate', return_value=changed):
            self.assertEqual(self.runs.replay(record['run_id'])['outcome'], 'MISMATCH')
        self.assertEqual(self.runs.read(record['run_id']), record)

    def test_closed_parent_and_backup_restore(self):
        closed = self.store.close(self.incident['incident_id'], expected_revision=2, actor='local')
        record = self.record()
        backup = Path(self.temp.name) / 'backup.db'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        restored = InvestigationRuns(IncidentStore(backup))
        self.assertEqual(restored.read(record['run_id']), record)
        self.assertEqual(restored.replay(record['run_id'])['outcome'], 'MATCH')
        self.assertEqual(self.store.read(self.incident['incident_id']), closed)

    def test_trace_budget_rejects_atomically(self):
        with patch('aegisflow_dr.storage.runs.MAX_TRACE_BYTES', 1):
            with self.assertRaises(StoreError): self.record()
        self.assertEqual(self.record()['trace']['status'], 'COMPLETED')

    def test_tool_and_investigation_json_and_repr_hide_snapshot_rows(self):
        result = ToolGateway(default_policy()).execute(ToolRequest('run_batch','source_orders',generate_orders().decode()))
        self.assertEqual(len(result.snapshots),4)
        trace = investigate(self.store,self.incident['incident_id'],default_policy())
        for value in [result.to_json(),repr(result),trace.to_json(),repr(trace),repr(result.snapshots[0])]:
            self.assertNotIn('ORD-',value)
        self.assertNotIn('snapshots',trace.to_json())

    def test_missing_forged_duplicate_and_oversize_snapshots_fail_closed(self):
        execution = execute_batch(generate_orders())
        report = json.loads(execution.report.to_json())
        for snapshots in [(), execution.snapshots[:-1], execution.snapshots[:3]+execution.snapshots[:1],
                          (BatchSnapshot('staging_orders',b'x'),)+execution.snapshots[1:],
                          (BatchSnapshot('staging_orders',b'x'*2_000_001),)+execution.snapshots[1:]]:
            with self.subTest(length=len(snapshots)), self.assertRaises(ValueError): validate_snapshots(report,snapshots)

    def test_process_exit_before_commit_leaves_no_partial_run(self):
        import subprocess
        program = """import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute('BEGIN IMMEDIATE')
c.execute('INSERT INTO investigation_runs VALUES (?,?,?,?,?,?)',
          ('partial',sys.argv[2],'crash',b'{}','fake',b'{}'))
c.execute('INSERT INTO run_artifacts VALUES (?,?,?,?)',('partial','stage',b'x','fake'))
os._exit(17)
"""
        result = subprocess.run([sys.executable, '-c', program, str(self.path), self.incident['incident_id']],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 17, result.stderr)
        with closing(sqlite3.connect(self.path)) as connection:
            for table in ['investigation_runs', 'run_artifacts']:
                self.assertEqual(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertEqual(self.store.read(self.incident['incident_id']), self.incident)

    def test_gateway_missing_snapshot_cannot_become_completed_run(self):
        original = ToolGateway.execute
        def without_snapshots(gateway, request):
            result = original(gateway, request)
            return replace(result, snapshots=()) if request.tool == 'run_batch' else result
        with patch.object(ToolGateway, 'execute', without_snapshots):
            record = self.record()
        self.assertEqual(record['trace']['status'], 'INCONCLUSIVE')
        self.assertEqual(record['trace']['reason'], 'INVALID_EVIDENCE')
        self.assertEqual(record['manifest']['artifacts'], [])

    def test_malformed_retained_metadata_is_integrity_failure(self):
        record = self.record()
        record['manifest']['request']['policy']['grants'] = ['malformed']
        self.rewrite(record)
        with self.assertRaises(IntegrityFailure): self.runs.read(record['run_id'])

    def test_cli_durable_round_trip_and_sanitized_rejection(self):
        def invoke(args):
            out,err=io.StringIO(),io.StringIO()
            with redirect_stdout(out),redirect_stderr(err): code=main(args)
            return code,out.getvalue(),err.getvalue()
        base=['--db',str(self.path)]
        code,out,_=invoke(['record-investigation',*base,'--incident',self.incident['incident_id'],'--key','cli'])
        self.assertEqual(code,0)
        record=json.loads(out)
        code,out,_=invoke(['read-investigation',*base,'--run',record['run_id']])
        self.assertEqual((code,json.loads(out)),(0,record))
        code,out,_=invoke(['replay-investigation',*base,'--run',record['run_id']])
        self.assertEqual((code,json.loads(out)['outcome']),(0,'MATCH'))
        code,out,err=invoke(['read-investigation',*base,'--run','secret-invalid-id'])
        self.assertEqual((code,out),(2,''))
        self.assertNotIn('secret-invalid-id',err)
        self.assertNotIn(str(self.path),err)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'v1.db'
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(schema_sql(1))
            connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
            connection.execute('PRAGMA user_version=1')
        self.store=IncidentStore(self.path)
        self.record=self.store.record(generate_orders(),request_key='legacy')

    def test_explicit_upgrade_preserves_exact_legacy_rows_and_replay(self):
        before=self.path.read_bytes()
        self.assertEqual(self.store.read(self.record['incident_id']),self.record)
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(StoreError):
            InvestigationRuns(self.store).execute(self.record['incident_id'],default_policy(),request_key='run')
        self.assertEqual(self.path.read_bytes(),before)
        migrate(self.path)
        self.assertEqual(self.store.read(self.record['incident_id']),self.record)
        self.assertEqual(self.store.replay(self.record['incident_id'])['outcome'],'MATCH')
        run=InvestigationRuns(self.store).execute(self.record['incident_id'],default_policy(),request_key='run')
        self.assertEqual(InvestigationRuns(self.store).replay(run['run_id'])['outcome'],'MATCH')

    def test_repeated_upgrade_is_idempotent(self):
        migrate(self.path)
        before=self.path.read_bytes()
        migrate(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_migration_failure_rolls_back_ddl_and_version(self):
        ddl=run_schema_sql()
        expected_schema(1);expected_schema(2)
        with patch('aegisflow_dr.storage.schema.run_schema_sql',return_value=ddl+'INVALID SQL;\n'):
            with self.assertRaises(sqlite3.DatabaseError):migrate(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertEqual(signature(connection),expected_schema(1))
        self.assertEqual(self.store.read(self.record['incident_id']),self.record)

    def test_incomplete_migration_rolls_back(self):
        expected_schema(1);expected_schema(2)
        with patch('aegisflow_dr.storage.schema.run_schema_sql',return_value=run_schema_sql()+'CREATE TABLE unfinished'):
            with self.assertRaises(ValueError):migrate(self.path)
        self.assertEqual(self.store.read(self.record['incident_id']),self.record)

    def test_unknown_version_and_modified_schema_are_rejected_unchanged(self):
        with closing(sqlite3.connect(self.path)) as connection:connection.execute('PRAGMA user_version=99')
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):migrate(self.path)
        self.assertEqual(self.path.read_bytes(),before)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('PRAGMA user_version=1')
            connection.execute('DROP TRIGGER immutable_events_update')
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):migrate(self.path)
        self.assertEqual(self.path.read_bytes(),before)

    def test_missing_database_is_never_created_by_migration(self):
        path=self.path.parent/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):migrate(path)
        self.assertFalse(path.exists())
