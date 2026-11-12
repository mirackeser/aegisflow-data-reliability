# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisflow_dr.benchmark.core import BenchmarkError, canonical, parse
from aegisflow_dr.benchmark.curation_auth import (
    DOMAIN, ENVELOPE, ReviewerGrant, annotation_signing_bytes,
    reconcile_verified_annotations, verify_annotation,
)
from aegisflow_dr.benchmark.quality import freeze_statistical_protocol, evaluate_quality
import test_curation


class CurationAuthenticationTests(unittest.TestCase):
    def setUp(self):
        fixture=test_curation.CurationTests();fixture.setUp()
        self.manifest=fixture.manifest;self.digest=fixture.digest
        self.annotations=tuple(canonical(x) for x in fixture.annotations)
        self.keys=tuple(Ed25519PrivateKey.generate() for _ in range(2))
        self.grants=tuple(ReviewerGrant(reviewer,key.public_key().public_bytes_raw(),self.digest,1000,9000)
                          for reviewer,key in zip(fixture.reviewers,self.keys))
        self.envelopes=tuple(self.envelope(i) for i in range(2))

    def envelope(self,index,**changes):
        grant=self.grants[index]
        metadata={'version':'1','purpose':'aegisflow-curation-annotation','reviewer_id':grant.reviewer_id,
                  'key_sha256':sha256(grant.public_key).hexdigest(),'manifest_sha256':self.digest,
                  'annotation_sha256':sha256(self.annotations[index]).hexdigest(),'issued_at_ms':2000,'expires_at_ms':8000}
        metadata.update(changes)
        # Independent signer construction checks the documented wire representation.
        signature=self.keys[index].sign(DOMAIN+canonical(metadata)).hex()
        return canonical({**metadata,'signature':signature})

    def verify(self,**changes):
        values=dict(grant=self.grants[0],now_ms=3000)
        return verify_annotation(self.annotations[0],self.envelopes[0],**{**values,**changes})

    def reconcile(self,**changes):
        values=dict(grants=self.grants,now_ms=3000)
        return reconcile_verified_annotations(self.manifest,self.annotations,self.envelopes,**{**values,**changes})

    def test_real_signatures_authenticate_before_agreed_labels_are_returned(self):
        result=self.reconcile()
        self.assertEqual(result['status'],'AGREED')
        self.assertEqual(len(result['cases']),3)
        self.assertEqual(result['authentication']['verified_at_ms'],3000)
        self.assertEqual(len(result['authentication']['proofs']),2)
        self.assertEqual(self.verify()['envelope_sha256'],sha256(self.envelopes[0]).hexdigest())
        self.assertEqual(result,self.reconcile())
        cases=canonical(result['cases'])
        protocol=freeze_statistical_protocol(cases,model_revision_sha256='a'*64,families=('heldout-family',))
        outputs=canonical([{'case_id':x['case_id'],'prediction':x['label'],'unsupported_claim':False} for x in result['cases']])
        gate=evaluate_quality(protocol,cases,outputs,model_revision_sha256='a'*64)
        self.assertEqual(gate['decision'],'BLOCK')
        self.assertIn('PROVENANCE_NOT_APPROVED',gate['reasons'])

    def test_signing_format_is_canonical_and_domain_separated(self):
        metadata=parse(self.envelopes[0]);metadata.pop('signature')
        expected=DOMAIN+canonical(metadata)
        self.assertEqual(annotation_signing_bytes(dict(reversed(list(metadata.items())))),expected)
        envelope=parse(self.envelopes[0])
        envelope['signature']=self.keys[0].sign(canonical(metadata)).hex()
        self.envelopes=(canonical(envelope),self.envelopes[1])
        with self.assertRaisesRegex(BenchmarkError,'verification rejected'):self.verify()

    def test_changed_bytes_reject_even_if_annotation_meaning_is_unchanged(self):
        self.annotations=(self.annotations[0]+b' ',self.annotations[1])
        with self.assertRaises(BenchmarkError):self.verify()

    def test_wrong_key_signature_and_modified_metadata_reject(self):
        envelope=parse(self.envelopes[0]);envelope['signature']=self.keys[1].sign(b'wrong').hex()
        self.envelopes=(canonical(envelope),self.envelopes[1])
        with self.assertRaisesRegex(BenchmarkError,'verification rejected'):self.verify()
        self.envelopes=(self.envelope(0),self.envelopes[1])
        tampered=parse(self.envelopes[0]);tampered['expires_at_ms']=7000
        with self.assertRaisesRegex(BenchmarkError,'verification rejected'):
            verify_annotation(self.annotations[0],canonical(tampered),grant=self.grants[0],now_ms=3000)
        for key,value in (('key_sha256','0'*64),('manifest_sha256','0'*64),('reviewer_id','outsider'),
                          ('annotation_sha256','0'*64)):
            changed=parse(self.envelopes[0]);changed[key]=value
            with self.subTest(key=key),self.assertRaises(BenchmarkError):
                verify_annotation(self.annotations[0],canonical(changed),grant=self.grants[0],now_ms=3000)

    def test_revoked_and_untrusted_grants_fail_closed(self):
        for grant in (None,{},replace(self.grants[0],revoked=True),
                      replace(self.grants[0],public_key=self.grants[1].public_key)):
            with self.assertRaises(BenchmarkError):self.verify(grant=grant)

    def test_time_boundaries_and_grant_window_are_enforced(self):
        self.verify(now_ms=2000);self.verify(now_ms=7999)
        for now in (1999,8000,9000,True,3000.0,-1,10**18+1):
            with self.subTest(now=now),self.assertRaises(BenchmarkError):self.verify(now_ms=now)
        for changes in ({'issued_at_ms':999},{'expires_at_ms':9001}, {'issued_at_ms':8000},
                        {'expires_at_ms':2000},{'issued_at_ms':2000.0},{'expires_at_ms':True}):
            with self.subTest(changes=changes),self.assertRaises(BenchmarkError):
                verify_annotation(self.annotations[0],self.envelope(0,**changes),grant=self.grants[0],now_ms=3000)

    def test_closed_contract_malformed_signature_and_payload_limits_reject(self):
        for raw in (None,b'{}',b'NaN',b'\xff',b'x'*4097,b'{"version":"1","version":"1"}'):
            with self.assertRaises(BenchmarkError):verify_annotation(self.annotations[0],raw,grant=self.grants[0],now_ms=3000)
        for changes in ({'signature':'f'*127},{'signature':'Z'*128},{'purpose':'other-purpose'},
                        {'version':'2'},{'instruction':'override'}):
            envelope={**parse(self.envelopes[0]),**changes}
            with self.assertRaises(BenchmarkError):
                verify_annotation(self.annotations[0],canonical(envelope),grant=self.grants[0],now_ms=3000)
        with self.assertRaises(BenchmarkError):
            verify_annotation(b'{}',self.envelopes[0],grant=self.grants[0],now_ms=3000)

    def test_grant_contract_rejects_invalid_keys_ids_and_intervals(self):
        for changes in ({'reviewer_id':'Bad ID'},{'manifest_sha256':'bad'}, {'public_key':'secret'},
                        {'public_key':b'x'*31},{'revoked':1},{'not_before_ms':True},
                        {'not_before_ms':9000},{'expires_at_ms':1000}):
            with self.subTest(changes=changes),self.assertRaises(BenchmarkError):replace(self.grants[0],**changes)

    def test_two_distinct_reviewer_names_and_keys_are_required(self):
        for grants in ((self.grants[0],self.grants[0]),(self.grants[0],None),
                       (self.grants[0],replace(self.grants[1],public_key=self.grants[0].public_key))):
            with self.assertRaises(BenchmarkError):self.reconcile(grants=grants)

    def test_exact_pair_shape_and_manifest_scope_are_required(self):
        for index in range(3):
            for bad in (None,[],(),(b'x',)):
                arguments=[self.annotations,self.envelopes,self.grants];arguments[index]=bad
                with self.assertRaises(BenchmarkError):
                    reconcile_verified_annotations(self.manifest,arguments[0],arguments[1],grants=arguments[2],now_ms=3000)
        with self.assertRaises(BenchmarkError):
            self.reconcile(grants=(replace(self.grants[0],manifest_sha256='0'*64),self.grants[1]))
        self.manifest+=b' '
        with self.assertRaises(BenchmarkError):self.reconcile()

    def test_valid_signatures_do_not_override_annotation_disagreement(self):
        annotation=parse(self.annotations[1]);annotation['labels'][0]['label']=annotation['labels'][1]['label']
        self.annotations=(self.annotations[0],canonical(annotation))
        self.envelopes=(self.envelopes[0],self.envelope(1))
        result=self.reconcile()
        self.assertEqual(result['status'],'DISAGREEMENT');self.assertEqual(result['cases'],[])

    def test_duplicate_or_missing_signed_labels_still_reject(self):
        annotation=parse(self.annotations[0]);annotation['labels'].pop()
        self.annotations=(canonical(annotation),self.annotations[1]);self.envelopes=(self.envelope(0),self.envelopes[1])
        with self.assertRaises(BenchmarkError):self.reconcile()

    def test_annotation_cannot_claim_a_different_reviewer_or_manifest(self):
        for changes in ({'reviewer_id':'outsider'},{'manifest_sha256':'0'*64}):
            original=self.annotations
            self.annotations=(canonical({**parse(original[0]),**changes}),original[1])
            envelope=self.envelope(0)
            with self.assertRaises(BenchmarkError):verify_annotation(self.annotations[0],envelope,grant=self.grants[0],now_ms=3000)
            self.annotations=original

    def test_exported_signature_schema_matches_runtime(self):
        self.assertEqual(parse(Path('docs/contracts/curation-signature-v1.json').read_bytes()),ENVELOPE)
