# SPDX-License-Identifier: Apache-2.0
"""Retained agent run records (owner-only, digest-verified on load), the dashboard aggregates and the model check."""
import base64
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

import agent_runs
import agent_summary
from agent_runs import RunManager, RunStore
from agent_summary import model_status, percentile, summarize
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.pipeline import generate_orders
from test_agent_runs import GatedRunner, TOKEN, finish, unreachable
from workbench import Workbench, make_server

DUPLICATES = generate_orders(rows=24, fault='duplicate_order')
_RECORDS = []


def real_records():
    """Two sealed records of real runs (model stopped), made once for the module."""
    if not _RECORDS:
        manager = RunManager(model_factory=lambda: LocalModel(transport=unreachable), transport='in_process')
        for payload in (DUPLICATES, generate_orders(rows=24)):
            _RECORDS.append(finish(manager, manager.start(payload, name='orders.csv'))['record'])
    return _RECORDS


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def manager(self, **kwargs):
        return RunManager(model_factory=lambda: LocalModel(transport=unreachable), transport='in_process',
                          store=RunStore(self.root), **kwargs)

    def test_records_survive_a_restart_with_their_decisions_and_replay_on_the_stream(self):
        first = self.manager()
        run_id = finish(first, first.start(DUPLICATES, name='orders.csv'))['run_id']
        record = first.detail(run_id)['record']
        path = self.root / agent_runs.STORE_FILE
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        if record['approvals']:
            first.decide(run_id, 0, 'approved')
        restarted = self.manager()
        detail = restarted.detail(run_id)
        self.assertEqual((detail['state'], detail['record'], detail['input']['name']), ('finished', record, 'orders.csv'))
        self.assertEqual(detail['decisions'], first.detail(run_id)['decisions'])
        events, done, error = restarted.wait(run_id, 0, 0)
        self.assertEqual(([e['seq'] for e in events], done, error),
                         (list(range(1, len(record['events']) + 1)), True, None))
        listing = restarted.summaries()
        self.assertEqual((listing['runs'][0]['run_id'], listing['retained'], listing['rejected_on_load']), (run_id, True, False))
        self.assertEqual(restarted.records(), [(record, detail['decisions'])])

    def test_retention_is_bounded(self):
        store = RunStore(self.root, limit=2)
        runner = GatedRunner()
        runner.release.set()
        manager = RunManager(runner=runner, model_factory=lambda: None, store=store, history=5)
        original = agent_runs.verify_record
        ids = [finish(manager, manager.start(DUPLICATES))['run_id'] for _ in range(3)]
        self.assertEqual([item['record']['run_id'] for item in store.items], ids[1:])
        with patch.object(agent_runs, 'verify_record', lambda record: record):
            self.assertEqual(len(RunStore(self.root, limit=2).items), 2)
            data = json.loads((self.root / agent_runs.STORE_FILE).read_text())
            with self.assertRaises(ValueError):
                RunStore(self.root / 'elsewhere', limit=1)._parse(data)
        self.assertIs(agent_runs.verify_record, original)

    def test_an_edited_or_unreadable_file_is_set_aside_and_never_trusted(self):
        manager = self.manager()
        finish(manager, manager.start(DUPLICATES))
        path, rejected = self.root / agent_runs.STORE_FILE, self.root / agent_runs.STORE_REJECTED
        data = json.loads(path.read_text())
        good = json.dumps(data)

        def reload(content):
            path.write_text(content if type(content) is str else json.dumps(content))
            store = RunStore(self.root)
            self.assertEqual((store.rejected_on_load, store.items, path.exists(), rejected.exists()), (True, [], False, True))
            rejected.unlink()

        tampered = json.loads(good)
        tampered['runs'][0]['record']['status'] = 'completed'
        tampered['runs'][0]['record']['duration_ms'] += 1  # the trace digest no longer matches
        reload(tampered)
        reload('{not json')
        reload({'format_version': '2', 'runs': []})
        reload({'format_version': '1', 'runs': [{'record': {}}]})
        renamed = json.loads(good)
        renamed['runs'][0]['meta'] = 'x'
        reload(renamed)
        with patch.object(agent_runs, 'MAX_STORE_BYTES', 10):
            reload(good)
        bad_id = json.loads(good)
        with patch.object(agent_runs, 'verify_record', lambda record: record):
            bad_id['runs'][0]['record']['run_id'] = 'Run-X'
            reload(bad_id)
        path.write_text(good)
        self.assertEqual(len(RunStore(self.root).items), 1)
        self.assertTrue(self.manager().summaries()['runs'])

    def test_a_failed_write_is_reported_and_not_fatal(self):
        store = RunStore(self.root)
        runner = GatedRunner()
        runner.release.set()
        manager = RunManager(runner=runner, model_factory=lambda: None, store=store)
        with patch.object(store, 'save', side_effect=OSError('disk full')):
            run_id = manager.start(DUPLICATES)
            self.assertEqual(finish(manager, run_id)['state'], 'finished')
        self.assertTrue(manager.summaries()['store_error'])
        manager.start(DUPLICATES)
        finish(manager, manager.summaries()['runs'][0]['run_id'])
        self.assertFalse(manager.summaries()['store_error'])


