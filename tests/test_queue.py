# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout, redirect_stderr
from dataclasses import replace
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aegisflow_dr.__main__ import main
from aegisflow_dr.coordination.contracts import encode
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize as initialize_store, IntegrityFailure
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import canonical, sha
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.gateway import ToolPolicy
from aegisflow_dr.workflow.schema import initialize
from aegisflow_dr.workflow.queue import ReviewQueue
from aegisflow_dr.workflow.model import RetryPolicy, QueueError, QueueIntegrityError, LeaseLost, Lease
from aegisflow_dr.workflow.worker import enqueue_review, work_once, workflow_fingerprint


class Clock:
    def __init__(self):self.now=1_000_000
    def __call__(self):return self.now


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'queue.db';self.db=self.root/'evidence.db'
        initialize_store(self.db);initialize(self.path)
        self.store=IncidentStore(self.db);self.runs=InvestigationRuns(self.store)
        self.clock=Clock();self.queue=ReviewQueue(self.path,clock=self.clock)
        incident=self.store.record(generate_orders(),request_key='source')
        self.record=self.runs.execute(incident['incident_id'],default_policy(),request_key='run')
        self.proposal={'version':'1','run_id':self.record['run_id'],'incident_id':incident['incident_id'],
                       'assessment':self.record['trace']['assessment'],
                       'evidence_sha256':sorted({self.record['trace']['source_sha256'],
                           *(s['report_sha256'] for s in self.record['trace']['steps'])})}

    def submit(self,key='job',retry=RetryPolicy()):
        return enqueue_review(self.queue,self.runs,encode('proposal',self.proposal),request_key=key,retry=retry)

    def pointer(self):
        return {'run_id':self.record['run_id'],'record_sha256':sha(canonical(self.record))}

    def read(self,job):return self.queue.read(job['job_id'])

    def test_round_trip_two_workers_and_independent_judge(self):
        evidence=self.db.read_bytes();job=self.submit()
        self.assertEqual(job['status'],'QUEUED')
        self.assertEqual(work_once(self.queue,self.runs)['task_id'],'collect')
        fresh=ReviewQueue(self.path,clock=self.clock)
        self.assertEqual(work_once(fresh,self.runs)['task_id'],'judge')
        saved=self.read(job)
        self.assertEqual(saved['status'],'SUCCEEDED')
        self.assertEqual(saved['tasks']['judge']['result']['decision'],'ACCEPT')
        self.assertEqual(work_once(fresh,self.runs),{'outcome':'IDLE'})
        self.assertEqual(self.db.read_bytes(),evidence)
        self.assertNotIn('lease_hash',json.dumps(saved));self.assertNotIn('ORD-',json.dumps(saved))

    def test_wrong_assessment_finishes_with_rejection_not_approval(self):
        self.proposal['assessment']='SOURCE_QUALITY_FAILURE';job=self.submit()
        work_once(self.queue,self.runs);work_once(self.queue,self.runs)
        saved=self.read(job)
        self.assertEqual(saved['status'],'SUCCEEDED')
        self.assertEqual(saved['tasks']['judge']['result']['decision'],'REJECT')

    def test_inconclusive_run_produces_durable_abstention(self):
        run=self.runs.execute(self.proposal['incident_id'],ToolPolicy(frozenset()),request_key='denied')
        self.proposal.update(run_id=run['run_id'],evidence_sha256=[run['trace']['source_sha256']])
        job=self.submit();work_once(self.queue,self.runs);work_once(self.queue,self.runs)
        self.assertEqual(self.read(job)['tasks']['judge']['result']['decision'],'ABSTAIN')

    def test_duplicate_submission_is_idempotent_even_when_evidence_order_changes(self):
        first=self.submit();self.proposal['evidence_sha256'].reverse()
        self.assertEqual(self.submit(),first)
        self.assertEqual(self.read(first)['history'],first['history'])

    def test_duplicate_conflicts_preserve_original(self):
        first=self.submit();self.proposal['assessment']='SOURCE_QUALITY_FAILURE'
        with self.assertRaises(QueueError):self.submit()
        self.proposal['assessment']='NO_FAILURE_OBSERVED'
        with self.assertRaises(QueueError):self.submit(retry=RetryPolicy(max_attempts=2))
        self.assertEqual(self.read(first),first)

    def test_concurrent_submission_and_reservation_only_accept_one(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            jobs=list(workers.map(lambda _:self.submit(),range(8)))
        self.assertEqual(len({j['job_id'] for j in jobs}),1)
        with ThreadPoolExecutor(max_workers=4) as workers:
            leases=list(workers.map(lambda n:self.queue.reserve('worker-'+str(n)),range(8)))
        self.assertEqual(sum(lease is not None for lease in leases),1)
        self.assertEqual(self.read(jobs[0])['tasks']['judge']['state'],'PENDING')

    def test_expired_reservation_backoff_and_fencing(self):
        job=self.submit(retry=RetryPolicy(base_delay_ms=100,max_delay_ms=1000))
        old=self.queue.reserve('old',lease_ms=50)
        self.clock.now+=50
        with self.assertRaises(LeaseLost):self.queue.complete(old,self.pointer())
        recovered=self.queue.recover(job['job_id'])
        self.assertEqual(recovered['tasks']['collect']['state'],'RETRY_WAIT')
        self.assertIsNone(self.queue.reserve('new'))
        self.clock.now+=100;new=self.queue.reserve('new')
        self.assertEqual(new.fence,2)
        for operation in [lambda:self.queue.complete(old,self.pointer()),lambda:self.queue.fail(old,'TEMPORARY_UNAVAILABLE'),lambda:self.queue.renew(old)]:
            with self.assertRaises(LeaseLost):operation()
        self.queue.complete(new,self.pointer())
        self.assertEqual(self.read(job)['tasks']['collect']['attempt'],2)

    def test_recovery_is_idempotent_and_does_not_skip_delay(self):
        job=self.submit();lease=self.queue.reserve('worker',lease_ms=1)
        self.clock.now+=1
        once=self.queue.recover(job['job_id']);twice=self.queue.recover(job['job_id'])
        self.assertEqual(once,twice)
        self.assertIsNone(self.queue.reserve('worker'))

    def test_reserve_automatically_recovers_expired_work(self):
        job=self.submit();self.queue.reserve('worker',lease_ms=1)
        self.clock.now+=1
        self.assertIsNone(self.queue.reserve('other'))
        self.assertEqual(self.read(job)['tasks']['collect']['reason'],'LEASE_EXPIRED')
        self.clock.now+=1000
        self.assertIsNotNone(self.queue.reserve('other'))

    def test_retry_delay_is_exponential_and_capped(self):
        job=self.submit(retry=RetryPolicy(max_attempts=5,base_delay_ms=100,max_delay_ms=150))
        for expected in [100,150,150,150]:
            lease=self.queue.reserve('worker')
            saved=self.queue.fail(lease,'TEMPORARY_UNAVAILABLE')
            self.assertEqual(saved['tasks']['collect']['ready_at_ms'],self.clock.now+expected)
            self.assertIsNone(self.queue.reserve('worker'))
            self.clock.now+=expected
        final=self.queue.fail(self.queue.reserve('worker'),'TEMPORARY_UNAVAILABLE')
        self.assertEqual((final['status'],final['tasks']['collect']['attempt']),('FAILED',5))
        self.assertEqual(final['tasks']['judge']['state'],'BLOCKED')
        self.assertIsNone(self.queue.reserve('worker'))

    def test_expired_final_attempt_is_terminal_and_blocks_dependency(self):
        job=self.submit(retry=RetryPolicy(max_attempts=1));self.queue.reserve('worker',lease_ms=1)
        self.clock.now+=1;saved=self.queue.recover(job['job_id'])
        self.assertEqual(saved['status'],'FAILED')
        self.assertEqual(saved['tasks']['judge']['state'],'BLOCKED')

    def test_renewal_extends_reservation_and_is_bounded(self):
        job=self.submit();lease=self.queue.reserve('worker',lease_ms=100)
        self.clock.now+=90
        self.queue.renew(lease,lease_ms=100)
        self.clock.now+=20
        self.queue.renew(lease,lease_ms=100);self.queue.renew(lease,lease_ms=100)
        with self.assertRaises(QueueError):self.queue.renew(lease)
        self.queue.complete(lease,self.pointer())
        self.assertEqual(self.read(job)['tasks']['collect']['state'],'SUCCEEDED')

    def test_wrong_token_owner_fence_and_task_cannot_commit(self):
        job=self.submit();lease=self.queue.reserve('worker')
        for altered in [replace(lease,token='b'*64),replace(lease,token='invalid'),replace(lease,fence=True),
                        replace(lease,owner='other'),replace(lease,fence=99),replace(lease,task_id='judge'),None]:
            with self.assertRaises(LeaseLost):self.queue.complete(altered,self.pointer())
        self.assertNotIn(lease.token,repr(lease));self.assertNotIn(lease.token,json.dumps(self.read(job)))
        self.queue.complete(lease,self.pointer())
        with self.assertRaises(LeaseLost):self.queue.complete(lease,self.pointer())

    def test_pending_cancellation_is_idempotent(self):
        job=self.submit();cancelled=self.queue.cancel(job['job_id'])
        self.assertEqual(cancelled['status'],'CANCELLED')
        self.assertEqual(self.queue.cancel(job['job_id']),cancelled)
        self.assertIsNone(self.queue.reserve('worker'))

    def test_cancel_during_execution_discards_late_result(self):
        job=self.submit();original=self.runs.read
        def cancel_then_read(run):
            self.queue.cancel(job['job_id'])
            return original(run)
        with patch.object(self.runs,'read',side_effect=cancel_then_read):result=work_once(self.queue,self.runs)
        self.assertEqual(result['outcome'],'LEASE_LOST')
        self.assertEqual(self.read(job)['status'],'CANCELLED')
        self.assertIsNone(self.read(job)['tasks']['collect']['result'])

    def test_cancel_preserves_finished_parent_and_invalidates_active_judge(self):
        job=self.submit();work_once(self.queue,self.runs)
        lease=self.queue.reserve('worker');self.queue.cancel(job['job_id'])
        self.assertEqual(self.read(job)['tasks']['collect']['state'],'SUCCEEDED')
        for operation in [lambda:self.queue.fail(lease,'INTERNAL_ERROR'),lambda:self.queue.renew(lease)]:
            with self.assertRaises(LeaseLost):operation()

    def test_completed_and_failed_jobs_cannot_be_reopened_by_cancellation(self):
        job=self.submit();work_once(self.queue,self.runs);work_once(self.queue,self.runs)
        with self.assertRaises(QueueError):self.queue.cancel(job['job_id'])
        other=self.submit('other');self.queue.fail(self.queue.reserve('worker'),'INTERNAL_ERROR')
        with self.assertRaises(QueueError):self.queue.cancel(other['job_id'])

    def test_transient_busy_error_retries_but_integrity_and_internal_errors_do_not(self):
        job=self.submit();busy=sqlite3.OperationalError('private-detail');busy.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch.object(self.runs,'read',side_effect=busy):result=work_once(self.queue,self.runs)
        self.assertEqual(result['task_state'],'RETRY_WAIT')
        self.clock.now+=1000
        with patch.object(self.runs,'read',side_effect=IntegrityFailure('private-detail')):result=work_once(self.queue,self.runs)
        self.assertEqual(result['job_status'],'FAILED')
        self.assertNotIn('private-detail',json.dumps(self.read(job)))
        self.submit('internal')
        with patch.object(self.runs,'read',side_effect=RuntimeError('private-detail')):
            self.assertEqual(work_once(self.queue,self.runs)['job_status'],'FAILED')

    def test_missing_store_error_is_terminal_not_an_infinite_retry(self):
        job=self.submit()
        with patch.object(self.runs,'read',side_effect=sqlite3.OperationalError('missing private path')):
            result=work_once(self.queue,self.runs)
        self.assertEqual(result['task_state'],'FAILED')
        self.assertEqual(self.read(job)['tasks']['collect']['reason'],'EVIDENCE_UNAVAILABLE')

    def test_version_mismatch_fails_closed_without_reading_evidence(self):
        job=self.submit()
        with patch('aegisflow_dr.workflow.worker.workflow_fingerprint',return_value='a'*64),patch.object(self.runs,'read',side_effect=AssertionError):
            result=work_once(self.queue,self.runs)
        self.assertEqual(result['job_status'],'FAILED')
        self.assertEqual(self.read(job)['tasks']['collect']['reason'],'VERSION_MISMATCH')

    def test_changed_context_or_metadata_hash_is_not_accepted(self):
        for mutation in ['hash','context']:
            job=self.submit(mutation);record=deepcopy(self.record)
            if mutation=='hash':record['trace']['assessment']='SOURCE_QUALITY_FAILURE'
            else:record['manifest']['request']['incident_id']='00000000-0000-0000-0000-000000000000'
            with patch.object(self.runs,'read',return_value=record):work_once(self.queue,self.runs)
            self.assertEqual(self.read(job)['tasks']['collect']['reason'],'INTEGRITY_FAILURE')

    def test_enqueue_rejects_cross_context_without_partial_job(self):
        self.proposal['incident_id']='00000000-0000-0000-0000-000000000000'
        with self.assertRaises(QueueError):self.submit()
        with closing(sqlite3.connect(self.path)) as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_invalid_result_and_failure_reason_leave_reservation_unchanged(self):
        job=self.submit();lease=self.queue.reserve('worker');before=self.read(job)
        for result in [{},dict(self.pointer(),record_sha256='b'*64),dict(self.pointer(),api_key='private')]:
            with self.assertRaises(QueueError):self.queue.complete(lease,result)
        for reason in ['private-exception',None,'LEASE_EXPIRED']:
            with self.assertRaises(QueueError):self.queue.fail(lease,reason)
        self.assertEqual(self.read(job),before)

    def test_clock_rollback_and_invalid_duration_are_rejected(self):
        job=self.submit();self.clock.now-=1
        with self.assertRaises(QueueError):self.queue.reserve('worker')
        self.clock.now+=1
        for duration in [0,True,-1,60_001,'100']:
            with self.assertRaises(QueueError):self.queue.reserve('worker',lease_ms=duration)
        for value in [-1,True,1.5,10**18]:
            self.clock.now=value
            with self.assertRaises(QueueError):self.queue.reserve('worker')

    def test_initialization_and_open_never_overwrite_or_create_accidentally(self):
        before=self.path.read_bytes()
        with self.assertRaises(FileExistsError):initialize(self.path)
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(QueueError):ReviewQueue(self.db)
        missing=self.root/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):ReviewQueue(missing)
        self.assertFalse(missing.exists())
        if os.name=='posix':self.assertEqual(self.path.stat().st_mode & 0o777,0o600)

    def test_bad_keys_policies_hashes_and_capacity_are_rejected(self):
        for args in [dict(max_attempts=0),dict(max_attempts=True),dict(base_delay_ms=0),dict(max_delay_ms=0),dict(max_attempts=6)]:
            with self.assertRaises(QueueError):RetryPolicy(**args)
        for key in ['',None,'bad key','../escape','x'*65]:
            with self.assertRaises(QueueError):self.submit(key)
        for values in [dict(record_sha256='invalid',workflow_sha256='a'*64),dict(record_sha256='a'*64,workflow_sha256='bad'),
                       dict(record_sha256='a'*64,workflow_sha256='b'*64,retry={})]:
            with self.assertRaises(QueueError):self.queue.submit(encode('proposal',self.proposal),request_key='x',**values)
        self.submit()
        with patch('aegisflow_dr.workflow.queue.MAX_ACTIVE',1):
            with self.assertRaises(QueueError):self.submit('other')

    def test_failed_event_insert_rolls_back_projection_and_job(self):
        original=ReviewQueue._persist
        def broken(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('injected')
        with patch.object(ReviewQueue,'_persist',broken):
            with self.assertRaises(RuntimeError):self.submit()
        with closing(sqlite3.connect(self.path)) as c:
            for table in ['jobs','events','projections']:self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
        job=self.submit();before=self.read(job)
        with patch.object(ReviewQueue,'_persist',broken):
            with self.assertRaises(RuntimeError):self.queue.reserve('worker')
        self.assertEqual(self.read(job),before)

    def test_jobs_and_events_are_immutable_and_foreign_keys_enforced(self):
        self.submit()
        with closing(sqlite3.connect(self.path)) as c:
            for table in ['jobs','events']:
                for operation in [f'UPDATE {table} SET rowid=rowid',f'DELETE FROM {table}']:
                    with self.assertRaises(sqlite3.IntegrityError):c.execute(operation)
                    c.rollback()
        with self.queue._connect(write=True) as c:
            with self.assertRaises(sqlite3.IntegrityError):c.execute('INSERT INTO projections VALUES (?,?,?,?)',('missing','QUEUED',b'{}','bad'))

    def test_projection_tampering_and_status_substitution_are_detected(self):
        job=self.submit()
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("UPDATE projections SET status='FAILED'");c.commit()
        with self.assertRaises(QueueIntegrityError):self.read(job)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("UPDATE projections SET status='QUEUED',content=?",(b'{}',));c.commit()
        with self.assertRaises(QueueIntegrityError):self.read(job)

    def test_unknown_jobs_and_modified_schema_fail_closed(self):
        for key in ['missing','00000000-0000-0000-0000-000000000000']:
            with self.assertRaises(QueueError):self.queue.read(key)
        with closing(sqlite3.connect(self.path)) as c:c.execute('DROP TRIGGER immutable_events_update')
        with self.assertRaises(QueueError):ReviewQueue(self.path)

    def test_backup_restore_preserves_active_reservation_and_history(self):
        job=self.submit();lease=self.queue.reserve('worker',lease_ms=10)
        backup=self.root/'backup.db'
        with closing(sqlite3.connect(self.path)) as source,closing(sqlite3.connect(backup)) as target:source.backup(target)
        restored=ReviewQueue(backup,clock=self.clock)
        self.assertEqual(restored.read(job['job_id']),self.read(job))
        self.clock.now+=10
        restored.recover(job['job_id']);self.clock.now+=1000
        self.assertIsNotNone(restored.reserve('restored'))

    def test_process_exit_after_reservation_can_be_recovered_after_restart(self):
        job=self.submit()
        program='''from pathlib import Path
import os,sys
from aegisflow_dr.workflow.queue import ReviewQueue
q=ReviewQueue(Path(sys.argv[1]),clock=lambda:1000000)
q.reserve('crashed',lease_ms=1)
os._exit(17)
'''
        env=dict(os.environ,PYTHONPATH=str(Path('src').resolve()),PYTHONDONTWRITEBYTECODE='1')
        child=subprocess.run([sys.executable,'-c',program,str(self.path)],env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(child.returncode,17,child.stderr)
        self.clock.now+=1;self.queue.recover(job['job_id']);self.clock.now+=1000
        self.assertEqual(self.queue.reserve('replacement').fence,2)

    def test_cli_round_trip_and_sanitized_errors(self):
        proposal_file=self.root/'proposal.json';proposal_file.write_bytes(encode('proposal',self.proposal))
        def invoke(args):
            out,err=io.StringIO(),io.StringIO()
            with redirect_stdout(out),redirect_stderr(err):code=main(args)
            return code,out.getvalue(),err.getvalue()
        args=['--queue',str(self.path)]
        code,out,_=invoke(['submit-review',*args,'--db',str(self.db),'--proposal',str(proposal_file),'--key','cli'])
        self.assertEqual(code,0);job=json.loads(out)
        for _ in range(2):
            code,out,_=invoke(['work-once',*args,'--db',str(self.db)])
            self.assertEqual((code,json.loads(out)['outcome']),(0,'APPLIED'))
        code,out,_=invoke(['read-job',*args,'--job',job['job_id']])
        self.assertEqual((code,json.loads(out)['status']),(0,'SUCCEEDED'))
        code,out,err=invoke(['read-job',*args,'--job','private-invalid'])
        self.assertEqual((code,out),(2,''));self.assertNotIn('private-invalid',err);self.assertNotIn(str(self.path),err)

    def test_second_job_can_run_while_first_waits_for_backoff(self):
        first=self.submit('first');self.queue.fail(self.queue.reserve('worker'),'TEMPORARY_UNAVAILABLE')
        second=self.submit('second')
        self.assertEqual(self.queue.reserve('worker').job_id,second['job_id'])
        self.assertEqual(self.read(first)['tasks']['collect']['state'],'RETRY_WAIT')

    def test_cancel_and_completion_race_has_one_atomic_winner(self):
        job=self.submit();lease=self.queue.reserve('worker')
        def complete():
            try:return self.queue.complete(lease,self.pointer())['tasks']['collect']['state']
            except LeaseLost:return 'LEASE_LOST'
        with ThreadPoolExecutor(max_workers=2) as workers:
            completed=workers.submit(complete);cancelled=workers.submit(self.queue.cancel,job['job_id'])
            completed.result();cancelled.result()
        saved=self.read(job)
        self.assertEqual(saved['status'],'CANCELLED')
        self.assertIn(saved['tasks']['collect']['state'],{'CANCELLED','SUCCEEDED'})
        self.assertEqual(saved['tasks']['judge']['state'],'CANCELLED')

    def test_expiry_during_read_prevents_both_success_and_failure_commit(self):
        job=self.submit();original=self.runs.read
        def late_read(run):self.clock.now+=30_000;return original(run)
        with patch.object(self.runs,'read',side_effect=late_read):
            self.assertEqual(work_once(self.queue,self.runs)['outcome'],'LEASE_LOST')
        self.queue.recover(job['job_id']);self.clock.now+=1000
        def late_failure(run):self.clock.now+=30_000;raise RuntimeError('private')
        with patch.object(self.runs,'read',side_effect=late_failure):
            self.assertEqual(work_once(self.queue,self.runs)['outcome'],'LEASE_LOST')

    def tamper(self,table,sql,parameters=(),kind='update'):
        with closing(sqlite3.connect(self.path)) as c:
            trigger='immutable_'+table+'_'+kind
            ddl=c.execute('SELECT sql FROM sqlite_master WHERE name=?',(trigger,)).fetchone()[0]
            c.execute('DROP TRIGGER '+trigger);c.execute(sql,parameters);c.execute(ddl);c.commit()

    def test_manifest_corruption_and_request_key_substitution_fail_closed(self):
        job=self.submit()
        self.tamper('jobs','UPDATE jobs SET manifest=?',(b'{}',))
        with self.assertRaises(QueueIntegrityError):self.read(job)
        other=self.submit('other')
        self.tamper('jobs',"UPDATE jobs SET request_key='substituted' WHERE id=?",(other['job_id'],))
        with self.assertRaises(QueueIntegrityError):self.read(other)

    def test_corrupt_missing_and_reordered_event_history_rejected(self):
        first=self.submit('first')
        self.tamper('events','UPDATE events SET content=? WHERE job_id=?',(b'{}',first['job_id']))
        with self.assertRaises(QueueIntegrityError):self.read(first)
        second=self.submit('second')
        self.tamper('events','DELETE FROM events WHERE job_id=?',(second['job_id'],),kind='delete')
        with self.assertRaises(QueueIntegrityError):self.read(second)
        third=self.submit('third')
        self.tamper('events','UPDATE events SET revision=2 WHERE job_id=?',(third['job_id'],))
        with self.assertRaises(QueueIntegrityError):self.read(third)

    def test_rehashed_projection_cannot_disagree_with_immutable_history(self):
        job=self.submit()
        with closing(sqlite3.connect(self.path)) as c:
            value=json.loads(c.execute('SELECT content FROM projections').fetchone()[0])
            value['tasks']['collect']['ready_at_ms']+=1;data=canonical(value)
            c.execute('UPDATE projections SET content=?,sha256=?',(data,sha(data)));c.commit()
        with self.assertRaises(QueueIntegrityError):self.read(job)

    def test_malformed_projection_states_are_rejected_before_execution(self):
        from aegisflow_dr.workflow.model import initial
        base=initial(self.clock.now)
        def executed(state):
            return dict(base['tasks']['collect'],state=state,attempt=1,fence=1,owner='worker')
        variants=[]
        value=deepcopy(base);value.pop('cancelled');variants.append(value)
        value=deepcopy(base);value['tasks']['collect']['state']='unknown';variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('LEASED');variants.append(value)
        value=deepcopy(base);value['tasks']['collect']['lease_hash']='a'*64;variants.append(value)
        value=deepcopy(base);value['tasks']['collect']['result']=self.pointer();variants.append(value)
        value=deepcopy(base);value['tasks']['collect']['owner']='x'*65;variants.append(value)
        value=deepcopy(base);value['tasks']['collect']['attempt']=1;value['tasks']['collect']['fence']=1;variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('SUCCEEDED');value['tasks']['collect'].update(attempt=0,fence=0,result=self.pointer());variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('LEASED');value['tasks']['collect'].update(lease_hash='a'*64,lease_until_ms=self.clock.now+1000,reason='INTERNAL_ERROR');variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('RETRY_WAIT');value['tasks']['collect']['reason']='INTERNAL_ERROR';variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('FAILED');variants.append(value)
        value=deepcopy(base);value['tasks']['collect'].update(state='BLOCKED',reason='DEPENDENCY_FAILED');variants.append(value)
        value=deepcopy(base);value['tasks']['collect'].update(state='CANCELLED',reason='OPERATOR_CANCELLED');variants.append(value)
        value=deepcopy(base);value['tasks']['collect']=executed('FAILED');value['tasks']['collect']['reason']='INTERNAL_ERROR';variants.append(value)
        value=deepcopy(base);value['tasks']['judge']=executed('LEASED');value['tasks']['judge'].update(lease_hash='a'*64,lease_until_ms=self.clock.now+1000);variants.append(value)
        value=deepcopy(base);value['cancelled']=True;variants.append(value)
        for number,value in enumerate(variants):
            job=self.submit('corruption-'+str(number));data=canonical(value)
            with closing(sqlite3.connect(self.path)) as c:
                c.execute('UPDATE projections SET content=?,sha256=? WHERE job_id=?',(data,sha(data),job['job_id']));c.commit()
            with self.subTest(number=number),self.assertRaises(QueueIntegrityError):self.read(job)

    def test_rehashed_manifest_and_event_bindings_rejected(self):
        for number,mutation in enumerate(['manifest-version','graph','event-time','event-prev','event-initial']):
            job=self.submit('binding-'+str(number))
            with closing(sqlite3.connect(self.path)) as c:
                table='jobs' if mutation.startswith('manifest') or mutation=='graph' else 'events'
                column='manifest' if table=='jobs' else 'content'
                where='id' if table=='jobs' else 'job_id'
                value=json.loads(c.execute(f'SELECT {column} FROM {table} WHERE {where}=?',(job['job_id'],)).fetchone()[0])
            if mutation=='manifest-version':value['version']='999'
            elif mutation=='graph':value['tasks'].reverse()
            elif mutation=='event-time':value['at_ms']-=1
            elif mutation=='event-prev':value['previous_sha256']='a'*64
            else:value['kind']='RESERVED'
            data=canonical(value)
            self.tamper(table,f'UPDATE {table} SET {column}=?,sha256=? WHERE {where}=?',(data,sha(data),job['job_id']))
            with self.assertRaises(QueueIntegrityError):self.read(job)

    def test_budget_guards_and_invalid_judge_result_are_atomic(self):
        with patch('aegisflow_dr.workflow.queue.MAX_BYTES',1):
            with self.assertRaises(QueueError):self.submit()
        job=self.submit();work_once(self.queue,self.runs);lease=self.queue.reserve('worker')
        wrong={'version':'1','run_id':self.record['run_id'],'decision':'ACCEPT','reason':'MATCH',
               'assessment':'NO_FAILURE_OBSERVED','reviewer':'A27','mode':'deterministic','record_sha256':'a'*64}
        with self.assertRaises(QueueError):self.queue.complete(lease,wrong)
        before=self.read(job)
        with patch('aegisflow_dr.workflow.queue.MAX_EVENTS',len(before['history'])):
            with self.assertRaises(QueueError):self.queue.renew(lease)
        self.assertEqual(self.read(job),before)

    def test_cli_initialization_cancel_recover_and_lost_lease_status(self):
        def invoke(args):
            out,err=io.StringIO(),io.StringIO()
            with redirect_stdout(out),redirect_stderr(err):code=main(args)
            return code,out.getvalue(),err.getvalue()
        path=self.root/'other.db';code,out,_=invoke(['queue-init','--queue',str(path)])
        self.assertEqual((code,json.loads(out)['outcome']),(0,'QUEUE_INITIALIZED'))
        job=self.submit();args=['--queue',str(self.path),'--job',job['job_id']]
        code,out,_=invoke(['recover-job',*args]);self.assertEqual(code,0)
        code,out,_=invoke(['cancel-job',*args]);self.assertEqual(json.loads(out)['status'],'CANCELLED')
        with patch('aegisflow_dr.workflow.cli.work_once',return_value={'outcome':'LEASE_LOST'}):
            code,out,_=invoke(['work-once','--queue',str(self.path),'--db',str(self.db)])
        self.assertEqual(code,1)

    def test_process_exit_before_projection_commit_rolls_back(self):
        job=self.submit();before=self.read(job)
        program='''import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute('PRAGMA cache_size=1')
c.execute('PRAGMA cache_spill=ON')
c.execute('BEGIN IMMEDIATE')
c.execute("UPDATE projections SET content=?",(b'private-incomplete'*10000,))
os._exit(18)
'''
        child=subprocess.run([sys.executable,'-c',program,str(self.path)],capture_output=True,text=True,timeout=10)
        self.assertEqual(child.returncode,18,child.stderr)
        self.assertEqual(self.read(job),before)

    def test_projection_budget_and_invalid_event_kind_cannot_commit(self):
        job=self.submit();before=self.read(job)
        with patch('aegisflow_dr.workflow.model.MAX_BYTES',1):
            with self.assertRaises(QueueIntegrityError):self.read(job)
        with self.queue._connect(write=True) as c:
            manifest,projection,_=self.queue._load(c,job['job_id'])
            with self.assertRaises(QueueError):self.queue._persist(c,manifest,projection,'UNKNOWN_EVENT',self.clock.now)
        self.assertEqual(self.read(job),before)

    def test_final_completion_and_cancellation_race_have_one_terminal_outcome(self):
        from aegisflow_dr.coordination.judge import review
        job=self.submit();work_once(self.queue,self.runs);lease=self.queue.reserve('worker')
        verdict=review(self.record,self.proposal)
        def complete():
            try:self.queue.complete(lease,verdict);return 'SUCCEEDED'
            except LeaseLost:return 'LEASE_LOST'
        def cancel():
            try:self.queue.cancel(job['job_id']);return 'CANCELLED'
            except QueueError:return 'ALREADY_TERMINAL'
        with ThreadPoolExecutor(max_workers=2) as workers:
            a,b=workers.submit(complete),workers.submit(cancel)
            outcomes={a.result(),b.result()}
        saved=self.read(job)
        self.assertIn(saved['status'],{'CANCELLED','SUCCEEDED'})
        self.assertIn(outcomes,[{'SUCCEEDED','ALREADY_TERMINAL'},{'LEASE_LOST','CANCELLED'}])
        self.assertEqual(saved['tasks']['judge']['result'] is not None,saved['status']=='SUCCEEDED')

    def test_explicit_evidence_recovery_after_dirty_page_spill_preserves_history(self):
        from aegisflow_dr.storage.recovery import recover
        program='''import sqlite3,sys,os
c=sqlite3.connect(sys.argv[1])
c.execute('PRAGMA cache_size=1')
c.execute('PRAGMA cache_spill=ON')
c.execute('BEGIN IMMEDIATE')
c.execute('DROP TRIGGER immutable_evidence_update')
c.execute("UPDATE evidence SET content=? WHERE id='report'",(b'incomplete'*30000,))
os._exit(19)
'''
        child=subprocess.run([sys.executable,'-c',program,str(self.db)],capture_output=True,text=True,timeout=10)
        self.assertEqual(child.returncode,19,child.stderr)
        recover(self.db)
        self.assertEqual(self.runs.read(self.record['run_id']),self.record)
        self.assertEqual(self.runs.replay(self.record['run_id'])['outcome'],'MATCH')
        self.assertEqual(self.store.replay(self.proposal['incident_id'])['outcome'],'MATCH')

    def test_evidence_recovery_never_creates_adopts_or_changes_committed_records(self):
        from aegisflow_dr.storage.recovery import recover
        missing=self.root/'absent.db'
        with self.assertRaises(sqlite3.OperationalError):recover(missing)
        self.assertFalse(missing.exists())
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):recover(self.path)
        self.assertEqual(self.path.read_bytes(),before)
        before=self.db.read_bytes();recover(self.db)
        self.assertEqual(self.db.read_bytes(),before)

    def test_evidence_recovery_rolls_back_on_failed_page_check(self):
        from aegisflow_dr.storage.recovery import recover
        class BadPages(sqlite3.Connection):
            def execute(self,sql,*args):
                if sql=='PRAGMA quick_check':return super().execute("SELECT 'damaged'")
                return super().execute(sql,*args)
        original=sqlite3.connect
        before=self.db.read_bytes()
        with patch('aegisflow_dr.storage.recovery.sqlite3.connect',side_effect=lambda *a,**k:original(*a,**k,factory=BadPages)):
            with self.assertRaises(ValueError):recover(self.db)
        self.assertEqual(self.db.read_bytes(),before)

    def test_cli_explicit_evidence_recovery(self):
        out=io.StringIO()
        with redirect_stdout(out):code=main(['store-recover','--db',str(self.db)])
        self.assertEqual((code,json.loads(out.getvalue())['outcome']),(0,'STORE_RECOVERED'))
