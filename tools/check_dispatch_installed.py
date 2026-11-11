# SPDX-License-Identifier: Apache-2.0
"""Verify one-shot dispatch from an installed distribution, without a provider."""
from pathlib import Path
from tempfile import TemporaryDirectory
import aegisflow_dr
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.dispatch import Adapter, AdapterResult, AdapterFailure, dispatch
from aegisflow_dr.advisory.contracts import decode, encode
from aegisflow_dr.storage.store import sha
from aegisflow_dr.advisory.contracts import AdvisoryError
from aegisflow_dr.advisory.usage import UsageLedger, UsagePolicy, UsageQuote, initialize_usage
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns

checkout = Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
    raise RuntimeError('Installed usage check imported source checkout')
with TemporaryDirectory() as temporary:
    evidence, usage = Path(temporary) / 'evidence.db', Path(temporary) / 'usage.db'
    initialize(evidence)
    store = IncidentStore(evidence)
    source = store.record(generate_orders(), request_key='usage-installed')
    runs = InvestigationRuns(store)
    record = runs.execute(source['incident_id'], default_policy(), request_key='usage-installed')
    before = evidence.read_bytes()
    prepared = PreparedAdvisory(runs, record['run_id'], model_id='offline/test')
    quote = UsageQuote(prepared.manifest['input_sha256'], 'offline/test', 'fixture-v1', 10, 5, 2, 3)
    initialize_usage(usage, UsagePolicy(max_tokens=15, max_cost_nusd=35))
    ledger = UsageLedger(usage, clock_ms=lambda: 1000)
    request = decode('request', prepared.request)
    payload = encode('response', {'version':'1', 'request_sha256':sha(prepared.request),
        'decision':'PROPOSE', 'assessment':record['trace']['assessment'],
        'evidence_sha256':request['evidence_sha256']})
    adapter = Adapter('fixture-v1', lambda request: AdapterResult(payload,8,2))
    result = dispatch(prepared,quote,ledger,adapter,attempt_key='installed',deadline_ms=2000)
    if result['review']['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed dispatch review failed')
    try:
        dispatch(prepared,quote,ledger,adapter,attempt_key='installed',deadline_ms=2000)
    except AdvisoryError:
        pass
    else:
        raise RuntimeError('Installed dispatch allowed duplicate send')
    snapshot = UsageLedger(usage).snapshot()
    if (snapshot['held_tokens'], snapshot['charged_tokens'], snapshot['charged_cost_nusd']) != (0, 10, 22):
        raise RuntimeError('Installed usage accounting mismatch')
    failure_path = Path(temporary) / 'failure.db'
    initialize_usage(failure_path)
    failure_ledger = UsageLedger(failure_path, clock_ms=lambda:1000)
    failure_adapter = Adapter('fixture-v1', lambda request: AdapterFailure('RETRYABLE',0,0))
    failed = dispatch(prepared,quote,failure_ledger,failure_adapter,attempt_key='failure',deadline_ms=2000)
    if failed['status'] != 'KNOWN_RETRYABLE_FAILURE' or failure_ledger.snapshot()['held_tokens'] != 0:
        raise RuntimeError('Installed known failure accounting failed')
    if evidence.read_bytes() != before:
        raise RuntimeError('Installed usage check changed evidence')
print('Installed one-shot dispatch, review, exact accounting and duplicate denial passed.')
