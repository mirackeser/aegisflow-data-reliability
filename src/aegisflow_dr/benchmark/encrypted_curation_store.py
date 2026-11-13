# SPDX-License-Identifier: Apache-2.0
"""Authenticated encryption of signed evidence; keys stay with the trusted host."""
from hashlib import sha256
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .core import BenchmarkError, ID, canonical, closed, parse, validate
from .curation_store import _read_snapshot, _write_snapshot
from .quality import HASH
from .signed_curation_store import ARTIFACT_NAMES, _prepare, _verify_artifacts

NAMES = (*ARTIFACT_NAMES, 'signed_header')
HEADER = closed({'version': {'const': 'encrypted-curation-v1'}, 'key_id': ID,
                 'snapshot_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$', 'minLength': 32, 'maxLength': 32},
                 'artifacts': closed({name: HASH for name in NAMES})})


def _cipher(key, key_id):
    validate(ID, key_id)
    if type(key) is not bytes or len(key) != 32:
        raise BenchmarkError('Host supplied 256-bit curation key required')
    return AESGCM(key)


def _aad(header, name):
    return b'aegisflow/encrypted-curation/v1\x00' + canonical(
        {field: header[field] for field in ('version', 'key_id', 'snapshot_id')} | {'artifact': name})


def retain_encrypted_curation(path, development, candidate, annotations, envelopes, *, grants,
                              policy_revision, now_ms, key, key_id):
    """Validate and encrypt in memory before exclusive transactional creation."""
    cipher = _cipher(key, key_id)
    signed_header, artifacts, _, _ = _prepare(development, candidate, annotations, envelopes,
                                             grants, policy_revision, now_ms)
    artifacts['signed_header'] = signed_header
    header = {'version': 'encrypted-curation-v1', 'key_id': key_id, 'snapshot_id': os.urandom(16).hex()}
    encrypted = {}
    for name, raw in artifacts.items():
        nonce = os.urandom(12)
        encrypted[name] = nonce + cipher.encrypt(nonce, raw, _aad(header, name))
    header['artifacts'] = {name: sha256(raw).hexdigest() for name, raw in encrypted.items()}
    return _write_snapshot(path, canonical(header), encrypted)


def read_encrypted_curation(path, *, expected_sha256, grants, policy_revision, now_ms, key, key_id):
    """Decrypt only under external key selection, then recheck current signing policy."""
    cipher = _cipher(key, key_id)
    encrypted = _read_snapshot(path, expected_sha256, {*NAMES, 'header'}, maximum_blob_bytes=1_000_028)
    header = parse(encrypted.pop('header')); validate(HEADER, header)
    if header['key_id'] != key_id:
        raise BenchmarkError('Curation encryption key binding rejected')
    artifacts = {}
    for name, raw in encrypted.items():
        if len(raw) < 29 or sha256(raw).hexdigest() != header['artifacts'][name]:
            raise BenchmarkError('Encrypted curation integrity rejected')
        try:
            artifacts[name] = cipher.decrypt(raw[:12], raw[12:], _aad(header, name))
        except InvalidTag:
            raise BenchmarkError('Curation decryption rejected') from None
    artifacts['header'] = artifacts.pop('signed_header')
    result = _verify_artifacts(artifacts, expected_sha256=sha256(artifacts['header']).hexdigest(),
                               grants=grants, policy_revision=policy_revision, now_ms=now_ms)
    return {**result, 'encryption': {'version': '1', 'algorithm': 'AES-256-GCM', 'key_id': key_id,
                                    'snapshot_sha256': expected_sha256}}
