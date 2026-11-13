# SPDX-License-Identifier: Apache-2.0
"""Exercise installed detached signature verification with ephemeral in-memory keys."""
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
import tempfile
import os
from aegisflow_dr.benchmark.encrypted_curation_store import retain_encrypted_curation, read_encrypted_curation

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import aegisflow_dr
from aegisflow_dr.benchmark.core import BenchmarkError, canonical
from aegisflow_dr.benchmark.curation import prepare_manifest
from aegisflow_dr.benchmark.curation_auth import ReviewerGrant, annotation_signing_bytes, reconcile_verified_annotations
from aegisflow_dr.benchmark.signed_curation_store import retain_signed_curation, read_signed_curation

checkout=Path(__file__).resolve().parents[1]
if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout/'src'):
    raise RuntimeError('Installed curation authentication check imported checkout')
requirements=distribution('aegisflow-data-reliability').requires or []
if not any('cryptography==50.0.2' in requirement and 'curation' in requirement for requirement in requirements):
    raise RuntimeError('Installed curation optional dependency missing')
development=canonical([{'case_id':'development','family':'development','group_id':'development',
                        'csv_text':'id,value\n1,100\n','transform':'clean'}])
candidate=canonical([{'case_id':'candidate','family':'candidate','group_id':'candidate',
                      'csv_text':'id,value\n2,200\n','transform':'clean'}])
manifest=prepare_manifest(development,candidate);digest=sha256(manifest).hexdigest()
grants=[];annotations=[];envelopes=[]
for reviewer in ('reviewer-a','reviewer-b'):
    key=Ed25519PrivateKey.generate()
    grant=ReviewerGrant(reviewer,key.public_key().public_bytes_raw(),digest,1000,9000)
    annotation=canonical({'version':'1','reviewer_id':reviewer,'manifest_sha256':digest,
                          'labels':[{'case_id':'candidate','label':'NO_FAILURE_OBSERVED'}]})
    metadata={'version':'1','purpose':'aegisflow-curation-annotation','reviewer_id':reviewer,
              'key_sha256':sha256(grant.public_key).hexdigest(),'manifest_sha256':digest,
              'annotation_sha256':sha256(annotation).hexdigest(),'issued_at_ms':2000,'expires_at_ms':8000}
    envelopes.append(canonical({**metadata,'signature':key.sign(annotation_signing_bytes(metadata)).hex()}))
    grants.append(grant);annotations.append(annotation)
result=reconcile_verified_annotations(manifest,tuple(annotations),tuple(envelopes),grants=tuple(grants),now_ms=3000)
if result['status'] != 'AGREED' or len(result['authentication']['proofs']) != 2:
    raise RuntimeError('Installed signed curation reconciliation failed')
try:
    reconcile_verified_annotations(manifest,tuple(annotations),tuple(envelopes),grants=tuple(grants),now_ms=8000)
except BenchmarkError:
    pass
else:
    raise RuntimeError('Installed signature expiry was not enforced')
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)/'signed.db'
    snapshot = retain_signed_curation(path, development, candidate, tuple(annotations), tuple(envelopes),
                                       grants=tuple(grants), policy_revision='policy-1', now_ms=3000)
    retained = read_signed_curation(path, expected_sha256=snapshot, grants=tuple(grants),
                                    policy_revision='policy-1', now_ms=4000)
    if retained['status'] != 'AGREED' or retained['retention']['retained_at_ms'] != 3000:
        raise RuntimeError('Installed signed curation retention failed')
    for revision, now in (('policy-2', 4000), ('policy-1', 8000)):
        try:
            read_signed_curation(path, expected_sha256=snapshot, grants=tuple(grants),
                                 policy_revision=revision, now_ms=now)
        except BenchmarkError:
            pass
        else:
            raise RuntimeError('Installed retained evidence authority was not enforced')
print('Installed signature binding, retention, current policy and expiry passed.')

with tempfile.TemporaryDirectory() as directory:
    key = os.urandom(32)
    path = Path(directory)/'encrypted.db'
    snapshot = retain_encrypted_curation(path, development, candidate, tuple(annotations), tuple(envelopes),
                                         grants=tuple(grants), policy_revision='policy-1', now_ms=3000,
                                         key=key, key_id='installed-key')
    result = read_encrypted_curation(path, expected_sha256=snapshot, grants=tuple(grants),
                                     policy_revision='policy-1', now_ms=4000, key=key, key_id='installed-key')
    if result['status'] != 'AGREED' or candidate in path.read_bytes():
        raise RuntimeError('Installed encryption boundary failed')
    try:
        read_encrypted_curation(path, expected_sha256=snapshot, grants=tuple(grants),
                                policy_revision='policy-1', now_ms=4000, key=os.urandom(32), key_id='installed-key')
    except BenchmarkError:
        pass
    else:
        raise RuntimeError('Installed wrong encryption key accepted')
print('Installed encrypted retention and wrong-key rejection passed.')

from aegisflow_dr.benchmark.curation_access import EvaluationAccess, read_for_evaluation
access = EvaluationAccess('installed-evaluator', 'a'*64, 'installed-key', 'policy-1', 1000, 9000)
def forbidden_resolver(grant):
    raise AssertionError('Denied caller reached key resolver')
try:
    read_for_evaluation('/nonexistent', access=access, principal_id='installed-evaluator', role='curator',
                        expected_sha256='a'*64, key_id='installed-key', policy_revision='policy-1',
                        now_ms=4000, grants=(), resolve_key=forbidden_resolver)
except BenchmarkError as error:
    if str(error) != 'Evaluation access denied':
        raise
else:
    raise RuntimeError('Installed curator role was accepted')
print('Installed evaluator authorization boundary passed.')
