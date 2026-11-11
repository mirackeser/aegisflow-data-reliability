# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from aegisflow_dr.benchmark.core import BenchmarkError,LABELS,canonical
from aegisflow_dr.benchmark.quality import freeze_protocol
from aegisflow_dr.benchmark.protocol_store import EvaluationRegistry,register_protocol


class ProtocolStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'evaluation.db'
        self.cases=canonical([{'case_id':str(i),'family':'fixture','label':label} for i,label in enumerate(LABELS)])
        self.outputs=canonical([{'case_id':str(i),'prediction':label,'unsupported_claim':False} for i,label in enumerate(LABELS)])
        self.model='a'*64
        self.protocol=freeze_protocol(self.cases,model_revision_sha256=self.model,families=('fixture',))
        self.digest=register_protocol(self.path,self.protocol)
        self.registry=EvaluationRegistry(self.path,expected_protocol_sha256=self.digest)
        self.run=str(uuid4())

    def evaluate(self,**changes):
        values=dict(run_id=self.run,model_revision_sha256=self.model)
        return self.registry.evaluate(self.cases,self.outputs,**{**values,**changes})

    def test_registration_precedes_results_and_block_is_retained_after_reopen(self):
        self.assertEqual(self.registry.history(),[])
        value=self.evaluate();self.assertEqual(value['decision'],'BLOCK')
        reopened=EvaluationRegistry(self.path,expected_protocol_sha256=self.digest)
        self.assertEqual(reopened.history(),[{'sequence':1,'run_id':self.run,'result':value}])
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_repeat_is_idempotent_but_conflicting_output_rejected(self):
        first=self.evaluate();self.assertEqual(first,self.evaluate())
        import json
        outputs=json.loads(self.outputs);outputs[0]['prediction']='ERROR';self.outputs=canonical(outputs)
        with self.assertRaises(BenchmarkError):self.evaluate()
        self.assertEqual(len(self.registry.history()),1)

    def test_later_runs_preserve_failed_history(self):
        self.evaluate();self.evaluate(run_id=str(uuid4()))
        self.assertEqual([x['sequence'] for x in self.registry.history()],[1,2])

    def test_existing_file_and_registration_never_overwritten(self):
        before=self.path.read_bytes()
        with self.assertRaises(BenchmarkError):register_protocol(self.path,self.protocol)
        self.assertEqual(before,self.path.read_bytes())

    def test_policy_substitution_and_missing_database_rejected(self):
        with self.assertRaises(BenchmarkError):EvaluationRegistry(self.path,expected_protocol_sha256='0'*64)
        with self.assertRaises(BenchmarkError):EvaluationRegistry(self.path.parent/'missing.db',expected_protocol_sha256=self.digest)

    def test_invalid_protocol_creates_no_file(self):
        path=self.path.parent/'bad.db'
        with self.assertRaises(BenchmarkError):register_protocol(path,b'{}')
        self.assertFalse(path.exists())

    def test_wrong_model_dataset_and_invalid_run_cannot_append(self):
        for run in (None,'bad',str(uuid4()).upper()):
            with self.assertRaises(BenchmarkError):self.evaluate(run_id=run)
        with self.assertRaises(BenchmarkError):self.evaluate(model_revision_sha256='b'*64)
        self.cases+=b' '
        with self.assertRaises(BenchmarkError):self.evaluate()
        self.assertEqual(self.registry.history(),[])

    def test_concurrent_identical_runs_append_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.evaluate(),range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.registry.history()),1)

    def test_update_delete_triggers_preserve_registration_and_results(self):
        self.evaluate()
        for table in ('registration','evaluations'):
            for statement in (f'DELETE FROM {table}',f'UPDATE {table} SET '+('id=id' if table=='registration' else 'sequence=sequence')):
                with closing(sqlite3.connect(self.path)) as connection:
                    with self.assertRaises(sqlite3.IntegrityError):connection.execute(statement)
        self.assertEqual(len(self.registry.history()),1)

    def test_storage_failure_rolls_back_without_partial_result(self):
        with closing(sqlite3.connect(self.path)) as connection,connection:
            connection.execute("CREATE TRIGGER fail BEFORE INSERT ON evaluations BEGIN SELECT RAISE(ABORT,'private failure'); END")
        with self.assertRaisesRegex(BenchmarkError,'^Evaluation registry unavailable$'):self.evaluate()
        self.assertEqual(self.registry.history(),[])

    def test_changed_registration_is_checked_before_each_read_and_write(self):
        with closing(sqlite3.connect(self.path)) as connection,connection:
            connection.execute('DROP TRIGGER registration_update')
            connection.execute('UPDATE registration SET protocol=?',(b'{}',))
        with self.assertRaises(BenchmarkError):self.evaluate()
        with self.assertRaises(BenchmarkError):self.registry.history()

    def test_passing_fixture_is_bound_to_registered_protocol_and_preserved(self):
        # Synthetic annotations exercise mechanics, not actual independent model evidence.
        cases=canonical([{'case_id':str(i),'family':'fixture','label':LABELS[i%3]} for i in range(1200)])
        outputs=canonical([{'case_id':str(i),'prediction':LABELS[i%3],'unsupported_claim':False} for i in range(1200)])
        protocol=freeze_protocol(cases,model_revision_sha256=self.model,families=('fixture',),
            independent_labels=True,sealed=True,leakage_checked=True,independent_claim_review=True)
        path=self.path.parent/'passing.db';digest=register_protocol(path,protocol)
        registry=EvaluationRegistry(path,expected_protocol_sha256=digest)
        result=registry.evaluate(cases,outputs,run_id=self.run,model_revision_sha256=self.model)
        self.assertEqual(result['decision'],'PASS')
        self.assertEqual(result['protocol_sha256'],digest)
        self.assertEqual(registry.history()[0]['result'],result)