def fake_record(run_id, *, status='completed', duration=100, llm=(), approvals=0, accepted=True):
    agents = [{'agent_id': 'A%02d' % n, 'result': {'status': 'COMPLETED' if n in (10, 27) else 'SKIPPED',
                                                   'claims': [{'text_key': 'a10.profile'}] if n == 10 else []}}
              for n in range(1, 37)]
    events = [{'seq': i + 1, 'agent_id': agent, 'type': 'llm_call',
               'data': {'ok': ok, 'latency_ms': ms, 'tokens_in': 10, 'tokens_out': 5, 'cache': cache,
                        'error_code': None if ok else 'MODEL_UNAVAILABLE'}}
              for i, (agent, ok, ms, cache) in enumerate(llm)]
    return {'run_id': run_id, 'started_at': '2026-01-01T00:00:00.000Z', 'status': status, 'duration_ms': duration,
            'agents': agents, 'events': events,
            'selection': [{'selected': a['agent_id'] in ('A10', 'A27')} for a in agents],
            'judge': {'verdicts': [{'verdict': 'accepted'}, {'verdict': 'advisory'}, {'verdict': 'rejected'}, {'verdict': 'accepted'}],
                      'accepted_findings': [{'agent': 'A10', 'claim': 0}, {'agent': 'A10', 'claim': 5}] if accepted else []},
            'approvals': [{'items': [{}] * approvals}] if approvals else [],
            'usage': {'totals': {'llm_calls': len(llm)}}}


class SummaryTests(unittest.TestCase):
    def test_percentile_is_nearest_rank_and_none_when_empty(self):
        self.assertIsNone(percentile([], 0.5))
        self.assertEqual((percentile(list(range(1, 21)), 0.5), percentile(list(range(1, 21)), 0.95)), (10, 19))
        self.assertEqual(percentile([7], 0.95), 7)

    def test_aggregates_are_computed_from_the_records_only(self):
        runs = [(fake_record('r1', duration=100, llm=[('A23', True, 40, 'miss'), ('A23', True, 10, 'hit')], approvals=2),
                 {'0': {'decision': 'approved'}}),
                (fake_record('r2', status='failed_agents', duration=300, llm=[('A29', False, 5, 'none')], accepted=False), {})]
        s = summarize(runs)
        self.assertEqual((s['runs'], s['source']), (2, 'retained_agent_run_records'))
        self.assertEqual(s['statuses'], {'completed': 1, 'failed_agents': 1})
        self.assertEqual(s['agents']['COMPLETED'], 4)
        self.assertEqual(s['layers']['specialists']['COMPLETED'], 2)
        self.assertEqual(s['layers']['reasoning']['COMPLETED'], 2)
        self.assertEqual(s['judge'], {'accepted': 4, 'advisory': 2, 'rejected': 2, 'verdicts': 8, 'acceptance': 0.5})
        self.assertEqual((s['llm']['calls'], s['llm']['ok'], s['llm']['tokens_in'], s['llm']['tokens_out']), (3, 2, 30, 15))
        self.assertEqual((s['llm']['latency_p50_ms'], s['llm']['latency_p95_ms']), (10, 40))
        self.assertEqual(s['llm']['per_agent']['A23']['cache_hits'], 1)
        self.assertEqual(s['llm']['per_agent']['A29']['errors'], {'MODEL_UNAVAILABLE': 1})
        self.assertEqual(s['durations']['p50_ms'], 100)
        self.assertEqual([r['run_id'] for r in s['durations']['last']], ['r1', 'r2'])
        self.assertEqual(s['top_findings'], [{'agent': 'A10', 'text_key': 'a10.profile', 'runs': 1}])
        self.assertEqual(s['pending_approvals'], [{'run_id': 'r1', 'items': 2, 'undecided': 1}])
        self.assertEqual([r['run_id'] for r in s['recent']], ['r2', 'r1'])
        self.assertEqual((s['recent'][1]['selected'], s['recent'][1]['undecided']), (2, 1))
        empty = summarize([])
        self.assertEqual((empty['runs'], empty['judge']['acceptance'], empty['llm']['latency_p50_ms']), (0, None, None))

    def test_real_records_summarize(self):
        s = summarize([(record, {}) for record in real_records()])
        self.assertEqual(s['runs'], 2)
        self.assertEqual(sum(s['agents'].values()), 72)
        self.assertTrue(all(row['errors'] == {'MODEL_UNAVAILABLE': row['calls']} for row in s['llm']['per_agent'].values()))
        self.assertGreater(s['judge']['verdicts'], 0)


