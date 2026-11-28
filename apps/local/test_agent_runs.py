# SPDX-License-Identifier: Apache-2.0
"""Run manager and the agent-flow HTTP endpoints: one run at a time, bounded history, SSE framing and resume,
authorization, malformed bodies and owner-only state files."""
import base64
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest

from agent_runs import RUN_FAILED, Busy, RunManager, knowledge_retriever, roles
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.agents.runtime import verify_record
from aegisflow_dr.pipeline import InputRejected, generate_orders
from baseline_store import BaselineStore
from workbench import AGENT_RUN_BODY_LIMIT, Workbench, make_server, secure_state_directory, write_private

ORDERS = generate_orders(rows=24)
DUPLICATES = generate_orders(rows=24, fault='duplicate_order')
TOKEN = 'test-local-token'


def event(seq, kind, data, agent='A01', t_ms=None):
    return {'seq': seq, 't_ms': seq if t_ms is None else t_ms, 'agent_id': agent, 'type': kind, 'data': data}


class GatedRunner:
    """A stand-in for run_case: emits run_started, waits for ``release``, then emits run_finished."""

    def __init__(self, *, fail=False, approvals=None):
        self.release, self.calls, self.fail, self.approvals = Event(), [], fail, approvals

    def __call__(self, case, *, model, cache, run_id, on_event, transport):
        self.calls.append({'case': case, 'model': model, 'run_id': run_id, 'transport': transport})
        on_event(event(1, 'run_started', {'run_id': run_id}))
        self.release.wait(5)
        if self.fail:
            raise RuntimeError('/secret/path exploded')
        on_event(event(2, 'run_finished', {'status': 'completed', 'duration_ms': 2, 'budget_exceeded': []}))
        return {'run_id': run_id, 'status': 'completed', 'approvals': self.approvals or []}


def finish(manager, run_id):
    for _ in range(200):
        if manager.detail(run_id)['state'] != 'running':
            return manager.detail(run_id)
        time.sleep(0.01)
    raise AssertionError('run did not finish')


def unreachable(url, body, timeout):
    raise ConnectionRefusedError('no model here')


