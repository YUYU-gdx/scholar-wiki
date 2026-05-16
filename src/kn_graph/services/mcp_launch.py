from __future__ import annotations


def default_mcp_server_args() -> list[str]:
    """Stable MCP launch args for both dev and onefile builds."""
    return ["run", "python", "-m", "kn_graph.services.kn_mcp_server"]

