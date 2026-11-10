# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.batch import run_batch
from aegisflow_dr.gateway import ToolGateway, ToolPolicy, ToolResult
from aegisflow_dr.investigation import default_policy, investigate
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.storage import IncidentStore, initialize
from aegisflow_dr.__main__ import main


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'research.db'
        initialize(self.path)
        self.store = IncidentStore(self.path)
        self.record = self.store.record(generate_orders(), request_key='clean')
        self.incident = self.record['incident_id']

    def run_case(self, *, policy=None, **options):
        return investigate(self.store, self.incident, policy or default_policy(), **options)

    def test_clean_path_uses_two_tools_and_does_not_claim_global_health(self):
        result = self.run_case()
        self.assertEqual((result.status, result.assessment), ('COMPLETED', 'NO_FAILURE_OBSERVED'))
        self.assertEqual([s.tool for s in result.steps], ['diagnose_csv', 'run_batch'])
        self.assertEqual(result.calls_used, 2)
        self.assertEqual(len(result.observations), 2)
        self.assertEqual(self.store.read(self.incident), self.record)

    def test_source_failures_skip_batch_and_investigate_declared_impact(self):
        for fault in ['schema_drift', 'null_total', 'duplicate_order']:
            with self.subTest(fault=fault):
                record = self.store.record(generate_orders(fault=fault), request_key=fault)
                result = investigate(self.store, record['incident_id'], default_policy())
                self.assertEqual(result.assessment, 'SOURCE_QUALITY_FAILURE')
                self.assertEqual([s.tool for s in result.steps], ['diagnose_csv', 'query_lineage'])
                self.assertEqual(result.steps[-1].report['potential_downstream'],
                                 ['staging_orders', 'customer_sales', 'sales_dashboard'])

    def test_transformation_regression_uses_three_tools(self):
        result = self.run_case(transform='exclude_first')
        self.assertEqual(result.assessment, 'TRANSFORMATION_RECONCILIATION_FAILURE')
        self.assertEqual(result.calls_used, 3)
        self.assertEqual(result.steps[-1].dataset, 'customer_sales')
        self.assertEqual(result.steps[-1].report['potential_downstream'], ['sales_dashboard'])

    def test_observations_reference_stored_source_and_retained_step_reports(self):
        result = self.run_case(transform='exclude_first')
        report_hashes = {s.report_sha256 for s in result.steps}
        for observation in result.observations:
            self.assertEqual(observation.evidence_sha256[0], self.record['manifest']['source_sha256'])
            self.assertIn(observation.evidence_sha256[1], report_hashes)
        from aegisflow_dr.storage.store import canonical, sha
        for step in result.steps:
            self.assertEqual(step.report_sha256, sha(canonical(step.report)))

    def test_policy_denial_never_infers_a_quality_outcome(self):
        result = self.run_case(policy=ToolPolicy(frozenset()))
        self.assertEqual((result.status, result.reason), ('INCONCLUSIVE', 'DENIED'))
        self.assertIsNone(result.assessment)
        self.assertEqual(result.observations, ())
        self.assertEqual(result.calls_used, 0)

    def test_budget_exhaustion_stops_at_failed_step_without_new_session(self):
        result = self.run_case(policy=replace(default_policy(), max_calls=1))
        self.assertEqual(result.reason, 'BUDGET_EXCEEDED')
        self.assertEqual(result.calls_used, 1)
        self.assertEqual(len(result.steps), 2)
        self.assertEqual(result.observations, ())

    def test_missing_impact_permission_withholds_final_assessment(self):
        grants = default_policy().grants - {('query_lineage', 'customer_sales')}
        result = self.run_case(policy=ToolPolicy(grants), transform='exclude_first')
        self.assertEqual(result.reason, 'DENIED')
        self.assertIsNone(result.assessment)

    def test_byte_limit_remains_enforced_by_gateway(self):
        result = self.run_case(policy=replace(default_policy(), max_input_bytes=1))
        self.assertEqual(result.reason, 'INPUT_REJECTED')
        self.assertEqual(result.calls_used, 0)

    def test_deadline_cannot_be_reset_by_routing(self):
        times = iter([0.0, 2.0])
        result = self.run_case(policy=replace(default_policy(), timeout_seconds=1),
                               clock=lambda: next(times))
        self.assertEqual(result.reason, 'DEADLINE_EXCEEDED')
        self.assertEqual(result.calls_used, 0)

    def test_version_mismatch_rejects_current_tool_execution(self):
        with patch('aegisflow_dr.investigation.engine_fingerprint', return_value='a'*64), \
             patch.object(ToolGateway, 'execute') as tool:
            result = self.run_case()
        self.assertEqual(result.reason, 'VERSION_MISMATCH')
        tool.assert_not_called()

    def test_corrupt_source_is_inconclusive_before_any_tool(self):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            connection.execute('DROP TRIGGER immutable_evidence_update')
        with patch.object(ToolGateway, 'execute') as tool:
            result = self.run_case()
        self.assertEqual(result.reason, 'SOURCE_UNAVAILABLE')
        tool.assert_not_called()

    def test_missing_incident_is_inconclusive(self):
        from uuid import uuid4
        result = investigate(self.store, str(uuid4()), default_policy())
        self.assertEqual(result.reason, 'SOURCE_UNAVAILABLE')
        self.assertEqual(result.calls_used, 0)

    def test_repeated_run_is_identical_and_does_not_reopen_closed_case(self):
        self.store.close(self.incident, expected_revision=2, actor='local')
        first = self.run_case().to_json()
        self.assertEqual(first, self.run_case().to_json())
        self.assertEqual(self.store.read(self.incident)['state'], 'CLOSED')

    def test_utf8_bom_and_multiline_values_preserve_exact_source_binding(self):
        payload = '\ufefforder_id,customer_id,order_total\na,"Müşteri\nBir",1.25\n'.encode()
        record = self.store.record(payload, request_key='bom')
        result = investigate(self.store, record['incident_id'], default_policy())
        self.assertEqual(result.status, 'COMPLETED')
        self.assertEqual(result.source_sha256, record['manifest']['source_sha256'])
        self.assertNotIn('Müşteri', result.to_json())

    def test_bad_source_report_and_transport_never_become_claims(self):
        for response in [ToolResult('OK', {'status': 'PASS'}),
                         ToolResult('OK', None), ToolResult('unknown-sensitive-text', {'secret': 'value'}),
                         {'outcome': 'OK'}]:
            with self.subTest(response=type(response)), patch.object(ToolGateway, 'execute', return_value=response):
                result = self.run_case()
                self.assertEqual(result.reason, 'INVALID_EVIDENCE')
                self.assertEqual(result.observations, ())
                self.assertIsNone(result.steps[-1].report)
                self.assertNotIn('sensitive', result.to_json())

    def test_unexpected_tool_exception_is_sanitized(self):
        with patch.object(ToolGateway, 'execute', side_effect=RuntimeError('private-value')):
            result = self.run_case()
        self.assertEqual(result.reason, 'TOOL_ERROR')
        self.assertNotIn('private-value', result.to_json())

    def test_batch_contract_rejects_forged_hashes_types_and_counts(self):
        original = ToolGateway.execute
        baseline = json.loads(run_batch(generate_orders()).to_json())
        mutations = [
            lambda r: r.update(status='FAIL'),
            lambda r: r.update(transform_sha256='0'*64),
            lambda r: r['source_check'].update(source_sha256='0'*64),
            lambda r: r['artifacts'][1].update(upstream_sha256='0'*64),
            lambda r: r['artifacts'][1].update(sha256='not-a-hash'),
            lambda r: r['artifacts'][2].update(row_count=True),
            lambda r: r['artifacts'][2].update(row_count=0),
            lambda r: r['reconciliation'][0].update(passed=1),
            lambda r: r['reconciliation'][0].update(expected=999),
            lambda r: r['reconciliation'][1].update(actual=-1),
            lambda r: r['reconciliation'][0].update(evidence_sha256=[]),
            lambda r: r.update(potential_downstream=['unverified']),
            lambda r: r.update(extra='unreviewed'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                forged = copy.deepcopy(baseline)
                mutate(forged)
                def execute(gateway, request):
                    if request.tool == 'run_batch': return ToolResult('OK', forged)
                    return original(gateway, request)
                with patch.object(ToolGateway, 'execute', execute): result = self.run_case()
                self.assertEqual(result.reason, 'INVALID_EVIDENCE')
                self.assertIsNone(result.steps[-1].report)
                self.assertEqual(result.observations, ())

    def test_forged_impact_is_not_accepted(self):
        original = ToolGateway.execute
        def execute(gateway, request):
            if request.tool == 'query_lineage':
                return ToolResult('OK', {'dataset': 'customer_sales', 'potential_downstream': [],
                                         'lineage_kind': 'declared_dataset_dag'})
            return original(gateway, request)
        with patch.object(ToolGateway, 'execute', execute):
            result = self.run_case(transform='exclude_first')
        self.assertEqual(result.reason, 'INVALID_EVIDENCE')

    def test_input_contract_is_closed_to_unknown_transform_or_incident(self):
        for incident, transform in [('not-an-id', 'clean'), (self.incident, 'arbitrary-sql')]:
            with self.assertRaises(ValueError):
                investigate(self.store, incident, default_policy(), transform=transform)

    def test_cli_completion_and_inconclusive_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['investigate-incident', '--db', str(self.path), '--incident', self.incident])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['assessment'], 'NO_FAILURE_OBSERVED')
        with patch('aegisflow_dr.investigation.engine_fingerprint', return_value='a'*64), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['investigate-incident', '--db', str(self.path), '--incident', self.incident]), 1)
