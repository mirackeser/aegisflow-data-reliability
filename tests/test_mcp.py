# SPDX-License-Identifier: Apache-2.0
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types import CallToolRequestParams, INVALID_PARAMS, METHOD_NOT_FOUND, UNSUPPORTED_PROTOCOL_VERSION

from aegisflow_dr.gateway import ToolPolicy, ToolResult
from aegisflow_dr.pipeline import generate_orders
from aegisflow_dr.integration.mcp_tools import (LocalToolSession, PROTOCOL_VERSION, RESULT_SCHEMA,
    MAX_PARAMS_BYTES, MAX_RESULT_BYTES, MAX_CSV_CHARACTERS, _result)

GRANTS = frozenset((tool, 'source_orders') for tool in ('diagnose_csv', 'run_batch', 'query_lineage'))


class MCPProfileTests(unittest.IsolatedAsyncioTestCase):
    def session(self, **options):
        return LocalToolSession(ToolPolicy(GRANTS, **options))

    def client(self, session):
        return Client(session.server, mode=PROTOCOL_VERSION, raise_exceptions=True)

    async def test_official_client_discovers_exact_version_and_tools(self):
        session = self.session()
        async with self.client(session) as client:
            self.assertEqual(client.protocol_version, PROTOCOL_VERSION)
            listed = await client.list_tools()
            self.assertEqual([tool.name for tool in listed.tools], ['diagnose_csv', 'query_lineage', 'run_batch'])
            self.assertEqual(listed.cache_scope, 'private')
            self.assertEqual(listed.ttl_ms, 0)
            for tool in listed.tools:
                Draft202012Validator.check_schema(tool.input_schema)
                Draft202012Validator.check_schema(tool.output_schema)
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.open_world_hint)
                self.assertFalse(tool.annotations.destructive_hint)
            self.assertIsNone(client.server_capabilities.resources)
            self.assertIsNone(client.server_capabilities.prompts)
            self.assertIsNone(client.server_capabilities.tasks)
        self.assertEqual(session.calls_used, 0)

    async def test_all_three_tools_execute_via_sdk_and_preserve_input(self):
        session = self.session()
        text = generate_orders().decode()
        async with self.client(session) as client:
            for name in ('diagnose_csv', 'run_batch', 'query_lineage'):
                args = {'dataset': 'source_orders'}
                if name != 'query_lineage':
                    args['csv_text'] = text
                before = deepcopy(args)
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['outcome'], 'OK')
                self.assertEqual(json.loads(result.content[0].text), result.structured_content)
                self.assertNotIn('snapshots', result.model_dump_json())
                self.assertEqual(args, before)
        self.assertEqual(session.calls_used, 3)

    async def test_quality_failures_are_successful_tool_results(self):
        async with self.client(self.session()) as client:
            for name in ('diagnose_csv', 'run_batch'):
                result = await client.call_tool(name, {'dataset': 'source_orders',
                    'csv_text': generate_orders(fault='null_total').decode()})
                self.assertFalse(result.is_error)
                self.assertIn(result.structured_content['report']['status'], ['FAIL', 'BLOCKED'])

    async def test_empty_grants_hide_and_deny_all_tools(self):
        session = LocalToolSession(ToolPolicy(frozenset()))
        async with self.client(session) as client:
            self.assertEqual((await client.list_tools()).tools, [])
            with patch('aegisflow_dr.gateway.downstream', side_effect=AssertionError):
                with self.assertRaises(MCPError):
                    await client.call_tool('query_lineage', {'dataset': 'source_orders'})
        self.assertEqual(session.calls_used, 0)

    async def test_dataset_isolation_and_unusable_grants(self):
        session = LocalToolSession(ToolPolicy(frozenset({('query_lineage', 'customer_sales'),
                                                       ('diagnose_csv', 'staging_orders')})))
        async with self.client(session) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual([t.name for t in tools], ['query_lineage'])
            self.assertEqual(tools[0].input_schema['properties']['dataset']['enum'], ['customer_sales'])
            rejected = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
            self.assertTrue(rejected.is_error)
            result = await client.call_tool('query_lineage', {'dataset': 'customer_sales'})
            self.assertEqual(result.structured_content['report']['potential_downstream'], ['sales_dashboard'])
        self.assertEqual(session.calls_used, 1)

    async def test_privileged_and_wrong_arguments_never_dispatch(self):
        session = self.session()
        variants = [{}, {'dataset': None}, {'dataset': ['source_orders']}, {'dataset': 'unknown'}]
        variants += [{'dataset': 'source_orders', key: 'untrusted'} for key in
                     ('tool', 'policy', 'path', 'url', 'sql', 'transform', 'csv_text', 'max_calls')]
        async with self.client(session) as client:
            with patch('aegisflow_dr.gateway.downstream', side_effect=AssertionError):
                for args in variants:
                    self.assertTrue((await client.call_tool('query_lineage', args)).is_error)
        self.assertEqual(session.calls_used, 0)

    async def test_csv_input_types_length_and_unicode_byte_budget(self):
        session = self.session(max_input_bytes=3)
        async with self.client(session) as client:
            for value in [None, 7, '', 'ğğ', 'x' * (MAX_CSV_CHARACTERS + 1)]:
                result = await client.call_tool('diagnose_csv', {'dataset': 'source_orders', 'csv_text': value})
                self.assertTrue(result.is_error)
        # Empty CSV is admitted and rejected by the tool; other inputs never execute.
        self.assertEqual(session.calls_used, 1)

    async def test_failure_is_sanitized_and_spends_one_call(self):
        session = self.session(max_calls=1)
        async with self.client(session) as client:
            with patch('aegisflow_dr.gateway.downstream', side_effect=RuntimeError('private-sensitive-value')):
                result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
            self.assertEqual(result.structured_content['outcome'], 'TOOL_ERROR')
            self.assertNotIn('private-sensitive-value', result.model_dump_json())
            result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
            self.assertEqual(result.structured_content['outcome'], 'BUDGET_EXCEEDED')

    async def test_reconnect_does_not_reset_budget_and_hosts_are_isolated(self):
        session = self.session(max_calls=1)
        for expected in ('OK', 'BUDGET_EXCEEDED'):
            async with self.client(session) as client:
                result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
                self.assertEqual(result.structured_content['outcome'], expected)
        async with self.client(self.session(max_calls=1)) as client:
            self.assertFalse((await client.call_tool('query_lineage', {'dataset': 'source_orders'})).is_error)

    async def test_concurrent_sdk_calls_do_not_overspend(self):
        session = self.session(max_calls=2)
        async with self.client(session) as client:
            await client.list_tools()
            results = await asyncio.gather(*(client.call_tool('query_lineage', {'dataset': 'source_orders'})
                                            for _ in range(8)))
        self.assertEqual(sum(not r.is_error for r in results), 2)
        self.assertEqual(session.calls_used, 2)

    async def test_expired_host_session_never_dispatches(self):
        session = self.session()
        session._gateway._clock = lambda: float('inf')
        async with self.client(session) as client:
            with patch('aegisflow_dr.gateway.downstream', side_effect=AssertionError):
                result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
            self.assertEqual(result.structured_content['outcome'], 'DEADLINE_EXCEEDED')
        self.assertEqual(session.calls_used, 0)

    async def test_resources_prompts_and_legacy_version_are_unavailable(self):
        session = self.session()
        async with self.client(session) as client:
            for operation in (client.list_resources, client.list_prompts):
                with self.assertRaises(MCPError):
                    await operation()
        rejected = False
        try:
            async with Client(session.server, mode='legacy'):
                self.fail('Legacy handshake must reject')
        except* MCPError as errors:
            rejected = True
            self.assertIn('MCP profile version rejected', str(errors.exceptions))
        self.assertTrue(rejected)

    async def test_untrusted_metadata_is_rejected_without_tool_dispatch(self):
        session = self.session()
        async with self.client(session) as client:
            for meta in ({'policy': 'admin'}, {'authorization': 'private-value'}):
                with self.assertRaises(MCPError) as error:
                    await client.call_tool('query_lineage', {'dataset': 'source_orders'}, meta=meta)
                self.assertNotIn('private-value', str(error.exception))
        self.assertEqual(session.calls_used, 0)

    async def test_listing_and_schema_accessor_are_detached(self):
        session = self.session()
        async with self.client(session) as client:
            first = await client.list_tools()
            first.tools[0].input_schema['properties']['dataset']['enum'].append('evil')
            second = await client.list_tools()
            self.assertNotIn('evil', second.model_dump_json())
        schema = session.server.get_tool_input_schema('query_lineage')
        schema['properties']['dataset']['enum'].append('evil')
        self.assertNotIn('evil', str(session.server.get_tool_input_schema('query_lineage')))
        self.assertIsNone(session.server.get_tool_input_schema('missing'))

    async def test_invalid_or_oversized_tool_output_fails_closed(self):
        session = self.session()
        async with self.client(session) as client:
            for value in [None, ToolResult('OK', {'large': 'x' * MAX_RESULT_BYTES}),
                          ToolResult('OK', {'nonfinite': float('nan')}), ToolResult('OK', None)]:
                with patch.object(session._gateway, 'execute', return_value=value):
                    result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
                self.assertEqual(result.structured_content['outcome'], 'OUTPUT_REJECTED')
                self.assertTrue(result.is_error)

    async def test_cancelled_request_cannot_dispatch_at_checkpoint(self):
        session = self.session()
        params = CallToolRequestParams(name='query_lineage', arguments={'dataset': 'source_orders'})
        with patch('aegisflow_dr.integration.mcp_tools.anyio.lowlevel.checkpoint', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await session._call(None, params)
        self.assertEqual(session.calls_used, 0)

    async def test_unknown_tool_handler_fails_closed(self):
        with self.assertRaises(MCPError):
            await self.session()._call(None, CallToolRequestParams(name='shell', arguments={}))

    async def test_guard_rejects_version_operation_and_nonprofile_fields(self):
        session = self.session()
        allowed = {'protocol_version': PROTOCOL_VERSION, 'method': 'tools/call',
                   'params': {'name': 'query_lineage', 'arguments': {'dataset': 'source_orders'}}}
        variants = [({'protocol_version': '2025-11-25'}, UNSUPPORTED_PROTOCOL_VERSION),
                    ({'method': 'tasks/cancel'}, METHOD_NOT_FOUND)]
        for params in [[], {'task': {}}, {'requestState': 'private'}, {'inputResponses': {}},
                       {'name': 'x' * MAX_PARAMS_BYTES}, {'arguments': {'x': float('nan')}},
                       {'arguments': {'x': '\ud800'}}, {'_meta': []}, {'_meta': {'untrusted': True}}]:
            variants.append(({'params': params}, INVALID_PARAMS))
        for change, code in variants:
            callback = AsyncMock()
            with self.assertRaises(MCPError) as error:
                await session._guard(SimpleNamespace(**(allowed | change)), callback)
            self.assertEqual(error.exception.code, code)
            callback.assert_not_awaited()

    async def test_guard_allows_empty_params_and_sanitizes_sdk_errors(self):
        session = self.session()
        context = SimpleNamespace(protocol_version=PROTOCOL_VERSION, method='ping', params=None)
        self.assertEqual(await session._guard(context, AsyncMock(return_value='ok')), 'ok')
        with self.assertRaises(MCPError) as error:
            await session._guard(context, AsyncMock(side_effect=MCPError(INVALID_PARAMS, 'private-value')))
        self.assertNotIn('private-value', str(error.exception))

    def test_invalid_host_policy_and_result_contracts_reject(self):
        with self.assertRaises(ValueError):
            LocalToolSession({'grants': 'all'})
        for outcome, report in [('UNKNOWN', None), ('OK', []), ('DENIED', {'secret': True})]:
            result = _result(outcome, report)
            self.assertEqual(result.structured_content['outcome'], 'OUTPUT_REJECTED')
            Draft202012Validator(RESULT_SCHEMA).validate(result.structured_content)


if __name__ == '__main__':
    unittest.main()
