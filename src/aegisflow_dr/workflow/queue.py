# SPDX-License-Identifier: Apache-2.0
"""Atomic local reservations, fenced results, bounded retries and immutable history."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import secrets
import sqlite3
from time import time_ns
from uuid import uuid4

from ..coordination.contracts import encode, parse
from ..coordination.routing import TaskGraph
from ..coordination.service import review_tasks
from ..storage.store import canonical, sha
from . import schema
from .model import (Lease, LeaseLost, QueueError, QueueIntegrityError, RetryPolicy,
                    MAX_ACTIVE, MAX_BYTES, MAX_EVENTS, REASONS, TERMINAL, digest,
                    identifier, initial, milliseconds, status, uuid, validate_projection, validate_result)

KINDS = frozenset({'SUBMITTED', 'RESERVED', 'RENEWED', 'COMPLETED', 'RETRY_SCHEDULED',
                   'FAILED', 'RECOVERED', 'CANCELLED'})


class ReviewQueue:
    """Trusted host API; reservation tokens are fences, not remote credentials."""
    def __init__(self, path: Path, *, clock=lambda: time_ns() // 1_000_000):
        self.path, self.clock = Path(path).resolve(), clock
        with self._connect():
            pass

    @contextmanager
    def _connect(self, *, write=False):
        # A hot rollback journal requires pager writes even before a SELECT.
        # mode=rw permits crash recovery without implicitly creating a file.
        uri = self.path.as_uri() + '?mode=rw'
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                schema.validate(connection)
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _now(self, projection=None):
        now = milliseconds(self.clock())
        if projection is not None and now < projection['updated_ms']:
            raise QueueError('Scheduler clock moved backwards')
        return now

    def submit(self, payload: bytes, *, request_key: str, record_sha256: str,
               workflow_sha256: str, retry: RetryPolicy = RetryPolicy()) -> dict:
        proposal = parse('proposal', payload)
        proposal['evidence_sha256'].sort()
        identifier(request_key)
        if not digest(record_sha256) or not digest(workflow_sha256) or type(retry) is not RetryPolicy:
            raise QueueError('Invalid host submission')
        request = {'proposal': proposal, 'record_sha256': record_sha256, 'retry': retry.mapping()}
        with self._connect(write=True) as connection:
            old = connection.execute('SELECT id FROM jobs WHERE request_key=?', (request_key,)).fetchone()
            if old:
                manifest, projection, events = self._load(connection, old[0])
                if canonical(manifest['request']) != canonical(request):
                    raise QueueError('Job idempotency conflict')
                return self._public(manifest, projection, events)
            count = connection.execute("SELECT count(*) FROM projections WHERE status IN ('QUEUED','RUNNING')").fetchone()[0]
            if count >= MAX_ACTIVE:
                raise QueueError('Active queue capacity exhausted')
            now, job_id = self._now(), str(uuid4())
            tasks = review_tasks(proposal)
            TaskGraph(tasks)
            manifest = {'version': '1', 'job_id': job_id, 'request_key': request_key,
                        'request': request, 'tasks': tasks, 'workflow_sha256': workflow_sha256, 'created_ms': now}
            content = canonical(manifest)
            if len(content) > MAX_BYTES:
                raise QueueError('Job manifest exceeds budget')
            connection.execute('INSERT INTO jobs VALUES (?,?,?,?)', (job_id, request_key, content, sha(content)))
            projection = initial(now)
            self._persist(connection, manifest, projection, 'SUBMITTED', now, create=True)
            return self._public(*self._load(connection, job_id))

    def _load(self, connection, job_id):
        uuid(job_id)
        row = connection.execute('SELECT request_key,manifest,sha256 FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise QueueError('Unknown job')
        try:
            key, data, checksum = row
            if type(data) is not bytes or len(data) > MAX_BYTES or sha(data) != checksum:
                raise ValueError('Manifest mismatch')
            manifest = json.loads(data)
            if (set(manifest) != {'version', 'job_id', 'request_key', 'request', 'tasks', 'workflow_sha256', 'created_ms'}
                    or manifest['version'] != '1' or manifest['job_id'] != job_id
                    or manifest['request_key'] != key or not digest(manifest['workflow_sha256'])
                    or set(manifest['request']) != {'proposal', 'record_sha256', 'retry'}
                    or not digest(manifest['request']['record_sha256'])):
                raise ValueError('Manifest binding mismatch')
            identifier(key)
            milliseconds(manifest['created_ms'])
            request = manifest['request']
            parse('proposal', encode('proposal', request['proposal']))
            RetryPolicy(**request['retry'])
            if canonical(manifest['tasks']) != canonical(review_tasks(request['proposal'])):
                raise ValueError('Unsupported job graph')
            TaskGraph(manifest['tasks'])
            projection_row = connection.execute('SELECT status,content,sha256 FROM projections WHERE job_id=?', (job_id,)).fetchone()
            state, data, checksum = projection_row
            if type(data) is not bytes or len(data) > MAX_BYTES or sha(data) != checksum:
                raise ValueError('Projection checksum mismatch')
            projection = json.loads(data)
            validate_projection(projection, manifest)
            if status(projection) != state:
                raise ValueError('Projection status mismatch')
            events = []
            previous, last_time = None, manifest['created_ms']
            rows = connection.execute('SELECT revision,content,sha256 FROM events WHERE job_id=? ORDER BY revision', (job_id,)).fetchmany(MAX_EVENTS + 1)
            if not 1 <= len(rows) <= MAX_EVENTS:
                raise ValueError('Invalid history bounds')
            for revision, data, checksum in rows:
                if type(data) is not bytes or len(data) > MAX_BYTES + 1024 or sha(data) != checksum:
                    raise ValueError('Event checksum mismatch')
                event = json.loads(data)
                if (set(event) != {'version', 'job_id', 'revision', 'kind', 'at_ms', 'previous_sha256', 'projection'}
                        or event['version'] != '1' or event['job_id'] != job_id
                        or revision != len(events) + 1 or event['revision'] != revision
                        or event['previous_sha256'] != previous or event['kind'] not in KINDS
                        or event['at_ms'] < last_time or event['projection']['updated_ms'] != event['at_ms']):
                    raise ValueError('Event chain mismatch')
                validate_projection(event['projection'], manifest)
                if revision == 1 and (event['kind'] != 'SUBMITTED' or event['projection'] != initial(manifest['created_ms'])):
                    raise ValueError('Invalid initial event')
                previous, last_time = checksum, event['at_ms']
                events.append({'revision': revision, 'kind': event['kind'], 'at_ms': last_time, 'sha256': checksum})
            if canonical(event['projection']) != canonical(projection):
                raise ValueError('Projection differs from immutable history')
            return manifest, projection, events
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise QueueIntegrityError('Queue integrity verification failed') from None

    def _persist(self, connection, manifest, projection, kind, now, *, create=False):
        if kind not in KINDS:
            raise QueueError('Invalid event kind')
        projection['updated_ms'] = now
        validate_projection(projection, manifest)
        last = connection.execute('SELECT revision,sha256 FROM events WHERE job_id=? ORDER BY revision DESC LIMIT 1',
                                  (manifest['job_id'],)).fetchone()
        revision = last[0] + 1 if last else 1
        if revision > MAX_EVENTS:
            raise QueueError('Job history budget exhausted')
        event = {'version': '1', 'job_id': manifest['job_id'], 'revision': revision,
                 'kind': kind, 'at_ms': now, 'previous_sha256': last[1] if last else None, 'projection': projection}
        data = canonical(projection)
        values = (status(projection), data, sha(data), manifest['job_id'])
        if create:
            connection.execute('INSERT INTO projections(status,content,sha256,job_id) VALUES (?,?,?,?)', values)
        else:
            connection.execute('UPDATE projections SET status=?,content=?,sha256=? WHERE job_id=?', values)
        content = canonical(event)
        connection.execute('INSERT INTO events VALUES (?,?,?,?)', (manifest['job_id'], revision, content, sha(content)))

    @staticmethod
    def _public(manifest, projection, events):
        public_tasks = {key: {name: value for name, value in task.items() if name != 'lease_hash'}
                        for key, task in projection['tasks'].items()}
        return {'version': '1', 'job_id': manifest['job_id'], 'request_key': manifest['request_key'],
                'status': status(projection), 'workflow_sha256': manifest['workflow_sha256'],
                'request': manifest['request'], 'tasks': public_tasks,
                'updated_ms': projection['updated_ms'], 'history': events}

    def read(self, job_id):
        with self._connect() as connection:
            return self._public(*self._load(connection, job_id))

    @staticmethod
    def _release(task):
        task['lease_hash'], task['lease_until_ms'] = None, None

    @staticmethod
    def _block(projection):
        if projection['tasks']['collect']['state'] == 'FAILED':
            judge = projection['tasks']['judge']
            judge.update(state='BLOCKED', reason='DEPENDENCY_FAILED')

    def _failure(self, projection, key, reason, manifest, now):
        task = projection['tasks'][key]
        retry = RetryPolicy(**manifest['request']['retry'])
        self._release(task)
        if reason in {'TEMPORARY_UNAVAILABLE', 'LEASE_EXPIRED'} and task['attempt'] < retry.max_attempts:
            task.update(state='RETRY_WAIT', reason=reason, ready_at_ms=now + retry.delay(task['attempt']))
        else:
            task.update(state='FAILED', reason=reason)
        self._block(projection)

    def _recover(self, connection, manifest, projection, now):
        expired = [key for key, task in projection['tasks'].items()
                   if task['state'] == 'LEASED' and now >= task['lease_until_ms']]
        for key in expired:
            self._failure(projection, key, 'LEASE_EXPIRED', manifest, now)
        if expired:
            self._persist(connection, manifest, projection, 'RECOVERED', now)

    def recover(self, job_id):
        with self._connect(write=True) as connection:
            manifest, projection, _ = self._load(connection, job_id)
            self._recover(connection, manifest, projection, self._now(projection))
            return self._public(*self._load(connection, job_id))

    def reserve(self, owner: str, *, lease_ms=30_000) -> Lease | None:
        identifier(owner)
        self._duration(lease_ms)
        with self._connect(write=True) as connection:
            ids = connection.execute("SELECT job_id FROM projections WHERE status IN ('QUEUED','RUNNING') ORDER BY rowid LIMIT ?",
                                     (MAX_ACTIVE,)).fetchall()
            for (job_id,) in ids:
                manifest, projection, _ = self._load(connection, job_id)
                now = self._now(projection)
                self._recover(connection, manifest, projection, now)
                graph = TaskGraph(manifest['tasks'])
                for key in graph.order:
                    task = projection['tasks'][key]
                    dependencies = graph.task(key)['depends_on']
                    if (task['state'] not in {'PENDING', 'RETRY_WAIT'} or task['ready_at_ms'] > now
                            or any(projection['tasks'][d]['state'] != 'SUCCEEDED' for d in dependencies)):
                        continue
                    token = secrets.token_hex(32)
                    task.update(state='LEASED', attempt=task['attempt'] + 1, fence=task['fence'] + 1,
                                owner=owner, lease_hash=sha(token.encode()), lease_until_ms=now + lease_ms,
                                renewals=0, reason=None)
                    self._persist(connection, manifest, projection, 'RESERVED', now)
                    return Lease(job_id, key, task['fence'], owner, token)
        return None

    @staticmethod
    def _duration(value):
        if type(value) is not int or not 1 <= value <= 60_000:
            raise QueueError('Invalid reservation duration')

    def _active(self, connection, lease):
        if type(lease) is not Lease:
            raise LeaseLost('Reservation is unavailable')
        manifest, projection, _ = self._load(connection, lease.job_id)
        now = self._now(projection)
        task = projection['tasks'].get(lease.task_id)
        if (task is None or task['state'] != 'LEASED' or task['fence'] != lease.fence or task['owner'] != lease.owner
                or type(lease.fence) is not int or not digest(lease.token) or not secrets.compare_digest(task['lease_hash'], sha(lease.token.encode()))
                or now >= task['lease_until_ms']):
            raise LeaseLost('Reservation is unavailable')
        return manifest, projection, task, now

    def context(self, lease):
        with self._connect() as connection:
            manifest, _, _, _ = self._active(connection, lease)
            return manifest

    def renew(self, lease, *, lease_ms=30_000):
        self._duration(lease_ms)
        with self._connect(write=True) as connection:
            manifest, projection, task, now = self._active(connection, lease)
            if task['renewals'] >= 3:
                raise QueueError('Reservation renewal budget exhausted')
            task.update(lease_until_ms=max(task['lease_until_ms'], now + lease_ms), renewals=task['renewals'] + 1)
            self._persist(connection, manifest, projection, 'RENEWED', now)
            return self._public(*self._load(connection, lease.job_id))

    def complete(self, lease, result):
        with self._connect(write=True) as connection:
            manifest, projection, task, now = self._active(connection, lease)
            result = validate_result(lease.task_id, result, manifest)
            self._release(task)
            task.update(state='SUCCEEDED', result=result, reason=None)
            self._persist(connection, manifest, projection, 'COMPLETED', now)
            return self._public(*self._load(connection, lease.job_id))

    def fail(self, lease, reason):
        if type(reason) is not str or reason not in REASONS - {'LEASE_EXPIRED', 'DEPENDENCY_FAILED', 'OPERATOR_CANCELLED'}:
            raise QueueError('Invalid failure reason')
        with self._connect(write=True) as connection:
            manifest, projection, _, now = self._active(connection, lease)
            self._failure(projection, lease.task_id, reason, manifest, now)
            kind = 'RETRY_SCHEDULED' if projection['tasks'][lease.task_id]['state'] == 'RETRY_WAIT' else 'FAILED'
            self._persist(connection, manifest, projection, kind, now)
            return self._public(*self._load(connection, lease.job_id))

    def cancel(self, job_id):
        with self._connect(write=True) as connection:
            manifest, projection, events = self._load(connection, job_id)
            current = status(projection)
            if current == 'CANCELLED':
                return self._public(manifest, projection, events)
            if current in {'SUCCEEDED', 'FAILED'}:
                raise QueueError('Completed job cannot be cancelled')
            now = self._now(projection)
            projection['cancelled'] = True
            for task in projection['tasks'].values():
                if task['state'] not in TERMINAL:
                    self._release(task)
                    task.update(state='CANCELLED', reason='OPERATOR_CANCELLED')
            self._persist(connection, manifest, projection, 'CANCELLED', now)
            return self._public(*self._load(connection, job_id))
