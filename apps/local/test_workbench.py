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
   for page in ('/overview','/investigations','/activity','/knowledge','/history','/i18n.js'):
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
