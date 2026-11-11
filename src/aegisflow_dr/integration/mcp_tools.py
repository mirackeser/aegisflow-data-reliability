# SPDX-License-Identifier: Apache-2.0
"""Optional official MCP adapter for one trusted local tool-policy lifetime."""
from copy import deepcopy
import json

import anyio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp_types import (CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations,
                       INVALID_PARAMS, METHOD_NOT_FOUND, UNSUPPORTED_PROTOCOL_VERSION)

from ..gateway import ToolGateway, ToolPolicy, ToolRequest, ToolResult

PROTOCOL_VERSION = '2026-07-28'
MAX_PARAMS_BYTES = 32_768
MAX_RESULT_BYTES = 65_536
MAX_CSV_CHARACTERS = 16_384
OUTCOMES = ['OK', 'INVALID_REQUEST', 'DENIED', 'INPUT_REJECTED', 'DEADLINE_EXCEEDED',
            'BUDGET_EXCEEDED', 'TOOL_ERROR', 'OUTPUT_REJECTED']
RESULT_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['outcome', 'report'],
    'properties': {'outcome': {'enum': OUTCOMES}, 'report': {'type': ['object', 'null']}},
    'if': {'properties': {'outcome': {'const': 'OK'}}},
    'then': {'properties': {'report': {'type': 'object'}}},
    'else': {'properties': {'report': {'type': 'null'}}},
}
_RESULT_VALIDATOR = Draft202012Validator(RESULT_SCHEMA)
_META = frozenset({'io.modelcontextprotocol/protocolVersion',
                   'io.modelcontextprotocol/clientInfo', 'io.modelcontextprotocol/clientCapabilities'})
_METHOD_FIELDS = {'server/discover': set(), 'ping': set(), 'tools/list': set(),
                  'tools/call': {'name', 'arguments'}}


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _schemas(policy):
    schemas = {}
    for name in ('diagnose_csv', 'query_lineage', 'run_batch'):
        datasets = sorted(dataset for tool, dataset in policy.grants
                          if tool == name and (name == 'query_lineage' or dataset == 'source_orders'))
        if not datasets:
            continue
        properties = {'dataset': {'type': 'string', 'enum': datasets}}
        required = ['dataset']
        if name != 'query_lineage':
            properties['csv_text'] = {'type': 'string', 'maxLength': MAX_CSV_CHARACTERS}
            required.append('csv_text')
        schemas[name] = {'type': 'object', 'properties': properties,
                         'required': required, 'additionalProperties': False}
    return schemas


def _result(outcome, report=None):
    value = {'outcome': outcome, 'report': report}
    try:
        _RESULT_VALIDATOR.validate(value)
        result = CallToolResult(content=[TextContent(type='text', text=_json(value).decode())],
                                structured_content=value, is_error=outcome != 'OK')
        if len(_json(result.model_dump(by_alias=True, exclude_none=True))) > MAX_RESULT_BYTES:
            raise ValueError('Output exceeds budget')
        return result
    except (ValueError, TypeError, RecursionError, UnicodeError, ValidationError):
        # Never echo an invalid or unbounded report from a tool implementation.
        return CallToolResult(content=[TextContent(type='text', text='Tool output rejected')],
            structured_content={'outcome': 'OUTPUT_REJECTED', 'report': None}, is_error=True)


class LocalToolSession:
    """A host owns one instance per policy/budget lifetime; reconnects do not reset it.

    The returned official Server is intended for an in-process Client(mode=PROTOCOL_VERSION).
    It supplies no HTTP listener, remote authentication or process isolation.
    """
    def __init__(self, policy: ToolPolicy):
        if type(policy) is not ToolPolicy:
            raise ValueError('A trusted ToolPolicy is required')
        self._gateway = ToolGateway(policy)
        self._schemas = _schemas(policy)
        self._validators = {name: Draft202012Validator(schema) for name, schema in self._schemas.items()}
        self.server = Server('AegisFlow Local Tool Gateway', version='0.1.0',
            on_list_tools=self._list, on_call_tool=self._call,
            get_tool_input_schema=lambda name: deepcopy(self._schemas.get(name)))
        # No implicit telemetry exporter or payload tracing from SDK middleware.
        self.server.middleware = [self._guard]

    @property
    def calls_used(self):
        return self._gateway.calls_used

    async def _guard(self, context, call_next):
        if context.protocol_version != PROTOCOL_VERSION:
            raise MCPError(UNSUPPORTED_PROTOCOL_VERSION, 'MCP profile version rejected')
        if context.method not in _METHOD_FIELDS:
            raise MCPError(METHOD_NOT_FOUND, 'MCP operation unavailable')
        try:
            params = context.params if context.params is not None else {}
            if (type(params) is not dict or set(params) - (_METHOD_FIELDS[context.method] | {'_meta'})
                    or len(_json(params)) > MAX_PARAMS_BYTES):
                raise ValueError('Invalid params')
            meta = params.get('_meta', {})
            if type(meta) is not dict or set(meta) - _META:
                raise ValueError('Unsupported metadata')
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise MCPError(INVALID_PARAMS, 'MCP request rejected') from None
        try:
            return await call_next(context)
        except MCPError as error:
            raise MCPError(error.code, 'MCP request rejected') from None

    async def _list(self, context, params):
        return ListToolsResult(tools=[Tool(name=name, description='Bounded local ' + name.replace('_', ' '),
            input_schema=deepcopy(schema), output_schema=deepcopy(RESULT_SCHEMA),
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                        idempotent_hint=True, open_world_hint=False))
            for name, schema in self._schemas.items()])

    async def _call(self, context, params):
        # Only listed host-authorized tools can dispatch; annotations grant no access.
        if params.name not in self._validators:
            raise MCPError(METHOD_NOT_FOUND, 'MCP tool unavailable')
        arguments = params.arguments
        if not self._validators[params.name].is_valid(arguments):
            return _result('INVALID_REQUEST')
        await anyio.lowlevel.checkpoint()
        request = ToolRequest.from_mapping({'tool': params.name, **arguments})
        result = self._gateway.execute(request)
        if type(result) is not ToolResult:
            return _result('OUTPUT_REJECTED')
        # Snapshots remain local; the MCP contract exposes only the existing report.
        return _result(result.outcome, result.report)
