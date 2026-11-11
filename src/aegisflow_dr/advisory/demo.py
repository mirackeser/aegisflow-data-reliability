# SPDX-License-Identifier: Apache-2.0
"""Synthetic offline cross-model budget demonstration; no provider or credentials."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode, encode
from .dispatch import Adapter, AdapterFailure, AdapterResult, dispatch
from .operation import bind_operation
from .routing import RouteCandidate, execute_route
from .usage import UsageLedger, UsagePolicy, UsageQuote, initialize_usage
from ..investigation import default_policy
from ..pipeline import generate_orders
from ..storage import IncidentStore, initialize
from ..storage.runs import InvestigationRuns
from ..storage.store import sha


def run_demo():
    with TemporaryDirectory() as temporary:
        evidence, usage = Path(temporary)/'evidence.db', Path(temporary)/'usage.db'
        initialize(evidence)
        store = IncidentStore(evidence)
        incident = store.record(generate_orders(), request_key='demo')
        runs = InvestigationRuns(store)
        record = runs.execute(incident['incident_id'], default_policy(), request_key='demo')
        before = evidence.read_bytes()
        models = ('fixture/primary','fixture/secondary','fixture/third')
        operation_id = str(uuid4())
        primary = PreparedAdvisory(runs,record['run_id'],model_id=models[0])
        binding = bind_operation(primary, operation_id=operation_id,
                                 allowed_models=models, deadline_ms=2000)
        initialize_usage(usage, UsagePolicy(max_tokens=30, max_cost_nusd=70, max_total_attempts=2),
                         operation=binding, routing=True)
        ledger = UsageLedger(usage, clock_ms=lambda:1000, operation_id=operation_id)
        calls = []
        def candidate(index, model):
            prepared = PreparedAdvisory(runs,record['run_id'],model_id=model)
            quote = UsageQuote(prepared.manifest['input_sha256'],model,'synthetic-v1',10,5,2,3)
            metadata = decode('request',prepared.request)
            payload = encode('response',{'version':'1','request_sha256':sha(prepared.request),
                'decision':'PROPOSE','assessment':record['trace']['assessment'],
                'evidence_sha256':metadata['evidence_sha256']})
            def send(request):
                calls.append(model)
                return AdapterFailure('RETRYABLE',2,0) if index==0 else AdapterResult(payload,8,2)
            return RouteCandidate(prepared,quote,Adapter('synthetic-v1',send))
        candidates = tuple(candidate(index, model) for index, model in enumerate(models[:2]))
        result = execute_route(ledger,candidates)
        replay = execute_route(ledger,candidates)
        events = []
        for event in result['events']:
            events.extend([{'model':event['model_id'],'event':'ADAPTER_CALLED'},
                {'model':event['model_id'],'event':event['status'],'review':event['review_status']}])
        third = candidate(2,models[2])
        try:
            dispatch(third.prepared,third.quote,ledger,third.adapter,
                     attempt_key='manual-bypass',deadline_ms=2000)
        except AdvisoryError:
            events.append({'model':models[2],'event':'ADMISSION_DENIED'})
        return {'mode':'offline-synthetic','model_calls':0,'adapter_invocations':len(calls),
                'routing_status':result['status'],'replayed_without_dispatch':replay['replayed'],
                'events':events,'usage':ledger.snapshot(),'evidence_unchanged':before==evidence.read_bytes()}



if __name__ == '__main__':
    print(json.dumps(run_demo(),ensure_ascii=False,indent=2))
