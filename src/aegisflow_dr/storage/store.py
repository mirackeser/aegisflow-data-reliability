# SPDX-License-Identifier: Apache-2.0
"""Append-only local research records; not authenticated or tamper-proof storage."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import os
import platform
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from ..pipeline import MAX_INPUT_BYTES, diagnose_csv

APPLICATION_ID = 1095124051
SCHEMA_VERSION = 1


class StoreError(ValueError):
    """A rejected operation on the local research store."""


class IntegrityFailure(StoreError):
    """Stored bytes, references or events do not match their recorded digests."""


class VersionMismatch(StoreError):
    """The recorded diagnostic implementation is unavailable for exact replay."""


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def engine_fingerprint() -> str:
    return sha(canonical({'pipeline_sha256': sha(files('aegisflow_dr').joinpath('pipeline.py').read_bytes()),
                          'python': platform.python_version(),
                          'implementation': platform.python_implementation()}))


def _schema() -> str:
    ddl = '''
CREATE TABLE incidents (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
 manifest BLOB NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE evidence (
 incident_id TEXT NOT NULL REFERENCES incidents(id), id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('source_csv','diagnostic_report')),
 content BLOB NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(incident_id,id), UNIQUE(incident_id,kind)
);
CREATE TABLE claims (
 incident_id TEXT NOT NULL REFERENCES incidents(id), id TEXT NOT NULL,
 content BLOB NOT NULL, PRIMARY KEY(incident_id,id)
);
CREATE TABLE claim_evidence (
 incident_id TEXT NOT NULL, claim_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
 PRIMARY KEY(incident_id,claim_id,evidence_id),
 FOREIGN KEY(incident_id,claim_id) REFERENCES claims(incident_id,id),
 FOREIGN KEY(incident_id,evidence_id) REFERENCES evidence(incident_id,id)
);
CREATE TABLE events (
 incident_id TEXT NOT NULL REFERENCES incidents(id), revision INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('RECEIVED','DIAGNOSED','CLOSED')),
 content BLOB NOT NULL, previous_sha256 TEXT, sha256 TEXT NOT NULL,
 PRIMARY KEY(incident_id,revision)
);
'''
    for table in ('incidents', 'evidence', 'claims', 'claim_evidence', 'events'):
        for operation in ('UPDATE', 'DELETE'):
            ddl += (f'CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} '
                    f"ON {table} BEGIN SELECT RAISE(ABORT,'immutable record'); END;\n")
    return ddl


def _schema_signature(connection) -> tuple:
    return tuple(connection.execute("SELECT type,name,sql FROM sqlite_master "
                                    "WHERE sql IS NOT NULL ORDER BY type,name"))


@lru_cache(maxsize=1)
def _expected_schema() -> tuple:
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.executescript(_schema())
        return _schema_signature(connection)


def initialize(path: Path) -> None:
    """Create a new private database; never adopt or overwrite an existing file."""
    path = Path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript('BEGIN IMMEDIATE;\n' + _schema()
                                 + f'PRAGMA application_id={APPLICATION_ID};\n'
                                 + f'PRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;')


def _claims(report: dict) -> list[dict]:
    claims = [{'id': 'summary', 'kind': 'source_quality_summary',
               'status': report['status'], 'finding_count': report['finding_count'],
               'findings_truncated': report['findings_truncated']}]
    for index, finding in enumerate(report['findings']):
        claims.append({'id': f'finding-{index:03}', 'kind': 'source_quality_observation',
                       'finding_index': index, **finding})
    return claims


def _links(claims: list[dict]) -> list[list[str]]:
    return [[claim['id'], evidence] for claim in claims for evidence in ('report', 'source')]


def _event(case_id, revision, kind, content, previous):
    event = {'incident_id': case_id, 'revision': revision, 'kind': kind,
             'content': content, 'previous_sha256': previous}
    return event, sha(canonical(event))


class IncidentStore:
    """Each operation uses its own connection and explicit write transaction.

    The file owner and Python host are trusted. No network service, tenant ACL,
    hard isolation, encrypted storage or externally anchored audit is provided.
    """
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        with self._connect():
            pass

    @contextmanager
    def _connect(self, *, write=False):
        mode = 'rw' if write else 'ro'
        uri = self.path.as_uri() + '?mode=' + mode
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                    or connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION
                    or _schema_signature(connection) != _expected_schema()):
                raise StoreError('Unsupported store schema')
            if write:
                connection.execute('BEGIN IMMEDIATE')
            else:
                connection.execute('BEGIN')
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def record(self, payload: bytes, *, request_key: str) -> dict:
        if (type(request_key) is not str
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', request_key)):
            raise StoreError('Invalid idempotency key')
        if type(payload) is not bytes or len(payload) > MAX_INPUT_BYTES:
            raise StoreError('Invalid source bytes')
        with self._connect(write=True) as connection:
            old = connection.execute('SELECT id FROM incidents WHERE request_key=?',
                                     (request_key,)).fetchone()
            if old:
                record, source = self._load(connection, old[0])
                if source != payload:
                    raise StoreError('Idempotency conflict')
                return record
            # Diagnosis and persistence form one transaction; no half-created case.
            report = json.loads(diagnose_csv(payload).to_json())
            report_bytes = canonical(report)
            claims = _claims(report)
            links = _links(claims)
            manifest = {'format_version': '1', 'request_key': request_key, 'engine_fingerprint': engine_fingerprint(),
                        'source_sha256': sha(payload), 'report_sha256': sha(report_bytes),
                        'claims': claims, 'links': links}
            case_id = str(uuid4())
            connection.execute('INSERT INTO incidents VALUES (?,?,?,?)',
                               (case_id, request_key, canonical(manifest), sha(canonical(manifest))))
            for evidence_id, kind, content in [('source', 'source_csv', payload),
                                               ('report', 'diagnostic_report', report_bytes)]:
                connection.execute('INSERT INTO evidence VALUES (?,?,?,?,?)',
                                   (case_id, evidence_id, kind, content, sha(content)))
            for claim in claims:
                connection.execute('INSERT INTO claims VALUES (?,?,?)',
                                   (case_id, claim['id'], canonical(claim)))
            connection.executemany('INSERT INTO claim_evidence VALUES (?,?,?)',
                                   [(case_id, claim, evidence) for claim, evidence in links])
            previous = None
            for revision, kind, content in [(1, 'RECEIVED', {'manifest_sha256': sha(canonical(manifest))}),
                                             (2, 'DIAGNOSED', {'source_status': report['status']})]:
                previous = self._append(connection, case_id, revision, kind, content, previous)
            return self._load(connection, case_id)[0]

    @staticmethod
    def _append(connection, case_id, revision, kind, content, previous):
        body = {**content, 'recorded_at': datetime.now(timezone.utc).isoformat()}
        _, checksum = _event(case_id, revision, kind, body, previous)
        connection.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                           (case_id, revision, kind, canonical(body), previous, checksum))
        return checksum

    def _load(self, connection, case_id) -> tuple[dict, bytes]:
        if (type(case_id) is not str
                or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', case_id)):
            raise StoreError('Invalid incident identity')
        row = connection.execute('SELECT manifest,manifest_sha256,request_key FROM incidents WHERE id=?',
                                 (case_id,)).fetchone()
        if row is None:
            raise StoreError('Unknown incident')
        try:
            manifest_bytes, manifest_hash, request_key = row
            if sha(manifest_bytes) != manifest_hash:
                raise IntegrityFailure('Manifest checksum mismatch')
            manifest = json.loads(manifest_bytes)
            if (manifest['format_version'] != '1' or manifest['request_key'] != request_key
                    or not re.fullmatch(r'[0-9a-f]{64}', manifest['engine_fingerprint'])):
                raise IntegrityFailure('Manifest contract mismatch')
            evidence = {r[0]: r[1:] for r in connection.execute(
                'SELECT id,kind,content,sha256 FROM evidence WHERE incident_id=?', (case_id,))}
            if set(evidence) != {'source', 'report'}:
                raise IntegrityFailure('Incomplete evidence')
            for evidence_id, expected_kind in [('source', 'source_csv'), ('report', 'diagnostic_report')]:
                kind, content, checksum = evidence[evidence_id]
                if kind != expected_kind or sha(content) != checksum:
                    raise IntegrityFailure('Evidence checksum mismatch')
                if checksum != manifest[evidence_id + '_sha256']:
                    raise IntegrityFailure('Evidence manifest mismatch')
            source, report_bytes = evidence['source'][1], evidence['report'][1]
            report = json.loads(report_bytes)
            if report['source_sha256'] != sha(source) or report['source_bytes'] != len(source):
                raise IntegrityFailure('Report source mismatch')
            claims = []
            for claim_id, content in connection.execute(
                    'SELECT id,content FROM claims WHERE incident_id=? ORDER BY id', (case_id,)):
                claim = json.loads(content)
                if claim['id'] != claim_id:
                    raise IntegrityFailure('Claim identity mismatch')
                claims.append(claim)
            links = [list(r) for r in connection.execute(
                'SELECT claim_id,evidence_id FROM claim_evidence WHERE incident_id=? '
                'ORDER BY claim_id,evidence_id', (case_id,))]
            ordered = lambda items: sorted(items, key=lambda c: c['id'])
            if (ordered(claims) != ordered(manifest['claims'])
                    or ordered(claims) != ordered(_claims(report))
                    or links != sorted(manifest['links']) or links != sorted(_links(claims))):
                raise IntegrityFailure('Claim evidence mismatch')
            events = []
            previous = None
            for revision, kind, content_bytes, prev, checksum in connection.execute(
                    'SELECT revision,kind,content,previous_sha256,sha256 FROM events '
                    'WHERE incident_id=? ORDER BY revision', (case_id,)):
                event, actual = _event(case_id, revision, kind, json.loads(content_bytes), prev)
                if revision != len(events) + 1 or prev != previous or actual != checksum:
                    raise IntegrityFailure('Event chain mismatch')
                events.append({**event, 'sha256': checksum})
                previous = checksum
            if [e['kind'] for e in events] not in (['RECEIVED', 'DIAGNOSED'],
                                                   ['RECEIVED', 'DIAGNOSED', 'CLOSED']):
                raise IntegrityFailure('Invalid lifecycle')
            if (events[0]['content']['manifest_sha256'] != manifest_hash
                    or events[1]['content']['source_status'] != report['status']):
                raise IntegrityFailure('Event evidence mismatch')
            return {'incident_id': case_id, 'state': events[-1]['kind'],
                    'revision': len(events), 'manifest': manifest, 'report': report,
                    'events': events}, source
        except (KeyError, TypeError, IndexError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IntegrityFailure('Invalid stored record') from exc

    def read(self, case_id: str) -> dict:
        with self._connect() as connection:
            return self._load(connection, case_id)[0]

    def replay(self, case_id: str) -> dict:
        with self._connect() as connection:
            record, source = self._load(connection, case_id)
        if record['manifest']['engine_fingerprint'] != engine_fingerprint():
            raise VersionMismatch('Exact diagnostic implementation is unavailable')
        current = canonical(json.loads(diagnose_csv(source).to_json()))
        return {'incident_id': case_id,
                'outcome': 'MATCH' if sha(current) == record['manifest']['report_sha256'] else 'MISMATCH',
                'expected_sha256': record['manifest']['report_sha256'], 'actual_sha256': sha(current)}

    def close(self, case_id: str, *, expected_revision: int, actor: str) -> dict:
        if (type(expected_revision) is not int or type(actor) is not str
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', actor)):
            raise StoreError('Invalid closure request')
        with self._connect(write=True) as connection:
            record, _ = self._load(connection, case_id)
            if record['revision'] != expected_revision or record['state'] != 'DIAGNOSED':
                raise StoreError('Lifecycle revision conflict')
            self._append(connection, case_id, 3, 'CLOSED', {'local_actor_label': actor},
                         record['events'][-1]['sha256'])
            return self._load(connection, case_id)[0]
