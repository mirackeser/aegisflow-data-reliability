# SPDX-License-Identifier: Apache-2.0
"""Verify installed context projection and prompt contracts without a provider."""
from pathlib import Path
from tempfile import TemporaryDirectory
import aegisflow_dr
from aegisflow_dr.advisory.context import ContextPolicy, PreparedAdvisory
from aegisflow_dr.advisory.contracts import AdvisoryError, decode, encode
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import canonical, sha

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed context check imported source checkout')
with TemporaryDirectory() as temporary:
    path = Path(temporary) / 'evidence.db'
    initialize(path)
    store = IncidentStore(path)
    incident = store.record(b'order_id,customer_id,order_total\nprivate-order,private-customer,12345.67\n',
                            request_key='context-check')
    runs = InvestigationRuns(store)
    record = runs.execute(incident['incident_id'], default_policy(), request_key='context-check')
    before = path.read_bytes()
    prepared = PreparedAdvisory(runs, record['run_id'], model_id='offline/test')
    rendered = canonical(prepared.messages)
    if any(value in rendered for value in (b'private-order', b'private-customer', b'12345.67')):
        raise RuntimeError('Installed context leaked excluded source values')
    if prepared.manifest['input_sha256'] != sha(rendered):
        raise RuntimeError('Installed prompt digest mismatch')
    request = decode('request', prepared.request)
    response = {'version': '1', 'request_sha256': sha(prepared.request), 'decision': 'PROPOSE',
                'assessment': record['trace']['assessment'], 'evidence_sha256': request['evidence_sha256']}
    if prepared.review_response(encode('response', response))['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed prepared advisory gate failed')
    try:
        PreparedAdvisory(runs, record['run_id'], model_id='offline/test', policy=ContextPolicy(max_prompt_bytes=256))
    except AdvisoryError:
        pass
    else:
        raise RuntimeError('Installed prompt budget failed open')
    if path.read_bytes() != before:
        raise RuntimeError('Installed context preparation changed retained evidence')
print('Installed evidence projection, prompt binding, privacy exclusions and byte budgets passed.')
