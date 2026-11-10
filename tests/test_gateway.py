# SPDX-License-Identifier: Apache-2.0
from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aegisflow_dr.__main__ import main
from aegisflow_dr.gateway import ToolGateway, ToolPolicy, ToolRequest
from aegisflow_dr.pipeline import generate_orders


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.csv = generate_orders().decode()
        self.request = ToolRequest('diagnose_csv', 'source_orders', self.csv)
        self.grants = frozenset({('diagnose_csv', 'source_orders')})

    def gateway(self, **kwargs):
        return ToolGateway(ToolPolicy(self.grants, **kwargs))

    def test_authorized_source_tool_preserves_evidence(self):
        result = self.gateway().execute(self.request)
        self.assertEqual(result.outcome, 'OK')
        self.assertEqual(result.report['status'], 'PASS')
        self.assertEqual(len(result.report['source_sha256']), 64)

    def test_batch_and_lineage_exact_grants(self):
        grants = frozenset({('run_batch', 'source_orders'), ('query_lineage', 'customer_sales')})
        gateway = ToolGateway(ToolPolicy(grants))
        batch = gateway.execute(ToolRequest('run_batch', 'source_orders', self.csv))
        lineage = gateway.execute(ToolRequest('query_lineage', 'customer_sales'))
        self.assertEqual(batch.report['status'], 'PASS')
        self.assertEqual(lineage.report['potential_downstream'], ['sales_dashboard'])
        self.assertEqual(gateway.execute(ToolRequest('query_lineage', 'source_orders')).outcome,
                         'DENIED')

    def test_denied_requests_never_dispatch_or_spend_calls(self):
        gateway = ToolGateway(ToolPolicy(frozenset()))
        with patch('aegisflow_dr.gateway.diagnose_csv') as tool:
            self.assertEqual(gateway.execute(self.request).outcome, 'DENIED')
            tool.assert_not_called()
        self.assertEqual(gateway.calls_used, 0)

    def test_unknown_or_privileged_fields_are_not_accepted(self):
        for field in ['policy', 'allowed_tools', 'max_calls', 'sql', 'path']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                ToolRequest.from_mapping({'tool': 'query_lineage', 'dataset': 'source_orders',
                                          field: 'override'})

    def test_closed_schema_rejects_wrong_types_and_combinations(self):
        invalid = [None, [], {}, {'tool': [], 'dataset': 'source_orders'},
                   {'tool': 'query_lineage', 'dataset': []},
                   {'tool': 'query_lineage', 'dataset': 'source_orders', 'transform': []},
                   {'tool': 'write_production', 'dataset': 'source_orders'},
                   {'tool': 'query_lineage', 'dataset': 'unknown'},
                   {'tool': 'query_lineage', 'dataset': 'source_orders', 'csv_text': 'x'},
                   {'tool': 'diagnose_csv', 'dataset': 'source_orders', 'csv_text': 5},
                   {'tool': 'diagnose_csv', 'dataset': 'customer_sales', 'csv_text': 'x'},
                   {'tool': 'diagnose_csv', 'dataset': 'source_orders', 'csv_text': 'x',
                    'transform': 'exclude_first'}]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                ToolRequest.from_mapping(request)

    def test_direct_dataclass_cannot_bypass_validation(self):
        gateway = self.gateway()
        for request in [self.request.__dict__, ToolRequest('write_production', 'source_orders'),
                        ToolRequest('diagnose_csv', 'source_orders', object())]:
            self.assertEqual(gateway.execute(request).outcome, 'INVALID_REQUEST')
        self.assertEqual(gateway.calls_used, 0)

    def test_invalid_input_cannot_trigger_deepcopy(self):
        class Untrusted:
            def __deepcopy__(self, memo):
                raise RuntimeError('must never run')
        result = self.gateway().execute(ToolRequest('diagnose_csv', 'source_orders', Untrusted()))
        self.assertEqual(result.outcome, 'INVALID_REQUEST')

    def test_utf8_byte_budget_is_not_a_character_count(self):
        gateway = self.gateway(max_input_bytes=3)
        result = gateway.execute(ToolRequest('diagnose_csv', 'source_orders', 'ğğ'))
        self.assertEqual(result.outcome, 'INPUT_REJECTED')
        self.assertEqual(gateway.calls_used, 0)

    def test_oversized_and_unencodable_text_rejected(self):
        gateway = self.gateway(max_input_bytes=3)
        for text in ['xxxx', '\ud800']:
            self.assertEqual(gateway.execute(ToolRequest('diagnose_csv', 'source_orders', text)).outcome,
                             'INPUT_REJECTED')
        self.assertEqual(gateway.calls_used, 0)

    def test_failed_tool_attempt_still_consumes_budget_and_hides_details(self):
        gateway = self.gateway(max_calls=1)
        with patch('aegisflow_dr.gateway.diagnose_csv', side_effect=RuntimeError('/secret/value')):
            result = gateway.execute(self.request)
        self.assertEqual(result.outcome, 'TOOL_ERROR')
        self.assertNotIn('secret', result.to_json())
        self.assertIsNone(result.report)
        self.assertEqual(gateway.calls_used, 1)
        self.assertEqual(gateway.execute(self.request).outcome, 'BUDGET_EXCEEDED')

    def test_malformed_admitted_input_spends_a_call(self):
        gateway = self.gateway(max_calls=1)
        result = gateway.execute(ToolRequest('diagnose_csv', 'source_orders', 'a,a\n1,2'))
        self.assertEqual(result.outcome, 'INPUT_REJECTED')
        self.assertEqual(gateway.calls_used, 1)

    def test_quality_failure_is_a_successfully_executed_tool(self):
        result = self.gateway().execute(ToolRequest('diagnose_csv', 'source_orders',
                                                   generate_orders(fault='null_total').decode()))
        self.assertEqual(result.outcome, 'OK')
        self.assertEqual(result.report['status'], 'FAIL')

    def test_deadline_before_dispatch(self):
        now = [0.0]
        gateway = ToolGateway(ToolPolicy(self.grants, timeout_seconds=1), clock=lambda: now[0])
        now[0] = 1.0
        with patch('aegisflow_dr.gateway.diagnose_csv') as tool:
            self.assertEqual(gateway.execute(self.request).outcome, 'DEADLINE_EXCEEDED')
            tool.assert_not_called()
        self.assertEqual(gateway.calls_used, 0)

    def test_late_result_is_discarded_without_resetting_session_clock(self):
        now = [0.0]
        gateway = ToolGateway(ToolPolicy(self.grants, timeout_seconds=1), clock=lambda: now[0])
        from aegisflow_dr.pipeline import diagnose_csv
        def delayed(payload):
            now[0] = 2.0
            return diagnose_csv(payload)
        with patch('aegisflow_dr.gateway.diagnose_csv', side_effect=delayed):
            result = gateway.execute(self.request)
        self.assertEqual(result.outcome, 'DEADLINE_EXCEEDED')
        self.assertIsNone(result.report)
        self.assertEqual(gateway.execute(self.request).outcome, 'DEADLINE_EXCEEDED')
        self.assertEqual(gateway.calls_used, 1)

    def test_concurrent_call_reservations_cannot_overspend(self):
        gateway = self.gateway(max_calls=3)
        with ThreadPoolExecutor(max_workers=12) as workers:
            results = list(workers.map(lambda _: gateway.execute(self.request), range(24)))
        self.assertEqual(sum(r.outcome == 'OK' for r in results), 3)
        self.assertEqual(sum(r.outcome == 'BUDGET_EXCEEDED' for r in results), 21)
        self.assertEqual(gateway.calls_used, 3)

    def test_invalid_host_policy_is_rejected(self):
        options = [{'grants': set()}, {'grants': frozenset({('unknown', 'source_orders')})},
                   {'max_calls': True}, {'max_calls': 0}, {'max_calls': 101},
                   {'max_input_bytes': 0}, {'max_input_bytes': 1000001},
                   {'timeout_seconds': True}, {'timeout_seconds': float('nan')},
                   {'timeout_seconds': float('inf')}, {'timeout_seconds': 0},
                   {'timeout_seconds': 61}]
        for option in options:
            with self.subTest(option=option), self.assertRaises(ValueError):
                ToolPolicy(**({'grants': self.grants} | option))

    def test_cli_gateway_demo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['gateway-demo']), 0)
        self.assertEqual(json.loads(out.getvalue())['report']['status'], 'PASS')
