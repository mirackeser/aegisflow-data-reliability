# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jsonschema import Draft202012Validator
from aegisflow_dr.advisory.contracts import AdvisoryError, MAX_BYTES, SCHEMAS, decode, encode
from aegisflow_dr.advisory.session import AdvisorySession
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, StoreError, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import sha


class AdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'evidence.db'
        initialize(self.db)
        store = IncidentStore(self.db)
        source = store.record(generate_orders(), request_key='source')
        self.runs = InvestigationRuns(store)
        self.record = self.runs.execute(source['incident_id'], default_policy(), request_key='run')
        self.session = AdvisorySession(self.runs, self.record['run_id'],
                                       model_id='offline/demo-v1', prompt_sha256='a' * 64)

    def response(self, **changes):
        request = decode('request', self.session.request)
        return {'version': '1', 'request_sha256': sha(self.session.request), 'decision': 'PROPOSE',
                'assessment': self.record['trace']['assessment'],
                'evidence_sha256': request['evidence_sha256'], **changes}

    def test_matching_advice_is_verified_read_only_without_model_execution(self):
        before = self.db.read_bytes()
        result = self.session.review_response(encode('response', self.response()))
        self.assertEqual(result['status'], 'VERIFIED_ADVISORY')
        self.assertEqual(result['verdict']['decision'], 'ACCEPT')
        self.assertEqual(result['mode'], 'advisory-only')
        self.assertEqual(self.db.read_bytes(), before)
        request = decode('request', self.session.request)
        self.assertNotIn('assessment', request)
        self.assertNotIn('csv_text', request)

    def test_contradictory_assessment_never_overrides_deterministic_judge(self):
        value = self.response(assessment='SOURCE_QUALITY_FAILURE')
        result = self.session.review_response(encode('response', value))
        self.assertEqual(result['status'], 'REJECTED_ADVISORY')
        self.assertEqual(result['reason'], 'CONTRADICTION')

    def test_missing_fabricated_or_partial_citations_reject(self):
        refs = self.response()['evidence_sha256']
        for citations in [['b' * 64], refs[:1]]:
            result = self.session.review_response(encode('response', self.response(evidence_sha256=citations)))
            self.assertEqual(result['reason'], 'EVIDENCE_MISMATCH')
            self.assertEqual(result['status'], 'REJECTED_ADVISORY')

    def test_model_abstention_is_explicit_and_does_not_read_evidence(self):
        value = self.response(decision='ABSTAIN', assessment=None, evidence_sha256=[])
        with patch.object(self.runs, 'read', side_effect=AssertionError):
            result = self.session.review_response(encode('response', value))
        self.assertEqual(result['reason'], 'MODEL_ABSTAIN')
        self.assertIsNone(result['verdict'])

    def test_cross_request_response_and_new_session_replay_reject(self):
        for digest in ['0' * 64, sha(AdvisorySession(self.runs, self.record['run_id'],
                    model_id='offline/demo-v1', prompt_sha256='a' * 64).request)]:
            with self.assertRaises(AdvisoryError):
                self.session.review_response(encode('response', self.response(request_sha256=digest)))

    def test_unavailable_run_abstains_with_sanitized_reason(self):
        with patch.object(self.runs, 'read', side_effect=StoreError('private-path')):
            result = self.session.review_response(encode('response', self.response()))
        self.assertEqual(result['reason'], 'RUN_UNAVAILABLE')
        self.assertNotIn('private-path', str(result))

    def test_changed_record_abstains_before_judge(self):
        changed = deepcopy(self.record)
        changed['trace']['assessment'] = 'SOURCE_QUALITY_FAILURE'
        with patch.object(self.runs, 'read', return_value=changed), \
             patch('aegisflow_dr.advisory.session.review', side_effect=AssertionError):
            result = self.session.review_response(encode('response', self.response()))
        self.assertEqual(result['reason'], 'RECORD_CHANGED')

    def test_constructor_rejects_unverified_assessment(self):
        with patch('aegisflow_dr.advisory.session.review', return_value={'decision': 'ABSTAIN'}):
            with self.assertRaises(AdvisoryError):
                AdvisorySession(self.runs, self.record['run_id'], model_id='offline/test', prompt_sha256='a' * 64)

    def test_judge_abstention_remains_abstention(self):
        from aegisflow_dr.coordination.judge import abstain
        with patch('aegisflow_dr.advisory.session.review', return_value=abstain(self.record['run_id'])):
            result = self.session.review_response(encode('response', self.response()))
        self.assertEqual(result['status'], 'ABSTAIN')

    def test_request_model_and_prompt_are_host_only_and_strict(self):
        for model, prompt in [('https://untrusted.invalid', 'a' * 64), ('offline\n', 'a' * 64),
                              ('offline', 'not-a-digest'), (True, 'a' * 64)]:
            with self.assertRaises(AdvisoryError):
                AdvisorySession(self.runs, self.record['run_id'], model_id=model, prompt_sha256=prompt)

    def test_response_cannot_supply_policy_tools_confidence_secrets_or_reason_text(self):
        for field in ['policy', 'tool_calls', 'confidence', 'api_key', 'rationale', 'endpoint', 'prompt_sha256']:
            value = self.response(**{field: 'untrusted-value'})
            with self.assertRaises(AdvisoryError) as error:
                self.session.review_response(json.dumps(value).encode())
            self.assertNotIn('untrusted-value', str(error.exception))

    def test_malformed_duplicate_nonfinite_and_oversized_messages_reject(self):
        for value in [None, b'x' * (MAX_BYTES + 1), b'\xff', b'{', b'[]', b'NaN', b'Infinity',
                      b'{"version":"1","version":"1"}', b'[' * 1100]:
            with self.assertRaises(AdvisoryError): decode('response', value)
        for name in [None, 'unknown', []]:
            with self.assertRaises(AdvisoryError): decode(name, b'{}')
        for value in [object(), float('nan'), {'x': '\ud800'}]:
            with self.assertRaises(AdvisoryError): encode('response', value)

    def test_conditional_response_contract_and_reference_uniqueness(self):
        variants = [self.response(decision='ABSTAIN'), self.response(assessment=None),
                    self.response(evidence_sha256=[]), self.response(evidence_sha256=['a' * 64] * 2),
                    self.response(decision='EXECUTE'), self.response(assessment='ROOT_CAUSE_CONFIRMED')]
        for value in variants:
            with self.assertRaises(AdvisoryError): encode('response', value)

    def test_exported_schemas_match_runtime_and_no_dependency_or_prompt_text_is_required(self):
        for name, schema in SCHEMAS.items():
            Draft202012Validator.check_schema(schema)
            self.assertEqual(json.loads(Path('docs/contracts/advisory-' + name + '-v1.json').read_text()), schema)
        self.assertEqual(files('aegisflow_dr.advisory').joinpath('__init__.py').is_file(), True)
