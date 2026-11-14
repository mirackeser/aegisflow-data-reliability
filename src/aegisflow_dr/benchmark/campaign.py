# SPDX-License-Identifier: Apache-2.0
"""Retained public campaign linking investigation, dispatch, Judge and quality gates."""
from dataclasses import asdict
from pathlib import Path
import time
from uuid import uuid4

from .core import BenchmarkError, canonical, closed, load_suite, parse, validate
from .campaign_report import CONFIG, RECORD, CampaignPolicy, summarize
from .campaign_store import seal, verified_artifacts, write
from .quality import HASH, freeze_statistical_protocol
from ..advisory.context import PreparedAdvisory
from ..advisory.contracts import AdvisoryError, decode
from ..advisory.dispatch import Adapter, AdapterResult
from ..advisory.operation import bind_operation
from ..advisory.routing import RouteCandidate, execute_route
from ..advisory.usage import UsageLedger, UsagePolicy, initialize_usage, integer
from ..investigation import default_policy
from ..storage import IncidentStore, initialize
from ..storage.runs import InvestigationRuns
from ..storage.store import sha


def _quality_cases(suite):
    return canonical([{'case_id': c['case_id'], 'family': c['family'], 'label': c['expected_assessment']}
                      for c in suite['cases']])


def _protocol(suite, policy):
    return freeze_statistical_protocol(_quality_cases(suite),
        model_revision_sha256=policy.model_revision_sha256,
        families=tuple(sorted({c['family'] for c in suite['cases']})))


def read_campaign(directory, *, manifest_sha256):
    """Historical, read-only verification; never construct an adapter or replay calls."""
    artifacts = verified_artifacts(directory, manifest_sha256)
    suite, digest = load_suite()
    config = parse(artifacts['config.json'])
    validate(closed({'version': {'const': '1'}, 'suite_sha256': HASH, 'policy': CONFIG}), config)
    if config['suite_sha256'] != digest:
        raise BenchmarkError('Campaign suite changed')
    records = [parse(artifacts[f'case-{index:03}.json']) for index in range(len(suite['cases']))]
    expected = {'config.json', 'protocol.json', 'evidence.db', 'report.json'}
    for index, record in enumerate(records):
        validate(RECORD, record)
        expected.add(f'case-{index:03}.json')
        if record['status'] != 'NOT_RUN':
            expected.add(f'usage-{index:03}.db')
    if (set(artifacts) != expected or artifacts['protocol.json'] != _protocol(suite, CampaignPolicy(**config['policy']))):
        raise BenchmarkError('Campaign retained profile changed')
    report = summarize(suite, records, config['policy'], artifacts['protocol.json'], _quality_cases(suite))
    if canonical(report) != artifacts['report.json']:
        raise BenchmarkError('Campaign report differs from observations')
    return report


def run_campaign(directory, policy, build_adapter, *, clock_ms=None, clock_ns=time.monotonic_ns):
    """One trusted-host invocation, one isolated ledger per case, one aggregate budget.

    build_adapter(prepared, operation) returns (UsageQuote, Adapter), receives no
    case identity/label/split/family and MUST defer I/O until Adapter.send. It is
    trusted host code, not sandboxed. Public fixtures do not constitute a holdout.
    No provider is chosen/configured here and this API grants no live activation.
    Existing or incomplete directories are never resumed; all completed cases and
    started ledgers survive a crash. Unknown usage stops further case dispatch.
    """
    if type(policy) is not CampaignPolicy or not callable(build_adapter) or not callable(clock_ns):
        raise BenchmarkError('Trusted campaign configuration required')
    clock_ms = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1000000
    if not callable(clock_ms):
        raise BenchmarkError('Trusted campaign clock required')
    suite, digest = load_suite()
    root = Path(directory)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    protocol = _protocol(suite, policy)
    write(root / 'config.json', canonical({'version': '1', 'suite_sha256': digest, 'policy': asdict(policy)}))
    write(root / 'protocol.json', protocol)
    evidence = root / 'evidence.db'
    initialize(evidence)
    store = IncidentStore(evidence)
    runs = InvestigationRuns(store)
    records, used_tokens, used_cost, blocked = [], 0, 0, False
    for index, case in enumerate(suite['cases']):
        observation = {'case_id': case['case_id'], 'status': 'NOT_RUN', 'request_sha256': None,
            'input_sha256': None, 'response': None, 'adapter_invocations': 0, 'elapsed_ms': 0,
            'usage': {key: 0 for key in ('held_tokens', 'charged_tokens', 'held_cost_nusd', 'charged_cost_nusd')}}
        if not blocked:
            started = clock_ns()
            integer(started, 0, 10**18)
            source = store.record(case['csv_text'].encode(), request_key=f'campaign-{index}')
            record = runs.execute(source['incident_id'], default_policy(), request_key=f'campaign-{index}',
                                  transform=case['transform'])
            prepared = PreparedAdvisory(runs, record['run_id'], model_id=policy.model_id)
            now = clock_ms()
            integer(now, 0, 10**18 - policy.case_timeout_ms)
            operation = bind_operation(prepared, operation_id=str(uuid4()), allowed_models=(policy.model_id,),
                                       deadline_ms=now + policy.case_timeout_ms)
            quote, adapter = build_adapter(prepared, operation)
            if type(adapter) is not Adapter:
                raise BenchmarkError('Trusted campaign adapter required')
            def send(request):
                observation['adapter_invocations'] += 1
                result = adapter.send(request)
                if type(result) is AdapterResult:
                    try:
                        observation['response'] = decode('response', result.payload)
                    except AdvisoryError:
                        pass  # Never retain arbitrary model text or exception details.
                return result
            path = root / f'usage-{index:03}.db'
            write(path, b'')
            initialize_usage(path, UsagePolicy(max_tokens=max(1, policy.max_tokens - used_tokens),
                max_cost_nusd=policy.max_cost_nusd - used_cost, max_total_attempts=1,
                max_attempts=1, max_duration_ms=policy.case_timeout_ms), operation=operation, routing=True)
            ledger = UsageLedger(path, operation_id=decode('operation', operation.payload)['operation_id'], clock_ms=clock_ms)
            result = execute_route(ledger, (RouteCandidate(prepared, quote, Adapter(adapter.revision, send)),),
                                   clock=lambda: clock_ns() / 1000000000)
            ended = clock_ns()
            integer(ended, started, 10**18)
            usage = ledger.snapshot()
            observation.update(status=result['status'], request_sha256=sha(prepared.request),
                input_sha256=prepared.manifest['input_sha256'], elapsed_ms=(ended - started + 999999) // 1000000,
                usage={key: usage[key] for key in observation['usage']})
            used_tokens += usage['held_tokens'] + usage['charged_tokens']
            used_cost += usage['held_cost_nusd'] + usage['charged_cost_nusd']
            blocked = bool(usage['held_tokens'] or usage['held_cost_nusd'] or
                           used_tokens >= policy.max_tokens or used_cost >= policy.max_cost_nusd)
        write(root / f'case-{index:03}.json', canonical(observation))
        records.append(observation)
    report = summarize(suite, records, asdict(policy), protocol, _quality_cases(suite))
    write(root / 'report.json', canonical(report))
    digest = seal(root)
    return {'manifest_sha256': digest, 'report': read_campaign(root, manifest_sha256=digest)}
