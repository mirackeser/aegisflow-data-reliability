# SPDX-License-Identifier: Apache-2.0
"""Retain signed evidence without treating archived grants as current authority."""
from hashlib import sha256

from .core import BenchmarkError, ID, canonical, closed, parse, validate
from .curation import prepare_manifest
from .curation_auth import ReviewerGrant, TIME, _time, reconcile_verified_annotations
from .curation_store import _read_snapshot, _write_snapshot
from .quality import HASH

ARTIFACT_NAMES = ('development', 'candidate', 'annotation_a', 'annotation_b',
                  'envelope_a', 'envelope_b', 'trust_policy')
HEADER = closed({'version': {'const': 'signed-curation-v1'}, 'retained_at_ms': TIME,
                 'artifacts': closed({name: HASH for name in ARTIFACT_NAMES}),
                 'manifest_sha256': HASH, 'result_sha256': HASH})


def _policy(grants, revision):
    validate(ID, revision)
    if type(grants) is not tuple or len(grants) != 2 or any(type(g) is not ReviewerGrant for g in grants):
        raise BenchmarkError('Two trusted curation grants required')
    return canonical({'version': '1', 'revision': revision, 'grants': [
        {'reviewer_id': g.reviewer_id, 'public_key_hex': g.public_key.hex(),
         'manifest_sha256': g.manifest_sha256, 'not_before_ms': g.not_before_ms,
         'expires_at_ms': g.expires_at_ms, 'revoked': g.revoked} for g in grants]})


def _prepare(development, candidate, annotations, envelopes, grants, revision, now_ms):
    policy = _policy(grants, revision)
    manifest = prepare_manifest(development, candidate)
    result = reconcile_verified_annotations(manifest, annotations, envelopes, grants=grants, now_ms=now_ms)
    artifacts = dict(zip(ARTIFACT_NAMES, (development, candidate, *annotations, *envelopes, policy)))
    header = canonical({'version': 'signed-curation-v1', 'retained_at_ms': now_ms,
                        'artifacts': {name: sha256(raw).hexdigest() for name, raw in artifacts.items()},
                        'manifest_sha256': sha256(manifest).hexdigest(),
                        'result_sha256': sha256(canonical(result)).hexdigest()})
    return header, artifacts, result, manifest


def retain_signed_curation(path, development, candidate, annotations, envelopes, *, grants,
                           policy_revision, now_ms):
    """Create a new private local snapshot only after full signature/consensus checks.

    The returned digest must be retained independently by the trusted host.
    This plaintext format is not a sealed holdout or encrypted storage service.
    """
    header, artifacts, _, _ = _prepare(development, candidate, annotations, envelopes,
                                      grants, policy_revision, now_ms)
    return _write_snapshot(path, header, artifacts)


def read_signed_curation(path, *, expected_sha256, grants, policy_revision, now_ms):
    """Revalidate persisted evidence with current externally supplied authority.

    No stored key or grant is promoted to trust. Expired/revoked/changed policy
    blocks label export, even when the original retention was valid.
    """
    _policy(grants, policy_revision)
    _time(now_ms)
    artifacts = _read_snapshot(path, expected_sha256, {*ARTIFACT_NAMES, 'header'})
    return _verify_artifacts(artifacts, expected_sha256=expected_sha256, grants=grants,
                             policy_revision=policy_revision, now_ms=now_ms)


def _verify_artifacts(artifacts, *, expected_sha256, grants, policy_revision, now_ms):
    policy = _policy(grants, policy_revision)
    _time(now_ms)
    header = parse(artifacts['header'])
    validate(HEADER, header)
    _time(header['retained_at_ms'])
    if artifacts['trust_policy'] != policy or now_ms < header['retained_at_ms']:
        raise BenchmarkError('Curation retention policy or time rejected')
    annotations = (artifacts['annotation_a'], artifacts['annotation_b'])
    envelopes = (artifacts['envelope_a'], artifacts['envelope_b'])
    expected_header, _, _, manifest = _prepare(artifacts['development'], artifacts['candidate'],
                                               annotations, envelopes, grants, policy_revision,
                                               header['retained_at_ms'])
    if artifacts['header'] != expected_header:
        raise BenchmarkError('Signed curation snapshot integrity rejected')
    result = reconcile_verified_annotations(manifest, annotations, envelopes, grants=grants, now_ms=now_ms)
    return {**result, 'retention': {'snapshot_sha256': expected_sha256,
                                   'policy_sha256': sha256(policy).hexdigest(),
                                   'policy_revision': policy_revision,
                                   'retained_at_ms': header['retained_at_ms']}}
