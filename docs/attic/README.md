# Attic

Code removed from the product but kept recoverable, because this tree is not under version control.

## mcp-support-2026-11-04.tgz

Full MCP client support, removed 2026-11-04. It contained:

- `adapters/mcp/client.py` — streamable-HTTP MCP client (initialize / tools/list / tools/call, SSE + JSON)
- `adapters/mcp/backlinks.py`, `adapters/search_data/mcp.py` — MCP as a data provider
- `adapters/mcp/analyst.py`, `intelligence/mcp_tools.py` — MCP tools offered to the AI analyst
- its tests

**Why it was removed.** MCP ingestion duplicated the `custom_*` adapters (both need the same field mapping) and
the servers worth ingesting from ship as stdio, which this never supported. MCP analyst tools worked, but produced
no stored rows — nothing for the scorecard, plan rules or charts to use. GrowOS is a data platform; a feature that
accumulates no data does not fit it.

**If MCP comes back**, the direction worth building is the opposite one: GrowOS *as* an MCP server, so agents can
read the scorecard, plan and findings. `intelligence/tools.py` already defines 9 validated tools that would be most
of that work; the missing piece is per-token project scoping.

Restore with: `tar xzf docs/attic/mcp-support-2026-11-04.tgz` from the repository root.
