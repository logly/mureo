"""mureo MCP server

Exposes Google Ads / Meta Ads / Search Console tools via the MCP protocol.
Invoked over stdio by MCP clients such as Claude Code or Cursor.

Tool definitions and handlers are separated into per-service modules
(tools_google_ads.py, tools_meta_ads.py, tools_search_console.py).

Per-platform tool families can be disabled at server-startup time by
setting one of the following process env vars to the exact string ``"1"``
before launching the server (typically written by ``mureo providers add
<official-id>`` into ``mcpServers.mureo.env``):

- ``MUREO_DISABLE_GOOGLE_ADS`` — skip the ``google_ads_*`` tool family.
- ``MUREO_DISABLE_META_ADS`` — skip the ``meta_ads_*`` tool family.
- ``MUREO_DISABLE_GA4`` — wired in for forward-compat (no-op today; mureo
  ships no native GA4 tools yet).

The env vars are read **once at module import time**; the server starts
once per process and the gate is a startup decision. Search Console is
*always* registered regardless of env-var combinations — mureo is
canonical for SC because no official MCP exists.

The comparison is exact-string ``== "1"`` — any other value (``"0"``,
``""``, ``"true"``, ``"  1  "``) leaves tools enabled. Do not loosen this
comparison; multiple tests pin the contract.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server

if TYPE_CHECKING:
    from mcp.types import Tool

from mureo.mcp.tools_analysis import TOOLS as ANALYSIS_TOOLS
from mureo.mcp.tools_analysis import handle_tool as handle_analysis_tool
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_google_ads import handle_tool as handle_google_ads_tool
from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS
from mureo.mcp.tools_meta_ads import handle_tool as handle_meta_ads_tool
from mureo.mcp.tools_mureo_context import TOOLS as MUREO_CONTEXT_TOOLS
from mureo.mcp.tools_mureo_context import handle_tool as handle_mureo_context_tool
from mureo.mcp.tools_rollback import TOOLS as ROLLBACK_TOOLS
from mureo.mcp.tools_rollback import handle_tool as handle_rollback_tool
from mureo.mcp.tools_search_console import TOOLS as SEARCH_CONSOLE_TOOLS
from mureo.mcp.tools_search_console import handle_tool as handle_search_console_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env-var gating (read once at module import time — see module docstring)
# ---------------------------------------------------------------------------


def _is_disabled(env_var: str) -> bool:
    """Return True iff the env var equals the exact string ``"1"``.

    Exact-string comparison is intentional — see module docstring. Do NOT
    loosen this to ``bool(...)`` or ``strip().lower() == "1"``; the
    contract is locked in by ``test_truthy_coercion_does_not_disable``.
    """
    return os.environ.get(env_var) == "1"


_GOOGLE_ADS_ENABLED = not _is_disabled("MUREO_DISABLE_GOOGLE_ADS")
_META_ADS_ENABLED = not _is_disabled("MUREO_DISABLE_META_ADS")
# GA4 flag is wired in for forward-compat symmetry; mureo ships no native
# GA4 tools today, so the flag does not currently gate anything. Once GA4
# tools land in mureo, add a ``GA4_TOOLS`` import + ``_GA4_NAMES`` block
# below and the gate becomes operational automatically.
_GA4_ENABLED = not _is_disabled("MUREO_DISABLE_GA4")  # noqa: F841


# ---------------------------------------------------------------------------
# Combined tool list — built conditionally based on env-var gates above.
# ``MUREO_DISABLE_SEARCH_CONSOLE`` is deliberately NOT honored — mureo is
# canonical for Search Console (no official MCP equivalent exists).
# ---------------------------------------------------------------------------

_ALL_TOOLS: list[Tool] = [
    *(GOOGLE_ADS_TOOLS if _GOOGLE_ADS_ENABLED else []),
    *(META_ADS_TOOLS if _META_ADS_ENABLED else []),
    *SEARCH_CONSOLE_TOOLS,
    *ROLLBACK_TOOLS,
    *ANALYSIS_TOOLS,
    *MUREO_CONTEXT_TOOLS,
]
_GOOGLE_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in GOOGLE_ADS_TOOLS) if _GOOGLE_ADS_ENABLED else frozenset()
)
_META_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in META_ADS_TOOLS) if _META_ADS_ENABLED else frozenset()
)
_SEARCH_CONSOLE_NAMES: frozenset[str] = frozenset(t.name for t in SEARCH_CONSOLE_TOOLS)
_ROLLBACK_NAMES: frozenset[str] = frozenset(t.name for t in ROLLBACK_TOOLS)
_ANALYSIS_NAMES: frozenset[str] = frozenset(t.name for t in ANALYSIS_TOOLS)
_MUREO_CONTEXT_NAMES: frozenset[str] = frozenset(t.name for t in MUREO_CONTEXT_TOOLS)


# ---------------------------------------------------------------------------
# Handlers (defined as module-level functions so tests can call them directly)
# ---------------------------------------------------------------------------


async def handle_list_tools() -> list[Any]:
    """Return the list of registered tools."""
    return list(_ALL_TOOLS)


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Execute a tool and return the result.

    Raises:
        ValueError: Unknown tool name or missing required parameter
    """
    if name in _GOOGLE_ADS_NAMES:
        return await handle_google_ads_tool(name, arguments)
    if name in _META_ADS_NAMES:
        return await handle_meta_ads_tool(name, arguments)
    if name in _SEARCH_CONSOLE_NAMES:
        return await handle_search_console_tool(name, arguments)
    if name in _ROLLBACK_NAMES:
        return await handle_rollback_tool(name, arguments)
    if name in _ANALYSIS_NAMES:
        return await handle_analysis_tool(name, arguments)
    if name in _MUREO_CONTEXT_NAMES:
        return await handle_mureo_context_tool(name, arguments)
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# MCP server setup & entry point
# ---------------------------------------------------------------------------


def _create_server() -> Server:
    """Create an MCP Server instance and register handlers."""
    server = Server("mureo")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator, unused-ignore]
    async def list_tools() -> list[Any]:
        return await handle_list_tools()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        return await handle_call_tool(name, arguments)

    return server


async def main() -> None:
    """Start the MCP server over stdio."""
    server = _create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
