"""MCP tool sources for Strands agents.

    with http_mcp_client("http://localhost:8000/mcp") as client:
        agent = make_agent(name="x", system_prompt="...", tools=client.list_tools_sync())

Or pass the client itself in `tools=[client]` and Strands manages its lifecycle.
A2A: wrap an agent with `strands.multiagent.a2a.A2AServer(agent=...)` (needs the `a2a` extra).
"""

from __future__ import annotations

from typing import Any


def http_mcp_client(url: str, headers: dict[str, str] | None = None, prefix: str | None = None) -> Any:
    from strands.tools.mcp import MCPClient

    return MCPClient(url=url, headers=headers, prefix=prefix)


def stdio_mcp_client(command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> Any:
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from strands.tools.mcp import MCPClient

    params = StdioServerParameters(command=command, args=args or [], env=env)
    return MCPClient(lambda: stdio_client(params))
