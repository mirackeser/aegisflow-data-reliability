# SPDX-License-Identifier: Apache-2.0
"""Pinned mTLS model-gateway and independently signed usage inquiry profiles."""
from dataclasses import asdict
from .contracts import AdvisoryError,decode,encode
from .context import PreparedAdvisory
from .dispatch import Adapter,AdapterRequest,AdapterResult
from .operation import OperationBinding
from .recovery import assess_recovery
from .recovery_auth import RecoverySigner,verify_signature,verify_usage_attestation
from .usage import UsageLedger,UsageQuote,database,integer
from ..integration.secure_review import post_json,TransportError
from ..security.mtls import TLSFiles,SecurityError
from ..security.policy import EgressPolicy
from ..storage.store import canonical,sha


def _endpoint(endpoint, material):
    if type(endpoint) is not EgressPolicy or type(material) is not TLSFiles:
        raise AdvisoryError('Trusted gateway endpoint required')


def _active(grant, now_ms):
    integer(now_ms,0,10**18)
    if grant.revoked or not grant.not_before_ms <= now_ms < grant.expires_at_ms:
        raise AdvisoryError('Current gateway grant required')


def _post(payload, *, endpoint, material, timeout):
    try:
        return post_json(payload,endpoint=endpoint,material=material,timeout=timeout)
    except (TransportError,SecurityError):
        raise AdvisoryError('Gateway exchange unavailable') from None


def gateway_adapter(prepared, quote, operation, *, endpoint, material, grant, clock_ms):
    """Bind one prepared input/quote/operation to one explicitly configured gateway."""
    _endpoint(endpoint,material)
    if (type(prepared) is not PreparedAdvisory or type(quote) is not UsageQuote or
            type(operation) is not OperationBinding or type(grant) is not RecoverySigner or
            grant.purpose!='model-gateway-result' or grant.operation_sha256!=sha(operation.payload) or
            not callable(clock_ms)):
        raise AdvisoryError('Bound gateway configuration required')
    operation.admit(prepared,decode('operation',operation.payload)['deadline_ms'])
    metadata=decode('request',prepared.request)
    messages=canonical(prepared.messages)
    if quote.model_id!=metadata['model_id'] or quote.input_sha256!=sha(messages):
        raise AdvisoryError('Gateway quote binding rejected')
    identity={'version':'1','operation_sha256':sha(operation.payload),'request_sha256':sha(prepared.request),
              'input_sha256':sha(messages),'quote_sha256':sha(canonical(asdict(quote))),'model_id':quote.model_id}

    def send(request):
        if (type(request) is not AdapterRequest or request.messages!=messages or
                request.request_sha256!=identity['request_sha256'] or request.model_id!=quote.model_id or
                request.output_limit!=quote.output_limit):
            raise AdvisoryError('Gateway dispatch binding rejected')
        integer(request.remaining_ms,1,600000);integer(request.max_response_bytes,1,16384)
        now=clock_ms();_active(grant,now)
        remaining=min(request.remaining_ms,decode('operation',operation.payload)['deadline_ms']-now,10000)
        integer(remaining,1,10000)
        query=encode('gateway-request',{**identity,'messages_hex':messages.hex(),
                                      'output_limit':quote.output_limit,'remaining_ms':remaining})
        reply=decode('gateway-response',_post(query,endpoint=endpoint,material=material,timeout=remaining/1000))
        result=reply['result'];payload=encode('gateway-result',result)
        proof=verify_signature(payload,bytes.fromhex(reply['signature_hex']),grant=grant,
                               purpose='model-gateway-result',now_ms=clock_ms())
        if (proof['operation_sha256']!=identity['operation_sha256'] or
                any(result[k]!=v for k,v in identity.items())):
            raise AdvisoryError('Gateway result binding rejected')
        integer(result['input_tokens'],0,quote.input_tokens);integer(result['output_tokens'],0,quote.output_limit)
        response=bytes.fromhex(result['payload_hex'])
        if len(response)>request.max_response_bytes:
            raise AdvisoryError('Gateway response budget exceeded')
        return AdapterResult(response,result['input_tokens'],result['output_tokens'])
    return Adapter(quote.adapter_id,send)


def fetch_usage_attestation(ledger, attempt_id, *, endpoint, material, grant, now_ms, timeout=5.0):
    """Fetch exact signed evidence, then verify freshness after I/O; never settle."""
    _endpoint(endpoint,material)
    if (type(ledger) is not UsageLedger or ledger.version not in (3,4) or
            type(grant) is not RecoverySigner or grant.purpose!='usage-attestation' or not callable(now_ms)):
        raise AdvisoryError('Trusted usage inquiry configuration required')
    _active(grant,now_ms())
    # No ledger transaction is held during network I/O. Revalidation follows receipt.
    with database(ledger.path) as connection:
        ledger._validate(connection)
        report=assess_recovery(ledger)
        row=connection.execute('SELECT * FROM attempts WHERE attempt_id=?',(attempt_id,)).fetchone()
        if row is None or row['status'] not in ('UNKNOWN','IN_FLIGHT'):
            raise AdvisoryError('Unresolved usage attempt required')
        value={'version':'1',**{k:report['assessment'][k] for k in ('operation_sha256','snapshot_sha256')},
            'assessment_sha256':report['assessment_sha256'],
            **{k:row[k] for k in ('attempt_id','request_sha256','input_sha256','quote_sha256')}}
        if grant.operation_sha256!=value['operation_sha256']:
            raise AdvisoryError('Usage inquiry operation rejected')
    query=encode('usage-query',value)
    reply=decode('usage-reply',_post(query,endpoint=endpoint,material=material,timeout=timeout))
    payload=bytes.fromhex(reply['attestation_hex']);signature=bytes.fromhex(reply['signature_hex'])
    verified=verify_usage_attestation(ledger,payload,signature,grant=grant,now_ms=now_ms())
    return {'attestation':payload,'signature':signature,'verification':verified}
