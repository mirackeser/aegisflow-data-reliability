# SPDX-License-Identifier: Apache-2.0
"""Bind verified mTLS peers to evaluator grants and externally held key versions."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import os
from pathlib import Path

from .access_registry import _db, evaluate_registered
from .core import BenchmarkError, ID, canonical, parse, validate
from .curation_auth import _time
from .quality import HASH
from ..security.mtls import SecurityError, peer_fingerprint


@dataclass(frozen=True)
class IdentityKeyBinding:
    peer_sha256: str
    principal_id: str
    grant_sha256: str
    key_id: str
    key_material_sha256: str
    not_before_ms: int
    expires_at_ms: int

    def __post_init__(self):
        for value in (self.peer_sha256, self.grant_sha256, self.key_material_sha256):
            validate(HASH, value)
        for value in (self.principal_id, self.key_id):
            validate(ID, value)
        _time(self.not_before_ms); _time(self.expires_at_ms)
        if self.not_before_ms >= self.expires_at_ms:
            raise BenchmarkError('Identity/key interval rejected')


def initialize_binding(path, binding):
    if type(binding) is not IdentityKeyBinding:
        raise BenchmarkError('Identity/key binding required')
    raw = canonical(asdict(binding))
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    except (OSError, TypeError, ValueError):
        raise BenchmarkError('New identity/key registry required') from None
    with _db(path) as db:
        db.execute('CREATE TABLE binding (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL, identity_revoked INTEGER NOT NULL CHECK(identity_revoked IN (0,1)), key_disabled INTEGER NOT NULL CHECK(key_disabled IN (0,1)))')
        db.execute('INSERT INTO binding VALUES (1,?,0,0)', (raw,))
        db.execute("CREATE TRIGGER preserve_binding BEFORE UPDATE ON binding WHEN NEW.payload IS NOT OLD.payload OR NEW.id != OLD.id OR NEW.identity_revoked < OLD.identity_revoked OR NEW.key_disabled < OLD.key_disabled BEGIN SELECT RAISE(ABORT,'Immutable binding'); END")
        db.execute("CREATE TRIGGER preserve_binding_delete BEFORE DELETE ON binding BEGIN SELECT RAISE(ABORT,'Immutable binding'); END")
    return sha256(raw).hexdigest()


def _binding(db, expected_sha256):
    rows = db.execute('SELECT payload,identity_revoked,key_disabled FROM binding LIMIT 2').fetchall()
    if (len(rows) != 1 or type(rows[0][0]) is not bytes or sha256(rows[0][0]).hexdigest() != expected_sha256
            or any(type(flag) is not int or flag not in (0,1) for flag in rows[0][1:])):
        raise BenchmarkError('Identity/key registry binding rejected')
    try:
        binding = IdentityKeyBinding(**parse(rows[0][0]))
    except TypeError:
        raise BenchmarkError('Identity/key record rejected') from None
    return binding, bool(rows[0][1]), bool(rows[0][2])


def disable_binding(path, *, expected_sha256, component):
    """Terminal, idempotent disable for this exact identity or key-version binding."""
    if component not in ('identity', 'key'):
        raise BenchmarkError('Identity or key component required')
    column = {'identity':'identity_revoked', 'key':'key_disabled'}[component]
    with _db(path) as db:
        _binding(db, expected_sha256)
        db.execute(f'UPDATE binding SET {column}=1 WHERE id=1')


def evaluate_peer(binding_path, registry_path, snapshot_path, *, expected_binding_sha256, peer,
                  expected_sha256, policy_revision, now_ms, grants, resolve_key):
    """Derive principal from a verified TLS channel, never forwarded identity text."""
    _time(now_ms)
    if Path(binding_path).resolve() == Path(registry_path).resolve():
        raise BenchmarkError('Separate binding and access registries required')
    try:
        pin = peer_fingerprint(peer, client=True)
    except SecurityError:
        raise BenchmarkError('Authenticated evaluator channel required') from None
    with _db(binding_path) as db:
        binding, revoked, disabled = _binding(db, expected_binding_sha256)
        if (revoked or disabled or pin != binding.peer_sha256
                or not binding.not_before_ms <= now_ms < binding.expires_at_ms):
            raise BenchmarkError('Identity/key access denied')
        def checked_key(access):
            key = resolve_key(access)
            if type(key) is not bytes or len(key) != 32 or sha256(key).hexdigest() != binding.key_material_sha256:
                raise BenchmarkError('Identity/key material rejected')
            return key
        return evaluate_registered(registry_path, snapshot_path, expected_grant_sha256=binding.grant_sha256,
                                   principal_id=binding.principal_id, role='evaluator', expected_sha256=expected_sha256,
                                   key_id=binding.key_id, policy_revision=policy_revision, now_ms=now_ms,
                                   grants=grants, resolve_key=checked_key)
