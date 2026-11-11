# SPDX-License-Identifier: Apache-2.0
"""Synthetic offline cross-model budget demonstration; no provider or credentials."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .context import PreparedAdvisory
from .contracts import AdvisoryError, decode, encode
from .dispatch import Adapter, AdapterFailure, AdapterResult, dispatch
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
        initialize_usage(usage, UsagePolicy(max_tokens=30, max_cost_nusd=70, max_total_attempts=2))
        ledger = UsageLedger(usage, clock_ms=lambda:1000)
        events = []
        for index, model in enumerate(('fixture/primary','fixture/secondary','fixture/third')):
            prepared = PreparedAdvisory(runs,record['run_id'],model_id=model)
            quote = UsageQuote(prepared.manifest['input_sha256'],model,'synthetic-v1',10,5,2,3)
            metadata = decode('request',prepared.request)
            payload = encode('response',{'version':'1','request_sha256':sha(prepared.request),
                'decision':'PROPOSE','assessment':record['trace']['assessment'],
                'evidence_sha256':metadata['evidence_sha256']})
            def send(request):
                events.append({'model':model,'event':'ADAPTER_CALLED'})
                return AdapterFailure('RETRYABLE',2,0) if index==0 else AdapterResult(payload,8,2)
            try:
                result = dispatch(prepared,quote,ledger,Adapter('synthetic-v1',send),
                                  attempt_key=f'demo-{index}',deadline_ms=2000)
                events.append({'model':model,'event':result['status'],
                               'review':result['review']['status'] if result['review'] else None})
            except AdvisoryError:
                events.append({'model':model,'event':'ADMISSION_DENIED'})
        return {'mode':'offline-synthetic','model_calls':0,'adapter_invocations':sum(event['event']=='ADAPTER_CALLED' for event in events),
                'events':events,'usage':ledger.snapshot(),'evidence_unchanged':before==evidence.read_bytes()}


if __name__ == '__main__':
    print(json.dumps(run_demo(),ensure_ascii=False,indent=2))
