# SPDX-License-Identifier: Apache-2.0
"""Qualify installed signed gateway/usage profiles over ephemeral loopback mTLS."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
import sys
import aegisflow_dr
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from aegisflow_dr.advisory.context import PreparedAdvisory
from aegisflow_dr.advisory.contracts import decode,encode
from aegisflow_dr.advisory.dispatch import Adapter,dispatch
from aegisflow_dr.advisory.gateway import gateway_adapter,fetch_usage_attestation
from aegisflow_dr.advisory.operation import bind_operation
from aegisflow_dr.advisory.recovery_auth import RecoverySigner,signing_bytes
from aegisflow_dr.advisory.routing import RouteCandidate,execute_route
from aegisflow_dr.advisory.usage import UsageLedger,UsagePolicy,UsageQuote,initialize_usage
from aegisflow_dr.security.policy import AccessPolicy
from aegisflow_dr.storage import initialize,IncidentStore
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.investigation import default_policy

checkout=Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout/'src'):
    raise RuntimeError('Model gateway check imported source checkout')
sys.path.insert(0,str(checkout/'tests'))
from tls_support import TestCertificates,review_server

with TemporaryDirectory() as temporary:
    root=Path(temporary);certs=TestCertificates(root);evidence=root/'evidence.db'
    initialize(evidence);store=IncidentStore(evidence)
    source=store.record(generate_orders(),request_key='installed-gateway')
    runs=InvestigationRuns(store);record=runs.execute(source['incident_id'],default_policy(),request_key='installed-gateway')
    prepared=PreparedAdvisory(runs,record['run_id'],model_id='offline/test')
    quote=UsageQuote(prepared.manifest['input_sha256'],'offline/test','fixture-v1',10,5,2,3)
    operation_id=str(uuid4());binding=bind_operation(prepared,operation_id=operation_id,allowed_models=('offline/test',),deadline_ms=10000)
    key=Ed25519PrivateKey.generate();issuer_key=Ed25519PrivateKey.generate()
    grant=RecoverySigner(str(uuid4()),'model-gateway-result',sha(binding.payload),key.public_key().public_bytes_raw(),900,5000)
    issuer=RecoverySigner(str(uuid4()),'usage-attestation',sha(binding.payload),issuer_key.public_key().public_bytes_raw(),900,5000)
    def sign(payload,grant,key):
        value={'version':'1','purpose':grant.purpose,'principal_id':grant.principal_id,
            'operation_sha256':grant.operation_sha256,'key_sha256':sha(grant.public_key),
            'payload_sha256':sha(payload),'issued_at_ms':1000,'expires_at_ms':4000}
        return encode('recovery-signature',{**value,'signature':key.sign(signing_bytes(value)).hex()})
    metadata=decode('request',prepared.request)
    response=encode('response',{'version':'1','request_sha256':sha(prepared.request),
        'decision':'PROPOSE','assessment':record['trace']['assessment'],'evidence_sha256':metadata['evidence_sha256']})
    def handler(peer,body,*_):
        query=decode('gateway-request',body)
        value={**{k:query[k] for k in ('version','operation_sha256','request_sha256','input_sha256','quote_sha256','model_id')},
            'receipt_sha256':'1'*64,'payload_hex':response.hex(),'input_tokens':8,'output_tokens':2}
        return 200,encode('gateway-response',{'result':value,'signature_hex':sign(encode('gateway-result',value),grant,key).hex()})
    usage=root/'model.db';initialize_usage(usage,UsagePolicy(max_total_attempts=1),operation=binding)
    ledger=UsageLedger(usage,operation_id=operation_id,clock_ms=lambda:1000)
    before=evidence.read_bytes()
    with review_server(certs,runs,AccessPolicy(),handler=handler) as (server,endpoint):
        adapter=gateway_adapter(prepared,quote,binding,endpoint=endpoint,material=certs.client,grant=grant,clock_ms=lambda:1500)
        result=dispatch(prepared,quote,ledger,adapter,attempt_key='gateway',deadline_ms=10000)
        if server.requests!=1 or result['review']['status']!='VERIFIED_ADVISORY' or ledger.snapshot()['charged_cost_nusd']!=22:
            raise RuntimeError('Installed gateway/Judge/accounting qualification failed')
    usage=root/'unknown.db';initialize_usage(usage,UsagePolicy(max_total_attempts=1),operation=binding,routing=True)
    ledger=UsageLedger(usage,operation_id=operation_id,clock_ms=lambda:1000)
    result=execute_route(ledger,(RouteCandidate(prepared,quote,Adapter(quote.adapter_id,lambda _:None)),))
    def usage_handler(peer,body,*_):
        query=decode('usage-query',body)
        value={**query,'receipt_sha256':'2'*64,'input_tokens':8,'output_tokens':2};payload=encode('usage-attestation',value)
        return 200,encode('usage-reply',{'attestation_hex':payload.hex(),'signature_hex':sign(payload,issuer,issuer_key).hex()})
    saved=usage.read_bytes()
    with review_server(certs,runs,AccessPolicy(),handler=usage_handler) as (server,endpoint):
        fetched=fetch_usage_attestation(ledger,result['events'][0]['attempt_id'],endpoint=endpoint,
                                      material=certs.client,grant=issuer,now_ms=lambda:1500)
        if server.requests!=1 or fetched['verification']['charged_cost_nusd']!=22:
            raise RuntimeError('Installed independent usage inquiry failed')
    if saved!=usage.read_bytes() or ledger.snapshot()['held_tokens']!=15 or before!=evidence.read_bytes():
        raise RuntimeError('Installed gateway inquiry changed retained evidence or usage')
print('Installed pinned signed model gateway, Judge/accounting and read-only usage inquiry passed.')
