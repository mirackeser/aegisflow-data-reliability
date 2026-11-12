# SPDX-License-Identifier: Apache-2.0
from contextlib import closing, redirect_stdout, redirect_stderr
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from importlib.resources import files
import io
import json
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from aegisflow_dr.__main__ import main
from aegisflow_dr.batch import BatchSnapshot
from aegisflow_dr.evaluation import evaluate_development_suite
from aegisflow_dr.gateway import ToolGateway, ToolResult
from aegisflow_dr.investigation import default_policy, investigate, policy_manifest
from aegisflow_dr.pipeline import diagnose_csv, InputRejected
from aegisflow_dr.registry import load_catalog
from aegisflow_dr.storage import StoreError, IntegrityFailure
from aegisflow_dr.storage.runs import _binding, _policy
from aegisflow_dr.storage.schema import schema_sql
from aegisflow_dr.storage.schema import APPLICATION_ID, migrate, run_schema_sql, signature
from aegisflow_dr.storage.store import canonical, sha, _event
import test_runs
import test_store


class RetainedTraceDefensiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_runs.RunTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.record=self.fixture.record();self.policy=default_policy()
        self.snapshots=tuple(BatchSnapshot(x['name'],self.fixture.runs.artifact(self.record['run_id'],x['name']))
                             for x in self.record['manifest']['artifacts'])

    def check(self,trace,snapshots=None):
        _binding(trace,self.fixture.incident,self.policy,self.snapshots if snapshots is None else snapshots)

    def test_retained_policy_shape_and_duplicate_grants_reject(self):
        value=json.loads(canonical(policy_manifest(self.policy)))
        for candidate in ({}, {**value,'grants':'invalid'}, {**value,'grants':value['grants']*2}):
            with self.assertRaises(StoreError):_policy(candidate)
        self.assertEqual(_policy(value),self.policy)

    def test_contradictory_status_and_invalid_trace_structure_reject(self):
        for changes in ({'status':'INCONCLUSIVE'}, {'assessment':'UNSUPPORTED'}, {'steps':None}):
            trace=deepcopy(self.record['trace']);trace.update(changes)
            with self.assertRaises(IntegrityFailure):self.check(trace)

    def test_unknown_malformed_and_unbound_tools_reject(self):
        for mode in ('shape','unknown','hash','diagnosis','source','duplicate-batch'):
            trace=deepcopy(self.record['trace'])
            if mode=='shape':trace['steps'][0]['extra']=True
            elif mode=='unknown':trace['steps'][0]['tool']='write_database'
            elif mode=='hash':trace['steps'][0]['report_sha256']='0'*64
            elif mode=='diagnosis':
                trace['steps'][0]['report']['row_count']=999
                trace['steps'][0]['report_sha256']=sha(canonical(trace['steps'][0]['report']))
            elif mode=='source':
                trace['steps'][1]['report']['source_check']['row_count']=999
                trace['steps'][1]['report_sha256']=sha(canonical(trace['steps'][1]['report']))
            else:trace['steps'].append(deepcopy(trace['steps'][1]))
            with self.subTest(mode=mode),self.assertRaises(IntegrityFailure):self.check(trace)

    def test_failed_steps_cannot_continue_or_carry_success_evidence(self):
        for mode in ('unknown-failure','continue'):
            trace=deepcopy(self.record['trace'])
            trace.update(status='INCONCLUSIVE',assessment=None,reason='blocked',observations=[])
            trace['steps'][0].update(outcome='UNKNOWN' if mode=='unknown-failure' else 'DENIED',report=None,report_sha256=None)
            if mode=='unknown-failure':trace['steps']=trace['steps'][:1]
            with self.assertRaises(IntegrityFailure):self.check(trace)

    def test_call_accounting_and_orphan_snapshots_reject(self):
        trace=deepcopy(self.record['trace']);trace['calls_used']=0
        with self.assertRaises(IntegrityFailure):self.check(trace)
        trace.update(status='INCONCLUSIVE',assessment=None,reason='blocked',steps=[],observations=[])
        with self.assertRaises(IntegrityFailure):self.check(trace)
        self.check(trace,())

    def test_rehashed_run_source_substitution_rejects(self):
        record=deepcopy(self.record);record['manifest']['source_sha256']='0'*64
        self.fixture.rewrite(record)
        with self.assertRaisesRegex(IntegrityFailure,'Run source mismatch'):self.fixture.runs.read(record['run_id'])

    def test_excess_artifact_count_is_rejected_even_with_valid_content_hash(self):
        with closing(sqlite3.connect(self.fixture.path)) as connection,connection:
            connection.execute('INSERT INTO run_artifacts VALUES (?,?,?,?)',
                               (self.record['run_id'],'unexpected',b'x',sha(b'x')))
        with self.assertRaisesRegex(IntegrityFailure,'Run artifact budget exceeded'):
            self.fixture.runs.read(self.record['run_id'])


class IncidentDefensiveTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_store.StoreTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.record=self.fixture.record();self.identity=self.record['incident_id']

    def manifest(self,value):
        self.fixture.tamper('incidents','UPDATE incidents SET manifest=?,manifest_sha256=? WHERE id=?',
                            (canonical(value),sha(canonical(value)),self.identity))

    def test_invalid_manifest_contract_and_evidence_binding_reject(self):
        value=deepcopy(self.record['manifest']);value['format_version']='unsupported';self.manifest(value)
        with self.assertRaisesRegex(IntegrityFailure,'Manifest contract mismatch'):self.fixture.store.read(self.identity)
        value=deepcopy(self.record['manifest']);value['source_sha256']='0'*64;self.manifest(value)
        with self.assertRaisesRegex(IntegrityFailure,'Evidence manifest mismatch'):self.fixture.store.read(self.identity)

    def test_rehashed_report_with_false_source_size_rejects(self):
        report=deepcopy(self.record['report']);report['source_bytes']+=1;raw=canonical(report)
        self.fixture.tamper('evidence',"UPDATE evidence SET content=?,sha256=? WHERE id='report'",(raw,sha(raw)))
        value=deepcopy(self.record['manifest']);value['report_sha256']=sha(raw);self.manifest(value)
        with self.assertRaisesRegex(IntegrityFailure,'Report source mismatch'):self.fixture.store.read(self.identity)

    def test_claim_content_identity_cannot_replace_database_identity(self):
        self.fixture.tamper('claims',"UPDATE claims SET content=? WHERE id=(SELECT id FROM claims LIMIT 1)",
                            (canonical({'id':'substituted'}),))
        with self.assertRaisesRegex(IntegrityFailure,'Claim identity mismatch'):self.fixture.store.read(self.identity)

    def test_missing_required_evidence_cannot_be_replaced_by_unknown_entry(self):
        self.fixture.tamper('evidence',"UPDATE evidence SET id='unexpected' WHERE id='source'")
        with self.assertRaisesRegex(IntegrityFailure,'Incomplete evidence'):self.fixture.store.read(self.identity)

    def test_rehashed_invalid_lifecycle_and_evidence_events_reject(self):
        with closing(sqlite3.connect(self.fixture.path)) as connection:
            revision,kind,raw,previous,_=connection.execute('SELECT revision,kind,content,previous_sha256,sha256 FROM events WHERE revision=2').fetchone()
        for mode in ('lifecycle','evidence'):
            content=json.loads(raw)
            if mode=='evidence':content['source_status']='substituted'
            event_kind='RECEIVED' if mode=='lifecycle' else kind
            _,digest=_event(self.identity,revision,event_kind,content,previous)
            self.fixture.tamper('events','UPDATE events SET kind=?,content=?,sha256=? WHERE revision=2',
                                (event_kind,canonical(content),digest))
            with self.subTest(mode=mode),self.assertRaises(IntegrityFailure):self.fixture.store.read(self.identity)


