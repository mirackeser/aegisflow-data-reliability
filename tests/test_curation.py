# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from aegisflow_dr.benchmark.core import BenchmarkError, LABELS, canonical, parse
from aegisflow_dr.benchmark.curation import (
    ANNOTATION, CORPUS, MANIFEST, prepare_manifest, reconcile_annotations,
)
from aegisflow_dr.benchmark.protocol_store import EvaluationRegistry, register_protocol
from aegisflow_dr.benchmark.quality import freeze_protocol


class CurationTests(unittest.TestCase):
    def setUp(self):
        self.development = [{'case_id': 'dev', 'family': 'dev-family', 'group_id': 'dev-group',
                             'csv_text': 'id,value\n1,100\n', 'transform': 'clean'}]
        self.candidates = [
            {'case_id': str(i), 'family': 'heldout-family', 'group_id': 'heldout-'+str(i),
             'csv_text': 'id,value\n'+str(i+2)+',200\n', 'transform': 'clean'}
            for i in range(3)]
        self.manifest = prepare_manifest(canonical(self.development), canonical(self.candidates))
        self.digest = sha256(self.manifest).hexdigest()
        self.reviewers = ('reviewer-a', 'reviewer-b')
        self.annotations = [{'version': '1', 'reviewer_id': reviewer, 'manifest_sha256': self.digest,
                             'labels': [{'case_id': str(i), 'label': label}
                                        for i, label in enumerate(LABELS)]}
                            for reviewer in self.reviewers]

    def reconcile(self, **changes):
        values = dict(expected_manifest_sha256=self.digest, reviewer_ids=self.reviewers)
        return reconcile_annotations(self.manifest, tuple(canonical(x) for x in self.annotations),
                                     **{**values, **changes})

    def test_manifest_binds_exact_source_bytes_and_omits_source_and_labels(self):
        manifest = parse(self.manifest)
        self.assertEqual(manifest['candidate_sha256'], sha256(canonical(self.candidates)).hexdigest())
        self.assertEqual(manifest['development_sha256'], sha256(canonical(self.development)).hexdigest())
        self.assertEqual(set(manifest['cases'][0]), {'case_id', 'family', 'group_id', 'content_signature_sha256'})
        changed = prepare_manifest(canonical(self.development), canonical(self.candidates)+b' ')
        self.assertNotEqual(self.manifest, changed)

    def test_exact_agreement_produces_reproducible_bound_labels_without_mutation(self):
        before = deepcopy(self.annotations)
        result = self.reconcile()
        self.assertEqual(result['status'], 'AGREED')
        self.assertEqual(result['disagreements'], [])
        self.assertEqual(result['quality_cases_sha256'], sha256(canonical(result['cases'])).hexdigest())
        self.assertEqual(result['annotations'], {x['reviewer_id']: sha256(canonical(x)).hexdigest() for x in before})
        self.assertEqual(before, self.annotations)
        self.annotations.reverse()
        for annotation in self.annotations:
            annotation['labels'].reverse()
        reordered = self.reconcile()
        self.assertEqual(result['cases'], reordered['cases'])

    def test_single_disagreement_blocks_entire_label_export(self):
        self.annotations[1]['labels'][1]['label'] = LABELS[0]
        result = self.reconcile()
        self.assertEqual(result['status'], 'DISAGREEMENT')
        self.assertEqual(result['disagreements'], ['1'])
        self.assertEqual(result['cases'], [])
        self.assertIsNone(result['quality_cases_sha256'])

    def test_known_cross_split_identity_family_group_and_content_rejected(self):
        for key in ('case_id', 'family', 'group_id', 'csv_text'):
            cases = deepcopy(self.candidates)
            cases[0][key] = self.development[0][key]
            with self.subTest(key=key), self.assertRaises(BenchmarkError):
                prepare_manifest(canonical(self.development), canonical(cases))

    def test_row_column_whitespace_bom_and_transform_variants_still_detect_copy(self):
        development = deepcopy(self.development)
        development[0]['csv_text'] = 'id,value\n1,100\n9,300\n'
        candidates = deepcopy(self.candidates)
        candidates[0]['csv_text'] = '\ufeff value , id\n 300 , 9 \n100,1\n'
        candidates[0]['transform'] = 'exclude_first'
        with self.assertRaises(BenchmarkError):
            prepare_manifest(canonical(development), canonical(candidates))

    def test_repeated_holdout_identity_group_or_content_cannot_inflate_support(self):
        for key in ('case_id', 'group_id', 'csv_text'):
            cases = deepcopy(self.candidates)
            cases[1][key] = cases[0][key]
            with self.subTest(key=key), self.assertRaises(BenchmarkError):
                prepare_manifest(canonical(self.development), canonical(cases))
        development = self.development * 2
        with self.assertRaises(BenchmarkError):
            prepare_manifest(canonical(development), canonical(self.candidates))

    def test_missing_extra_duplicate_annotations_and_unknown_labels_rejected(self):
        for mode in ('missing', 'extra', 'duplicate', 'label'):
            with self.subTest(mode=mode):
                annotations = deepcopy(self.annotations)
                if mode == 'missing': annotations[0]['labels'].pop()
                if mode == 'extra': annotations[0]['labels'].append({'case_id': 'extra', 'label': LABELS[0]})
                if mode == 'duplicate': annotations[0]['labels'][1] = annotations[0]['labels'][0]
                if mode == 'label': annotations[0]['labels'][0]['label'] = 'ABSTAIN'
                with self.assertRaises(BenchmarkError):
                    reconcile_annotations(self.manifest, tuple(canonical(x) for x in annotations),
                                          expected_manifest_sha256=self.digest, reviewer_ids=self.reviewers)

    def test_wrong_manifest_unknown_reviewer_and_same_reviewer_twice_rejected(self):
        for key, value in (('manifest_sha256', 'a'*64), ('reviewer_id', 'outsider'),
                           ('reviewer_id', self.reviewers[1])):
            annotations = deepcopy(self.annotations)
            annotations[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(BenchmarkError):
                reconcile_annotations(self.manifest, tuple(canonical(x) for x in annotations),
                                      expected_manifest_sha256=self.digest, reviewer_ids=self.reviewers)
        with self.assertRaises(BenchmarkError): self.reconcile(expected_manifest_sha256='0'*64)

    def test_two_distinct_host_approved_reviewers_and_two_artifacts_required(self):
        for reviewers in (None, (), self.reviewers[:1], list(self.reviewers), ('same', 'same'), (1, 'name')):
            with self.subTest(reviewers=reviewers), self.assertRaises(BenchmarkError):
                self.reconcile(reviewer_ids=reviewers)
        for artifacts in (None, (), (canonical(self.annotations[0]),), list(map(canonical, self.annotations))):
            with self.assertRaises(BenchmarkError):
                reconcile_annotations(self.manifest, artifacts, expected_manifest_sha256=self.digest,
                                      reviewer_ids=self.reviewers)

    def test_closed_contracts_reject_embedded_labels_predictions_and_private_fields(self):
        for key in ('label', 'prediction', 'api_key'):
            candidates = deepcopy(self.candidates)
            candidates[0][key] = 'untrusted'
            with self.subTest(key=key), self.assertRaises(BenchmarkError):
                prepare_manifest(canonical(self.development), canonical(candidates))
        self.annotations[0]['prompt'] = 'untrusted'
        with self.assertRaises(BenchmarkError): self.reconcile()

    def test_corrupt_oversized_empty_duplicate_key_and_csv_inputs_rejected(self):
        for raw in (b'[]', b'{}', b'\xff', b'['*1_000_001, b'[{"case_id":"a","case_id":"b"}]'):
            with self.assertRaises(BenchmarkError): prepare_manifest(raw, canonical(self.candidates))
            with self.assertRaises(BenchmarkError): prepare_manifest(canonical(self.development), raw)
        candidates = deepcopy(self.candidates)
        candidates[0]['csv_text'] = '"unclosed'
        with self.assertRaises(BenchmarkError):
            prepare_manifest(canonical(self.development), canonical(candidates))

    def test_manifest_substitution_and_duplicate_manifest_entries_rejected(self):
        self.manifest += b' '
        with self.assertRaises(BenchmarkError): self.reconcile()
        manifest = parse(self.manifest)
        manifest['cases'][1] = manifest['cases'][0]
        self.manifest = canonical(manifest)
        self.digest = sha256(self.manifest).hexdigest()
        with self.assertRaises(BenchmarkError): self.reconcile()

    def test_consensus_alone_cannot_approve_quality_or_model_activation(self):
        result = self.reconcile()
        cases = canonical(result['cases'])
        outputs = canonical([{'case_id': x['case_id'], 'prediction': x['label'], 'unsupported_claim': False}
                             for x in result['cases']])
        model = 'a'*64
        protocol = freeze_protocol(cases, model_revision_sha256=model, families=('heldout-family',))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'evaluation.db'
            digest = register_protocol(path, protocol)
            registry = EvaluationRegistry(path, expected_protocol_sha256=digest)
            decision = registry.evaluate(cases, outputs, run_id=str(uuid4()), model_revision_sha256=model)
            self.assertEqual(decision['decision'], 'BLOCK')
            self.assertIn('PROVENANCE_NOT_APPROVED', decision['reasons'])
            self.assertEqual(registry.history()[0]['result'], decision)

    def test_published_schemas_match_runtime_contracts(self):
        root = Path(__file__).resolve().parents[1]/'docs/contracts'
        for name, schema in (('curation-corpus-v1', CORPUS), ('curation-manifest-v1', MANIFEST),
                             ('curation-annotation-v1', ANNOTATION)):
            self.assertEqual(json.loads((root/(name+'.json')).read_bytes()), schema)
