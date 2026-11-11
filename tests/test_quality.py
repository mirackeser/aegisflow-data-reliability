# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
import unittest
from aegisflow_dr.benchmark.core import BenchmarkError,LABELS,canonical
from aegisflow_dr.benchmark.quality import QualityPolicy,freeze_protocol,evaluate_quality


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.cases=[{'case_id':str(i),'family':'family-'+str(i%3),'label':LABELS[i%3]} for i in range(1200)]
        self.outputs=[{'case_id':x['case_id'],'prediction':x['label'],'unsupported_claim':False} for x in self.cases]
        self.model='a'*64
        self.flags=dict(independent_labels=True,sealed=True,leakage_checked=True,independent_claim_review=True)

    def protocol(self,policy=QualityPolicy(),**changes):
        return freeze_protocol(canonical(self.cases),model_revision_sha256=self.model,
            families=('family-0','family-1','family-2'),policy=policy,**{**self.flags,**changes})

    def evaluate(self,**flags):
        return evaluate_quality(self.protocol(**flags),canonical(self.cases),canonical(self.outputs),model_revision_sha256=self.model)

    def test_perfect_frozen_counts_pass_repeatably(self):
        value=self.evaluate()
        self.assertEqual(value['decision'],'PASS')
        self.assertEqual(value['correct'],1200)
        self.assertEqual(value,self.evaluate())

    def test_exact_threshold_and_abstention_denominator(self):
        for i in range(60):self.outputs[i]['prediction']='ABSTAIN'
        self.assertEqual(self.evaluate()['decision'],'PASS')
        self.outputs[60]['prediction']='ABSTAIN'
        self.assertEqual(self.evaluate()['decision'],'BLOCK')
        for item in self.outputs:item['prediction']='ABSTAIN'
        value=self.evaluate()
        self.assertEqual(value['correct'],0)
        self.assertEqual(value['abstentions'],1200)
        self.assertEqual(value['decision'],'BLOCK')

    def test_high_average_cannot_hide_rare_family_failure(self):
        self.cases[0]['family']='rare'
        protocol=freeze_protocol(canonical(self.cases),model_revision_sha256=self.model,
            families=('family-0','family-1','family-2','rare'),**self.flags)
        self.outputs[0]['prediction']=LABELS[1]
        value=evaluate_quality(protocol,canonical(self.cases),canonical(self.outputs),model_revision_sha256=self.model)
        self.assertIn('FAMILY_ACCURACY:rare',value['reasons'])
        self.assertIn('FAMILY_SUPPORT:rare',value['reasons'])

    def test_errors_and_unsupported_claims_block(self):
        self.outputs[0]['unsupported_claim']=True
        self.assertIn('UNSUPPORTED_CLAIMS',self.evaluate()['reasons'])
        self.outputs[0]['unsupported_claim']=False
        self.outputs[0]['prediction']='ERROR'
        self.assertIn('EXECUTION_ERRORS',self.evaluate()['reasons'])

    def test_public_unsealed_or_unreviewed_provenance_blocks(self):
        for field in self.flags:
            self.assertIn('PROVENANCE_NOT_APPROVED',self.evaluate(**{field:False})['reasons'])

    def test_insufficient_samples_missing_class_and_family_block(self):
        self.cases=self.cases[:2];self.outputs=self.outputs[:2]
        reasons=self.evaluate()['reasons']
        self.assertIn('INSUFFICIENT_CASES',reasons)
        self.assertIn('CLASS_SUPPORT:'+LABELS[2],reasons)
        self.assertIn('FAMILY_COVERAGE_MISMATCH',reasons)

    def test_class_precision_and_recall_enforced(self):
        for i in range(0,120,3):self.outputs[i]['prediction']=LABELS[1]
        reasons=self.evaluate()['reasons']
        self.assertIn('CLASS_RECALL:'+LABELS[0],reasons)
        self.assertIn('CLASS_PRECISION:'+LABELS[1],reasons)

    def test_wrong_model_or_changed_dataset_rejected(self):
        protocol=self.protocol()
        for cases,model in ((canonical(self.cases)+b' ','a'*64),(canonical(self.cases),'b'*64)):
            with self.assertRaises(BenchmarkError):evaluate_quality(protocol,cases,canonical(self.outputs),model_revision_sha256=model)

    def test_duplicate_missing_extra_predictions_or_cases_rejected(self):
        protocol=self.protocol()
        for outputs in (self.outputs[:-1],self.outputs+[self.outputs[0]],self.outputs[:-1]+[{**self.outputs[-1],'case_id':'extra'}]):
            with self.assertRaises(BenchmarkError):evaluate_quality(protocol,canonical(self.cases),canonical(outputs),model_revision_sha256=self.model)
        self.cases.append(self.cases[0])
        with self.assertRaises(BenchmarkError):self.protocol()
        # A forged protocol cannot hide duplicate ground-truth IDs either.
        import json,hashlib
        value=json.loads(protocol);value['dataset_sha256']=hashlib.sha256(canonical(self.cases)).hexdigest()
        with self.assertRaises(BenchmarkError):evaluate_quality(canonical(value),canonical(self.cases),canonical(self.outputs),model_revision_sha256=self.model)

    def test_invalid_policy_and_contracts_reject(self):
        for field in QualityPolicy.__dataclass_fields__:
            for value in (True,0,'9500',float('nan'),9500.0):
                with self.assertRaises(BenchmarkError):replace(QualityPolicy(),**{field:value})
        for policy,families in (({},('family-0',)),(QualityPolicy(),['family-0'])):
            with self.assertRaises(BenchmarkError):freeze_protocol(canonical(self.cases),model_revision_sha256=self.model,families=families,policy=policy)
        for raw in (b'{}',b'NaN',b'[{"case_id":"a","case_id":"b"}]'):
            with self.assertRaises(BenchmarkError):freeze_protocol(raw,model_revision_sha256=self.model,families=('family-0',))

    def test_provenance_defaults_to_block(self):
        protocol=freeze_protocol(canonical(self.cases),model_revision_sha256=self.model,families=('family-0','family-1','family-2'))
        self.assertEqual(evaluate_quality(protocol,canonical(self.cases),canonical(self.outputs),model_revision_sha256=self.model)['decision'],'BLOCK')

    def test_exported_contracts_equal_runtime(self):
        import json
        from pathlib import Path
        from aegisflow_dr.benchmark.quality import CASES,OUTPUTS,PROTOCOL
        for name,schema in [('cases',CASES),('outputs',OUTPUTS),('protocol',PROTOCOL)]:
            self.assertEqual(json.loads(Path('docs/contracts/quality-'+name+'-v1.json').read_text()),schema)
