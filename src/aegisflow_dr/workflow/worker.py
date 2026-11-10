# SPDX-License-Identifier: Apache-2.0
"""Execute read-only review tasks outside queue write transactions."""
from importlib.resources import files
from importlib.metadata import version
import platform
import sqlite3

from ..coordination.contracts import encode, parse
from ..coordination.judge import review
from ..storage import IntegrityFailure, StoreError
from ..storage.runs import InvestigationRuns
from ..storage.store import canonical, sha
from .model import LeaseLost, QueueError, RetryPolicy
from .queue import ReviewQueue


def workflow_fingerprint():
    root = files('aegisflow_dr')
    names = ('workflow/worker.py', 'workflow/model.py', 'workflow/schema.py', 'workflow/queue.py',
             'coordination/contracts.py', 'coordination/service.py', 'coordination/routing.py', 'coordination/judge.py',
             'batch.py', 'pipeline.py', 'storage/store.py', 'storage/runs.py', 'storage/schema.py',
             'sql/customer_sales_v1.sql', 'sql/customer_sales_exclude_first_v1.sql',
             *(f'coordination/schemas/{name}-v1.json' for name in ('task', 'proposal', 'receipt', 'verdict')))
    return sha(canonical({'modules': {name: sha(root.joinpath(name).read_bytes()) for name in names},
                          'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
                          'jsonschema': version('jsonschema')}))


def enqueue_review(queue: ReviewQueue, runs: InvestigationRuns, payload: bytes, *, request_key: str,
                   retry: RetryPolicy = RetryPolicy()) -> dict:
    proposal = parse('proposal', payload)
    record = runs.read(proposal['run_id'])
    if record['manifest']['request']['incident_id'] != proposal['incident_id']:
        raise QueueError('Review context mismatch')
    return queue.submit(encode('proposal', proposal), request_key=request_key,
                        record_sha256=sha(canonical(record)), workflow_sha256=workflow_fingerprint(), retry=retry)


def _classify(exc):
    if isinstance(exc, IntegrityFailure):
        return 'INTEGRITY_FAILURE'
    if isinstance(exc, sqlite3.OperationalError):
        code = getattr(exc, 'sqlite_errorcode', 0)
        if type(code) is int and code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return 'TEMPORARY_UNAVAILABLE'
    if isinstance(exc, (StoreError, OSError, sqlite3.DatabaseError)):
        return 'EVIDENCE_UNAVAILABLE'
    return 'INTERNAL_ERROR'


def work_once(queue: ReviewQueue, runs: InvestigationRuns, *, owner='local-worker', lease_ms=30_000) -> dict:
    lease = queue.reserve(owner, lease_ms=lease_ms)
    if lease is None:
        return {'outcome': 'IDLE'}
    try:
        manifest = queue.context(lease)
        failure = None
        if manifest['workflow_sha256'] != workflow_fingerprint():
            failure = 'VERSION_MISMATCH'
        else:
            request = manifest['request']
            try:
                record = runs.read(request['proposal']['run_id'])
                if (record['manifest']['request']['incident_id'] != request['proposal']['incident_id']
                        or sha(canonical(record)) != request['record_sha256']):
                    failure = 'INTEGRITY_FAILURE'
                elif lease.task_id == 'collect':
                    result = {'run_id': record['run_id'], 'record_sha256': request['record_sha256']}
                else:
                    result = review(record, request['proposal'])
            except Exception as exc:
                # Do not put file paths, data, exception messages or tokens into history.
                failure = _classify(exc)
        if failure:
            job = queue.fail(lease, failure)
        else:
            job = queue.complete(lease, result)
        return {'outcome': 'APPLIED', 'job_id': lease.job_id, 'task_id': lease.task_id,
                'task_state': job['tasks'][lease.task_id]['state'], 'job_status': job['status']}
    except LeaseLost:
        # Cancellation/expiry/reassignment wins even if a read already finished.
        return {'outcome': 'LEASE_LOST', 'job_id': lease.job_id, 'task_id': lease.task_id}
