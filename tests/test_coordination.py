# SPDX-License-Identifier: Apache-2.0
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.coordination.contracts import ContractError, MAX_MESSAGE_BYTES, _offline, _validator, encode, parse
from aegisflow_dr.coordination.routing import Worker, TaskGraph, RoutingError, LOCAL_WORKERS
from aegisflow_dr.coordination.judge import review
from aegisflow_dr.coordination.service import review_saved_run
from aegisflow_dr.storage import initialize, IncidentStore, IntegrityFailure
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha, canonical
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.gateway import ToolPolicy
from aegisflow_dr.__main__ import main
from referencing.exceptions import NoSuchResource

RUN='00000000-0000-0000-0000-000000000001'
INCIDENT='00000000-0000-0000-0000-000000000002'


def proposal():
    return {'version':'1','run_id':RUN,'incident_id':INCIDENT,'assessment':'NO_FAILURE_OBSERVED',
            'evidence_sha256':['a'*64]}


def task(key='collect', capability='evidence.read', dependencies=()):
    return {'version':'1','task_id':key,'incident_id':INCIDENT,'run_id':RUN,'capability':capability,
            'required_tags':['read-only'],'depends_on':list(dependencies)}


class ContractTests(unittest.TestCase):
    def test_schema_round_trip_detaches_input(self):
        original=proposal()
        decoded=parse('proposal',encode('proposal',original))
        original['evidence_sha256'].append('b'*64)
        self.assertEqual(decoded['evidence_sha256'],['a'*64])

    def test_all_packaged_schemas_are_valid_and_closed(self):
        for name in ['task','proposal','verdict','receipt']:
            validator=_validator(name)
            self.assertFalse(validator.schema['additionalProperties'])
            self.assertEqual(validator.schema['$schema'],'https://json-schema.org/draft/2020-12/schema')

    def test_unknown_contract_never_resolves_a_reference(self):
        for name in ['https://untrusted.invalid/schema',None,[], 'future']:
            with self.assertRaises(ContractError):parse(name,b'{}')
        with self.assertRaises(ContractError):_validator('unknown')
        with self.assertRaises(NoSuchResource):_offline('https://untrusted.invalid/schema')

    def test_malformed_utf8_nonfinite_and_duplicate_fields_rejected(self):
        for payload in [b'\xff',b'{',b'{"x":NaN}',b'{"x":Infinity}',b'{"x":1,"x":2}',b'null',b'[]']:
            with self.subTest(payload=payload),self.assertRaises(ContractError):parse('proposal',payload)

    def test_missing_fields_and_unknown_privilege_fields_rejected(self):
        for key in list(proposal()):
            value=proposal();del value[key]
            with self.assertRaises(ContractError):encode('proposal',value)
        for key in ['api_key','certificate','policy','endpoint','tenant_id','tool','prompt']:
            value=proposal();value[key]='private-value'
            with self.assertRaises(ContractError) as error:encode('proposal',value)
            self.assertNotIn('private-value',str(error.exception))

    def test_hash_and_identity_validation(self):
        for key,bad in [('run_id',RUN+'\n'),('run_id','../escape'),('incident_id',True),
                        ('evidence_sha256',['a'*63]),('evidence_sha256',['A'*64]),
                        ('evidence_sha256',['a'*64,'a'*64]),('evidence_sha256',[]),
                        ('evidence_sha256',['a'*64]*5),('assessment','ROOT_CAUSE_PROVEN'),('version','2')]:
            value=proposal();value[key]=bad
            with self.subTest(key=key),self.assertRaises(ContractError):encode('proposal',value)

    def test_byte_budget_and_type_rejected(self):
        for payload in ['text',None,b'x'*(MAX_MESSAGE_BYTES+1)]:
            with self.assertRaises(ContractError):parse('proposal',payload)
        valid=encode('proposal',proposal())
        self.assertEqual(parse('proposal',valid+b' '*(MAX_MESSAGE_BYTES-len(valid))),proposal())

    def test_deeply_nested_and_non_json_objects_rejected(self):
        with self.assertRaises(ContractError):parse('proposal',b'['*1100+b'0'+b']'*1100)
        for value in [set(),{'bad':object()},{'bad':float('nan')}]:
            with self.assertRaises(ContractError):encode('proposal',value)
        circular={};circular['self']=circular
        with self.assertRaises(ContractError):encode('proposal',circular)

    def test_task_names_dependencies_and_tags_are_bounded(self):
        for key,bad in [('task_id','bad\n'),('task_id','x'*65),('task_id','../escape'),
                        ('depends_on',['x']*2),('depends_on',['x'+str(i) for i in range(9)]),
                        ('required_tags',['read-only']*2),('required_tags',['root']),('required_tags',[])]:
            value=task();value[key]=bad
            with self.assertRaises(ContractError):encode('task',value)

    def test_receipt_state_and_result_must_agree(self):
        value={'version':'1','task_id':'collect','agent_id':'A26','state':'COMPLETED',
               'result_sha256':'a'*64,'reason':None}
        self.assertEqual(parse('receipt',encode('receipt',value)),value)
        for mutation in [{'result_sha256':None},{'reason':'RUN_UNAVAILABLE'},
                         {'state':'BLOCKED','result_sha256':None,'reason':'RUN_UNAVAILABLE'}]:
            with self.assertRaises(ContractError):encode('receipt',dict(value,**mutation))

    def test_verdict_decision_must_match_reason(self):
        value={'version':'1','run_id':RUN,'decision':'ACCEPT','reason':'MATCH','assessment':'NO_FAILURE_OBSERVED',
               'reviewer':'A27','mode':'deterministic','record_sha256':'a'*64}
        for mutation in [{'reason':'CONTRADICTION'},{'assessment':None},{'record_sha256':None},
                         {'decision':'ABSTAIN'},{'mode':'llm'}]:
            with self.assertRaises(ContractError):encode('verdict',dict(value,**mutation))


