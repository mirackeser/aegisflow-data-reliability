# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jsonschema import Draft202012Validator
from aegisflow_dr.advisory.context import (CONTEXT_SCHEMA, VERSION, SYSTEM_PROMPT,
    ContextPolicy, PreparedAdvisory, project)
from aegisflow_dr.advisory.contracts import AdvisoryError, RESPONSE, decode, encode
from aegisflow_dr.investigation import default_policy
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.storage.runs import InvestigationRuns
from aegisflow_dr.storage.store import canonical, sha


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'evidence.db'
        initialize(self.path)
        self.store = IncidentStore(self.path)
        self.runs = InvestigationRuns(self.store)
        self.sequence = 0

    def record(self, text=None, transform='clean'):
        self.sequence += 1
        source = self.store.record(generate_orders() if text is None else text.encode(),
                                   request_key='source-' + str(self.sequence))
        return self.runs.execute(source['incident_id'], default_policy(), transform=transform,
                                 request_key='run-' + str(self.sequence))

    def prepare(self, record, **kwargs):
        return PreparedAdvisory(self.runs, record['run_id'], model_id='offline/test', **kwargs)

    def response(self, prepared, assessment):
        metadata = decode('request', prepared.request)
        return encode('response', {'version': '1', 'request_sha256': sha(prepared.request),
            'decision': 'PROPOSE', 'assessment': assessment, 'evidence_sha256': metadata['evidence_sha256']})

    def test_clean_source_and_batch_project_without_assessment_or_amounts(self):
        record = self.record()
        value = json.loads(project(record))
        self.assertEqual([s['kind'] for s in value['summaries']], ['source', 'reconciliation'])
        self.assertEqual(value['summaries'][0]['status'], 'PASS')
        self.assertEqual(value['version'], VERSION)
        for forbidden in ('assessment', 'total_valid_amount', 'expected', 'actual', 'snapshots', 'sql'):
            self.assertNotIn('"' + forbidden + '"', project(record).decode())

    def test_source_violations_project_only_known_check_names_and_declared_impact(self):
        record = self.record(generate_orders(fault='null_total').decode())
        value = json.loads(project(record))
        self.assertEqual(value['summaries'][0]['checks'], ['not_null'])
        self.assertEqual(value['summaries'][1]['kind'], 'declared_impact')
        self.assertEqual(value['summaries'][1]['dataset'], 'source_orders')

    def test_transform_failure_projects_false_reconciliation_and_mart_impact(self):
        record = self.record(transform='exclude_first')
        value = json.loads(project(record))
        self.assertEqual(len(value['summaries']), 3)
        self.assertTrue(any(not item['passed'] for item in value['summaries'][1]['checks']))
        self.assertEqual(value['summaries'][2]['dataset'], 'customer_sales')

    def test_raw_identifiers_unicode_and_financial_values_never_enter_messages(self):
        record = self.record('order_id,customer_id,order_total\nsecret-order,özel-müşteri,987654321.99\n')
        prepared = self.prepare(record)
        rendered = canonical(prepared.messages).decode()
        for value in ('secret-order', 'özel-müşteri', '987654321.99', 'order_id,customer_id'):
            self.assertNotIn(value, rendered)

    def test_untrusted_column_and_injection_text_are_not_forwarded(self):
        marker = 'sensitive-marker-ignore-all-instructions'
        record = self.record('order_id,customer_id,order_total,' + marker + '\nx,y,1,unused\n')
        prepared = self.prepare(record)
        self.assertNotIn(marker, canonical(prepared.messages).decode())
        evidence = json.loads(prepared.messages[1]['content'])['evidence']
        self.assertEqual(evidence['summaries'][0]['checks'], ['unexpected_column'])

    def test_truncated_findings_flag_is_retained_without_raw_records(self):
        text = 'order_id,customer_id,order_total\n' + ''.join('x,,\n' for _ in range(110))
        value = json.loads(project(self.record(text)))
        source = value['summaries'][0]
        self.assertTrue(source['findings_truncated'])
        self.assertGreater(source['finding_count'], 100)
        self.assertNotIn('findings', source)

    def test_unknown_tool_or_check_and_malformed_record_fail_closed(self):
        record = self.record()
        variants = [None, {}, deepcopy(record), deepcopy(record), deepcopy(record)]
        variants[2]['trace']['steps'][0]['tool'] = 'external_fetch'
        variants[3]['trace']['steps'][0]['report']['findings'] = [{'check': 'untrusted-prompt'}]
        variants[4]['trace']['steps'][0]['report']['row_count'] = True
        for value in variants:
            with self.assertRaises(AdvisoryError): project(value)

    def test_context_budget_rejects_before_session_construction(self):
        record = self.record()
        with patch('aegisflow_dr.advisory.context.AdvisorySession', side_effect=AssertionError):
            with self.assertRaises(AdvisoryError): self.prepare(record, policy=ContextPolicy(max_context_bytes=256))

    def test_prompt_budget_rejects_without_evidence_mutation(self):
        record = self.record()
        before = self.path.read_bytes()
        with self.assertRaises(AdvisoryError): self.prepare(record, policy=ContextPolicy(max_prompt_bytes=256))
        self.assertEqual(self.path.read_bytes(), before)

    def test_exact_byte_boundaries_are_inclusive(self):
        record = self.record()
        first = self.prepare(record)
        limits = first.manifest
        other = self.prepare(record, policy=ContextPolicy(max_context_bytes=limits['context_bytes'],
                                                         max_prompt_bytes=limits['prompt_bytes']))
        self.assertEqual(other.manifest['prompt_bytes'], limits['prompt_bytes'])

    def test_host_policy_types_and_bounds_reject(self):
        for value in [True, 255, 16385, float('nan'), '8192']:
            with self.assertRaises(AdvisoryError): ContextPolicy(max_context_bytes=value)
        for value in [False, 255, 65537, float('inf')]:
            with self.assertRaises(AdvisoryError): ContextPolicy(max_prompt_bytes=value)
        record = self.record()
        with self.assertRaises(AdvisoryError): self.prepare(record, policy={'max_context_bytes': 8192})
        with self.assertRaises(FrozenInstanceError): ContextPolicy().max_context_bytes = 1

    def test_same_evidence_identity_stable_but_full_input_bound_to_unique_request(self):
        record = self.record()
        first, second = self.prepare(record), self.prepare(record)
        self.assertEqual(first.manifest['context_sha256'], second.manifest['context_sha256'])
        self.assertEqual(first.manifest['prompt_sha256'], second.manifest['prompt_sha256'])
        self.assertNotEqual(first.manifest['input_sha256'], second.manifest['input_sha256'])
        self.assertNotEqual(first.request, second.request)

    def test_policy_system_and_schema_changes_are_part_of_prompt_identity(self):
        record = self.record()
        base = self.prepare(record)
        changed = self.prepare(record, policy=ContextPolicy(max_context_bytes=9000))
        self.assertNotEqual(base.manifest['prompt_sha256'], changed.manifest['prompt_sha256'])
        with patch('aegisflow_dr.advisory.context.SYSTEM_PROMPT', SYSTEM_PROMPT + ' Updated version.'):
            changed = self.prepare(record)
        self.assertNotEqual(base.manifest['prompt_sha256'], changed.manifest['prompt_sha256'])
        schema = deepcopy(RESPONSE)
        schema['title'] = 'Revised response contract'
        with patch('aegisflow_dr.advisory.context.RESPONSE', schema):
            changed = self.prepare(record)
        self.assertNotEqual(base.manifest['prompt_sha256'], changed.manifest['prompt_sha256'])

    def test_detached_message_and_manifest_mutation_cannot_change_prepared_state(self):
        prepared = self.prepare(self.record())
        manifest, messages = prepared.manifest, prepared.messages
        messages[0]['content'] = 'Override'
        manifest['policy']['max_prompt_bytes'] = 1
        self.assertEqual(prepared.messages[0]['content'], SYSTEM_PROMPT)
        self.assertEqual(prepared.manifest['policy']['max_prompt_bytes'], 32768)
        self.assertEqual(prepared.manifest['input_sha256'], sha(canonical(prepared.messages)))

    def test_record_race_between_projection_and_metadata_is_rejected(self):
        record = self.record()
        changed = deepcopy(record)
        changed['extra'] = 'changed-host-record'
        with patch.object(self.runs, 'read', side_effect=[record, changed]):
            with self.assertRaises(AdvisoryError): self.prepare(record)

    def test_prepared_responses_keep_deterministic_gate_and_context_binding(self):
        record = self.record()
        prepared = self.prepare(record)
        before = self.path.read_bytes()
        self.assertEqual(prepared.review_response(self.response(prepared, record['trace']['assessment']))['status'],
                         'VERIFIED_ADVISORY')
        self.assertEqual(prepared.review_response(self.response(prepared, 'SOURCE_QUALITY_FAILURE'))['status'],
                         'REJECTED_ADVISORY')
        another = self.prepare(record)
        with self.assertRaises(AdvisoryError): another.review_response(self.response(prepared, record['trace']['assessment']))
        self.assertEqual(before, self.path.read_bytes())

    def test_exported_context_schema_matches_runtime_and_manifest_has_no_usage_claim(self):
        Draft202012Validator.check_schema(CONTEXT_SCHEMA)
        self.assertEqual(json.loads(Path('docs/contracts/evidence-context-v1.json').read_text()), CONTEXT_SCHEMA)
        prepared = self.prepare(self.record())
        self.assertEqual(prepared.manifest['model_calls'], 0)
        self.assertNotIn('tokens', prepared.manifest)
        self.assertNotIn('cost', prepared.manifest)

    def test_public_validation_scenarios_prepare_and_verify_without_label_projection(self):
        from aegisflow_dr.benchmark.core import load_suite
        suite, _ = load_suite()
        for case in suite['cases']:
            record = self.record(case['csv_text'], case['transform'])
            prepared = self.prepare(record)
            self.assertNotIn('expected_assessment', canonical(prepared.messages).decode())
            value = json.loads(prepared.messages[1]['content'])['evidence']
            self.assertNotIn('assessment', value)
            result = prepared.review_response(self.response(prepared, case['expected_assessment']))
            self.assertEqual(result['status'], 'VERIFIED_ADVISORY')