class RunManagerTests(unittest.TestCase):
    def manager(self, runner=None, **kwargs):
        runner = runner or GatedRunner()
        return RunManager(runner=runner, model_factory=lambda: None, **kwargs), runner

    def test_one_run_at_a_time_and_busy_until_it_ends(self):
        manager, runner = self.manager()
        first = manager.start(ORDERS, name='orders.csv')
        self.assertRegex(first, r'^run-[0-9a-f]{24}$')
        with self.assertRaises(Busy):
            manager.start(ORDERS)
        self.assertEqual(manager.summaries()['active'], first)
        runner.release.set()
        detail = finish(manager, first)
        self.assertEqual((detail['state'], detail['status'], detail['events']), ('finished', 'completed', 2))
        self.assertEqual(detail['input']['name'], 'orders.csv')
        self.assertIsNone(manager.summaries()['active'])
        self.assertNotEqual(manager.start(ORDERS), first)
        self.assertEqual(runner.calls[0]['run_id'], first)
        self.assertEqual(runner.calls[0]['transport'], 'auto')

    def test_history_is_bounded_and_drops_the_oldest_finished_runs(self):
        runner = GatedRunner()
        runner.release.set()
        manager, _ = self.manager(runner, history=3)
        ids = []
        for _ in range(5):
            ids.append(manager.start(ORDERS))
            finish(manager, ids[-1])
        listed = [run['run_id'] for run in manager.summaries()['runs']]
        self.assertEqual(listed, list(reversed(ids[-3:])))
        with self.assertRaises(KeyError):
            manager.detail(ids[0])
        self.assertFalse(manager.exists(ids[0]))
        self.assertTrue(manager.exists(ids[-1]))

    def test_wait_returns_events_after_a_seq_and_resumes_without_repeats(self):
        manager, runner = self.manager()
        run_id = manager.start(ORDERS)
        events, done, _ = manager.wait(run_id, 0, 1)
        self.assertEqual(([e['seq'] for e in events], done), ([1], False))
        events, done, _ = manager.wait(run_id, 1, 0.05)  # nothing new yet: a heartbeat interval passes
        self.assertEqual((events, done), ([], False))
        runner.release.set()
        finish(manager, run_id)
        events, done, error = manager.wait(run_id, 1, 1)
        self.assertEqual(([e['seq'] for e in events], done, error), ([2], True, None))
        self.assertEqual(manager.wait(run_id, 2, 1)[:2], ([], True))
        with self.assertRaises(KeyError):
            manager.wait('run-' + '0' * 24, 0, 0.01)

    def test_a_runtime_exception_is_sanitized(self):
        runner = GatedRunner(fail=True)
        runner.release.set()
        manager, _ = self.manager(runner)
        run_id = manager.start(ORDERS)
        detail = finish(manager, run_id)
        self.assertEqual((detail['state'], detail['record']), ('error', None))
        self.assertEqual(manager.wait(run_id, 1, 0)[2], RUN_FAILED)
        self.assertNotIn('secret', json.dumps(detail))

    def test_inputs_are_validated_before_a_run_starts(self):
        manager, runner = self.manager()
        for payload in (b'', b'x' * 1_000_001, 'text'):
            with self.assertRaises(InputRejected):
                manager.start(payload)
        with self.assertRaises(InputRejected):
            manager.start(ORDERS, second=b'')
        for as_of in ('', 'x' * 65, 'a\nb', 7):
            with self.assertRaises(InputRejected):
                manager.start(ORDERS, as_of=as_of)
        with self.assertRaises(InputRejected):
            manager.start(ORDERS, baseline='missing')  # no baseline store
        self.assertEqual(runner.calls, [])
        with TemporaryDirectory() as directory:
            store = BaselineStore(directory)
            store.save('reference', [ORDERS])
            manager = RunManager(runner=runner, model_factory=lambda: None, baselines=store)
            with self.assertRaises(KeyError):
                manager.start(ORDERS, baseline='unknown')
            with self.assertRaises(InputRejected):
                manager.start(ORDERS, baseline=5)
            run_id = manager.start(ORDERS, baseline='reference', as_of='2026-01-01T00:00:00', second=DUPLICATES,
                                   name='<b>"q3".csv')
            runner.release.set()
            detail = finish(manager, run_id)
        case = runner.calls[0]['case']
        self.assertEqual((type(case.baseline), case.as_of, case.second_payload), (dict, '2026-01-01T00:00:00', DUPLICATES))
        self.assertEqual(detail['input']['name'], 'bq3.csv')
        self.assertEqual(detail['input']['baseline'], 'reference')
        self.assertIsNotNone(detail['input']['second_sha256'])

    def test_a_decision_is_recorded_beside_the_record_and_executes_nothing(self):
        items = [{'agent': 'A29', 'text_key': 'a29.option', 'params': {}}]
        runner = GatedRunner(approvals=[{'agent': 'A33', 'decision': 'pending', 'executed': False, 'items': items}])
        manager, _ = self.manager(runner)
        run_id = manager.start(ORDERS)
        with self.assertRaises(KeyError):  # no record yet
            manager.decide(run_id, 0, 'approved')
        runner.release.set()
        finish(manager, run_id)
        decisions = manager.decide(run_id, 0, 'rejected')
        self.assertEqual((decisions['0']['decision'], decisions['0']['executed']), ('rejected', False))
        self.assertEqual(manager.detail(run_id)['record']['approvals'][0]['decision'], 'pending')
        for item, decision, error in ((1, 'approved', KeyError), (-1, 'approved', KeyError), ('0', 'approved', ValueError),
                                      (0, 'execute', ValueError)):
            with self.assertRaises(error):
                manager.decide(run_id, item, decision)
        with self.assertRaises(KeyError):
            manager.decide('nope', 0, 'approved')

    def test_settings_are_checked(self):
        for kwargs in ({'history': 0}, {'model_factory': None}, {'runner': 'run_case'}):
            with self.assertRaises(ValueError):
                RunManager(**kwargs)

    def test_retriever_passes_only_verified_passages_with_citations(self):
        class Kb:
            def __init__(self):
                self.limits = []

            def search(self, query, limit):
                self.limits.append(limit)
                return [{'source': 'duplicate-guidance', 'revision': 'r1', 'citation_sha256': 'a' * 64, 'text': 'Keep one.',
                         'verified': True},
                        {'source': 'forged', 'revision': 'r1', 'citation_sha256': 'b' * 64, 'text': 'x', 'verified': False}]
        kb = Kb()
        found = knowledge_retriever(kb)('duplicate order_id', 50)
        self.assertEqual(found, [{'source': 'duplicate-guidance', 'revision': 'r1', 'citation': 'a' * 64,
                                  'passage': 'Keep one.'}])
        knowledge_retriever(kb)('q', 0)
        self.assertEqual(kb.limits, [10, 1])

    def test_roles_list_the_36_registry_specs_and_the_limits(self):
        listing = roles()
        self.assertEqual([r['agent_id'] for r in listing['roles']], ['A%02d' % n for n in range(1, 37)])
        self.assertEqual(listing['limits'], {'specialists': 8, 'llm_calls': 12, 'tokens': 40000, 'elapsed_ms': 90000})
        self.assertEqual(listing['roles'][22]['kind'], 'llm')

    def test_real_run_with_the_model_stopped_reports_model_unavailable(self):
        with TemporaryDirectory() as directory:
            workbench = Workbench(directory, '/missing')
        manager = RunManager(model_factory=lambda: LocalModel(transport=unreachable), transport='in_process',
                             retriever=knowledge_retriever(workbench.kb))
        run_id = manager.start(DUPLICATES)
        detail = finish(manager, run_id)
        record = verify_record(detail['record'])
        live = manager.wait(run_id, 0, 0)[0]
        self.assertEqual([e['seq'] for e in live], list(range(1, len(live) + 1)))
        strip = lambda events: sorted(json.dumps({k: v for k, v in e.items() if k != 'seq'}, sort_keys=True)
                                      for e in events)
        self.assertEqual(strip(live), strip(record['events']))  # same events; only the order and numbering differ
        self.assertEqual((live[0]['type'], live[-1]['type']), ('run_started', 'run_finished'))
        model_calls = [e['data'] for e in live if e['type'] == 'llm_call']
        self.assertTrue(model_calls)
        self.assertTrue(all(not c['ok'] and c['error_code'] == 'MODEL_UNAVAILABLE' and c['tokens_out'] == 0
                            for c in model_calls))
        self.assertEqual(detail['status'], record['status'])
        retrieved = [e for e in live if e['type'] == 'retrieval']
        self.assertTrue(retrieved and retrieved[0]['data']['citations'] >= 1)


