# SPDX-License-Identifier: Apache-2.0
"""Operation-scoped recovery evidence signatures; verification never settles usage."""
from dataclasses import dataclass, field
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import AdvisoryError, decode, encode
from .recovery import assess_recovery
from .usage import UsageLedger, database, integer
from ..storage.store import canonical, sha

from .contracts import PURPOSES


def signing_bytes(metadata):
    value = decode('recovery-signature-metadata', encode('recovery-signature-metadata',metadata))
    integer(value['issued_at_ms'],0,10**18); integer(value['expires_at_ms'],0,10**18)
    if value['issued_at_ms'] >= value['expires_at_ms']:
        raise AdvisoryError('Recovery signature interval rejected')
    return b'aegisflow/recovery/v1\x00' + canonical(value)


@dataclass(frozen=True)
class RecoverySigner:
    principal_id: str
    purpose: str
    operation_sha256: str
    public_key: bytes = field(repr=False)
    not_before_ms: int
    expires_at_ms: int
    revoked: bool = False

    def __post_init__(self):
        integer(self.not_before_ms,0,10**18); integer(self.expires_at_ms,0,10**18)
        if (type(self.public_key) is not bytes or len(self.public_key)!=32 or
                type(self.revoked) is not bool or self.not_before_ms >= self.expires_at_ms):
            raise AdvisoryError('Recovery signer grant rejected')
        signing_bytes({'version':'1','purpose':self.purpose,'principal_id':self.principal_id,
            'operation_sha256':self.operation_sha256,'key_sha256':sha(self.public_key),
            'payload_sha256':'0'*64,'issued_at_ms':self.not_before_ms,'expires_at_ms':self.expires_at_ms})


def verify_signature(payload, envelope, *, grant, purpose, now_ms):
    integer(now_ms,0,10**18)
    if type(grant) is not RecoverySigner or grant.revoked or purpose not in PURPOSES:
        raise AdvisoryError('Active recovery signer required')
    value = decode('recovery-signature',envelope)
    metadata = {k:v for k,v in value.items() if k!='signature'}
    message = signing_bytes(metadata)
    if (type(payload) is not bytes or len(payload)>16384 or grant.purpose!=purpose or
            value['purpose']!=purpose or value['principal_id']!=grant.principal_id or
            value['operation_sha256']!=grant.operation_sha256 or value['key_sha256']!=sha(grant.public_key) or
            value['payload_sha256']!=sha(payload) or
            not grant.not_before_ms <= value['issued_at_ms'] <= now_ms < value['expires_at_ms'] <= grant.expires_at_ms):
        raise AdvisoryError('Recovery signature scope or validity rejected')
    try:
        Ed25519PublicKey.from_public_bytes(grant.public_key).verify(bytes.fromhex(value['signature']),message)
    except (InvalidSignature,UnsupportedAlgorithm,ValueError):
        raise AdvisoryError('Recovery signature rejected') from None
    return value


def _verify_usage(connection, ledger, payload, envelope, *, grant, now_ms):
    value = decode('usage-attestation',payload)
    proof = verify_signature(payload,envelope,grant=grant,purpose='usage-attestation',now_ms=now_ms)
    report = assess_recovery(ledger)
    assessment = report['assessment']
    if (proof['operation_sha256']!=assessment['operation_sha256'] or
            any(value[k]!=assessment[k] for k in ('operation_sha256','snapshot_sha256')) or
            value['assessment_sha256']!=report['assessment_sha256']):
        raise AdvisoryError('Stale usage attestation rejected')
    row = connection.execute('SELECT * FROM attempts WHERE attempt_id=?',(value['attempt_id'],)).fetchone()
    if (row is None or row['status'] not in ('UNKNOWN','IN_FLIGHT') or
            any(value[k]!=row[k] for k in ('request_sha256','input_sha256','quote_sha256'))):
        raise AdvisoryError('Usage attestation attempt rejected')
    integer(value['input_tokens'],0,row['input_cap']); integer(value['output_tokens'],0,row['output_cap'])
    return {'attestation':value,'proof':proof,'charged_tokens':value['input_tokens']+value['output_tokens'],
            'charged_cost_nusd':value['input_tokens']*row['input_rate']+value['output_tokens']*row['output_rate']}


def verify_usage_attestation(ledger, payload, envelope, *, grant, now_ms):
    if type(ledger) is not UsageLedger or ledger.version!=3:
        raise AdvisoryError('Routing ledger required for attestation')
    with database(ledger.path) as connection:
        ledger._validate(connection)
        return _verify_usage(connection,ledger,payload,envelope,grant=grant,now_ms=now_ms)
