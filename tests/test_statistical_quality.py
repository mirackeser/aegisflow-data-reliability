# SPDX-License-Identifier: Apache-2.0
from fractions import Fraction
from hashlib import sha256
from math import comb
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from aegisflow_dr.benchmark.core import BenchmarkError, LABELS, canonical, parse
from aegisflow_dr.benchmark.quality import (
    PROTOCOL_V2, evaluate_quality, freeze_protocol, freeze_statistical_protocol,
)
from aegisflow_dr.benchmark.protocol_store import EvaluationRegistry, register_protocol
from aegisflow_dr.benchmark.statistics import supports_target


class BinomialSupportTests(unittest.TestCase):
    def test_exact_decisions_match_independent_fraction_sum(self):
        for trials in range(1, 13):
            for successes in range(trials+1):
                for target in (1, 1000, 5000, 9500, 9999):
                    probability = Fraction(target, 10_000)
                    tail = sum(Fraction(comb(trials, k)) * probability**k * (1-probability)**(trials-k)
                               for k in range(successes, trials+1))
                    for comparisons in (1, 10, 71):
                        with self.subTest(n=trials, k=successes, target=target, m=comparisons):
                            self.assertEqual(supports_target(successes, trials, target, comparisons=comparisons),
                                             tail <= Fraction(500, 10_000*comparisons))

    def test_nist_exact_lower_limit_example(self):
        # NIST: 4/20 successes, 90% two-sided lower limit 0.071354 (5% lower tail).
        self.assertTrue(supports_target(4, 20, 713))
        self.assertFalse(supports_target(4, 20, 714))

    def test_perfect_sample_boundaries_and_multiplicity(self):
        self.assertFalse(supports_target(58, 58, 9500))
        self.assertTrue(supports_target(59, 59, 9500))
        self.assertFalse(supports_target(103, 103, 9500, comparisons=10))
        self.assertTrue(supports_target(104, 104, 9500, comparisons=10))

    def test_exact_alpha_equality_is_not_rounded(self):
        self.assertTrue(supports_target(1, 1, 500))
        self.assertFalse(supports_target(1, 1, 501))

    def test_zero_trials_no_success_and_perfection_target_block(self):
        for values in ((0, 0, 9500), (0, 100, 9500), (100, 100, 10_000)):
            self.assertFalse(supports_target(*values))

    def test_invalid_counts_types_and_unbounded_work_reject(self):
        for values in ((True, 10, 9500), (1.0, 10, 9500), (-1, 10, 9500), (11, 10, 9500),
                       (1, 10_001, 9500), (1, 10, 0), (1, 10, 10_001)):
            with self.assertRaises(BenchmarkError): supports_target(*values)
        for key, values in (('alpha_bps', (True, 500.0, 0, 501)), ('comparisons', (0, 72, 1.0))):
            for value in values:
                with self.assertRaises(BenchmarkError): supports_target(9, 10, 9500, **{key:value})

    def test_maximum_dataset_and_tighter_policy(self):
        self.assertTrue(supports_target(10_000, 10_000, 9500, comparisons=71))
        self.assertFalse(supports_target(9500, 10_000, 9500, comparisons=71))
        self.assertTrue(supports_target(59, 59, 9500))
        self.assertFalse(supports_target(59, 59, 9500, alpha_bps=100))


class StatisticalQualityTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{'case_id':str(i), 'family':'family-'+str(i%3), 'label':LABELS[i%3]} for i in range(1200)]
        self.outputs = [{'case_id':x['case_id'], 'prediction':x['label'], 'unsupported_claim':False} for x in self.cases]
        self.options = dict(model_revision_sha256='a'*64, families=('family-0','family-1','family-2'),
                            independent_labels=True, sealed=True, leakage_checked=True, independent_claim_review=True)

    def protocol(self, **changes):
        return freeze_statistical_protocol(canonical(self.cases),
                                           **{'sampling_assumptions_approved':True, **self.options, **changes})

    def test_sampling_assumptions_default_to_block_even_with_perfect_counts(self):
        protocol=freeze_statistical_protocol(canonical(self.cases),**self.options)
        result=self.evaluate(protocol)
        self.assertEqual(result['decision'],'BLOCK')
        self.assertIn('STATISTICAL_ASSUMPTIONS_NOT_APPROVED',result['reasons'])

    def evaluate(self, protocol=None):
        return evaluate_quality(self.protocol() if protocol is None else protocol, canonical(self.cases),
                                canonical(self.outputs), model_revision_sha256=self.options['model_revision_sha256'])

    def test_well_supported_perfect_fixture_passes_all_predeclared_comparisons(self):
        result = self.evaluate()
        self.assertEqual(result['version'], '2')
        self.assertEqual(result['decision'], 'PASS')
        self.assertEqual(result['statistics']['comparisons'], 10)
        self.assertEqual(len(result['statistics']['metrics']), 10)
        self.assertTrue(all(x['supported'] for x in result['statistics']['metrics'].values()))

    def test_observed_95_percent_blocks_v2_and_preserves_frozen_v1(self):
        for item in self.outputs[:60]: item['prediction'] = 'ABSTAIN'
        legacy = self.evaluate(freeze_protocol(canonical(self.cases), **self.options))
        self.assertEqual(legacy['decision'], 'PASS')
        self.assertNotIn('statistics', legacy)
        result = self.evaluate()
        self.assertEqual(result['correct'], 1140)
        self.assertEqual(result['abstentions'], 60)
        self.assertEqual(result['decision'], 'BLOCK')
        self.assertIn('STATISTICAL_SUPPORT:ACCURACY', result['reasons'])
        for label in LABELS:
            self.assertIn('STATISTICAL_SUPPORT:CLASS_RECALL:'+label, result['reasons'])

    def test_perfect_small_family_still_requires_statistical_support(self):
        for case in self.cases[:30]: case['family'] = 'rare'
        protocol = self.protocol(families=(*self.options['families'], 'rare'))
        result = self.evaluate(protocol)
        self.assertNotIn('FAMILY_SUPPORT:rare', result['reasons'])
        self.assertIn('STATISTICAL_SUPPORT:FAMILY_ACCURACY:rare', result['reasons'])
        self.assertEqual(result['statistics']['comparisons'], 11)

    def test_zero_predictions_errors_claims_and_provenance_remain_blocked(self):
        for item in self.outputs: item['prediction'] = 'ABSTAIN'
        result = self.evaluate()
        for label in LABELS:
            metric = result['statistics']['metrics']['CLASS_PRECISION:'+label]
            self.assertEqual(metric['trials'], 0)
            self.assertFalse(metric['supported'])
        self.outputs[0].update(prediction='ERROR', unsupported_claim=True)
        reasons = self.evaluate(self.protocol(sealed=False))['reasons']
        for reason in ('EXECUTION_ERRORS','UNSUPPORTED_CLAIMS','PROVENANCE_NOT_APPROVED'):
            self.assertIn(reason, reasons)

    def test_policy_is_registered_and_blocked_results_survive_replay(self):
        protocol = self.protocol()
        for item in self.outputs[:60]: item['prediction'] = 'ABSTAIN'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'quality.db'
            digest = register_protocol(path, protocol)
            registry = EvaluationRegistry(path, expected_protocol_sha256=digest)
            run = str(uuid4())
            arguments = dict(run_id=run, model_revision_sha256='a'*64)
            result = registry.evaluate(canonical(self.cases), canonical(self.outputs), **arguments)
            self.assertEqual(result['decision'], 'BLOCK')
            self.assertEqual(result['protocol_sha256'], digest)
            self.assertEqual(registry.evaluate(canonical(self.cases), canonical(self.outputs), **arguments), result)
            self.assertEqual(registry.history()[0]['result'], result)
            changed = sha256(self.protocol(familywise_alpha_bps=100)).hexdigest()
            with self.assertRaises(BenchmarkError): EvaluationRegistry(path, expected_protocol_sha256=changed)

    def test_unknown_method_version_missing_statistics_or_invalid_budget_reject(self):
        for alpha in (True, 0, 501, 500.0, '500'):
            with self.assertRaises(BenchmarkError): self.protocol(familywise_alpha_bps=alpha)
        for mutation in ('method', 'version', 'missing', 'extra'):
            protocol = parse(self.protocol())
            if mutation == 'method': protocol['statistics']['method'] = 'unreviewed'
            if mutation == 'version': protocol['version'] = '3'
            if mutation == 'missing': del protocol['statistics']
            if mutation == 'extra': protocol['statistics']['confidence'] = 1
            raw = canonical(protocol)
            with self.assertRaises(BenchmarkError): self.evaluate(raw)
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary)/'bad.db'
                with self.assertRaises(BenchmarkError): register_protocol(path, raw)
                self.assertFalse(path.exists())

    def test_v2_preserves_exact_model_and_dataset_binding(self):
        protocol = self.protocol()
        with self.assertRaises(BenchmarkError):
            evaluate_quality(protocol, canonical(self.cases)+b' ', canonical(self.outputs), model_revision_sha256='a'*64)
        with self.assertRaises(BenchmarkError):
            evaluate_quality(protocol, canonical(self.cases), canonical(self.outputs), model_revision_sha256='b'*64)

    def test_exported_v2_contract_matches_runtime(self):
        self.assertEqual(parse(Path('docs/contracts/quality-protocol-v2.json').read_bytes()), PROTOCOL_V2)
