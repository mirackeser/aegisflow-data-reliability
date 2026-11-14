# SPDX-License-Identifier: Apache-2.0
"""Authenticated loopback workbench for synthetic PostgreSQL investigations."""
import argparse
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
                'A mismatch is evidence of loss or inconsistent transformation, not proof of a causal root cause.')))
        self.state = {'status': 'IDLE', 'events': [], 'result': None, 'error': None,
                      'model': 'NOT_CONFIGURED', 'external_spend_usd': 0, 'history': [], 'scenario': 'suite',
                      'run_id': None, 'started_at': None, 'finished_at': None}
        path = self.root / 'state.json'
        if path.exists():
            self.state.update(json.loads(path.read_text()))
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
            return json.loads(json.dumps(self.state))

    def event(self, agent, state, description):
        with self.lock:
            self.state['events'].append({'agent': agent, 'state': state, 'description': description})
            self.save()

    def start(self, scenario='suite'):
        if scenario not in ('suite', 'clean', 'null_total', 'duplicate_order', 'transformation'):
            raise ValueError('Unsupported scenario')
        with self.lock:
            if self.state['status'] == 'RUNNING':
                return False
            if self.state['run_id'] is not None and self.state['status'] != 'IDLE':
                archive = {key: self.state[key] for key in ('run_id', 'scenario', 'status', 'started_at', 'finished_at', 'events', 'result', 'error')}
                self.state['history'] = [archive, *self.state['history']][:20]
            self.state.update(status='RUNNING', events=[], result=None, error=None, scenario=scenario,
                run_id=str(uuid4()), started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)
            self.save()
        Thread(target=self.run, daemon=True).start()
        return True

    def run(self):
        try:
            self.event('A07 / Source inspection', 'RUNNING', 'Opening isolated PostgreSQL source')
            result = qualify(self.bindir, self.state['scenario'])
            self.event('A07 / Source inspection', 'COMPLETED', 'Selected source scenarios checked against retained evidence')
            self.event('A10 / Data quality', 'COMPLETED', 'Source checks completed; findings are recorded per scenario')
            self.event('A22 / Knowledge retrieval', 'RUNNING', 'Retrieving authorized, revision-bound reference')
            allowed = frozenset({'reconciliation-contract'} if self.state['scenario'] == 'transformation' else {'quality-contract'})
            query = 'transformation reconciliation expected observed' if self.state['scenario'] == 'transformation' else 'source quality missing duplicate'
            references = self.knowledge.retrieve('local', query, allowed_sources=allowed)
            if not references or not all(self.knowledge.verify('local', r['citation_sha256'],
                    allowed_sources=allowed) for r in references):
                raise ValueError('Reference validation failed')
            self.event('A22 / Knowledge retrieval', 'COMPLETED', 'Reference provenance verified')
            self.event('A27 / Verification', 'COMPLETED', 'Expected assessments and three write denials verified')
            with self.lock:
                self.state.update(status='COMPLETED', finished_at=datetime.now(timezone.utc).isoformat(), result={**result, 'references': references,
                    'scope': 'synthetic deterministic capability slices; no LLM inference'})
                self.save()
        except Exception:
            with self.lock:
                self.state.update(status='FAILED', finished_at=datetime.now(timezone.utc).isoformat(), error='Investigation failed; no source repair or model retry performed.')
                self.save()


def make_server(workbench, token, port=0):
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
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if self.path in assets:
                name, mime = assets[self.path]
                self.respond(200, Path(__file__).with_name(name).read_bytes(), mime)
            elif self.path == '/api/state' and self.authorized():
                self.respond(200, json.dumps(workbench.snapshot()).encode())
            else:
                self.respond(403, b'{}')

        def do_POST(self):
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
    args = parser.parse_args()
    workbench = Workbench(args.state_dir, args.postgres_bindir)
    token = secrets.token_urlsafe(32)
    descriptor = os.open(Path(args.state_dir) / 'access-token', os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(token)
    server = make_server(workbench, token, args.port)
    print(f'Local workbench: http://127.0.0.1:{server.server_port}; access token is in the private state directory.', flush=True)
    server.serve_forever()