class ModelStatusTests(unittest.TestCase):
    def test_reachable_listed_unreadable_and_unreachable(self):
        tags = json.dumps({'models': [{'name': 'qwen3:4b'}, {'name': 'other'}]}).encode()
        seen = []
        status = model_status(lambda url, timeout: seen.append((url, timeout)) or tags)
        self.assertEqual((status['reachable'], status['model_listed'], status['model']), (True, True, 'qwen3:4b'))
        self.assertEqual(seen, [('http://127.0.0.1:11434/api/tags', 1.0)])
        self.assertFalse(model_status(lambda u, t: b'{"models": []}')['model_listed'])
        self.assertIsNone(model_status(lambda u, t: b'<html>')['model_listed'])
        self.assertIsNone(model_status(lambda u, t: b'x' * 1_000_001)['model_listed'])
        down = model_status(lambda u, t: (_ for _ in ()).throw(ConnectionRefusedError()))
        self.assertEqual((down['reachable'], down['model_listed']), (False, None))

    def test_the_default_fetch_reads_a_bounded_reply_without_proxies(self):
        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                self.limit = limit
                return b'{}'
        with patch.object(agent_summary._OPENER, 'open', return_value=Reply()) as opened:
            self.assertEqual(agent_summary._fetch('http://127.0.0.1:11434/api/tags', 1.0), b'{}')
        self.assertEqual(opened.call_args.kwargs['timeout'], 1.0)
        self.assertIsNone(agent_summary._NoRedirect().redirect_request(None, None, 302, '', {}, 'http://evil.invalid'))


class DashboardHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workbench = Workbench(self.tmp.name, '/missing')
        self.runner = GatedRunner()
        self.runner.release.set()
        self.workbench.agents = RunManager(runner=self.runner, model_factory=lambda: None)
        self.workbench.model_status = lambda: {'reachable': False}
        self.server = make_server(self.workbench, TOKEN)
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.auth = {'Authorization': 'Bearer ' + TOKEN}

    def call(self, path, method='GET', headers=None, body=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        value = (response.status, response.read())
        connection.close()
        return value

    def test_workbench_retains_runs_in_its_state_directory(self):
        self.assertIsInstance(Workbench(self.tmp.name, '/missing').agents._store, RunStore)

    def test_summary_and_model_are_authorized(self):
        for path in ('/api/agents/summary', '/api/agents/model'):
            self.assertEqual(self.call(path)[0], 403)
            self.assertEqual(self.call(path, headers={**self.auth, 'Origin': 'http://evil.invalid'})[0], 403)
        status, body = self.call('/api/agents/summary', headers=self.auth)
        self.assertEqual((status, json.loads(body)['runs']), (200, 0))
        self.assertEqual(json.loads(self.call('/api/agents/model', headers=self.auth)[1]), {'reachable': False})

    def test_page_links_with_a_query_serve_the_app_but_nothing_else(self):
        status, body = self.call('/flow?run=run-' + '0' * 24)
        self.assertEqual(status, 200)
        self.assertIn(b'/flow.js', body)
        self.assertEqual(self.call('/app.js?x=1')[0], 403)
        self.assertEqual(self.call('/missing?run=1')[0], 403)

    def test_the_confirmed_column_mapping_is_applied_to_the_agent_run(self):
        csv = b'id,customer_id,order_total\nO1,C1,1.00\n'
        body = lambda mapping: json.dumps({'csv_b64': base64.b64encode(csv).decode(), 'mapping': mapping}).encode()
        headers = {**self.auth, 'Content-Type': 'application/json'}
        status, raw = self.call('/api/agents/run', 'POST', headers, body({'id': 'order_id'}))
        self.assertEqual(status, 202)
        finish(self.workbench.agents, json.loads(raw)['run_id'])
        self.assertTrue(self.runner.calls[0]['case'].payload.startswith(b'order_id,'))
        self.assertEqual(self.call('/api/agents/run', 'POST', headers, body({'id': 'nope'}))[0], 422)


if __name__ == '__main__':
    unittest.main()