class OwnerOnlyStateTests(unittest.TestCase):
    def test_existing_state_and_token_files_are_made_owner_only_on_every_start(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'state'
            root.mkdir(mode=0o755)
            for name in ('state.json', 'access-token'):
                (root / name).write_text('{"status": "IDLE"}' if name == 'state.json' else 'old')
                os.chmod(root / name, 0o644)
            os.symlink(root / 'access-token', root / 'link')
            Workbench(root, '/missing')
            mode = lambda path: stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode)
            self.assertEqual(mode(root), 0o700)
            for name in ('state.json', 'access-token'):
                self.assertEqual(mode(root / name), 0o600, name)
            os.chmod(root / 'access-token', 0o644)
            write_private(root / 'access-token', 'fresh')
            self.assertEqual((mode(root / 'access-token'), (root / 'access-token').read_text()), (0o600, 'fresh'))
            write_private(root / 'new-token', 'n')
            self.assertEqual(mode(root / 'new-token'), 0o600)
            (root / 'state.next').write_text('{}')
            os.chmod(root / 'state.next', 0o644)
            Workbench(root, '/missing').save()
            self.assertEqual(mode(root / 'state.json'), 0o600)
            os.chmod(root, 0o755)
            secure_state_directory(root)
            self.assertEqual(mode(root), 0o700)


class AgentHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workbench = Workbench(self.tmp.name, '/missing')
        items = [{'agent': 'A29', 'text_key': 'a29.option', 'params': {}}]
        self.runner = GatedRunner(approvals=[{'agent': 'A33', 'decision': 'pending', 'executed': False, 'items': items}])
        self.workbench.agents = RunManager(runner=self.runner, model_factory=lambda: None,
                                           baselines=self.workbench.baselines, heartbeat_s=0.05)
        self.server = make_server(self.workbench, TOKEN)
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.runner.release.set)
        self.auth = {'Authorization': 'Bearer ' + TOKEN}

    def call(self, path, method='GET', headers=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        value = (response.status, response.read(), dict(response.getheaders()))
        connection.close()
        return value

    def post(self, path, payload, headers=None):
        body = payload if type(payload) is bytes else json.dumps(payload).encode()
        return self.call(path, 'POST', {**self.auth, 'Content-Type': 'application/json', **(headers or {})}, body)

    def start(self):
        status, body, _ = self.post('/api/agents/run', {'csv_b64': base64.b64encode(ORDERS).decode(), 'name': 'o.csv'})
        self.assertEqual(status, 202)
        return json.loads(body)['run_id']

    def test_flow_page_and_script_are_served(self):
        status, body, headers = self.call('/flow')
        self.assertEqual(status, 200)
        self.assertIn(b'/flow.js', body)
        status, _, headers = self.call('/flow.js')
        self.assertEqual((status, headers['Content-Type']), (200, 'text/javascript'))

    def test_run_endpoints_require_the_session_host_and_origin(self):
        encoded = json.dumps({'csv_b64': base64.b64encode(ORDERS).decode()}).encode()
        for path in ('/api/agents/runs', '/api/agents/roles', '/api/agents/stream?run=x'):
            self.assertEqual(self.call(path)[0], 403)
            self.assertEqual(self.call(path, headers={**self.auth, 'Origin': 'http://evil.invalid'})[0], 403)
            self.assertEqual(self.call(path, headers={**self.auth, 'Host': 'evil.invalid'})[0], 403)
        self.assertEqual(self.call('/api/agents/run', 'POST', {'Content-Type': 'application/json'}, encoded)[0], 403)
        self.assertEqual(self.post('/api/agents/run', encoded, {'Origin': 'http://evil.invalid'})[0], 403)
        self.assertEqual(self.post('/api/agents/run', encoded, {'Content-Type': 'text/csv'})[0], 403)
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.call('/api/agents/roles', headers=self.auth)[0], 200)

    def test_start_busy_listing_and_record(self):
        run_id = self.start()
        status, body, _ = self.post('/api/agents/run', {'csv_b64': base64.b64encode(ORDERS).decode()})
        self.assertEqual((status, json.loads(body)), (409, {'error': 'BUSY'}))
        listing = json.loads(self.call('/api/agents/runs', headers=self.auth)[1])
        self.assertEqual((listing['active'], listing['runs'][0]['state']), (run_id, 'running'))
        detail = json.loads(self.call('/api/agents/runs/' + run_id, headers=self.auth)[1])
        self.assertIsNone(detail['record'])
        self.runner.release.set()
        finish(self.workbench.agents, run_id)
        detail = json.loads(self.call('/api/agents/runs/' + run_id, headers=self.auth)[1])
        self.assertEqual((detail['record']['run_id'], detail['input']['name']), (run_id, 'o.csv'))
        for missing in ('run-' + '0' * 24, '../state.json', 'x'):
            self.assertEqual(self.call('/api/agents/runs/' + missing, headers=self.auth)[0], 404)

    def test_malformed_and_oversized_bodies_are_refused(self):
        self.assertEqual(self.post('/api/agents/run', b'{not json')[0], 400)
        self.assertEqual(self.post('/api/agents/run', b'[1]')[0], 400)
        self.assertEqual(self.post('/api/agents/run', {'csv_b64': '***'})[0], 422)
        self.assertEqual(self.post('/api/agents/run', {'csv_b64': 5})[0], 422)
        self.assertEqual(self.post('/api/agents/run', {'csv_b64': ''})[0], 422)
        encoded = base64.b64encode(ORDERS).decode()
        self.assertEqual(self.post('/api/agents/run', {'csv_b64': encoded, 'second_csv_b64': '%%'})[0], 422)
        status, body, _ = self.post('/api/agents/run', {'csv_b64': encoded, 'baseline': 'missing'})
        self.assertEqual((status, json.loads(body)), (404, {'error': 'NOT_FOUND'}))
        self.assertEqual(self.post('/api/agents/run', {'csv_b64': encoded, 'as_of': 'x' * 65})[0], 422)
        status = self.call('/api/agents/run', 'POST', {**self.auth, 'Content-Type': 'application/json',
                                                        'Content-Length': str(AGENT_RUN_BODY_LIMIT + 1)}, b'{}')[0]
        self.assertEqual(status, 413)
        self.assertEqual(self.runner.calls, [])
        # Two files at the 1 MB limit fit the body cap.
        big = base64.b64encode(b'a' * 1_000_000).decode()
        self.assertLess(len(json.dumps({'csv_b64': big, 'second_csv_b64': big, 'baseline': 'x' * 80,
                                        'as_of': 'x' * 64, 'name': 'x' * 80})), AGENT_RUN_BODY_LIMIT)

    def test_approval_records_a_decision_only(self):
        run_id = self.start()
        self.assertEqual(self.post('/api/agents/approval', {'run_id': run_id, 'item': 0, 'decision': 'approved'})[0], 404)
        self.runner.release.set()
        finish(self.workbench.agents, run_id)
        status, body, _ = self.post('/api/agents/approval', {'run_id': run_id, 'item': 0, 'decision': 'approved'})
        self.assertEqual((status, json.loads(body)['decisions']['0']['executed']), (200, False))
        self.assertEqual(self.post('/api/agents/approval', {'run_id': run_id, 'item': 0, 'decision': 'run'})[0], 400)
        self.assertEqual(self.post('/api/agents/approval', {'run_id': run_id, 'item': 3, 'decision': 'approved'})[0], 404)
        self.assertEqual(self.post('/api/agents/approval', b'"x"')[0], 400)
        self.assertEqual(self.post('/api/agents/approval', {'run_id': run_id, 'item': 0, 'decision': 'approved',
                                                            'pad': 'x' * 1100})[0], 413)

    def test_stream_frames_resume_after_last_event_id_and_end_after_the_run(self):
        run_id = self.start()
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('GET', '/api/agents/stream?run=' + run_id, headers=self.auth)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'text/event-stream; charset=utf-8')
        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
        self.assertEqual(response.readline(), b'id: 1\n')
        self.assertEqual(response.readline(), b'event: agent\n')
        first = response.readline()
        self.assertTrue(first.startswith(b'data: '))
        self.assertEqual(json.loads(first[6:])['type'], 'run_started')
        self.assertEqual(response.readline(), b'\n')
        self.assertEqual(response.readline(), b': heartbeat\n')  # the run is waiting; the stream stays alive
        self.runner.release.set()
        rest = response.read().decode()
        connection.close()
        self.assertIn('id: 2\nevent: agent\ndata: ', rest)
        self.assertTrue(rest.endswith('event: end\ndata: {"error": null}\n\n'))
        # A reconnect with Last-Event-ID replays only what came after it, then ends.
        status, body, _ = self.call('/api/agents/stream?run=' + run_id, headers={**self.auth, 'Last-Event-ID': '1'})
        frames = body.decode().split('\n\n')
        self.assertEqual((status, frames[0].split('\n')[0]), (200, 'id: 2'))
        self.assertEqual(frames[1], 'event: end\ndata: {"error": null}')
        status, body, _ = self.call('/api/agents/stream?run=' + run_id, headers={**self.auth, 'Last-Event-ID': '2'})
        self.assertEqual(body, b'event: end\ndata: {"error": null}\n\n')

    def test_stream_refuses_bad_queries_and_unknown_runs(self):
        run_id = self.start()
        for path, headers, expected in (
                ('/api/agents/stream?run=run-' + '0' * 24, {}, 404),
                ('/api/agents/stream?run=' + run_id + '&run=' + run_id, {}, 400),
                ('/api/agents/stream?run=' + run_id + '&token=x', {}, 400),
                ('/api/agents/stream?other=1', {}, 400),
                ('/api/agents/stream?a=1&b=2&c=3', {}, 400),
                ('/api/agents/stream?run=' + run_id, {'Last-Event-ID': '-1'}, 400),
                ('/api/agents/stream?run=' + run_id, {'Last-Event-ID': '1234567'}, 400),
                ('/api/agents/stream?run=' + run_id, {'Last-Event-ID': '1.5'}, 400)):
            self.assertEqual(self.call(path, headers={**self.auth, **headers})[0], expected, path)

    def test_stream_ends_when_the_run_is_dropped_or_fails(self):
        self.runner.fail = True
        run_id = self.start()
        self.runner.release.set()
        finish(self.workbench.agents, run_id)
        body = self.call('/api/agents/stream?run=' + run_id, headers=self.auth)[1].decode()
        self.assertTrue(body.endswith('event: end\ndata: {"error": "RUN_FAILED"}\n\n'))
        self.assertNotIn('secret', body)
        manager = self.workbench.agents
        original = manager.wait
        manager.wait = lambda *args: (_ for _ in ()).throw(KeyError('run'))
        try:
            body = self.call('/api/agents/stream?run=' + run_id, headers=self.auth)[1].decode()
        finally:
            manager.wait = original
        self.assertEqual(body, 'event: end\ndata: {"error": "RUN_UNAVAILABLE"}\n\n')


if __name__ == '__main__':
    unittest.main()
