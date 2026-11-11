# MCP local tools profile v1

Optional SDK: mcp 2.3.0. Supported profile revision: 2026-07-28. Transport tested: official in-process Client/Server dispatch. No listener, subprocess or outbound service is started.

```python
from mcp import Client
from aegisflow_dr.gateway import ToolPolicy
from aegisflow_dr.integration.mcp_tools import LocalToolSession, PROTOCOL_VERSION

session = LocalToolSession(ToolPolicy(frozenset({('query_lineage', 'source_orders')})))
# Retain session for the whole host-authorized policy/budget lifetime.
async with Client(session.server, mode=PROTOCOL_VERSION) as client:
    tools = await client.list_tools()
    result = await client.call_tool('query_lineage', {'dataset': 'source_orders'})
```

## Operations and arguments

Server discovery, ping, tools/list and tools/call are the only permitted methods. Discovery reflects the native SDK's tools capability; resources, prompts and Tasks are absent. Legacy protocol requests reject. The SDK's modern Client may re-list on a schema/header mismatch; it cannot reset gateway budgets or add grants.

- diagnose_csv: dataset must be source_orders; csv_text is required string.
- run_batch: same inputs; always the clean, packaged in-memory transformation.
- query_lineage: dataset must be in this host's exact grants; no CSV or transform argument.

Tool availability and dataset enums come from host ToolPolicy. Unusable CSV grants for other datasets are omitted. No additional argument property is permitted. ToolPolicy never comes from client input. Every advertised schema is returned as a detached copy through native SDK Tool models; inputSchema and outputSchema are authoritative for this profile.

Params permit only name/arguments for tools/call and no non-metadata fields for other methods. The SDK-required `_meta` keys io.modelcontextprotocol/protocolVersion, clientInfo and clientCapabilities are permitted; they establish no identity. Custom metadata, pagination cursors, task, requestState and inputResponses reject. Unknown tools/methods and malformed protocol parameters produce sanitized MCP errors; invalid business arguments return isError with INVALID_REQUEST. No error exposes raw exception details.

## Results and budgets

CallToolResult contains one text representation plus structuredContent with exactly outcome and report. Outcome is OK, INVALID_REQUEST, DENIED, INPUT_REJECTED, DEADLINE_EXCEEDED, BUDGET_EXCEEDED, TOOL_ERROR or OUTPUT_REJECTED. An OK result requires an object report; every other outcome requires null. isError is true for non-OK outcomes. Existing reports can indicate FAIL/BLOCKED while the tool call itself remains OK. Reports contain diagnostic metadata; retained raw snapshots are not exported. Consumers must inspect both outcome and report status.

Limits are 32,768 encoded UTF-8 bytes for params, 16,384 characters per CSV, and the host gateway's additional UTF-8 input-byte budget. Result content, including both text/structured representations, is limited to 65,536 encoded bytes before the SDK adds its small server identity stamp. SDK envelope/transport framing is outside these application limits. Serialization rejects nonfinite values and invalid Unicode. These are checks on already-created local objects, not a network frame parser.

Calls and deadline belong to one LocalToolSession, including across reconnects. The gateway atomically reserves authorized admitted calls; concurrent clients cannot overspend. Invalid arguments do not dispatch. Tool failures consume calls. A cancellation checkpoint runs before dispatch; synchronous execution is cooperative and cannot be forcibly interrupted. Network admission, process limits, persistent quotas and multi-tenant identities require a later host design.

```mermaid
sequenceDiagram
  participant Host
  participant MCP as Official MCP Client/Server
  participant Gate as ToolGateway
  participant Tool as Existing local tool
  Host->>MCP: One session with immutable grants and budgets
  MCP-->>Host: Filtered, detached input/output schemas
  Host->>MCP: tools/call with exact arguments
  MCP->>MCP: Version, method, metadata, shape and size validation
  MCP->>Gate: Validated ToolRequest
  Gate->>Gate: Exact grant, byte/deadline checks, atomic reservation
  alt admitted
    Gate->>Tool: Bounded read-only execution
    Tool-->>Gate: Diagnostic report
    Gate-->>MCP: Outcome/report; snapshots stay local
    MCP-->>Host: Validated bounded CallToolResult
  else denied or exhausted
    Gate-->>MCP: Constant failure outcome
    MCP-->>Host: isError with no report
  end
```

See [ADR-0012](../adr/0012-official-mcp-local-tools.md) for trust and deployment boundaries. SDK/model/schema version pins are not accuracy measurements; the implementation makes zero LLM calls.
