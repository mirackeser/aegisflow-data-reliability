# SPDX-License-Identifier: Apache-2.0
"""Read-only correlation of offline advice with verified retained evidence."""
import sqlite3
from uuid import uuid4

from ..coordination.judge import review
from ..storage import StoreError
from ..storage.store import canonical, sha
from .contracts import AdvisoryError, decode, encode


class AdvisorySession:
    """Trusted host owns this instance and its metadata; it never calls a model.

    A request hash correlates advice, not authentication. No durable quota,
    execution approval, provider transport or confidence calibration is supplied.
    """
    def __init__(self, runs, run_id, *, model_id, prompt_sha256):
        record = runs.read(run_id)
        proposal = {'version': '1', 'run_id': run_id,
            'incident_id': record['manifest']['request']['incident_id'],
            'assessment': record['trace']['assessment'],
            'evidence_sha256': sorted({record['trace']['source_sha256'],
                *(step['report_sha256'] for step in record['trace']['steps'])})}
        if review(record, proposal)['decision'] != 'ACCEPT':
            raise AdvisoryError('Verified completed evidence required')
        self._request = encode('request', {'version': '1', 'request_id': str(uuid4()),
            'run_id': run_id, 'incident_id': proposal['incident_id'],
            'record_sha256': sha(canonical(record)), 'model_id': model_id,
            'prompt_sha256': prompt_sha256, 'evidence_sha256': proposal['evidence_sha256']})
        self._runs = runs

    @property
    def request(self):
        return self._request

    def review_response(self, payload):
        response = decode('response', payload)
        request = decode('request', self._request)
        digest = sha(self._request)
        if response['request_sha256'] != digest:
            raise AdvisoryError('Advisory context rejected')
        if response['decision'] == 'ABSTAIN':
            return self._result('ABSTAIN', 'MODEL_ABSTAIN', None)
        try:
            record = self._runs.read(request['run_id'])
        except (StoreError, OSError, sqlite3.DatabaseError):
            return self._result('ABSTAIN', 'RUN_UNAVAILABLE', None)
        if sha(canonical(record)) != request['record_sha256']:
            return self._result('ABSTAIN', 'RECORD_CHANGED', None)
        proposal = {'version': '1', 'run_id': request['run_id'], 'incident_id': request['incident_id'],
            'assessment': response['assessment'], 'evidence_sha256': response['evidence_sha256']}
        verdict = review(record, proposal)
        status = {'ACCEPT': 'VERIFIED_ADVISORY', 'REJECT': 'REJECTED_ADVISORY', 'ABSTAIN': 'ABSTAIN'}
        return self._result(status[verdict['decision']], verdict['reason'], verdict)

    def _result(self, status, reason, verdict):
        return {'version': '1', 'mode': 'advisory-only', 'request_sha256': sha(self._request),
                'status': status, 'reason': reason, 'verdict': verdict}
