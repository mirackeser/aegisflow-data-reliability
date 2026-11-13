# SPDX-License-Identifier: Apache-2.0
"""Repeatable offline operational qualification, never a live activation permit."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode, encode
from .dispatch import Adapter, AdapterFailure, AdapterResult
from .operation import bind_operation
from .recovery import assess_recovery, prepare_recovery_review, verify_recovery_review
from .route_store import RouteJournal
from .routing import RouteCandidate, execute_route, plan_route
from .usage import UsageLedger, UsagePolicy, UsageQuote, initialize_usage
from ..investigation import default_policy
from ..pipeline import generate_orders
from ..storage import IncidentStore, initialize
from ..storage.runs import InvestigationRuns
from ..storage.store import sha

# Expected outcomes are independent of the adapter execution and ledger totals.
SCENARIOS = (
    ('known-failure-fallback', 'retry', 'VERIFIED_ADVISORY', 2, 0, 12, 26),
    ('unknown-usage', 'unknown', 'USAGE_UNKNOWN', 1, 15, 0, 0),
    ('terminal-failure', 'terminal', 'KNOWN_TERMINAL_FAILURE', 1, 0, 2, 4),
    ('invalid-response', 'invalid', 'RESPONSE_REJECTED', 1, 0, 10, 22),
    ('rejected-claim', 'wrong', 'REJECTED_ADVISORY', 1, 0, 10, 22),
    ('expired-deadline', 'expired', 'DEADLINE_EXCEEDED', 0, 0, 0, 0),
    ('cost-boundary', 'budget', 'ADMISSION_DENIED', 1, 0, 2, 4),
)


def require(condition):
    if not condition:
        raise AdvisoryError('Offline operational qualification failed')


def qualify_operations():
    """Exercise isolated synthetic stores; raise on any mismatch and export no data.

    Fixtures test routing/accounting behavior, not provider billing, tokenization,
    model quality, infrastructure availability or adversarial host resistance.
    """
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        evidence = root / 'evidence.db'
        initialize(evidence)
        store = IncidentStore(evidence)
        source = store.record(generate_orders(), request_key='qualification')
        runs = InvestigationRuns(store)
        record = runs.execute(source['incident_id'], default_policy(), request_key='qualification')
        before = evidence.read_bytes()
        results = []
        for name, mode, status, count, held, charged, cost in SCENARIOS:
            operation_id = str(uuid4())
            calls = []
            candidates = []
            for index, model in enumerate(('fixture/primary', 'fixture/secondary')):
                prepared = PreparedAdvisory(runs, record['run_id'], model_id=model)
                quote = UsageQuote(prepared.manifest['input_sha256'], model, 'fixture-v1', 10, 5, 2, 3)
                payload = encode('response', {'version':'1', 'request_sha256':sha(prepared.request),
                    'decision':'PROPOSE', 'assessment':'SOURCE_QUALITY_FAILURE' if mode == 'wrong'
                    else record['trace']['assessment'],
                    'evidence_sha256':decode('request', prepared.request)['evidence_sha256']})
                def send(request, index=index, payload=payload):
                    calls.append(index)
                    if mode == 'unknown':
                        raise TimeoutError('synthetic ambiguity')
                    if index == 0 and mode in ('retry', 'budget', 'terminal'):
                        return AdapterFailure('TERMINAL' if mode == 'terminal' else 'RETRYABLE', 2, 0)
                    return AdapterResult(b'invalid' if mode == 'invalid' else payload, 8, 2)
                candidates.append(RouteCandidate(prepared, quote, Adapter('fixture-v1', send)))
            candidates = tuple(candidates)
            binding = bind_operation(candidates[0].prepared, operation_id=operation_id,
                allowed_models=tuple(item.quote.model_id for item in candidates), deadline_ms=2000)
            path = root / (name + '.db')
            initialize_usage(path, UsagePolicy(max_cost_nusd=35 if mode == 'budget' else 70,
                max_total_attempts=2), operation=binding, routing=True)
            def reopen():
                return UsageLedger(path, operation_id=operation_id,
                                   clock_ms=lambda:2000 if mode == 'expired' else 1000)
            ledger = reopen()
            result = execute_route(ledger, candidates, clock=lambda:0)
            replay = execute_route(reopen(), candidates, clock=lambda:0)
            saved = path.read_bytes()
            report = assess_recovery(reopen())['assessment']
            usage = report['usage']
            require(result['status'] == status and replay['status'] == status and replay['replayed'])
            require((len(calls), usage['held_tokens'], usage['charged_tokens'], usage['charged_cost_nusd'])
                    == (count, held, charged, cost))
            require(usage['held_cost_nusd'] == (35 if held else 0))
            require(report['reasons'] == (['USAGE_UNRESOLVED'] if mode == 'unknown' else []))
            if mode == 'unknown':
                packet = prepare_recovery_review(ledger, review_id=str(uuid4()), operator_id=str(uuid4()),
                                                  action='REQUEST_USAGE_ATTESTATION')
                require(verify_recovery_review(reopen(), packet)['action'] == 'REQUEST_USAGE_ATTESTATION')
            require(path.read_bytes() == saved)
            results.append({'case':name, 'status':status, 'adapter_invocations':len(calls),
                            'held_tokens':held, 'charged_tokens':charged, 'charged_cost_nusd':cost})
        # An interrupted worker cannot be assumed dead or automatically resumed.
        interrupted = root / 'interrupted.db'
        initialize_usage(interrupted, UsagePolicy(max_total_attempts=2), operation=binding, routing=True)
        ledger = UsageLedger(interrupted, operation_id=operation_id, clock_ms=lambda:1000)
        token = RouteJournal(ledger).claim(plan_route(ledger, candidates))
        first = candidates[0]
        attempt = ledger.reserve(first.prepared, first.quote, attempt_key='interrupted',
                                  deadline_ms=2000, route_token=token)
        ledger.transition(attempt['attempt_id'], 'start')
        reopened = UsageLedger(interrupted, operation_id=operation_id, clock_ms=lambda:1000)
        saved = interrupted.read_bytes()
        report = assess_recovery(reopened)['assessment']
        require(report['reasons'] == ['ROUTE_NOT_FINALIZED', 'USAGE_UNRESOLVED'])
        require(report['usage']['held_tokens'] == 15 and report['usage']['held_cost_nusd'] == 35)
        count_before = len(calls)
        try:
            execute_route(reopened, candidates, clock=lambda:0)
        except AdvisoryError:
            pass
        else:
            raise AdvisoryError('Interrupted route was resumed')
        require(len(calls) == count_before and interrupted.read_bytes() == saved)
        require(evidence.read_bytes() == before)
        return {'version':'1', 'profile':'offline-operational-qualification', 'status':'PASS',
                'scenarios':results, 'interrupted_worker':'BLOCKED_WITH_HOLD', 'evidence_unchanged':True,
                'live_provider_calls':0, 'live_activation_authorized':False,
                'unverified_live_boundaries':['provider_usage_attestation', 'tokenizer_and_billable_categories',
                    'transport_deadline_enforcement', 'independent_model_quality', 'deployment_identity_and_custody']}
