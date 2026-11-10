# SPDX-License-Identifier: Apache-2.0
"""Two local specialist slices over verified retained investigation evidence."""
import sqlite3

from ..storage import StoreError
from ..storage.runs import InvestigationRuns
from ..storage.store import canonical, sha
from .contracts import encode, parse
from .judge import abstain, review
from .routing import TaskGraph


def review_saved_run(runs: InvestigationRuns, payload: bytes) -> dict:
    """Read-only simulation: no network, retries, model calls or durable job state."""
    proposal = parse('proposal', payload)
    tasks = review_tasks(proposal)
    graph = TaskGraph(tasks)
    receipts = []
    record = None
    verdict = abstain(proposal['run_id'])
    failed = set()
    for key in graph.order:
        task = graph.task(key)
        reason = None
        result_hash = None
        if failed.intersection(task['depends_on']):
            state, reason = 'BLOCKED', 'DEPENDENCY_FAILED'
        elif key == 'collect':
            try:
                record = runs.read(proposal['run_id'])
                if record['manifest']['request']['incident_id'] != proposal['incident_id']:
                    raise StoreError('Context binding rejected')
                state, result_hash = 'COMPLETED', sha(canonical(record))
            except (StoreError, OSError, sqlite3.DatabaseError):
                state, reason = 'FAILED', 'RUN_UNAVAILABLE'
        else:
            verdict = review(record, proposal)
            state, result_hash = 'COMPLETED', sha(encode('verdict', verdict))
        if state != 'COMPLETED':
            failed.add(key)
        receipt = {'version': '1', 'task_id': key, 'agent_id': graph.assignments[key].agent_id,
                   'state': state, 'result_sha256': result_hash, 'reason': reason}
        receipts.append(parse('receipt', encode('receipt', receipt)))
    return {'version': '1', 'transport': 'in-process', 'durable_job': False,
            'tasks': [graph.task(key) for key in graph.order], 'receipts': receipts, 'verdict': verdict}


def review_tasks(proposal: dict) -> list[dict]:
    """Host-owned graph shared by immediate and durable review paths."""
    return [
        {'version': '1', 'task_id': 'collect', 'incident_id': proposal['incident_id'],
         'run_id': proposal['run_id'], 'capability': 'evidence.read',
         'required_tags': ['read-only', 'retained-evidence'], 'depends_on': []},
        {'version': '1', 'task_id': 'judge', 'incident_id': proposal['incident_id'],
         'run_id': proposal['run_id'], 'capability': 'assessment.review',
         'required_tags': ['read-only', 'verification'], 'depends_on': ['collect']},
    ]
