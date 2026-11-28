"""mureo MCP — Model Context Protocol server for Google Ads / Meta Ads."""

from mureo.mcp.server import (
    handle_call_tool,
    handle_list_tools,
    main,
)
from mureo.mcp.tool_checks import (
    check_tool_call,
    in_ops_history_scope,
    writes_to_platform,
)

__all__ = [
    "check_tool_call",
    "handle_call_tool",
    "handle_list_tools",
    "in_ops_history_scope",
    "main",
    "writes_to_platform",
]
