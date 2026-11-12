# SPDX-License-Identifier: Apache-2.0
"""Detached annotation signatures under explicit, dataset-scoped host grants."""
from dataclasses import dataclass, field
from hashlib import sha256

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .core import BenchmarkError, ID, canonical, closed, parse, validate
from .curation import ANNOTATION, MANIFEST, reconcile_annotations
from .quality import HASH

TIME = {'type':'integer', 'minimum':0, 'maximum':10**18}
METADATA = closed({'version':{'const':'1'}, 'purpose':{'const':'aegisflow-curation-annotation'},
                   'reviewer_id':ID, 'key_sha256':HASH, 'manifest_sha256':HASH,
                   'annotation_sha256':HASH, 'issued_at_ms':TIME, 'expires_at_ms':TIME})
ENVELOPE = closed({**METADATA['properties'], 'signature':{'type':'string', 'minLength':128,
                                                       'maxLength':128, 'pattern':'^[0-9a-f]{128}$'}})
DOMAIN = b'aegisflow/curation-annotation/v1\x00'


def _time(value):
    if type(value) is not int or not 0 <= value <= 10**18:
        raise BenchmarkError('Integer curation time required')


def annotation_signing_bytes(metadata):
    """Public signing format; private-key custody belongs to the reviewer host."""
    validate(METADATA, metadata)
    for key in ('issued_at_ms','expires_at_ms'):
        _time(metadata[key])
    if metadata['issued_at_ms'] >= metadata['expires_at_ms']:
        raise BenchmarkError('Curation signature interval rejected')
    return DOMAIN + canonical(metadata)


@dataclass(frozen=True)
class ReviewerGrant:
    reviewer_id: str
    public_key: bytes = field(repr=False)
    manifest_sha256: str
    not_before_ms: int
    expires_at_ms: int
    revoked: bool = False

    def __post_init__(self):
        validate(ID,self.reviewer_id)
        validate(HASH,self.manifest_sha256)
        _time(self.not_before_ms);_time(self.expires_at_ms)
        if (type(self.public_key) is not bytes or len(self.public_key) != 32
                or type(self.revoked) is not bool or self.not_before_ms >= self.expires_at_ms):
            raise BenchmarkError('Curation reviewer grant rejected')


def verify_annotation(annotation_bytes, envelope_bytes, *, grant, now_ms):
    """Authenticate exact bytes with an out-of-band trusted grant and clock."""
    if type(grant) is not ReviewerGrant or grant.revoked:
        raise BenchmarkError('Active curation reviewer grant required')
    _time(now_ms)
    if type(envelope_bytes) is not bytes or len(envelope_bytes) > 4096:
        raise BenchmarkError('Curation signature envelope rejected')
    annotation=parse(annotation_bytes);validate(ANNOTATION,annotation)
    envelope=parse(envelope_bytes);validate(ENVELOPE,envelope)
    metadata={key:value for key,value in envelope.items() if key != 'signature'}
    message=annotation_signing_bytes(metadata)
    key_digest=sha256(grant.public_key).hexdigest()
    if (annotation['reviewer_id'] != grant.reviewer_id or metadata['reviewer_id'] != grant.reviewer_id
            or annotation['manifest_sha256'] != grant.manifest_sha256
            or metadata['manifest_sha256'] != grant.manifest_sha256 or metadata['key_sha256'] != key_digest
            or metadata['annotation_sha256'] != sha256(annotation_bytes).hexdigest()
            or not grant.not_before_ms <= metadata['issued_at_ms'] <= now_ms < metadata['expires_at_ms'] <= grant.expires_at_ms):
        raise BenchmarkError('Curation signature binding or validity rejected')
    try:
        Ed25519PublicKey.from_public_bytes(grant.public_key).verify(bytes.fromhex(envelope['signature']),message)
    except (InvalidSignature, UnsupportedAlgorithm, ValueError):
        raise BenchmarkError('Curation signature verification rejected') from None
    return {**metadata, 'envelope_sha256':sha256(envelope_bytes).hexdigest()}


def reconcile_verified_annotations(manifest_bytes, annotations, envelopes, *, grants, now_ms):
    """Two distinct granted keys before consensus; no deployment or storage authority."""
    if any(type(items) is not tuple or len(items) != 2 for items in (annotations,envelopes,grants)):
        raise BenchmarkError('Two signed curation artifacts and grants required')
    if (any(type(grant) is not ReviewerGrant for grant in grants)
            or grants[0].reviewer_id == grants[1].reviewer_id or grants[0].public_key == grants[1].public_key):
        raise BenchmarkError('Distinct curation reviewers and keys required')
    validate(MANIFEST,parse(manifest_bytes))
    digest=sha256(manifest_bytes).hexdigest()
    if any(grant.manifest_sha256 != digest for grant in grants):
        raise BenchmarkError('Curation grant manifest rejected')
    proofs=[verify_annotation(annotation,envelope,grant=grant,now_ms=now_ms)
            for annotation,envelope,grant in zip(annotations,envelopes,grants)]
    result=reconcile_annotations(manifest_bytes,annotations,expected_manifest_sha256=digest,
                                 reviewer_ids=tuple(grant.reviewer_id for grant in grants))
    return {**result,'authentication':{'version':'1','method':'ed25519','verified_at_ms':now_ms,'proofs':proofs}}