class BoundaryAndCliDefensiveTests(unittest.TestCase):
    def invoke(self,arguments):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):code=main(arguments)
        return code,out.getvalue(),err.getvalue()

    def test_cli_initialization_migration_read_and_closure_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            db=Path(temporary)/'evidence.db';source=Path(temporary)/'source.csv'
            source.write_bytes(b'order_id,customer_id,order_total\na,b,1.00\n')
            self.assertEqual(self.invoke(['store-init','--db',str(db)])[0],0)
            self.assertEqual(self.invoke(['store-migrate','--db',str(db)])[0],0)
            code,raw,_=self.invoke(['record-source','--db',str(db),'--source',str(source),'--key','cli'])
            self.assertEqual(code,0);identity=json.loads(raw)['incident_id']
            self.assertEqual(self.invoke(['read-incident','--db',str(db),'--incident',identity])[0],0)
            code,raw,_=self.invoke(['close-incident','--db',str(db),'--incident',identity,'--expected-revision','2','--actor','operator'])
            self.assertEqual(code,0);self.assertEqual(json.loads(raw)['state'],'CLOSED')

    def test_cli_evaluation_reports_both_success_and_failure(self):
        self.assertEqual(self.invoke(['evaluate-investigation'])[0],0)
        with patch('aegisflow_dr.__main__.evaluate_development_suite',return_value={'all_matched':False}):
            self.assertEqual(self.invoke(['evaluate-investigation'])[0],1)

    def test_cli_entrypoint_and_benchmark_import_have_safe_execution_boundaries(self):
        with patch.dict(sys.modules),patch.object(sys,'argv',['aegisflow_dr','catalog']),redirect_stdout(io.StringIO()),self.assertRaises(SystemExit) as exit:
            sys.modules.pop('aegisflow_dr.__main__',None)
            runpy.run_module('aegisflow_dr',run_name='__main__')
        self.assertEqual(exit.exception.code,0)
        with redirect_stdout(io.StringIO()) as output:runpy.run_module('aegisflow_dr.benchmark',run_name='not_main')
        self.assertEqual(output.getvalue(),'')

    def test_unknown_schema_and_untrusted_policy_fail_before_work(self):
        with self.assertRaises(ValueError):schema_sql(999)
        with self.assertRaises(ValueError):ToolGateway({})

    def test_incomplete_migration_rolls_back_schema_and_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'legacy.db'
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(schema_sql(1)+f'PRAGMA application_id={APPLICATION_ID}; PRAGMA user_version=1;')
                before=signature(connection)
            malformed=run_schema_sql()+'\nCREATE TABLE incomplete ('
            with patch('aegisflow_dr.storage.schema.run_schema_sql',return_value=malformed):
                with self.assertRaisesRegex(ValueError,'Incomplete migration statement'):migrate(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(signature(connection),before)
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],1)

    def test_incomplete_and_false_catalog_claims_reject(self):
        roles=json.loads(files('aegisflow_dr').joinpath('data/agent-catalog.json').read_bytes())
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'catalog.json'
            for changes in ({'responsibility':''},{'implementation_status':'implemented'}):
                value=deepcopy(roles);value[0].update(changes);path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):load_catalog(path)

    def test_invalid_development_suite_is_rejected_before_execution(self):
        for value in (None,{}, {'suite_id':'wrong','suite_kind':'development_regression','cases':[]}):
            with patch('aegisflow_dr.evaluation.files') as resource,patch('aegisflow_dr.evaluation.investigate') as execution:
                resource.return_value.joinpath.return_value.read_bytes.return_value=json.dumps(value).encode()
                with self.assertRaises(ValueError):evaluate_development_suite()
                execution.assert_not_called()

    def test_decimal_processing_failure_is_rejected(self):
        with patch('aegisflow_dr.pipeline.Decimal',side_effect=[Decimal('0'),InvalidOperation()]):
            with self.assertRaises(InputRejected):diagnose_csv(b'order_id,customer_id,order_total\na,b,1.00\n')

    def test_unexpected_snapshots_on_diagnosis_do_not_reach_next_tool(self):
        fixture=test_runs.RunTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        result=ToolResult('OK',fixture.incident['report'],(BatchSnapshot('unexpected',b'x'),))
        with patch.object(ToolGateway,'execute',return_value=result) as execution:
            outcome=investigate(fixture.store,fixture.incident['incident_id'],default_policy())
        self.assertEqual(outcome.status,'INCONCLUSIVE');self.assertEqual(execution.call_count,1)
