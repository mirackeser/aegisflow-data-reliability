# SPDX-License-Identifier: Apache-2.0
"""Trusted-host evaluation access; identity and key custody remain external."""
from dataclasses import dataclass

from .core import BenchmarkError, ID, validate
from .curation_auth import _time
from .encrypted_curation_store import read_encrypted_curation
from .quality import HASH


@dataclass(frozen=True)
class EvaluationAccess:
    principal_id: str
    snapshot_sha256: str
    key_id: str
    policy_revision: str
    not_before_ms: int
    expires_at_ms: int
    revoked: bool = False

    def __post_init__(self):
        for value in (self.principal_id, self.key_id, self.policy_revision):
            validate(ID, value)
        validate(HASH, self.snapshot_sha256)
        _time(self.not_before_ms); _time(self.expires_at_ms)
        if type(self.revoked) is not bool or self.not_before_ms >= self.expires_at_ms:
            raise BenchmarkError('Evaluation access interval or revocation rejected')


def read_for_evaluation(path, *, access, principal_id, role, expected_sha256, key_id,
                        policy_revision, now_ms, grants, resolve_key):
    """Authorize exact scope before invoking the trusted host's key resolver.

    All identity/role/access arguments are trusted host inputs, never model or
    request claims. The resolver must enforce its own current key policy.
    """
    _time(now_ms)
    if (type(access) is not EvaluationAccess or access.revoked or role != 'evaluator'
            or principal_id != access.principal_id or expected_sha256 != access.snapshot_sha256
            or key_id != access.key_id or policy_revision != access.policy_revision
            or not access.not_before_ms <= now_ms < access.expires_at_ms):
        raise BenchmarkError('Evaluation access denied')
    try:
        key = resolve_key(access)
    except Exception:
        raise BenchmarkError('Evaluation key unavailable') from None
    return read_encrypted_curation(path, expected_sha256=expected_sha256, grants=grants,
                                    policy_revision=policy_revision, now_ms=now_ms, key=key, key_id=key_id)
