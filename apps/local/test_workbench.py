# SPDX-License-Identifier: Apache-2.0
from http.client import HTTPConnection
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from workbench import Workbench, make_server

class WorkbenchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.w=Workbench(self.tmp.name,'/missing')
 def test_failure_is_sanitized_and_restart_preserves_outcome(self):
  self.w.run();self.assertEqual(self.w.snapshot()['status'],'FAILED')
  self.assertNotIn('/missing',str(self.w.snapshot()))
  self.assertEqual(Workbench(self.tmp.name,'/missing').snapshot()['status'],'FAILED')
 def test_interruption_is_not_resumed(self):
  self.w.state['status']='RUNNING';self.w.save()
  restored=Workbench(self.tmp.name,'/missing')
  self.assertEqual(restored.snapshot()['status'],'INTERRUPTED')
 def test_single_owner_and_detached_snapshot(self):
  with patch('workbench.Thread'):
   self.assertTrue(self.w.start());self.assertFalse(self.w.start())
  s=self.w.snapshot();s['status']='forged'
  self.assertEqual(self.w.snapshot()['status'],'RUNNING')
 def test_http_auth_origin_host_and_body_boundaries(self):
  server=make_server(self.w,'test-local-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def call(path='/',method='GET',headers=None,body=None):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=2)
    c.request(method,path,body=body,headers=headers or {});r=c.getresponse();value=(r.status,r.read(),dict(r.getheaders()));c.close();return value
   self.assertEqual(call()[0],200)
   self.assertEqual(call('/api/state')[0],403)
   auth={'Authorization':'Bearer test-local-token'}
   self.assertEqual(call('/api/state',headers=auth)[0],200)
   self.assertEqual(call('/api/state',headers={**auth,'Origin':'https://evil.invalid'})[0],403)
   self.assertEqual(call(headers={'Host':'evil.invalid'})[0],403)
   self.assertEqual(call('/api/run','POST',auth,b'input')[0],403)
   with patch('workbench.Thread'):
    self.assertEqual(call('/api/run','POST',auth)[0],202)
    self.assertEqual(call('/api/run','POST',auth)[0],409)
   self.assertEqual(call('/../workbench.py')[0],403)
   self.assertIn("frame-ancestors 'none'",call()[2]['Content-Security-Policy'])
  finally:server.shutdown();server.server_close();thread.join()

 def test_scenario_selection_history_and_restart(self):
  with patch('workbench.Thread'):
   self.assertTrue(self.w.start('transformation'))
   first=self.w.snapshot()['run_id']
   self.assertEqual(self.w.snapshot()['scenario'],'transformation')
   self.w.state['status']='COMPLETED';self.w.save()
   self.assertTrue(self.w.start('null_total'))
   self.assertEqual(self.w.snapshot()['history'][0]['run_id'],first)
   self.assertEqual(self.w.snapshot()['history'][0]['scenario'],'transformation')
  reopened=Workbench(self.tmp.name,'/missing')
  self.assertEqual(reopened.snapshot()['status'],'INTERRUPTED')
  self.assertEqual(reopened.snapshot()['history'][0]['run_id'],first)
  with self.assertRaises(ValueError): self.w.start('../arbitrary')
 def test_history_capacity_and_verified_result_persistence(self):
  result={'cases':[{'case':'clean'}], 'references':[]}
  with patch('workbench.Thread'):
   for i in range(23):
    self.w.start('clean');self.w.state.update(status='COMPLETED',result=result);self.w.save()
  self.assertEqual(len(self.w.snapshot()['history']),20)
  detached=self.w.snapshot();detached['history'][0]['result']['cases'].clear()
  self.assertEqual(len(self.w.snapshot()['history'][0]['result']['cases']),1)

 def test_transformation_retrieves_the_matching_contract(self):
  self.w.state['scenario']='transformation'
  with patch('workbench.qualify',return_value={'cases':[], 'write_denials':3}):
   self.w.run()
  self.assertEqual(self.w.snapshot()['status'],'COMPLETED')
  self.assertEqual(self.w.snapshot()['result']['references'][0]['source'],'reconciliation-contract')
  self.assertNotIn('detected',self.w.snapshot()['events'][2]['description'])
 def test_real_csv_upload_retains_evidence_and_finds_actual_records(self):
  from aegisflow_dr.pipeline import generate_orders
  for fault,expected in [('clean','NO_FAILURE_OBSERVED'),('null_total','SOURCE_QUALITY_FAILURE'),('duplicate_order','SOURCE_QUALITY_FAILURE')]:
   self.w.state.update(scenario='upload',run_id='upload-'+fault)
   self.w.run(generate_orders(fault=fault))
   snapshot=self.w.snapshot()
   self.assertEqual(snapshot['status'],'COMPLETED')
   case=snapshot['result']['cases'][0]
   self.assertEqual(case['assessment'],expected)
   self.assertIsNotNone(case['retained_run_id'])
   if fault=='null_total':self.assertEqual(case['source_report']['findings'][0]['record_numbers'],[1])
   self.assertIsNone(snapshot['result']['write_denials'])
  self.assertTrue((self.w.root/'evidence.db').is_file())
 def test_invalid_csv_and_upload_admission_bounds(self):
  for raw in (b'',b'x'*1000001,None):
   with self.assertRaises(ValueError):self.w.start('upload',raw)
  self.w.state.update(scenario='upload',run_id='malformed')
  self.w.run(b'\xff\xfe')
  self.assertEqual(self.w.snapshot()['status'],'FAILED')
 def test_page_routes_and_authenticated_csv_transport(self):
  server=make_server(self.w,'local-csv-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def call(path,method='GET',body=None,headers=None):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
    c.request(method,path,body=body,headers=headers or {});r=c.getresponse();status=r.status;r.read();c.close();return status
   for page in ('/overview','/sources','/presentation.js','/knowledgebase.js','/investigations','/activity','/knowledge','/history','/i18n.js'):
    self.assertEqual(call(page),200)
   self.assertEqual(call('/api/inspect','POST',b'csv',{'Content-Type':'text/csv'}),403)
   auth={'Authorization':'Bearer local-csv-token','Content-Type':'text/csv'}
   self.assertEqual(call('/api/inspect','POST',b'',auth),413)
   self.assertEqual(call('/api/inspect','POST',b'data',{**auth,'Content-Type':'application/json'}),403)
   self.assertEqual(call('/api/inspect','POST',b'data',{**auth,'Origin':'https://evil.invalid'}),403)
   with patch('workbench.Thread'):
    self.assertEqual(call('/api/inspect','POST',b'order_id,customer_id,order_total\n',auth),202)
    self.assertEqual(self.w.snapshot()['scenario'],'upload')
    self.assertEqual(call('/api/inspect','POST',b'order_id,customer_id,order_total\n',auth),409)
  finally:server.shutdown();server.server_close();thread.join()

 def test_upload_requires_independent_judge_acceptance(self):
  from aegisflow_dr.pipeline import generate_orders
  self.w.state.update(scenario='upload',run_id='rejected-upload')
  with patch('workbench.review',return_value={'decision':'REJECT'}):
   self.w.run(generate_orders())
  self.assertEqual(self.w.snapshot()['status'],'FAILED')
  self.assertIsNone(self.w.snapshot()['result'])


class WorkflowTests(unittest.TestCase):
 DRIFT=b'order_id,customer_id,total_amount\nA1,C1,10.00\nA2,C2,5.50\n'
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.w=Workbench(self.tmp.name,'/missing')
 def inspect(self,fault):
  from aegisflow_dr.pipeline import generate_orders
  self.w.state.update(scenario='upload',run_id='run-'+fault)
  self.w.run(generate_orders(fault=fault),{'kind':'synthetic_sample','fault':fault})
  return self.w.snapshot()
 def test_failed_source_plan_explains_each_skipped_blocked_and_pending_step(self):
  plan={s['id']:s for s in self.inspect('duplicate_order')['result']['plan']}
  self.assertEqual(plan['reconciliation']['status'],'skipped')
  self.assertEqual(plan['reconciliation']['reason'],'SOURCE_QUALITY_FAILURE')
  self.assertEqual(plan['verification']['status'],'completed')
  self.assertEqual(plan['human_review']['status'],'awaiting')
  self.assertEqual((plan['root_cause']['status'],plan['root_cause']['reason']),('unavailable','NO_MODEL_CONFIGURED'))
  self.assertEqual((plan['remediation']['status'],plan['remediation']['reason']),('disabled','READ_ONLY_POLICY'))
  self.assertEqual(plan['impact']['depends_on'],['contract_check'])
 def test_clean_source_runs_reconciliation_and_needs_no_review(self):
  result=self.inspect('clean')['result']
  plan={s['id']:s for s in result['plan']}
  self.assertEqual(plan['reconciliation']['status'],'completed')
  self.assertEqual(plan['human_review']['status'],'skipped')
  self.assertEqual(result['cases'][0]['analysis']['actions'],[])
  self.assertEqual(result['finding_references'],{})
 def test_each_finding_class_gets_a_verified_revision_bound_reference(self):
  result=self.inspect('duplicate_order')['result']
  reference=result['finding_references']['unique'][0]
  self.assertEqual(reference['source'],'duplicate-guidance')
  self.assertTrue(self.w.knowledge.verify('local',reference['citation_sha256'],allowed_sources=frozenset({'duplicate-guidance'})))
  drift=self.inspect('schema_drift')['result']['finding_references']
  self.assertEqual({k:v[0]['source'] for k,v in drift.items()},{'missing_column':'schema-contract','unexpected_column':'schema-contract'})
 def test_review_records_a_human_decision_without_touching_data_and_survives_restart(self):
  snapshot=self.inspect('null_total')
  action=snapshot['result']['cases'][0]['analysis']['actions'][0]
  self.w.review('run-null_total',action['id'],'accepted')
  reopened=Workbench(self.tmp.name,'/missing')
  decision=reopened.snapshot()['reviews']['run-null_total'][action['id']]
  self.assertEqual((decision['decision'],decision['reviewer']),('accepted','local-user'))
  for run,act,choice,error in (('run-null_total','ACT-99','accepted',KeyError),('nope',action['id'],'accepted',KeyError),
                               ('run-null_total',action['id'],'approve_and_apply',ValueError)):
   with self.assertRaises(error):self.w.review(run,act,choice)
 def test_reviews_are_pruned_to_retained_runs(self):
  self.inspect('null_total');self.w.review('run-null_total','ACT-01','dismissed')
  with patch('workbench.Thread'):
   for i in range(22):
    self.w.state.update(status='COMPLETED',result={'cases':[]});self.w.start('clean')
  self.assertNotIn('run-null_total',self.w.snapshot()['reviews'])
 def test_http_discovery_mapping_samples_and_review_boundaries(self):
  server=make_server(self.w,'workflow-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def call(path,method='POST',body=None,headers=None):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
    c.request(method,path,body=body,headers=headers or {});r=c.getresponse();value=(r.status,r.read());c.close();return value
   csv={'Authorization':'Bearer workflow-token','Content-Type':'text/csv'}
   self.assertEqual(call('/api/discover',body=self.DRIFT,headers={'Content-Type':'text/csv'})[0],403)
   status,body=call('/api/discover',body=self.DRIFT,headers=csv)
   self.assertEqual(status,200);found=__import__('json').loads(body)
   self.assertEqual(found['status'],'MAPPING_NEEDED')
   self.assertEqual(call('/api/discover',body=b'a,a\n1,2\n',headers=csv)[0],422)
   self.assertEqual(self.w.snapshot()['status'],'IDLE')
   with patch('workbench.Thread'):
    bad={**csv,'X-Column-Mapping':'{"total_amount":"nonsense"}'}
    self.assertEqual(call('/api/inspect',body=self.DRIFT,headers=bad)[0],422)
    self.assertEqual(call('/api/inspect',body=self.DRIFT,headers={**csv,'X-Column-Mapping':'not json'})[0],400)
    self.assertEqual(call('/api/inspect',body=self.DRIFT,headers={**csv,'X-Column-Mapping':'{"total_amount":"order_total"}','X-Source-Name':'q3<x>.csv'})[0],202)
    self.assertEqual(self.w.snapshot()['meta']['mapping'],{'total_amount':'order_total'})
    self.assertEqual(self.w.snapshot()['meta']['name'],'q3x.csv')
    self.w.state['status']='COMPLETED'
    self.assertEqual(call('/api/sample/duplicate_order',headers={'Authorization':'Bearer workflow-token'})[0],202)
    self.assertEqual(self.w.snapshot()['meta']['kind'],'synthetic_sample')
    self.w.state['status']='COMPLETED'
    self.assertEqual(call('/api/sample/../../etc',headers={'Authorization':'Bearer workflow-token'})[0],403)
    self.assertEqual(call('/api/sample/clean')[0],403)
   js={'Authorization':'Bearer workflow-token','Content-Type':'application/json'}
   self.assertEqual(call('/api/review',body=b'{"run_id":"x","action_id":"y","decision":"accepted"}',headers=js)[0],404)
   self.assertEqual(call('/api/review',body=b'[]',headers=js)[0],400)
   self.assertEqual(call('/api/review',body=b'{}',headers={**js,'Content-Type':'text/csv'})[0],403)
   self.assertEqual(call('/api/review',body=b'x'*2000,headers=js)[0],413)
  finally:server.shutdown();server.server_close();thread.join()
 def test_http_connected_sources_are_read_only_listed_and_inspected(self):
  import json,sqlite3
  from pathlib import Path
  from aegisflow_dr.connectors import SourceCatalog
  src=Path(self.tmp.name)/'sources';src.mkdir()
  (src/'orders.csv').write_bytes(self.DRIFT)
  db=sqlite3.connect(src/'shop.sqlite');db.execute('CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_total TEXT)')
  db.executemany('INSERT INTO orders VALUES (?,?,?)',[('A1','C1','10.00'),('A1','C1','10.00'),('A2','C2','')]);db.commit();db.close()
  before=(src/'shop.sqlite').read_bytes()
  server=make_server(self.w,'connect-token',catalog=SourceCatalog(src));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  bare=make_server(self.w,'connect-token');bare_thread=Thread(target=bare.serve_forever,daemon=True);bare_thread.start()
  try:
   def call(path,method='POST',body=None,headers=None,port=None):
    c=HTTPConnection('127.0.0.1',port or server.server_port,timeout=3)
    c.request(method,path,body=body,headers=headers or {});r=c.getresponse();value=(r.status,r.read());c.close();return value
   auth={'Authorization':'Bearer connect-token'};js={**auth,'Content-Type':'application/json'}
   self.assertEqual(call('/api/sources','GET',headers={'Host':'evil'})[0],403)
   self.assertEqual(call('/api/sources','GET')[0],403)
   listing=json.loads(call('/api/sources','GET',headers=auth)[1])
   self.assertEqual((listing['configured'],[s['id'] for s in listing['sources']]),(True,['orders.csv','shop.sqlite']))
   self.assertEqual(json.loads(call('/api/sources','GET',headers=auth,port=bare.server_port)[1]),{'configured':False,'sources':[]})
   self.assertEqual(call('/api/source/tables',body=b'{"source":"x"}',headers=js,port=bare.server_port)[0],422)
   tables=json.loads(call('/api/source/tables',body=b'{"source":"shop.sqlite"}',headers=js)[1])
   self.assertEqual(tables['tables'][0]['rows'],3)
   found=json.loads(call('/api/source/discover',body=b'{"source":"shop.sqlite","table":"orders"}',headers=js)[1])
   self.assertEqual((found['status'],found['provenance']['connector']),('COMPATIBLE',"sqlite"))
   self.assertEqual(call('/api/source/discover',body=b'{"source":"../etc/passwd"}',headers=js)[0],422)
   self.assertEqual(call('/api/source/inspect',body=b'{"table":"orders"}',headers=js)[0],400)
   self.assertEqual(call('/api/source/inspect',body=b'{"source":"shop.sqlite","table":"orders","mapping":{"zz":"order_total"}}',headers=js)[0],422)
   with patch('workbench.Thread'):
    self.assertEqual(call('/api/source/inspect',body=b'{"source":"shop.sqlite","table":"orders"}',headers=js)[0],202)
    meta=self.w.snapshot()['meta'];self.assertEqual((meta['kind'],meta['name']),('connected','shop.sqlite:orders'))
    self.assertEqual(meta['provenance']['total_rows'],3)
    self.w.state['status']='COMPLETED'
    self.assertEqual(call('/api/source/inspect',body=b'{"source":"orders.csv","mapping":{"total_amount":"order_total"}}',headers=js)[0],202)
    self.assertEqual(self.w.snapshot()['meta']['mapping'],{'total_amount':'order_total'})
   self.w.state['status']='IDLE'
   self.assertEqual(call('/api/source/tables',body=b'{"source":"shop.sqlite"}',headers={**auth,'Content-Type':'text/csv'})[0],403)
   self.assertEqual((src/'shop.sqlite').read_bytes(),before)
  finally:
   for s,t in ((server,thread),(bare,bare_thread)):s.shutdown();s.server_close();t.join()
 def test_connected_run_is_labelled_connected_source(self):
  from aegisflow_dr.pipeline import generate_orders
  meta={'kind':'connected','name':'shop.sqlite:orders'}
  self.w.state.update(scenario='upload',run_id='run-conn',meta=meta)
  self.w.run(generate_orders(fault='clean'),meta)
  self.assertEqual(self.w.snapshot()['result']['source'],'connected-source')
 def test_snapshot_reports_drift_across_retained_runs(self):
  from aegisflow_dr.pipeline import generate_orders
  meta={'kind':'synthetic_sample','name':'synthetic-clean'}
  self.assertEqual(self.w.snapshot()['monitoring']['streams'],[])
  self.w.state.update(scenario='upload',run_id='run-a',meta=meta);self.w.run(generate_orders(fault='clean'),meta)
  with patch('workbench.Thread'):
   self.w.start('upload',generate_orders(fault='duplicate_order'),meta)
  self.w.run(generate_orders(fault='duplicate_order'),meta)
  stream=self.w.snapshot()['monitoring']['streams'][0]
  self.assertEqual((len(stream['runs']),stream['status']),(2,'DEGRADED'))
 def test_snapshot_links_similar_earlier_inspections(self):
  from aegisflow_dr.pipeline import generate_orders
  meta={'kind':'synthetic_sample','name':'synthetic-null_total'}
  self.assertEqual(self.w.snapshot()['similar']['matches'],{})
  self.w.state.update(scenario='upload',run_id='run-a',meta=meta);self.w.run(generate_orders(fault='null_total'),meta)
  with patch('workbench.Thread'):
   self.w.start('upload',generate_orders(fault='null_total'),meta)
  self.w.run(generate_orders(fault='null_total'),meta)
  snap=self.w.snapshot()
  matches=snap['similar']['matches'][snap['run_id']]
  self.assertEqual((len(matches),matches[0]['score']),(1,1.0))
 def test_http_evaluation_is_authorized_and_reports_all_splits(self):
  import json
  server=make_server(self.w,'eval-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def get(headers):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=30);c.request('GET','/api/evaluation',headers=headers);r=c.getresponse();value=(r.status,r.read());c.close();return value
   self.assertEqual(get({})[0],403)
   status,body=get({'Authorization':'Bearer eval-token'})
   report=json.loads(body)
   self.assertEqual(status,200)
   self.assertTrue(report['heldout_evaluated'] and report['leakage']['clean'])
   self.assertEqual(set(report['results']['diagnose_csv']),{'development','validation','heldout'})
   self.assertEqual(self.w.snapshot()['status'],'IDLE')
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_capabilities_are_authorized_and_honest_about_coverage(self):
  import json
  server=make_server(self.w,'cap-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def get(headers):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('GET','/api/capabilities',headers=headers);r=c.getresponse();value=(r.status,r.read());c.close();return value
   self.assertEqual(get({})[0],403)
   status,body=get({'Authorization':'Bearer cap-token'});report=json.loads(body)
   self.assertEqual((status,report['total'],report['counts']['planned']),(200,36,18))
   self.assertEqual({r['agent_id']:r['status'] for r in report['roles']}['A23'],'unavailable')
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_knowledge_base_add_search_remove_and_refusals(self):
  import json
  server=make_server(self.w,'kb-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  auth={'Authorization':'Bearer kb-token'}
  def call(method,path,body=None,headers=None,mime='application/json'):
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
   h=dict(auth if headers is None else headers)
   data=None if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
   if data is not None:
    h.update({'Content-Type':mime,'Content-Length':str(len(data))})
   c.request(method,path,body=data,headers=h);r=c.getresponse();value=(r.status,json.loads(r.read() or b'{}'));c.close();return value
  try:
   self.assertEqual(call('GET','/api/knowledge',headers={})[0],403)
   self.assertEqual(call('POST','/api/knowledge/add',{'name':'x','text':'y'},headers={})[0],403)
   self.assertEqual(call('POST','/api/knowledge/add',b'{}',mime='text/plain')[0],403)
   status,listing=call('GET','/api/knowledge')
   self.assertEqual((status,len(listing['documents']),listing['limits']['documents']),(200,6,50))
   status,added=call('POST','/api/knowledge/add',{'name':'Gecikme Notu','text':'Ödeme gecikmeleri üç iş günü sürebilir.'})
   self.assertEqual((status,added['status'],added['source']),(200,'added','gecikme-notu'))
   self.assertEqual(call('GET','/api/knowledge')[1]['documents'][-1]['source'],'gecikme-notu')
   status,found=call('POST','/api/knowledge/search',{'query':'ödeme gecikmeleri'})
   self.assertEqual((status,found['results'][0]['source'],found['results'][0]['verified']),(200,'gecikme-notu',True))
   self.assertEqual(call('POST','/api/knowledge/add',{'name':'Schema Contract','text':'x'})[0],422)
   self.assertEqual(call('POST','/api/knowledge/add',{'name':'ok','text':''})[0],422)
   self.assertEqual(call('POST','/api/knowledge/add',[1])[0],400)
   self.assertEqual(call('POST','/api/knowledge/search',{'query':'ok','limit':'x'})[0],422)
   self.assertEqual(call('POST','/api/knowledge/search',{'query':''})[0],422)
   self.assertEqual(call('POST','/api/knowledge/remove',{'source':'gecikme-notu'})[0],200)
   self.assertEqual(call('POST','/api/knowledge/remove',{'source':'gecikme-notu'})[0],422)
   self.assertEqual(len(call('GET','/api/knowledge')[1]['documents']),6)
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_profile_finds_injected_faults_and_refuses_bad_requests(self):
  import json
  server=make_server(self.w,'pf-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  def call(body,headers=None,mime='text/csv',length=None):
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
   h={'Authorization':'Bearer pf-token'} if headers is None else dict(headers)
   h.update({'Content-Type':mime,'Content-Length':str(len(body) if length is None else length)})
   c.request('POST','/api/profile',body=body,headers=h);r=c.getresponse();value=(r.status,json.loads(r.read() or b'{}'));c.close();return value
  rows=['ts,temp']+['2026-01-01T00:%02d:%02d,%.3f'%(i//60,i%60,20+i*0.01+(0.1 if i%2 else -0.1)) for i in range(60)]
  rows[31]='2026-01-01T00:00:30,29.900'
  try:
   status,report=call(('\n'.join(rows)+'\n').encode())
   self.assertEqual((status,report['status'],report['time_column'],report['records']),(200,'FINDINGS',"ts",60))
   self.assertIn(('outlier','temp',[31]),[(f['check'],f['column'],f['records']) for f in report['findings']])
   self.assertEqual(call(b'a\n1\n',headers={})[0],403)
   self.assertEqual(call(b'a\n1\n',mime='application/json')[0],403)
   self.assertEqual(call(b'a,a\n1,2\n')[0],422)
   self.assertEqual(call(b'\xff\xfe')[0],422)
   self.assertEqual(call(b'a\n1\n',length=1000001)[0],413)
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_baseline_script_is_served_as_javascript(self):
  server=make_server(self.w,'bl-static-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=3);c.request('GET','/baseline.js');r=c.getresponse();body=r.read();c.close()
   self.assertEqual(r.status,200)
   self.assertEqual(r.getheader('Content-Type'),'text/javascript')
   self.assertIn(b'function baselinePanel',body)
  finally:server.shutdown();server.server_close();thread.join()
 def test_http_baselines_save_compare_remove_and_refusals(self):
  import json
  server=make_server(self.w,'bl-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  auth={'Authorization':'Bearer bl-token'}
  def call(method,path,body=None,headers=None,mime='application/json'):
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
   h=dict(auth if headers is None else headers)
   data=None if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
   if data is not None:
    h.update({'Content-Type':mime,'Content-Length':str(len(data))})
   c.request(method,path,body=data,headers=h);r=c.getresponse();value=(r.status,json.loads(r.read() or b'{}'));c.close();return value
  def oversize(path,length):
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.putrequest('POST',path)
   for k,v in {**auth,'Content-Type':'application/json','Content-Length':str(length)}.items():c.putheader(k,v)
   c.endheaders();r=c.getresponse();r.read();c.close();return r.status
  ref='ts,v\n2026-01-01T00:00:00,1\n2026-01-01T01:00:00,2\n2026-01-01T02:00:00,3\n'
  try:
   self.assertEqual(call('GET','/api/baselines',headers={})[0],403)
   self.assertEqual(call('POST','/api/baselines/save',{'name':'a','references':[ref]},headers={})[0],403)
   self.assertEqual(call('POST','/api/baselines/save',b'{}',mime='text/plain')[0],403)
   self.assertEqual(call('GET','/api/baselines')[1],{'baselines':[],'rejected_on_load':False})
   status,saved=call('POST','/api/baselines/save',{'name':'Orders','references':[ref],'freshness_sla_seconds':7200})
   self.assertEqual((status,saved['name'],saved['records']),(200,'orders',3))
   self.assertEqual(call('GET','/api/baselines')[1]['baselines'],[saved])
   self.assertEqual(call('POST','/api/baselines/save',{'name':'orders','references':[ref]})[0],422)
   self.assertEqual(call('POST','/api/baselines/save',{'name':'orders','references':[ref],'replace':True})[0],200)
   status,body=call('POST','/api/baselines/save',{'name':'bad name!','references':'x'})
   self.assertEqual((status,body['error']),(422,'INPUT_REJECTED'));self.assertTrue(body['message'])
   status,result=call('POST','/api/baselines/compare',{'name':'orders','csv':'ts,v\n2026-01-02T00:00:00,1\n','as_of':'2026-01-02T00:00:00'})
   self.assertEqual((status,result['name']),(200,'orders'));self.assertIn('status',result)
   self.assertEqual(call('POST','/api/baselines/compare',{'name':'orders','csv':'ts,v\n','as_of':'junk'})[0],422)
   self.assertEqual(call('POST','/api/baselines/compare',{'name':'nope','csv':ref}),(404,{'error':'NOT_FOUND'}))
   self.assertEqual(call('POST','/api/baselines/remove',{'name':'nope'}),(404,{'error':'NOT_FOUND'}))
   self.assertEqual(call('POST','/api/baselines/remove',[1])[0],400)
   self.assertEqual(call('POST','/api/baselines/save',b'not json')[0],400)
   self.assertEqual(call('POST','/api/baselines/compare',{'name':'orders','csv':ref,'as_of':5})[0],422)
   self.assertEqual(call('POST','/api/baselines/remove',{'name':'orders'}),(200,{'removed':'orders'}))
   self.assertEqual(call('GET','/api/baselines')[1]['baselines'],[])
   self.assertEqual(oversize('/api/baselines/remove',2049),413)
   self.assertEqual(oversize('/api/baselines/compare',1100001),413)
   self.assertEqual(oversize('/api/baselines/save',5300001),413)
  finally:server.shutdown();server.server_close();thread.join()

 def test_http_schema_registry_register_contract_drift_and_refusals(self):
  import json
  server=make_server(self.w,'sr-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  auth={'Authorization':'Bearer sr-token'}
  def call(method,path,body=None,headers=None,mime='application/json'):
   c=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
   h=dict(auth if headers is None else headers)
   data=None if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
   if data is not None:
    h.update({'Content-Type':mime,'Content-Length':str(len(data))})
   c.request(method,path,body=data,headers=h);r=c.getresponse();value=(r.status,json.loads(r.read() or b'{}'));c.close();return value
  base=[{'name':'order_id','type':'integer'},{'name':'order_total','type':'decimal'}]
  try:
   self.assertEqual(call('GET','/api/schemas',headers={})[0],403)
   self.assertEqual(call('POST','/api/schemas/register',{'subject':'o','columns':base},headers={})[0],403)
   self.assertEqual(call('POST','/api/schemas/register',b'{}',mime='text/plain')[0],403)
   self.assertEqual(call('GET','/api/schemas')[1],{'subjects':[],'rejected_on_load':False})
   status,first=call('POST','/api/schemas/register',{'subject':'orders','columns':base})
   self.assertEqual((status,first['version'],first['created'],first['drift']['status']),(200,1,True,'NO_CONTRACT'))
   self.assertEqual(call('POST','/api/schemas/contract',{'subject':'orders','version':1})[1],{'subject':'orders','contract':1})
   widened=[{'name':'order_id','type':'text'},base[1]]
   status,second=call('POST','/api/schemas/register',{'subject':'orders','columns':widened})
   self.assertEqual((status,second['version'],second['drift']['status']),(200,2,'DRIFT_BREAKING'))
   self.assertEqual(second['diff']['widened'][0]['name'],'order_id')
   status,listing=call('GET','/api/schemas')
   self.assertEqual([(x['subject'],x['versions'],x['contract']) for x in listing['subjects']],[('orders',2,1)])
   self.assertEqual(call('POST','/api/schemas/register',{'subject':'bad name','columns':base})[0],422)
   self.assertEqual(call('POST','/api/schemas/register',{'subject':'orders','columns':[]})[0],422)
   self.assertEqual(call('POST','/api/schemas/contract',{'subject':'orders','version':9})[0],422)
   self.assertEqual(call('POST','/api/schemas/contract',{'subject':'nope','version':1})[0],422)
   self.assertEqual(call('POST','/api/schemas/register',[1])[0],400)
   self.assertEqual(call('POST','/api/schemas/register',b'not json')[0],400)
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_passage_report_is_authorized_and_synthetic(self):
  import json
  server=make_server(self.w,'psg-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def get(headers):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('GET','/api/passages',headers=headers);r=c.getresponse();value=(r.status,r.read());c.close();return value
   self.assertEqual(get({})[0],403)
   status,body=get({'Authorization':'Bearer psg-token'});report=json.loads(body)
   self.assertEqual((status,report['synthetic'],report['queries_per_group']),(200,True,96))
   self.assertEqual(report['groups']['4_distinctive_words']['passage_level']['right_passage_first']['numerator'],96)
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_retrieval_report_is_authorized_and_measured(self):
  import json
  server=make_server(self.w,'ret-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def get(headers):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('GET','/api/retrieval',headers=headers);r=c.getresponse();value=(r.status,r.read());c.close();return value
   self.assertEqual(get({})[0],403)
   status,body=get({'Authorization':'Bearer ret-token'});report=json.loads(body)
   self.assertEqual((status,report['queries'],report['authored_with_corpus_in_view']),(200,32,True))
   self.assertEqual(report['groups']['out_of_scope']['false_retrieval']['numerator'],0)
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_platform_map_is_authorized_and_claims_nothing_live(self):
  import json
  server=make_server(self.w,'plat-token');thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   def get(headers):
    c=HTTPConnection('127.0.0.1',server.server_port,timeout=5);c.request('GET','/api/platform',headers=headers);r=c.getresponse();value=(r.status,r.read());c.close();return value
   self.assertEqual(get({})[0],403)
   status,body=get({'Authorization':'Bearer plat-token'});report=json.loads(body)
   self.assertEqual((status,report['total'],report['live'],report['counts']['not_implemented']),(200,10,0,0))
   self.assertEqual({c['id']:c['status'] for c in report['components']}['CAG'],'partial')
  finally:
   server.shutdown();server.server_close();thread.join()
 def test_http_compare_sources_is_read_only_masked_and_flags_sampling(self):
  import json,sqlite3
  from pathlib import Path
  from unittest import mock
  from aegisflow_dr import connectors
  from aegisflow_dr.connectors import SourceCatalog
  src=Path(self.tmp.name)/'cmp';src.mkdir()
  (src/'a.csv').write_bytes(b'order_id,customer_id,order_total\nORDER-0001,C1,10.00\nORDER-0002,C1,5\nORDER-0003,C9,1\n')
  db=sqlite3.connect(src/'b.sqlite');db.execute('CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_total TEXT)')
  db.executemany('INSERT INTO orders VALUES (?,?,?)',[('ORDER-0001','C1','10'),('ORDER-0002','C2','5.00'),('ORDER-0004','C1','2')]);db.commit();db.close()
  before=(src/'a.csv').read_bytes(),(src/'b.sqlite').read_bytes()
  server=make_server(self.w,'cmp-token',catalog=SourceCatalog(src));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  bare=make_server(self.w,'cmp-token');bare_thread=Thread(target=bare.serve_forever,daemon=True);bare_thread.start()
  try:
   def post(body,port=None,headers=None):
    c=HTTPConnection('127.0.0.1',port or server.server_port,timeout=3);c.request('POST','/api/source/compare',body=body,headers=headers or {'Authorization':'Bearer cmp-token','Content-Type':'application/json'});r=c.getresponse();value=(r.status,r.read());c.close();return value
   good=json.dumps({'first':{'source':'a.csv'},'second':{'source':'b.sqlite','table':'orders'}}).encode()
   status,body=post(good);report=json.loads(body)
   self.assertEqual(status,200)
   self.assertEqual((report['identical'],report['differing'],report['only_in_first'],report['only_in_second'],report['complete']),(1,1,1,1,True))
   self.assertNotIn('ORDER-0001',body.decode());self.assertEqual(report['samples']['differing'][0]['columns'],['customer_id'])
   self.assertEqual(report['provenance']['second']['connector'],'sqlite')
   self.assertEqual((report['cardinality']['shared_keys'],report['cardinality']['join_rows'],report['cardinality']['fan_out']),(2,2,False))
   with mock.patch.object(connectors,'MAX_ROWS',2):
    self.assertFalse(json.loads(post(good)[1])['complete'])
   self.assertEqual(post(good,headers={'Content-Type':'application/json'})[0],403)
   self.assertEqual(post(good,port=bare.server_port)[0],422)
   self.assertEqual(post(json.dumps({'first':{'source':'../x'},'second':{'source':'a.csv'}}).encode())[0],422)
   self.assertEqual(post(json.dumps({'first':{'source':'a.csv'}}).encode())[0],400)
   self.assertEqual(post(b'[1]')[0],400)
   self.assertEqual(((src/'a.csv').read_bytes(),(src/'b.sqlite').read_bytes()),before)
   self.assertEqual(self.w.snapshot()['status'],'IDLE')
  finally:
   for s,t in ((server,thread),(bare,bare_thread)):s.shutdown();s.server_close();t.join()
