# SPDX-License-Identifier: Apache-2.0
"""The Command Center's simulated plant endpoints: authorization, controls, fault validation, the state shape,
investigations through the run manager, body caps and the busy answer."""
from http.client import HTTPConnection
import json
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from unittest import mock

from agent_runs import RunManager
from aegisflow_dr.agents.context import reference
from aegisflow_dr.hypotheses import investigate
from aegisflow_dr.pipeline import InputRejected
from aegisflow_dr import simulation as sim
from plant import DEFAULT_SPEED, MODEL_TTL_S, PlantController
from test_agent_runs import GatedRunner, finish, unreachable
from aegisflow_dr.agents.llm import LocalModel
from aegisflow_dr.casefile import decision_record
from workbench import PLANT_BODY_LIMIT, Workbench, make_server

TOKEN = 'test-local-token'


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PlantHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workbench = Workbench(self.tmp.name, '/missing')
        self.runner = GatedRunner()
        self.addCleanup(self.runner.release.set)
        self.workbench.agents = RunManager(runner=self.runner, model_factory=lambda: None,
                                           baselines=self.workbench.baselines, heartbeat_s=0.05)
        self.model_calls = 0

        def model():
            self.model_calls += 1
            return {'reachable': False, 'model': 'qwen3:4b', 'model_listed': None}
        self.clock = Clock()
        self.workbench.plant = PlantController(lambda: self.workbench.agents, model_status=model, clock=self.clock,
                                               thread=False)
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
        value = (response.status, response.read(), dict(response.getheaders()))
        connection.close()
        return value

    def post(self, path, payload, headers=None):
        body = payload if type(payload) is bytes else json.dumps(payload).encode()
        return self.call(path, 'POST', {**self.auth, 'Content-Type': 'application/json', **(headers or {})}, body)

    def state(self):
        status, body, _ = self.call('/api/plant/state', headers=self.auth)
        self.assertEqual(status, 200)
        return json.loads(body)

    def open_incident(self, ready=True):
        """Inject unit x10 on pressure until an incident opens; with ``ready`` also until its evidence is frozen."""
        plant = self.workbench.plant.plant
        plant.inject('unit_change', 'pressure_kpa')
        plant.advance(2 * sim.CHECK_EVERY)
        incident = plant.incidents[0]['id']
        if ready:
            plant.advance(sim.WINDOW_SECONDS)
            self.assertEqual(plant.incident(incident)['evidence']['state'], sim.READY)
        return incident

    def test_authorization_host_and_origin(self):
        self.assertEqual(self.call('/api/plant/state')[0], 403)
        self.assertEqual(self.call('/api/plant/state', headers={**self.auth, 'Origin': 'http://evil.invalid'})[0], 403)
        self.assertEqual(self.call('/api/plant/state', headers={**self.auth, 'Host': 'evil.invalid'})[0], 403)
        for path in ('/api/plant/control', '/api/plant/inject', '/api/plant/clear', '/api/plant/incidents/INC-0001/investigate'):
            body = b'{"action": "start"}'
            self.assertEqual(self.call(path, 'POST', {'Content-Type': 'application/json'}, body)[0], 403, path)
            self.assertEqual(self.post(path, body, {'Origin': 'http://evil.invalid'})[0], 403, path)
            self.assertEqual(self.post(path, body, {'Content-Type': 'text/plain'})[0], 403, path)
        self.assertEqual(self.post('/api/plant/incidents/../investigate', {})[0], 403)
        self.assertFalse(self.workbench.plant.running)
        status, body, headers = self.call('/command.js')
        self.assertEqual((status, headers['Content-Type']), (200, 'text/javascript'))
        self.assertIn(b'commandRender', body)
        self.assertEqual(self.call('/overview')[0], 200)

    def test_controls_follow_the_clock_times_speed(self):
        self.assertEqual(self.state()['status'], {'running': False, 'speed': DEFAULT_SPEED, 'speeds': [1, 5, 20]})
        self.clock.now += 10
        self.assertEqual(self.state()['elapsed_s'], 0)  # paused: nothing advances
        status, body, _ = self.post('/api/plant/control', {'action': 'start'})
        self.assertEqual((status, json.loads(body)['running']), (200, True))
        self.clock.now += 2
        self.assertEqual(self.state()['elapsed_s'], 2 * DEFAULT_SPEED)
        self.assertEqual(self.post('/api/plant/control', {'action': 'speed', 'speed': 20})[0], 200)
        self.clock.now += 0.5
        self.assertEqual(self.state()['elapsed_s'], 2 * DEFAULT_SPEED + 10)
        self.clock.now += 3600  # a long stall catches up at most MAX_STEPS_PER_TICK seconds
        self.assertEqual(self.state()['elapsed_s'], 2 * DEFAULT_SPEED + 10 + 120)
        self.assertEqual(self.post('/api/plant/control', {'action': 'pause'})[0], 200)
        self.clock.now += 5
        paused = self.state()['elapsed_s']
        self.assertEqual(paused, 2 * DEFAULT_SPEED + 10 + 120)
        self.workbench.plant.tick()
        self.assertEqual(self.state()['elapsed_s'], paused)
        status, body, _ = self.post('/api/plant/control', {'action': 'reset'})
        self.assertEqual(json.loads(body), {'running': False, 'speed': DEFAULT_SPEED, 'speeds': [1, 5, 20]})
        self.assertEqual((self.state()['elapsed_s'], self.state()['incidents']), (0, []))
        for bad in ({'action': 'jump'}, {'action': 'speed', 'speed': 3}, {'action': 'speed', 'speed': True},
                    {'action': 'speed', 'speed': '5'}, {'action': 'speed'}, {}):
            self.assertEqual(self.post('/api/plant/control', bad)[0], 422, bad)
        self.assertEqual(self.post('/api/plant/control', b'[1]')[0], 400)
        self.assertEqual(self.post('/api/plant/control', b'{nope')[0], 400)

    def test_inject_and_clear_validation(self):
        status, body, _ = self.post('/api/plant/inject', {'fault': 'unit_change', 'sensor': 'pressure_kpa'})
        fault = json.loads(body)
        self.assertEqual((status, fault['fault'], fault['sensor'], fault['ended_t']), (200, 'unit_change', 'pressure_kpa', None))
        self.assertEqual(self.post('/api/plant/inject', {'fault': 'unit_change', 'sensor': 'pressure_kpa'})[0], 422)
        for bad in ({'fault': 'melt', 'sensor': 'temp_c'}, {'fault': 'unit_change'}, {'fault': 'unit_change', 'sensor': 'rpm'},
                    {'fault': 'unit_change', 'sensor': ['temp_c']}, {'fault': 'ingestion_pause', 'sensor': 'temp_c'},
                    {'fault': ['unit_change'], 'sensor': 'temp_c'}, {'fault': {'a': 1}}):
            status, body, _ = self.post('/api/plant/inject', bad)
            self.assertEqual(status, 422, bad)
            self.assertEqual(json.loads(body)['error'], 'INPUT_REJECTED')
        self.assertEqual(self.post('/api/plant/inject', {'fault': 'ingestion_pause'})[0], 200)
        self.assertEqual(self.post('/api/plant/clear', {'fault_id': 'F9'})[0], 404)
        self.assertEqual(self.post('/api/plant/clear', {'fault_id': ['F1']})[0], 404)
        status, body, _ = self.post('/api/plant/clear', {'fault_id': fault['id']})
        self.assertEqual((status, json.loads(body)['id']), (200, fault['id']))
        self.assertEqual(self.post('/api/plant/clear', {'fault_id': fault['id']})[0], 404)
        self.assertEqual([f['id'] for f in self.state()['faults'] if f['ended_t'] is None], ['F2'])

    def test_state_shape(self):
        state = self.state()
        self.assertEqual(set(state), {'simulation', 'seed', 'start', 'now_t', 'now', 'live_start_t', 'elapsed_s', 'emitted',
                                      'checks', 'detected', 'last_check', 'units', 'settings', 'baseline', 'series',
                                      'current', 'faults', 'incidents', 'detections', 'status', 'kpis', 'model', 'seasonality',
                                      'catalog', 'agents'})
        self.assertTrue(state['simulation'])
        self.assertEqual(set(state['kpis']), {'active_incidents', 'incidents', 'detections', 'investigations',
                                              'investigations_from_plant', 'judge_acceptance', 'judge_accepted',
                                              'judge_verdicts', 'median_investigation_ms', 'data_points', 'readings',
                                              'checks'})
        self.assertEqual((state['kpis']['judge_acceptance'], state['kpis']['median_investigation_ms']), (None, None))
        self.assertEqual(state['kpis']['data_points'], 3 * state['emitted'])
        self.assertEqual(set(state['agents']), {'runs', 'layers', 'statuses', 'active', 'recent'})
        self.assertEqual(set(state['agents']['layers']), {'orchestration', 'specialists', 'reasoning', 'remediation', 'governance'})
        self.assertEqual(state['catalog']['faults'], list(sim.FAULTS))
        self.assertEqual(len(state['series']['t']), sim.CHART_READINGS)
        self.assertEqual(set(state['baseline']['bands']), set(sim.SENSORS))
        self.assertEqual(state['model']['reachable'], False)
        self.open_incident()
        incident = self.state()['incidents'][0]
        self.assertEqual(set(incident), {'id', 'sensor', 'status', 'opened_t', 'opened_at', 'closed_t', 'closed_at',
                                         'clean_checks', 'findings', 'run_id', 'window', 'checks', 'severity', 'evidence', 'truth'})
        self.assertEqual(set(incident['window']), {'sha256', 'first_t', 'last_t', 'records', 'as_of'})
        self.assertEqual(self.state()['kpis']['active_incidents'], 1)

    def test_model_status_is_cached(self):
        self.state()
        self.state()
        self.assertEqual(self.model_calls, 1)
        self.clock.now += MODEL_TTL_S
        self.state()
        self.assertEqual(self.model_calls, 2)
        self.assertIsNone(PlantController(lambda: self.workbench.agents, thread=False).model())

    def test_investigate_starts_an_agent_run_and_answers_busy(self):
        incident = self.open_incident()
        self.assertEqual(self.post('/api/plant/incidents/INC-0099/investigate', {})[0], 404)
        status, body, _ = self.post('/api/plant/incidents/%s/investigate' % incident, {})
        self.assertEqual(status, 202)
        run_id = json.loads(body)['run_id']
        self.assertRegex(run_id, r'^run-[0-9a-f]{24}$')
        call = self.runner.calls[0]['case']
        payload, as_of = self.workbench.plant.plant.evidence(incident)
        self.assertEqual((call.payload, call.as_of), (payload, as_of))
        self.assertEqual(call.baseline, self.workbench.plant.plant.baseline)
        detail = self.workbench.agents.detail(run_id)
        self.assertEqual(detail['input']['baseline'], 'simulated-plant')
        self.assertEqual(detail['input']['name'], 'simulated-plant %s pressure_kpa' % incident)
        state = self.state()
        self.assertEqual(state['incidents'][0]['run_id'], run_id)
        self.assertEqual(state['agents']['active'], run_id)
        self.assertEqual(state['agents']['recent'][0]['from_plant'], True)
        self.assertEqual(state['kpis']['investigations_from_plant'], 1)
        self.assertEqual(self.post('/api/plant/incidents/%s/investigate' % incident, {})[0], 409)
        self.runner.release.set()
        finish(self.workbench.agents, run_id)
        self.workbench.agents.records = lambda: []  # the stand-in runner's record is not a full sealed record
        self.assertEqual(self.state()['agents']['recent'][0]['state'], 'finished')

    def test_probe_loop_summaries_are_cached_and_bounded(self):
        incident = self.open_incident(ready=False)
        controller = self.workbench.plant
        self.assertIsNone(controller.incident(incident)['investigation'])
        controller.plant.advance(sim.WINDOW_SECONDS)
        first = controller.incident(incident)['investigation']
        with mock.patch('plant.investigate', side_effect=AssertionError('recomputed')):
            self.assertIs(controller.incident(incident)['investigation'], first)
        controller._investigations = {('stale', 'digest', 'as_of'): {}}
        with mock.patch('plant.MAX_INVESTIGATIONS', 1):
            self.assertEqual(controller.incident(incident)['investigation'], first)
        self.assertNotIn(('stale', 'digest', 'as_of'), controller._investigations)
        self.assertEqual(len(controller._investigations), 1)

    def test_investigation_waits_for_complete_evidence(self):
        incident = self.open_incident(ready=False)
        status, body, _ = self.post('/api/plant/incidents/%s/investigate' % incident, {})
        answer = json.loads(body)
        self.assertEqual((status, answer['error'], answer['evidence']['state']), (409, 'EVIDENCE_NOT_READY', 'collecting'))
        self.assertGreater(answer['evidence']['collected_s'], 0)
        self.assertEqual(self.runner.calls, [])
        status, body, _ = self.call('/api/plant/incidents/%s/evidence.csv' % incident, headers=self.auth)
        self.assertEqual((status, json.loads(body)['error']), (409, 'EVIDENCE_NOT_READY'))

    def test_incident_view_and_evidence_download(self):
        incident = self.open_incident()
        status, body, _ = self.call('/api/plant/incidents/%s' % incident, headers=self.auth)
        view = json.loads(body)
        self.assertEqual((status, view['incident']['id'], view['run']), (200, incident, None))
        self.assertTrue(view['simulation'])
        self.assertEqual(view['incident']['truth']['onset_error_s'], 0)
        payload, as_of = self.workbench.plant.plant.evidence(incident)
        record = investigate(self.workbench.plant.plant.baseline, payload, as_of=as_of)
        self.assertEqual(view['investigation']['ref'], reference('investigation', record))
        self.assertEqual((view['investigation']['probes'], view['investigation']['verdict']), (record['probes'], 'single_supported'))
        self.assertEqual([h['mechanism'] for h in view['investigation']['hypotheses'] if h['status'] == 'supported'], ['unit_change'])
        self.assertIsNone(view['runs_active'])
        status, body, headers = self.call('/api/plant/incidents/%s/evidence.csv' % incident, headers=self.auth)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'text/csv; charset=utf-8')
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="%s-evidence.csv"' % incident)
        self.assertEqual(body, self.workbench.plant.plant.evidence(incident)[0])
        self.post('/api/plant/incidents/%s/investigate' % incident, {})
        view = json.loads(self.call('/api/plant/incidents/%s' % incident, headers=self.auth)[1])
        self.assertEqual(view['run']['run_id'], view['incident']['run_id'])
        for path in ('/api/plant/incidents/INC-0404', '/api/plant/incidents/INC-0404/evidence.csv'):
            self.assertEqual(self.call(path, headers=self.auth)[0], 404)
        for path in ('/api/plant/incidents/%s' % incident, '/api/plant/incidents/INC-1/evidence.csv'):
            self.assertEqual(self.call(path)[0], 403)

    def test_investigation_survives_a_reset(self):
        incident = self.open_incident()
        controller = self.workbench.plant
        original = controller.plant
        started = controller._agents().start

        def start_then_reset(*args, **kwargs):
            run = started(*args, **kwargs)
            controller.plant = sim.Plant(seed=1, start=original.start)
            return run
        controller._agents = lambda: type('M', (), {'start': staticmethod(start_then_reset)})()
        run_id = controller.investigate(incident)
        self.assertIsNone(original.incident(incident)['run_id'])
        self.assertEqual(controller.launched, [run_id])

    def test_body_caps(self):
        big = json.dumps({'action': 'start', 'pad': 'x' * PLANT_BODY_LIMIT}).encode()
        self.assertEqual(self.post('/api/plant/control', big)[0], 413)
        self.assertEqual(self.post('/api/plant/inject', b'')[0], 413)
        status = self.call('/api/plant/control', 'POST', {**self.auth, 'Content-Type': 'application/json',
                                                          'Transfer-Encoding': 'chunked'}, b'2\r\n{}\r\n0\r\n\r\n')[0]
        self.assertEqual(status, 403)
        self.assertFalse(self.workbench.plant.running)

    def test_background_clock_runs_after_start_and_stops_on_close(self):
        controller = PlantController(lambda: self.workbench.agents, tick_s=0.01)
        controller.control('speed', 20)
        controller.control('start')
        self.addCleanup(controller.close)
        deadline = time.time() + 5
        while controller.plant.now == controller.plant.live_start and time.time() < deadline:
            time.sleep(0.02)
        self.assertGreater(controller.plant.now, controller.plant.live_start)
        thread = controller._thread
        controller.control('start')
        self.assertIs(controller._thread, thread)
        controller.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        with self.assertRaises(InputRejected):
            controller.inject('unit_change', 5)


