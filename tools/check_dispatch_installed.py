# SPDX-License-Identifier: Apache-2.0
"""Verify one-shot dispatch from an installed distribution, without a provider."""
from pathlib import Path
from tempfile import TemporaryDirectory
import aegisflow_dr
from aegisflow_dr.advisory.demo import run_demo
from aegisflow_dr.advisory.operation import bind_operation
from uuid import uuid4
from aegisflow_dr.advisory.retry import retry_dispatch
import asyncio
from aegisflow_dr.advisory.stream import stream_adapter, UsageFrame
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
    stream_path = Path(temporary) / 'stream.db'
    initialize_usage(stream_path)
    stream_ledger = UsageLedger(stream_path, clock_ms=lambda:1000)
    async def source(request):
        yield payload[:10]
        yield payload[10:]
        yield UsageFrame(8,2)
    result = dispatch(prepared,quote,stream_ledger,stream_adapter('fixture-v1',source),
                      attempt_key='stream',deadline_ms=2000)
    if result['review']['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed stream review failed')
    closed = []
    async def stalled(request):
        try:
            await asyncio.sleep(1)
            yield b'x'
        finally:
            closed.append(True)
    stream_ledger.clock_ms = lambda:1995
    result = dispatch(prepared,quote,stream_ledger,stream_adapter('fixture-v1',stalled),
                      attempt_key='timeout',deadline_ms=2000)
    if result['status'] != 'USAGE_UNKNOWN' or closed != [True] or stream_ledger.snapshot()['held_tokens'] != 15:
        raise RuntimeError('Installed stream timeout/cleanup accounting failed')
    retry_path = Path(temporary) / 'retry.db'
    initialize_usage(retry_path)
    retry_ledger = UsageLedger(retry_path, clock_ms=lambda:1000)
    retry_calls = []
    def retry_send(request):
        retry_calls.append(request)
        return AdapterFailure('RETRYABLE',0,0) if len(retry_calls)==1 else AdapterResult(payload,8,2)
    retry_adapter = Adapter('fixture-v1',retry_send)
    result = retry_dispatch(prepared,quote,retry_ledger,retry_adapter,
                            operation_key='installed',deadline_ms=2000,wait=lambda _:None)
    if result['attempts_started'] != 2 or result['last_result']['review']['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed bounded retry failed')
    result = retry_dispatch(prepared,quote,retry_ledger,retry_adapter,
                            operation_key='installed',deadline_ms=2000,wait=lambda _:None)
    if result['status'] != 'ADMISSION_DENIED' or len(retry_calls) != 2:
        raise RuntimeError('Installed retry duplicate protection failed')
    bound_path = Path(temporary) / 'bound.db'
    operation_id = str(uuid4())
    binding = bind_operation(prepared, operation_id=operation_id,
                             allowed_models=('offline/test',), deadline_ms=2000)
    initialize_usage(bound_path, UsagePolicy(max_total_attempts=2), operation=binding)
    bound = UsageLedger(bound_path, operation_id=operation_id, clock_ms=lambda:1000)
    result = dispatch(prepared,quote,bound,adapter,attempt_key='bound',deadline_ms=2000)
    if result['review']['status'] != 'VERIFIED_ADVISORY':
        raise RuntimeError('Installed bound operation verification failed')
    denied = PreparedAdvisory(runs,record['run_id'],model_id='offline/unapproved')
    from dataclasses import replace
    denied_quote = replace(quote,input_sha256=denied.manifest['input_sha256'],model_id='offline/unapproved')
    bound = UsageLedger(bound_path, operation_id=operation_id, clock_ms=lambda:1000)
    try:
        dispatch(denied,denied_quote,bound,adapter,attempt_key='denied',deadline_ms=2000)
    except AdvisoryError:
        pass
    else:
        raise RuntimeError('Installed operation allowed an unapproved model')
    if bound.snapshot()['attempts'] != 1:
        raise RuntimeError('Installed operation denial mutated usage')
    if evidence.read_bytes() != before:
        raise RuntimeError('Installed usage check changed evidence')
print('Installed one-shot dispatch, review, exact accounting and duplicate denial passed.')

shared = run_demo()
if shared['adapter_invocations'] != 2 or shared['events'][-1]['event'] != 'ADMISSION_DENIED' or not shared['evidence_unchanged']:
    raise RuntimeError('Installed shared budget demo failed')