class RoutingTests(unittest.TestCase):
    def test_graph_orders_dependencies_and_selects_scoped_workers(self):
        graph=TaskGraph([task('judge','assessment.review',['collect']),task()])
        self.assertEqual(graph.order,('collect','judge'))
        self.assertEqual(graph.assignments['collect'].agent_id,'A26')
        self.assertEqual(graph.assignments['judge'].agent_id,'A27')
        self.assertEqual(graph.ready(frozenset()),('collect',))
        self.assertEqual(graph.ready(frozenset({'collect'})),('judge',))
        self.assertEqual(graph.ready(frozenset(),frozenset({'collect'})),())

    def test_independent_tasks_form_deterministic_ready_set(self):
        graph=TaskGraph([task('z'),task('a')])
        self.assertEqual(graph.ready(frozenset()),('a','z'))

    def test_original_and_returned_task_mutation_cannot_change_plan(self):
        original=task();graph=TaskGraph([original]);original['required_tags'].append('root')
        returned=graph.task('collect');returned['depends_on'].append('bad')
        self.assertEqual(graph.task('collect')['depends_on'],[])
        with self.assertRaises(TypeError):graph.assignments['collect']=LOCAL_WORKERS[1]

    def test_cycles_self_dependency_missing_and_duplicate_tasks_rejected(self):
        cases=[[task('a',dependencies=['a'])], [task('a',dependencies=['b']),task('b',dependencies=['a'])],
               [task('a',dependencies=['missing'])], [task(),task()]]
        for tasks in cases:
            with self.assertRaises(RoutingError):TaskGraph(tasks)

    def test_cross_context_and_cross_run_graphs_rejected(self):
        for field in ['run_id','incident_id']:
            other=task('other');other[field]='00000000-0000-0000-0000-000000000003'
            with self.assertRaises(RoutingError):TaskGraph([task(),other])

    def test_unavailable_or_ambiguous_capability_rejected(self):
        requested=task();requested['required_tags']=['verification']
        with self.assertRaises(RoutingError):TaskGraph([requested])
        with self.assertRaises(RoutingError):TaskGraph([task()],workers=(LOCAL_WORKERS[1],))
        with self.assertRaises(RoutingError):TaskGraph([task()],workers=(LOCAL_WORKERS[0],Worker('A01','evidence.read',frozenset({'read-only'}))))

    def test_invalid_worker_registration_and_registry_rejected(self):
        for values in [('A37','evidence.read',frozenset({'read-only'})),('A26',[],frozenset({'read-only'})),
                       ('A26','evidence.read',{'read-only'}),('A26','evidence.read',frozenset({'root'}))]:
            with self.assertRaises(RoutingError):Worker(*values)
        for workers in [(),[],(LOCAL_WORKERS[0],LOCAL_WORKERS[0]),('worker',)]:
            with self.assertRaises(RoutingError):TaskGraph([task()],workers=workers)

    def test_graph_size_and_scheduler_state_rejected(self):
        for tasks in [[],None,[task(str(i)) for i in range(9)]]:
            with self.assertRaises(RoutingError):TaskGraph(tasks)
        graph=TaskGraph([task(),task('judge','assessment.review',['collect'])])
        for completed,failed in [(set(),frozenset()),(frozenset({'missing'}),frozenset()),
                                 (frozenset({'collect'}),frozenset({'collect'})),(frozenset({'judge'}),frozenset())]:
            with self.assertRaises(RoutingError):graph.ready(completed,failed)


class JudgeSimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'research.db';initialize(self.path)
        self.store=IncidentStore(self.path);self.runs=InvestigationRuns(self.store)

    def saved(self,fault='clean',transform='clean',policy=None):
        incident=self.store.record(generate_orders(fault=fault),request_key=fault)
        record=self.runs.execute(incident['incident_id'],policy or default_policy(),request_key=transform,transform=transform)
        p={'version':'1','run_id':record['run_id'],'incident_id':incident['incident_id'],
           'assessment':record['trace']['assessment'] or 'NO_FAILURE_OBSERVED',
           'evidence_sha256':sorted({record['trace']['source_sha256'],
                                    *(s['report_sha256'] for s in record['trace']['steps'] if s['outcome']=='OK')})}
        return record,p

    def test_clean_source_failure_and_transform_failure_end_to_end(self):
        for fault,transform in [('clean','clean'),('schema_drift','clean'),('null_total','clean'),('clean','exclude_first')]:
            record,p=self.saved(fault,transform)
            before=self.path.read_bytes()
            result=review_saved_run(self.runs,encode('proposal',p))
            self.assertEqual(result['verdict']['decision'],'ACCEPT')
            self.assertEqual([r['agent_id'] for r in result['receipts']],['A26','A27'])
            self.assertEqual([r['state'] for r in result['receipts']],['COMPLETED','COMPLETED'])
            self.assertEqual(result['verdict']['record_sha256'],sha(canonical(record)))
            self.assertEqual(self.path.read_bytes(),before)
            self.assertNotIn('ORD-',json.dumps(result))
            self.assertFalse(result['durable_job'])

    def test_wrong_assessment_is_rejected(self):
        record,p=self.saved(transform='exclude_first');p['assessment']='NO_FAILURE_OBSERVED'
        result=review_saved_run(self.runs,encode('proposal',p))
        self.assertEqual(result['verdict']['decision'],'REJECT')
        self.assertEqual(result['verdict']['reason'],'CONTRADICTION')
        self.assertEqual(self.runs.read(record['run_id']),record)

    def test_missing_unknown_or_cross_run_evidence_is_rejected(self):
        record,p=self.saved()
        for evidence in [[p['evidence_sha256'][0]],['b'*64],p['evidence_sha256']+['b'*64]]:
            invalid=dict(p,evidence_sha256=evidence)
            result=review_saved_run(self.runs,encode('proposal',invalid))
            self.assertEqual(result['verdict']['reason'],'EVIDENCE_MISMATCH')

    def test_inconclusive_trace_never_receives_approval(self):
        record,p=self.saved(policy=ToolPolicy(frozenset()))
        result=review_saved_run(self.runs,encode('proposal',p))
        self.assertEqual((result['verdict']['decision'],result['verdict']['reason']),('ABSTAIN','INCOMPLETE'))

    def test_unavailable_or_corrupt_run_blocks_judge(self):
        record,p=self.saved()
        for method in [lambda:dict(p,run_id=RUN),lambda:p]:
            with patch.object(self.runs,'read',side_effect=IntegrityFailure('private-error')):
                result=review_saved_run(self.runs,encode('proposal',method()))
            self.assertEqual([r['state'] for r in result['receipts']],['FAILED','BLOCKED'])
            self.assertEqual(result['verdict']['reason'],'RUN_UNAVAILABLE')
            self.assertNotIn('private-error',json.dumps(result))

    def test_cross_incident_context_does_not_expose_result(self):
        record,p=self.saved();p['incident_id']=INCIDENT
        result=review_saved_run(self.runs,encode('proposal',p))
        self.assertEqual(result['verdict']['reason'],'RUN_UNAVAILABLE')
        self.assertIsNone(result['verdict']['record_sha256'])
        self.assertTrue(all(r['result_sha256'] is None for r in result['receipts']))

    def test_judge_does_not_echo_forged_workflow_assessment(self):
        record,p=self.saved()
        record['trace']['assessment']='SOURCE_QUALITY_FAILURE'
        record['manifest']['trace_sha256']=sha(canonical(record['trace']))
        result=review(record,p)
        self.assertEqual((result['decision'],result['reason']),('ABSTAIN','INVALID_EVIDENCE'))

    def test_inconsistent_reconciliation_cannot_be_approved(self):
        record,p=self.saved()
        for field,value in [('actual',-1),('passed',False),('expected',999),('check','wrong')]:
            forged=deepcopy(record);batch=forged['trace']['steps'][1]
            batch['report']['reconciliation'][0][field]=value
            batch['report_sha256']=sha(canonical(batch['report']))
            forged['manifest']['trace_sha256']=sha(canonical(forged['trace']))
            self.assertEqual(review(forged,p)['reason'],'INVALID_EVIDENCE')

    def test_report_hash_and_workflow_path_are_verified(self):
        record,p=self.saved()
        for mutation in ['report','path','source','trace']:
            forged=deepcopy(record)
            if mutation=='report':forged['trace']['steps'][0]['report_sha256']='b'*64
            if mutation=='path':forged['trace']['steps'][0]['tool']='run_batch'
            if mutation=='source':forged['trace']['source_sha256']='b'*64
            if mutation!='trace':forged['manifest']['trace_sha256']=sha(canonical(forged['trace']))
            else:forged['manifest']['trace_sha256']='b'*64
            self.assertEqual(review(forged,p)['reason'],'INVALID_EVIDENCE')

    def test_missing_batch_or_inconsistent_impact_abstains(self):
        record,p=self.saved(transform='exclude_first')
        for mutation in ['missing','impact','status','source','checks']:
            forged=deepcopy(record)
            if mutation=='missing':forged['trace']['steps']=forged['trace']['steps'][:1]
            elif mutation=='impact':forged['trace']['steps'][-1]['report']['potential_downstream']=[]
            elif mutation=='status':forged['trace']['steps'][1]['report']['status']='PASS'
            elif mutation=='source':forged['trace']['steps'][1]['report']['source_check']['row_count']=999
            else:forged['trace']['steps'][1]['report']['reconciliation']=[]
            for step in forged['trace']['steps']:step['report_sha256']=sha(canonical(step['report']))
            forged['manifest']['trace_sha256']=sha(canonical(forged['trace']))
            self.assertEqual(review(forged,p)['reason'],'INVALID_EVIDENCE')

    def test_pure_judge_rejects_cross_context_and_missing_record_keys(self):
        record,p=self.saved()
        self.assertEqual(review(dict(record,run_id=RUN),p)['reason'],'INVALID_EVIDENCE')
        forged=deepcopy(record);del forged['trace']['steps'][0]['report']['source_sha256']
        forged['manifest']['trace_sha256']=sha(canonical(forged['trace']))
        self.assertEqual(review(forged,p)['reason'],'INVALID_EVIDENCE')

    def test_cli_accept_reject_and_malformed_message(self):
        record,p=self.saved();file=Path(self.temp.name)/'proposal.json'
        def invoke():
            out,err=io.StringIO(),io.StringIO()
            with redirect_stdout(out),redirect_stderr(err):
                code=main(['review-investigation','--db',str(self.path),'--proposal',str(file)])
            return code,out.getvalue(),err.getvalue()
        file.write_bytes(encode('proposal',p));code,out,_=invoke()
        self.assertEqual((code,json.loads(out)['verdict']['decision']),(0,'ACCEPT'))
        p['assessment']='SOURCE_QUALITY_FAILURE';file.write_bytes(encode('proposal',p));code,out,_=invoke()
        self.assertEqual((code,json.loads(out)['verdict']['decision']),(1,'REJECT'))
        file.write_bytes(b'{"api_key":"private-value"}');code,out,err=invoke()
        self.assertEqual((code,out),(2,''));self.assertNotIn('private-value',err)
        self.assertNotIn(str(file),err)