class CaseFileTests(unittest.TestCase):
    """The evidence chain and the human decision, over a real agent run (the local model is unreachable)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workbench = Workbench(self.tmp.name, '/missing')
        model = lambda: LocalModel(transport=unreachable)  # noqa: E731 - LLM roles answer MODEL_UNAVAILABLE honestly
        self.workbench.agents = RunManager(model_factory=model, baselines=self.workbench.baselines, transport='in_process')
        self.workbench.plant = PlantController(lambda: self.workbench.agents, thread=False,
                                               decisions=self.workbench.decisions)
        self.server = make_server(self.workbench, TOKEN)
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.auth = {'Authorization': 'Bearer ' + TOKEN}

    call, post = PlantHttpTests.call, PlantHttpTests.post

    def case(self, incident):
        status, body, _ = self.call('/api/plant/incidents/%s/case' % incident, headers=self.auth)
        self.assertEqual(status, 200)
        return json.loads(body)

    def investigated(self):
        plant = self.workbench.plant.plant
        plant.inject('unit_change', 'pressure_kpa')
        plant.advance(2 * sim.CHECK_EVERY)
        incident = plant.incidents[0]['id']
        early = self.case(incident)
        self.assertEqual([c['status'] for c in early['checks']], ['verified'] + ['missing'] * 4)
        self.assertEqual(self.post('/api/plant/incidents/%s/decision' % incident,
                                   {'decision': 'rejected', 'reviewer': 'R'})[0], 409)
        plant.advance(sim.WINDOW_SECONDS)
        self.assertEqual(self.post('/api/plant/incidents/%s/decision' % incident,
                                   {'decision': 'rejected', 'reviewer': 'R'})[0], 422)  # no finished run yet
        run_id = json.loads(self.post('/api/plant/incidents/%s/investigate' % incident, {})[1])['run_id']
        deadline = time.monotonic() + 60
        while self.workbench.agents.detail(run_id)['state'] == 'running' and time.monotonic() < deadline:
            time.sleep(0.05)
        return incident

    def test_chain_is_verified_link_by_link_and_completed_by_a_decision(self):
        incident = self.investigated()
        before = self.case(incident)
        self.assertEqual([(c['kind'], c['status']) for c in before['checks']],
                         [('baseline', 'verified'), ('evidence', 'verified'), ('probes', 'verified'),
                          ('agent_run', 'verified'), ('decision', 'missing')])
        self.assertTrue(before['intact'])
        self.assertFalse(before['complete'])
        self.assertTrue(before['chain'][3]['summary']['a24_matches_probes'])
        self.assertEqual(before['chain'][2]['summary']['supported'], ['unit_change'])
        status, body, _ = self.post('/api/plant/incidents/%s/decision' % incident,
                                    {'decision': 'accepted', 'candidate': 'noise_increase', 'reviewer': 'R'})
        self.assertEqual(status, 422)  # not supported on the frozen evidence
        for bad in ({'decision': 'accepted', 'candidate': 'unit_change', 'reviewer': 'R', 'run': 'x'}, ['list']):
            self.assertIn(self.post('/api/plant/incidents/%s/decision' % incident, bad)[0], (400, 422))
        status, body, _ = self.post('/api/plant/incidents/%s/decision' % incident,
                                    {'decision': 'accepted', 'candidate': 'unit_change', 'reviewer': ' Ada ',
                                     'note': 'Scale ratio near 10.'})
        after = json.loads(body)
        self.assertEqual((status, after['complete'], len(after['chain'])), (200, True, 5))
        self.assertEqual(after['chain'][4]['summary'], {'decision': 'accepted', 'candidate': 'unit_change', 'reviewer': 'Ada'})
        self.assertEqual(after['head'], after['chain'][4]['link_sha256'])
        self.assertEqual(len(after['decisions']), 1)
        view = json.loads(self.call('/api/plant/incidents/%s' % incident, headers=self.auth)[1])
        self.assertEqual(view['decision']['decision'], 'accepted')
        self.assertEqual(self.call('/api/plant/incidents/INC-0404/case', headers=self.auth)[0], 404)
        self.assertEqual(self.call('/api/plant/incidents/%s/case' % incident)[0], 403)

        # Tampering with any source shows up as a mismatch on its link.
        controller, decisions = self.workbench.plant, self.workbench.decisions
        latest = decisions.latest(view['incident']['evidence']['sha256'])
        with mock.patch.object(decisions, 'latest', return_value={**latest, 'note': 'edited'}):
            self.assertEqual(controller.case_file(incident)['checks'][4]['status'], 'mismatch')
        detail = self.workbench.agents.detail(view['incident']['run_id'])
        tampered = {**detail, 'record': {**detail['record'], 'status': 'edited'}}
        with mock.patch.object(self.workbench.agents, 'detail', return_value=tampered):
            self.assertEqual(controller.case_file(incident)['checks'][3]['status'], 'mismatch')
        with mock.patch('plant.canonical_digest', return_value='0' * 64):
            self.assertEqual(controller.case_file(incident)['checks'][0]['status'], 'mismatch')
        with mock.patch('plant.verify_investigation', side_effect=InputRejected('edited')):
            controller._investigations.clear()
            self.assertEqual(controller.case_file(incident)['checks'][2]['status'], 'mismatch')
        evidence = controller.plant._evidence[incident]
        controller.plant._evidence[incident] = (evidence[0] + b'x', evidence[1])
        self.assertEqual(controller.case_file(incident)['checks'][1]['status'], 'mismatch')
        controller.plant._evidence[incident] = evidence
        with mock.patch.object(self.workbench.agents, 'detail', side_effect=KeyError('gone')):
            self.assertEqual(controller.case_file(incident)['checks'][3]['status'], 'missing')

    def test_a_decision_from_another_run_is_not_linked_and_no_store_refuses(self):
        incident = self.investigated()
        controller = self.workbench.plant
        sha = controller.incident(incident)['incident']['evidence']['sha256']
        other = decision_record(incident_id=incident, evidence_sha256=sha, run_id='run-other', decision='rejected',
                                candidate=None, supported=[], reviewer='R', note='', decided_at='t')
        self.workbench.decisions.add(other)
        self.assertEqual(controller.case_file(incident)['checks'][4]['status'], 'missing')
        bare = PlantController(lambda: self.workbench.agents, thread=False)
        bare.plant = controller.plant
        with self.assertRaisesRegex(InputRejected, 'state folder'):
            bare.decide(incident, {'decision': 'rejected', 'reviewer': 'R'})
        self.assertEqual(bare.case_file(incident)['decisions'], [])
        self.assertIsNone(bare.incident(incident)['decision'])

if __name__ == '__main__':
    unittest.main()
