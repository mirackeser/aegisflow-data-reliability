# SPDX-License-Identifier: Apache-2.0
"""The Command Center's simulated plant endpoints: authorization, controls, fault validation, the state shape,
investigations through the run manager, body caps and the busy answer."""
from http.client import HTTPConnection
import json
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest

from agent_runs import RunManager
from aegisflow_dr.pipeline import InputRejected
from aegisflow_dr import simulation as sim
from plant import DEFAULT_SPEED, MODEL_TTL_S, PlantController
from test_agent_runs import GatedRunner, finish
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

    def open_incident(self):
        plant = self.workbench.plant.plant
        plant.inject('unit_change', 'pressure_kpa')
        plant.advance(4 * sim.CHECK_EVERY)
        return plant.incidents[0]['id']

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
                                      'current', 'faults', 'incidents', 'detections', 'status', 'kpis', 'model',
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
                                         'clean_checks', 'findings', 'run_id', 'window', 'checks', 'severity'})
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


if __name__ == '__main__':
    unittest.main()
