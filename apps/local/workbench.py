# SPDX-License-Identifier: Apache-2.0
"""Authenticated loopback workbench for synthetic PostgreSQL investigations."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
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
            'A finding is an observation, not a causal explanation. Never repair source data automatically.'),))
        self.state = {'status': 'IDLE', 'events': [], 'result': None, 'error': None,
                      'model': 'NOT_CONFIGURED', 'external_spend_usd': 0}
        path = self.root / 'state.json'
        if path.exists():
            self.state = json.loads(path.read_text())
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

    def start(self):
        with self.lock:
            if self.state['status'] == 'RUNNING':
                return False
            self.state.update(status='RUNNING', events=[], result=None, error=None)
            self.save()
        Thread(target=self.run, daemon=True).start()
        return True

    def run(self):
        try:
            self.event('A07 / Source inspection', 'RUNNING', 'Opening isolated PostgreSQL source')
            result = qualify(self.bindir)
            self.event('A07 / Source inspection', 'COMPLETED', 'Three source scenarios retained and checked')
            self.event('A10 / Data quality', 'COMPLETED', 'Missing values and duplicate records detected')
            self.event('A22 / Knowledge retrieval', 'RUNNING', 'Retrieving authorized, revision-bound reference')
            references = self.knowledge.retrieve('local', 'source quality missing duplicate',
                                                allowed_sources=frozenset({'quality-contract'}))
            if not references or not all(self.knowledge.verify('local', r['citation_sha256'],
                    allowed_sources=frozenset({'quality-contract'})) for r in references):
                raise ValueError('Reference validation failed')
            self.event('A22 / Knowledge retrieval', 'COMPLETED', 'Reference provenance verified')
            self.event('A27 / Verification', 'COMPLETED', 'Expected assessments and three write denials verified')
            with self.lock:
                self.state.update(status='COMPLETED', result={**result, 'references': references,
                    'scope': 'synthetic deterministic capability slices; no LLM inference'})
                self.save()
        except Exception:
            with self.lock:
                self.state.update(status='FAILED', error='Investigation failed; no source repair or model retry performed.')
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
                and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token)
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
            if (self.path != '/api/run' or not self.authorized()
                    or self.headers.get('Content-Length', '0') != '0'
                    or self.headers.get('Transfer-Encoding') is not None):
                self.respond(403, b'{}'); return
            self.respond(202 if workbench.start() else 409, b'{}')

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
