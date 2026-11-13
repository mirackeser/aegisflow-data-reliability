# SPDX-License-Identifier: Apache-2.0
"""Verify installed recovery signatures and durable decisions on synthetic evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import json
import sqlite3
from contextlib import closing
import aegisflow_dr
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import encode
from aegisflow_dr.advisory.dispatch import Adapter
from aegisflow_dr.advisory.operation import bind_operation
from aegisflow_dr.advisory.recovery import assess_recovery,prepare_recovery_review
from aegisflow_dr.advisory.recovery_auth import RecoverySigner,signing_bytes,verify_usage_attestation
from aegisflow_dr.advisory.recovery_decisions import initialize_decisions,record_decision,decision_history,decision_payload
from aegisflow_dr.advisory.routing import RouteCandidate,execute_route
from aegisflow_dr.advisory.usage import UsageLedger,UsagePolicy,UsageQuote,initialize_usage
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import initialize,IncidentStore
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha

if Path(aegisflow_dr.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]/'src'):
    raise RuntimeError('Recovery check imported source checkout')
with TemporaryDirectory() as temporary:
    root=Path(temporary);evidence=root/'evidence.db';usage=root/'usage.db';log=root/'decisions.db'
    initialize(evidence);store=IncidentStore(evidence)
    source=store.record(generate_orders(),request_key='installed-recovery')
    runs=InvestigationRuns(store);record=runs.execute(source['incident_id'],default_policy(),request_key='installed-recovery')
    prepared=PreparedAdvisory(runs,record['run_id'],model_id='offline/test')
    operation_id=str(uuid4());binding=bind_operation(prepared,operation_id=operation_id,allowed_models=('offline/test',),deadline_ms=2000)
    initialize_usage(usage,UsagePolicy(max_total_attempts=1),operation=binding,routing=True)
    ledger=UsageLedger(usage,operation_id=operation_id,clock_ms=lambda:1000)
    quote=UsageQuote(prepared.manifest['input_sha256'],'offline/test','fixture-v1',10,5,2,3)
    execute_route(ledger,(RouteCandidate(prepared,quote,Adapter('fixture-v1',lambda _:None)),))
    report=assess_recovery(ledger);op=report['assessment']['operation_sha256']
    keys=[Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()]
    grants=[RecoverySigner(str(uuid4()),purpose,op,key.public_key().public_bytes_raw(),900,5000)
            for key,purpose in zip(keys,('recovery-decision','usage-attestation'))]
    def sign(payload,index):
        grant=grants[index]
        metadata={'version':'1','purpose':grant.purpose,'principal_id':grant.principal_id,
            'operation_sha256':op,'key_sha256':sha(grant.public_key),'payload_sha256':sha(payload),
            'issued_at_ms':1000,'expires_at_ms':4000}
        return encode('recovery-signature',{**metadata,'signature':keys[index].sign(signing_bytes(metadata)).hex()})
    with closing(sqlite3.connect(usage)) as db:
        db.row_factory=sqlite3.Row;row=db.execute('SELECT * FROM attempts').fetchone()
    payload=encode('usage-attestation',{'version':'1','operation_sha256':op,
        'snapshot_sha256':report['assessment']['snapshot_sha256'],'assessment_sha256':report['assessment_sha256'],
        **{k:row[k] for k in ('attempt_id','request_sha256','input_sha256','quote_sha256')},
        'receipt_sha256':'1'*64,'input_tokens':8,'output_tokens':2})
    signature=sign(payload,1);before=usage.read_bytes()
    verified=verify_usage_attestation(ledger,payload,signature,grant=grants[1],now_ms=1500)
    review=prepare_recovery_review(ledger,review_id=str(uuid4()),operator_id=grants[0].principal_id,action='KEEP_BLOCKED')
    decision_signature=sign(decision_payload(review,payload,signature),0)
    initialize_decisions(log,operation_sha256=op)
    args=dict(grant=grants[0],now_ms=1500,attestation=payload,attestation_envelope=signature,issuer_grant=grants[1])
    digest=record_decision(log,ledger,review,decision_signature,**args)
    if record_decision(log,ledger,review,decision_signature,**args)!=digest or len(decision_history(log,operation_sha256=op))!=1:
        raise RuntimeError('Installed recovery decision replay failed')
    if verified['charged_cost_nusd']!=22 or ledger.snapshot()['held_tokens']!=15 or usage.read_bytes()!=before:
        raise RuntimeError('Installed recovery verification changed usage')
print('Installed authenticated usage evidence and durable idempotent decisions passed.')
