# SPDX-License-Identifier: Apache-2.0
"""Exercise installed advisory contracts without credentials or a model provider."""
from pathlib import Path
from tempfile import TemporaryDirectory
import aegisflow_dr
from aegisflow_dr.advisory.contracts import decode, encode
from aegisflow_dr.advisory.session import AdvisorySession
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed advisory check imported source checkout')
with TemporaryDirectory() as temporary:
    path = Path(temporary) / 'evidence.db'
    initialize(path)
    store = IncidentStore(path)
    incident = store.record(generate_orders(), request_key='advisory-check')
    runs = InvestigationRuns(store)
    record = runs.execute(incident['incident_id'], default_policy(), request_key='advisory-check')
    session = AdvisorySession(runs, record['run_id'], model_id='offline/test', prompt_sha256='a' * 64)
    request = decode('request', session.request)
    response = {'version': '1', 'request_sha256': sha(session.request), 'decision': 'PROPOSE',
        'assessment': record['trace']['assessment'], 'evidence_sha256': request['evidence_sha256']}
    before = path.read_bytes()
    if session.review_response(encode('response', response))['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed advisory acceptance failed')
    response['assessment'] = 'SOURCE_QUALITY_FAILURE'
    if session.review_response(encode('response', response))['status'] != 'REJECTED_ADVISORY':
        raise RuntimeError('Installed contradictory advice accepted')
    if path.read_bytes() != before:
        raise RuntimeError('Installed advisory changed retained evidence')
print('Installed advisory contracts, deterministic gate and read-only evidence checks passed.')
