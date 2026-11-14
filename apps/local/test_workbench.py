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
