# SPDX-License-Identifier: Apache-2.0
"""Authenticated loopback workbench for retained local data investigations."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
from datetime import datetime, timezone
from uuid import uuid4
from threading import Lock, Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from knowledge import Document, Knowledge

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from check_postgres_local import qualify
from dataclasses import asdict
from aegisflow_dr.analysis import analyze_csv, apply_mapping, discover_schema
from functools import lru_cache

from aegisflow_dr.capability_map import capability_map
from aegisflow_dr.platform_map import platform_map
from aegisflow_dr.check_evaluation import evaluate as evaluate_checks
from aegisflow_dr.connectors import SourceCatalog
from aegisflow_dr.cardinality import join_cardinality
from aegisflow_dr.consistency import compare as compare_sources
from aegisflow_dr.similar import similar_index
from aegisflow_dr.execution_view import build_plan
from aegisflow_dr.monitoring import monitor
from aegisflow_dr.pipeline import FAULTS, InputRejected, diagnose_csv, generate_orders
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.coordination.judge import review


class Workbench:
    def __init__(self, directory, bindir):
        self.root = Path(directory)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.bindir = bindir
        self.lock = Lock()
        self.knowledge = Knowledge()
        self.knowledge.replace((Document('local', 'quality-contract', 'v1',
            'Source quality failure: check missing order_total values and duplicate order_id records. '
            'A finding is an observation, not a causal explanation. Never repair source data automatically.'),
            Document('local', 'reconciliation-contract', 'v1',
                'Transformation reconciliation compares expected and observed order count and amount cents. '
                'A mismatch is evidence of loss or inconsistent transformation, not proof of a causal root cause.'),
            Document('local', 'schema-contract', 'v1',
                'Schema contract: order_id, customer_id and order_total are required and no other column is allowed. '
                'A missing or unexpected column often means a renamed or reordered export field. A rename is a candidate '
                'explanation to confirm with the data owner, never proof; map columns only after confirmation.'),
            Document('local', 'missing-value-guidance', 'v1',
                'Empty required value: a blank order_total understates revenue and a blank identifier prevents matching. '
                'The inspection reports the record number only. Fix the value at its source system and inspect a new export.'),
            Document('local', 'duplicate-guidance', 'v1',
                'Duplicate order_id: identical repeated records are consistent with a repeated load or export; records with '
                'conflicting values indicate a key collision or conflicting updates. Repeats counted twice overstate revenue. '
                'The observed pattern does not prove the cause; confirm in the source system before removing anything.'),
            Document('local', 'amount-format-guidance', 'v1',
                'Invalid amount format: order_total must be a nonnegative decimal with at most two decimal places and no '
                'currency symbol, thousands separator or exponent. A locale decimal comma or text value cannot be summed safely.')))
        self.state = {'status': 'IDLE', 'events': [], 'result': None, 'error': None,
                      'model': 'NOT_CONFIGURED', 'external_spend_usd': 0, 'history': [], 'scenario': 'suite',
                      'run_id': None, 'started_at': None, 'finished_at': None, 'meta': None, 'reviews': {}}
        path = self.root / 'state.json'
        if path.exists():
            self.state.update(json.loads(path.read_text()))
            self.state.setdefault('reviews', {}); self.state.setdefault('meta', None)
            if self.state['status'] == 'RUNNING':
                self.state.update(status='INTERRUPTED', error='Previous process stopped; no automatic resume.')
                self.save()

    def save(self):
        temporary = self.root / 'state.next'
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.root / 'state.json')

    def snapshot(self):
        with self.lock:
            data = json.loads(json.dumps(self.state))
        current = [data] if data.get('run_id') and data.get('result') else []
        data['monitoring'] = monitor([*reversed(data['history']), *current])
        data['similar'] = similar_index([*current, *data['history']])
        return data

    def event(self, agent, state, description):
        with self.lock:
            self.state['events'].append({'agent': agent, 'state': state, 'description': description,
                                         'at': datetime.now(timezone.utc).isoformat()})
            self.save()

    def start(self, scenario='suite', payload=None, meta=None):
        if scenario == 'upload' and (type(payload) is not bytes or not 1 <= len(payload) <= 1000000):
            raise ValueError('Invalid CSV payload')
        if scenario not in ('suite', 'clean', 'null_total', 'duplicate_order', 'transformation', 'upload'):
            raise ValueError('Unsupported scenario')
        with self.lock:
            if self.state['status'] == 'RUNNING':
                return False
            if self.state['run_id'] is not None and self.state['status'] != 'IDLE':
                archive = {key: self.state[key] for key in ('run_id', 'scenario', 'status', 'started_at', 'finished_at', 'events', 'result', 'error', 'meta')}
                self.state['history'] = [archive, *self.state['history']][:20]
                kept = {self.state['run_id'], *(r['run_id'] for r in self.state['history'])}
                self.state['reviews'] = {k: v for k, v in self.state['reviews'].items() if k in kept}
            self.state.update(status='RUNNING', events=[], result=None, error=None, scenario=scenario,
                run_id=str(uuid4()), started_at=datetime.now(timezone.utc).isoformat(), finished_at=None,
                meta=meta if scenario == 'upload' else None)
            self.save()
        Thread(target=self.run, args=(payload, meta), daemon=True).start()
        return True

    def inspect_csv(self, payload):
        path = self.root / 'evidence.db'
        if not path.exists():
            initialize(path)
        store = IncidentStore(path)
        source = store.record(payload, request_key=self.state['run_id'])
        report = asdict(diagnose_csv(payload))
        record = InvestigationRuns(store).execute(source['incident_id'], default_policy(), request_key=self.state['run_id'])
        if record['trace']['status'] != 'COMPLETED':
            raise ValueError('Incomplete investigation')
        verified = InvestigationRuns(store).read(record['run_id'])
        proposal = {'version':'1', 'run_id':record['run_id'], 'incident_id':source['incident_id'],
            'assessment':record['trace']['assessment'],
            'evidence_sha256':sorted({record['trace']['source_sha256'],
                *(step['report_sha256'] for step in record['trace']['steps'])})}
        verdict = review(verified, proposal)
        if verdict['decision'] != 'ACCEPT':
            raise ValueError('Independent evidence verification rejected')
        analysis = analyze_csv(payload)
        kind = (self.state.get('meta') or {}).get('kind')
        origin = {'synthetic_sample': 'synthetic-sample', 'connected': 'connected-source'}.get(kind, 'local-upload')
        return {'status':'PASS', 'judge':verdict, 'source':origin,
            'write_denials':None,
            'existing_servers_accessed':False, 'live_model_calls':0,
            'cases':[{'case':'upload','assessment':record['trace']['assessment'],'rows':report['row_count'],
                'source_report':report, 'retained_run_id':record['run_id'], 'analysis':analysis,
                'steps':[{'tool':step['tool'],'report_sha256':step['report_sha256'],'report':step['report']}
                         for step in record['trace']['steps']]}]}

    REFERENCE_FOR_CHECK = {
        'missing_column': ('schema-contract', 'schema contract column renamed missing unexpected'),
        'unexpected_column': ('schema-contract', 'schema contract column renamed missing unexpected'),
        'not_null': ('missing-value-guidance', 'empty required value blank order_total identifier'),
        'unique': ('duplicate-guidance', 'duplicate order_id repeated records conflicting'),
        'amount_format': ('amount-format-guidance', 'invalid amount format decimal order_total'),
    }

    def finding_references(self, result):
        """Retrieve one verified, revision-bound reference per finding class that was observed."""
        found = {}
        for case in result.get('cases', []):
            for finding in (case.get('source_report') or {}).get('findings', []):
                source = self.REFERENCE_FOR_CHECK.get(finding['check'])
                if source is None or finding['check'] in found:
                    continue
                allowed = frozenset({source[0]})
                references = self.knowledge.retrieve('local', source[1], allowed_sources=allowed, limit=1)
                if not references or not all(self.knowledge.verify('local', r['citation_sha256'],
                        allowed_sources=allowed) for r in references):
                    raise ValueError('Reference validation failed')
                found[finding['check']] = references
        return found

    def run(self, payload=None, meta=None):
        try:
            csv_mode = payload is not None
            self.event('A09 / Contract check', 'RUNNING', 'Reading local CSV evidence' if csv_mode else 'Opening isolated PostgreSQL source')
            result = self.inspect_csv(payload) if csv_mode else qualify(self.bindir, self.state['scenario'])
            self.event('A09 / Contract check', 'COMPLETED', 'Source checks completed; findings are recorded per scenario')
            if csv_mode:
                self.event('A10 / Data profiling', 'COMPLETED', 'Quality dimensions and record impact computed from exact counts')
                self.event('A26 / Evidence retention', 'COMPLETED', 'Exact input and checks retained with content hashes')
            self.event('A22 / Knowledge retrieval', 'RUNNING', 'Retrieving authorized, revision-bound reference')
            allowed = frozenset({'reconciliation-contract'} if self.state['scenario'] == 'transformation' else {'quality-contract'})
            query = 'transformation reconciliation expected observed' if self.state['scenario'] == 'transformation' else 'source quality missing duplicate'
            references = self.knowledge.retrieve('local', query, allowed_sources=allowed)
            if not references or not all(self.knowledge.verify('local', r['citation_sha256'],
                    allowed_sources=allowed) for r in references):
                raise ValueError('Reference validation failed')
            by_finding = self.finding_references(result) if csv_mode else {}
            self.event('A22 / Knowledge retrieval', 'COMPLETED', 'Reference provenance verified')
            self.event('A27 / Verification', 'COMPLETED', 'Retained CSV evidence and completed checks verified' if csv_mode else 'Expected assessments and three write denials verified')
            cases = result.get('cases', [])
            decision = (result.get('judge') or {}).get('decision', 'ACCEPT' if result.get('status') == 'PASS' else None)
            plan = build_plan(
                tools_run=frozenset(step['tool'] for case in cases for step in case.get('steps', [])),
                source_failed=any(case.get('assessment') == 'SOURCE_QUALITY_FAILURE' for case in cases),
                profiled=any('analysis' in case for case in cases),
                has_actions=any((case.get('analysis') or {}).get('actions') for case in cases),
                judge_decision=decision, retained=any(case.get('retained_run_id') for case in cases))
            with self.lock:
                result = {**result, 'references': references, 'finding_references': by_finding, 'plan': plan,
                          'scope': 'local deterministic inspection; no LLM inference'}
                if csv_mode and meta:
                    result['input'] = meta
                self.state.update(status='COMPLETED', finished_at=datetime.now(timezone.utc).isoformat(), result=result)
                self.save()
        except Exception:
            with self.lock:
                self.state.update(status='FAILED', finished_at=datetime.now(timezone.utc).isoformat(), error='Investigation failed; no source repair or model retry performed.')
                self.save()

    DECISIONS = ('accepted', 'dismissed', 'deferred')

    def review(self, run_id, action_id, decision):
        """Record a human triage decision. It never changes data; it only documents intent."""
        if decision not in self.DECISIONS:
            raise ValueError('Unsupported decision')
        with self.lock:
            run = next((r for r in (self.state, *self.state['history'])
                        if r.get('run_id') == run_id and r.get('result')), None)
            actions = {a['id'] for case in (run or {}).get('result', {}).get('cases', [])
                       for a in (case.get('analysis') or {}).get('actions', [])}
            if run is None or action_id not in actions:
                raise KeyError('Unknown action')
            self.state['reviews'].setdefault(run_id, {})[action_id] = {
                'decision': decision, 'decided_at': datetime.now(timezone.utc).isoformat(), 'reviewer': 'local-user'}
            self.save()


@lru_cache(maxsize=1)
def evaluation_report():
    # Deterministic and independent of any run; computed once per process.
    return json.dumps(evaluate_checks(include_heldout=True)).encode()


def make_server(workbench, token, port=0, catalog=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, body, mime='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                and hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode())
                and self.headers.get('Origin', f'http://127.0.0.1:{self.server.server_port}')
                    == f'http://127.0.0.1:{self.server.server_port}')

        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self.respond(403, b'{}'); return
            pages = ('/', '/overview', '/sources', '/investigations', '/activity', '/knowledge', '/history', '/evidence', '/agents')
            assets = {**{page: ('index.html', 'text/html; charset=utf-8') for page in pages},
                      '/app.js': ('app.js', 'text/javascript'), '/i18n.js': ('i18n.js', 'text/javascript'),
                      '/presentation.js': ('presentation.js', 'text/javascript'), '/charts.js': ('charts.js', 'text/javascript'), '/strings.js': ('strings.js', 'text/javascript'), '/workspace.js': ('workspace.js', 'text/javascript'),
                      '/style.css': ('style.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
            if self.path in assets:
                name, mime = assets[self.path]
                self.respond(200, Path(__file__).with_name(name).read_bytes(), mime)
            elif self.path == '/api/capabilities' and self.authorized():
                self.respond(200, json.dumps(capability_map()).encode())
            elif self.path == '/api/platform' and self.authorized():
                self.respond(200, json.dumps(platform_map()).encode())
            elif self.path == '/api/evaluation' and self.authorized():
                self.respond(200, evaluation_report())
            elif self.path == '/api/sources' and self.authorized():
                listing = {'configured': catalog is not None, 'sources': catalog.sources() if catalog else []}
                self.respond(200, json.dumps(listing).encode())
            elif self.path == '/api/state' and self.authorized():
                self.respond(200, json.dumps(workbench.snapshot()).encode())
            else:
                self.respond(403, b'{}')

        def read_body(self, mime, limit):
            """Return the bounded request body, or None after sending the refusal."""
            if (not self.authorized() or self.headers.get('Transfer-Encoding') is not None
                    or len(self.headers.get_all('Content-Length', [])) != 1
                    or self.headers.get('Content-Type') != mime):
                self.respond(403, b'{}'); return None
            try:
                raw_length = self.headers['Content-Length']
                if not raw_length.isascii() or not raw_length.isdecimal():
                    raise ValueError('Invalid length')
                length = int(raw_length)
                if not 1 <= length <= limit:
                    self.respond(413, b'{}'); return None
                self.connection.settimeout(5)
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError('Incomplete body')
                return payload
            except (ValueError, TimeoutError, OSError):
                self.respond(400, b'{}'); return None

        def source_name(self):
            raw = self.headers.get('X-Source-Name', '')
            cleaned = ''.join(c for c in raw[:80] if c.isprintable() and c not in '<>"\'\\/')
            return cleaned.strip() or None

        def do_POST(self):
            if self.path in ('/api/inspect', '/api/discover'):
                payload = self.read_body('text/csv', 1000000)
                if payload is None:
                    return
                try:
                    if self.path == '/api/discover':
                        self.respond(200, json.dumps(discover_schema(payload)).encode()); return
                    meta = {'kind': 'file', 'name': self.source_name(), 'source_sha256': hashlib.sha256(payload).hexdigest(),
                            'mapping': None}
                    raw_mapping = self.headers.get('X-Column-Mapping')
                    if raw_mapping:
                        if len(raw_mapping) > 512:
                            raise ValueError('Mapping too large')
                        meta['mapping'] = json.loads(raw_mapping)
                        payload = apply_mapping(payload, meta['mapping'])
                    else:
                        diagnose_csv(payload)
                    self.respond(202 if workbench.start('upload', payload, meta) else 409, b'{}')
                except InputRejected as error:
                    self.respond(422, json.dumps({'error': 'INPUT_REJECTED', 'message': str(error)}).encode())
                except (ValueError, TypeError):
                    self.respond(400, b'{}')
                return
            if self.path == '/api/source/compare':
                body = self.read_body('application/json', 2048)
                if body is None:
                    return
                try:
                    if catalog is None:
                        raise InputRejected('No source directory is configured')
                    request = json.loads(body)
                    exports = [catalog.export(request[side]['source'], request[side].get('table')) for side in ('first', 'second')]
                    result = compare_sources(exports[0][0], exports[1][0])
                    result['cardinality'] = join_cardinality(exports[0][0], exports[1][0])
                    result['provenance'] = {'first': exports[0][1], 'second': exports[1][1]}
                    result['complete'] = not any(meta['sampled'] for _, meta in exports)
                    self.respond(200, json.dumps(result).encode())
                except InputRejected as error:
                    self.respond(422, json.dumps({'error': 'INPUT_REJECTED', 'message': str(error)}).encode())
                except (KeyError, ValueError, TypeError, AttributeError):
                    self.respond(400, b'{}')
                return
            if self.path in ('/api/source/tables', '/api/source/discover', '/api/source/inspect'):
                body = self.read_body('application/json', 2048)
                if body is None:
                    return
                try:
                    if catalog is None:
                        raise InputRejected('No source directory is configured')
                    request = json.loads(body)
                    name, table = request['source'], request.get('table')
                    if self.path == '/api/source/tables':
                        self.respond(200, json.dumps(catalog.tables(name)).encode()); return
                    payload, provenance = catalog.export(name, table)
                    if self.path == '/api/source/discover':
                        self.respond(200, json.dumps({**discover_schema(payload), 'provenance': provenance}).encode()); return
                    mapping = request.get('mapping')
                    meta = {'kind': 'connected', 'name': name if table is None else f'{name}:{table}',
                            'source_sha256': hashlib.sha256(payload).hexdigest(), 'mapping': mapping,
                            'provenance': provenance}
                    if mapping:
                        payload = apply_mapping(payload, mapping)
                    else:
                        diagnose_csv(payload)
                    self.respond(202 if workbench.start('upload', payload, meta) else 409, b'{}')
                except InputRejected as error:
                    self.respond(422, json.dumps({'error': 'INPUT_REJECTED', 'message': str(error)}).encode())
                except (KeyError, ValueError, TypeError):
                    self.respond(400, b'{}')
                return
            if self.path == '/api/review':
                body = self.read_body('application/json', 1024)
                if body is None:
                    return
                try:
                    request = json.loads(body)
                    workbench.review(request['run_id'], request['action_id'], request['decision'])
                    self.respond(200, b'{}')
                except KeyError:
                    self.respond(404, b'{}')
                except (ValueError, TypeError):
                    self.respond(400, b'{}')
                return
            if self.path.startswith('/api/sample/'):
                fault = self.path.removeprefix('/api/sample/')
                if (fault not in FAULTS or not self.authorized() or self.headers.get('Content-Length', '0') != '0'
                        or self.headers.get('Transfer-Encoding') is not None):
                    self.respond(403, b'{}'); return
                meta = {'kind': 'synthetic_sample', 'name': 'synthetic-' + fault, 'fault': fault, 'mapping': None}
                self.respond(202 if workbench.start('upload', generate_orders(fault=fault), meta) else 409, b'{}')
                return
            scenario = self.path.removeprefix('/api/run/') if self.path.startswith('/api/run/') else 'suite'
            if (self.path not in ('/api/run', '/api/run/clean', '/api/run/null_total', '/api/run/duplicate_order', '/api/run/transformation') or not self.authorized()
                    or self.headers.get('Content-Length', '0') != '0'
                    or self.headers.get('Transfer-Encoding') is not None):
                self.respond(403, b'{}'); return
            self.respond(202 if workbench.start(scenario) else 409, b'{}')

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--postgres-bindir', required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--source-dir', help='directory whose CSV and SQLite files are exposed read-only')
    args = parser.parse_args()
    workbench = Workbench(args.state_dir, args.postgres_bindir)
    token = secrets.token_urlsafe(32)
    descriptor = os.open(Path(args.state_dir) / 'access-token', os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(token)
    server = make_server(workbench, token, args.port, SourceCatalog(args.source_dir) if args.source_dir else None)
    print(f'Local workbench: http://127.0.0.1:{server.server_port}; access token is in the private state directory.', flush=True)
    server.serve_forever()
