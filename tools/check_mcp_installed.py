# SPDX-License-Identifier: Apache-2.0
"""Verify the installed official MCP profile outside the source checkout."""
import asyncio
from importlib.metadata import distribution
from pathlib import Path

import aegisflow_dr
from mcp import Client
from mcp.shared.exceptions import MCPError

from aegisflow_dr.gateway import ToolPolicy
from aegisflow_dr.integration.mcp_tools import LocalToolSession, PROTOCOL_VERSION
from aegisflow_dr.pipeline import generate_orders


async def main():
    checkout = Path(__file__).resolve().parents[1]
    if Path(aegisflow_dr.__file__).resolve().is_relative_to(checkout / 'src'):
        raise RuntimeError('Installed MCP check imported source checkout')
    requirements = distribution('aegisflow-data-reliability').requires or []
    if not any('mcp==2.3.0' in item and 'extra == "mcp"' in item for item in requirements):
        raise RuntimeError('Optional SDK pin missing from installed metadata')
    policy = ToolPolicy(frozenset((tool, 'source_orders') for tool in
                                  ('diagnose_csv', 'run_batch', 'query_lineage')), max_calls=3)
    session = LocalToolSession(policy)
    async with Client(session.server, mode=PROTOCOL_VERSION, raise_exceptions=True) as client:
        if len((await client.list_tools()).tools) != 3:
            raise RuntimeError('Installed tool discovery failed')
        for name in ('diagnose_csv', 'run_batch', 'query_lineage'):
            arguments = {'dataset': 'source_orders'}
            if name != 'query_lineage':
                arguments['csv_text'] = generate_orders().decode()
            result = await client.call_tool(name, arguments)
            if result.is_error or result.structured_content['outcome'] != 'OK':
                raise RuntimeError('Installed gateway call failed')
    async with Client(session.server, mode=PROTOCOL_VERSION) as client:
        result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
        if result.structured_content['outcome'] != 'BUDGET_EXCEEDED':
            raise RuntimeError('Installed reconnect reset policy budget')
    denied = LocalToolSession(ToolPolicy(frozenset()))
    async with Client(denied.server, mode=PROTOCOL_VERSION) as client:
        if (await client.list_tools()).tools:
            raise RuntimeError('Installed default-deny discovery failed')
        try:
            await client.call_tool('query_lineage', {'dataset': 'source_orders'})
        except MCPError:
            pass
        else:
            raise RuntimeError('Installed default-deny dispatch failed')
    print('Installed official MCP discovery, three tools, default denial and shared budgets passed.')


if __name__ == '__main__':
    asyncio.run(main())
