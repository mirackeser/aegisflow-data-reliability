# SPDX-License-Identifier: Apache-2.0
"""Atomic, immutable investigation runs with retained batch evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from time import monotonic
from uuid import uuid4

from ..batch import BatchSnapshot, TRANSFORMS
from ..gateway import ToolPolicy
from ..investigation import (investigate, implementation_fingerprint,
                             policy_manifest, validate_snapshots)
from .schema import validate_schema
from .store import IncidentStore, IntegrityFailure, StoreError, VersionMismatch, canonical, sha

MAX_TRACE_BYTES = 4_000_000


def _policy(value: dict) -> ToolPolicy:
    if type(value) is not dict or set(value) != {'grants', 'max_calls', 'max_input_bytes', 'timeout_seconds'}:
        raise StoreError('Invalid retained policy')
    grants = value['grants']
    if (type(grants) is not list or any(type(g) is not list or len(g) != 2
                                       or any(type(x) is not str for x in g) for g in grants)):
        raise StoreError('Invalid retained grants')
    policy = ToolPolicy(frozenset(tuple(g) for g in grants), value['max_calls'],
                        value['max_input_bytes'], value['timeout_seconds'])
    if canonical(policy_manifest(policy)) != canonical(value):
        raise StoreError('Noncanonical retained grants')
    return policy


def _binding(trace: dict, incident: dict, policy: ToolPolicy, snapshots: tuple[BatchSnapshot, ...]) -> None:
    """Verify stored references without rerunning tools or assuming current model semantics."""
    if (type(trace) is not dict or set(trace) != {'incident_id', 'source_sha256', 'status', 'assessment', 'reason', 'calls_used',
                       'steps', 'observations', 'policy_sha256', 'implementation_sha256', 'workflow_version'}
            or trace['incident_id'] != incident['incident_id']
            or trace['source_sha256'] != incident['manifest']['source_sha256']
            or trace['policy_sha256'] != sha(canonical(policy_manifest(policy)))
            or type(trace['calls_used']) is not int or not 0 <= trace['calls_used'] <= policy.max_calls
            or type(trace['implementation_sha256']) is not str
            or not re.fullmatch(r'[0-9a-f]{64}', trace['implementation_sha256'])
            or trace['workflow_version'] != 'bounded-investigation-v1'
            or trace['status'] not in {'COMPLETED', 'INCONCLUSIVE'}):
        raise IntegrityFailure('Investigation binding mismatch')
    if trace['status'] == 'INCONCLUSIVE':
        if trace['assessment'] is not None or trace['observations'] or not trace['reason']:
            raise IntegrityFailure('Inconclusive run contains a final assessment')
    elif trace['assessment'] not in {'NO_FAILURE_OBSERVED', 'SOURCE_QUALITY_FAILURE',
                                    'TRANSFORMATION_RECONCILIATION_FAILURE'} or trace['reason'] is not None:
        raise IntegrityFailure('Invalid completed assessment')
    if type(trace['steps']) is not list or len(trace['steps']) > 3 or type(trace['observations']) is not list:
        raise IntegrityFailure('Invalid trace bounds')
    supported = {trace['source_sha256']}
    batch = None
    successful = 0
    failed = False
    for step in trace['steps']:
        if (type(step) is not dict or set(step) != {
                'tool', 'dataset', 'outcome', 'report_sha256', 'report'} or failed):
            raise IntegrityFailure('Invalid tool trace')
        if step['tool'] not in {'diagnose_csv', 'run_batch', 'query_lineage'}:
            raise IntegrityFailure('Unknown retained tool')
        if step['outcome'] == 'OK':
            if ((step['tool'], step['dataset']) not in policy.grants or type(step['report']) is not dict
                    or sha(canonical(step['report'])) != step['report_sha256']):
                raise IntegrityFailure('Tool evidence mismatch')
            supported.add(step['report_sha256'])
            successful += 1
            if step['tool'] == 'diagnose_csv' and canonical(step['report']) != canonical(incident['report']):
                raise IntegrityFailure('Retained diagnosis mismatch')
            if step['tool'] == 'run_batch':
                if batch is not None or canonical(step['report']['source_check']) != canonical(incident['report']):
                    raise IntegrityFailure('Retained batch source mismatch')
                batch = step['report']
        else:
            failed = True
            if (step['outcome'] not in {'DENIED', 'INVALID_REQUEST', 'BUDGET_EXCEEDED',
                                       'DEADLINE_EXCEEDED', 'INPUT_REJECTED', 'TOOL_ERROR', 'INVALID_EVIDENCE'}
                    or step['report'] is not None or step['report_sha256'] is not None):
                raise IntegrityFailure('Invalid failure evidence')
    if successful > trace['calls_used'] or (trace['status'] == 'COMPLETED' and (failed or successful < 2)):
        raise IntegrityFailure('Trace call accounting mismatch')
    if batch is None:
        if snapshots:
            raise IntegrityFailure('Snapshots without accepted batch execution')
    else:
        validate_snapshots(batch, snapshots)
    for observation in trace['observations']:
        if (type(observation) is not dict or set(observation) != {'dataset', 'check', 'evidence_sha256'}
                or type(observation['evidence_sha256']) is not list
                or len(observation['evidence_sha256']) != 2
                or observation['evidence_sha256'][0] != trace['source_sha256']
                or observation['evidence_sha256'][1] not in supported):
            raise IntegrityFailure('Observation evidence is unavailable')


class InvestigationRuns:
    """Trusted local operator interface; never exposed as an agent-write tool."""
    def __init__(self, store: IncidentStore):
        self.store = store

    @staticmethod
    def _require_v2(connection):
        if validate_schema(connection) != 2:
            raise StoreError('Explicit V1 to V2 migration is required')

    def execute(self, incident_id: str, policy: ToolPolicy, *, request_key: str,
                transform: str = 'clean', clock=monotonic) -> dict:
        if (type(policy) is not ToolPolicy or type(request_key) is not str
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', request_key)
                or type(transform) is not str or transform not in TRANSFORMS):
            raise StoreError('Invalid run request')
        request = {'incident_id': incident_id, 'policy': policy_manifest(policy), 'transform': transform}
        # Only bounded deterministic work is supported while this write lock is held.
        # External/model work will need durable reservations, not this transaction model.
        with self.store._connect(write=True) as connection:
            self._require_v2(connection)
            incident, _ = self.store._load(connection, incident_id)
            old = connection.execute('SELECT id FROM investigation_runs WHERE incident_id=? AND request_key=?',
                                     (incident_id, request_key)).fetchone()
            if old:
                record, _ = self._load(connection, old[0])
                if canonical(record['manifest']['request']) != canonical(request):
                    raise StoreError('Run idempotency conflict')
                return record
            result = investigate(self.store, incident_id, policy, transform=transform, clock=clock)
            trace = json.loads(result.to_json())
            _binding(trace, incident, policy, result.snapshots)
            trace_bytes = canonical(trace)
            if len(trace_bytes) > MAX_TRACE_BYTES:
                raise StoreError('Trace exceeds storage budget')
            run_id = str(uuid4())
            descriptors = [{'name': item.name, 'sha256': sha(item.content), 'bytes': len(item.content)}
                           for item in sorted(result.snapshots, key=lambda item: item.name)]
            manifest = {'format_version': '1', 'run_id': run_id, 'request_key': request_key,
                        'request': request, 'source_sha256': incident['manifest']['source_sha256'],
                        'trace_sha256': sha(trace_bytes), 'artifacts': descriptors,
                        'created_at': datetime.now(timezone.utc).isoformat()}
            connection.execute('INSERT INTO investigation_runs VALUES (?,?,?,?,?,?)',
                               (run_id, incident_id, request_key, canonical(manifest), sha(canonical(manifest)), trace_bytes))
            for snapshot in result.snapshots:
                self._insert_artifact(connection, run_id, snapshot)
            return self._load(connection, run_id)[0]

    @staticmethod
    def _insert_artifact(connection, run_id, snapshot):
        connection.execute('INSERT INTO run_artifacts VALUES (?,?,?,?)',
                           (run_id, snapshot.name, snapshot.content, sha(snapshot.content)))

    def _load(self, connection, run_id):
        self._require_v2(connection)
        if type(run_id) is not str or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', run_id):
            raise StoreError('Invalid run identity')
        row = connection.execute('SELECT incident_id,request_key,manifest,manifest_sha256,trace '
                                 'FROM investigation_runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise StoreError('Unknown investigation run')
        try:
            incident_id, key, manifest_bytes, checksum, trace_bytes = row
            if sha(manifest_bytes) != checksum or len(trace_bytes) > MAX_TRACE_BYTES:
                raise IntegrityFailure('Run manifest checksum mismatch')
            manifest, trace = json.loads(manifest_bytes), json.loads(trace_bytes)
            if (set(manifest) != {'format_version', 'run_id', 'request_key', 'request', 'source_sha256',
                                  'trace_sha256', 'artifacts', 'created_at'}
                    or manifest['format_version'] != '1' or manifest['run_id'] != run_id
                    or manifest['request_key'] != key or manifest['request']['incident_id'] != incident_id
                    or set(manifest['request']) != {'incident_id', 'policy', 'transform'}
                    or type(manifest['request']['transform']) is not str
                    or manifest['request']['transform'] not in TRANSFORMS
                    or sha(trace_bytes) != manifest['trace_sha256']):
                raise IntegrityFailure('Run identity or trace mismatch')
            incident, _ = self.store._load(connection, incident_id)
            if manifest['source_sha256'] != incident['manifest']['source_sha256']:
                raise IntegrityFailure('Run source mismatch')
            snapshots = []
            descriptors = []
            for name, content, digest in connection.execute(
                    'SELECT name,content,sha256 FROM run_artifacts WHERE run_id=? ORDER BY name', (run_id,)):
                if type(content) is not bytes or len(content) > 2_000_000 or sha(content) != digest:
                    raise IntegrityFailure('Run artifact checksum mismatch')
                snapshots.append(BatchSnapshot(name, content))
                descriptors.append({'name': name, 'sha256': digest, 'bytes': len(content)})
            if len(snapshots) > 4 or sum(len(s.content) for s in snapshots) > 4_000_000:
                raise IntegrityFailure('Run artifact budget exceeded')
            if descriptors != manifest['artifacts']:
                raise IntegrityFailure('Run artifact manifest mismatch')
            _binding(trace, incident, _policy(manifest['request']['policy']), tuple(snapshots))
            return {'run_id': run_id, 'manifest': manifest, 'trace': trace}, tuple(snapshots)
        except (KeyError, TypeError, IndexError, ValueError, UnicodeDecodeError) as exc:
            if isinstance(exc, IntegrityFailure):
                raise
            raise IntegrityFailure('Invalid retained investigation') from exc

    def read(self, run_id: str) -> dict:
        with self.store._connect() as connection:
            return self._load(connection, run_id)[0]

    def artifact(self, run_id: str, name: str) -> bytes:
        """Explicit trusted-host access to retained synthetic bytes, not a JSON/API export."""
        with self.store._connect() as connection:
            _, snapshots = self._load(connection, run_id)
        for snapshot in snapshots:
            if snapshot.name == name:
                return snapshot.content
        raise StoreError('Unknown run artifact')

    def replay(self, run_id: str) -> dict:
        with self.store._connect() as connection:
            record, snapshots = self._load(connection, run_id)
        trace, request = record['trace'], record['manifest']['request']
        if trace['implementation_sha256'] != implementation_fingerprint(request['transform']):
            raise VersionMismatch('Exact workflow implementation is unavailable')
        current = investigate(self.store, request['incident_id'], _policy(request['policy']),
                              transform=request['transform'])
        actual = sha(canonical(json.loads(current.to_json())))
        expected_artifacts = {s.name: s.content for s in snapshots}
        actual_artifacts = {s.name: s.content for s in current.snapshots}
        return {'run_id': run_id, 'outcome': 'MATCH' if actual == record['manifest']['trace_sha256']
                and actual_artifacts == expected_artifacts else 'MISMATCH',
                'expected_trace_sha256': record['manifest']['trace_sha256'], 'actual_trace_sha256': actual}
