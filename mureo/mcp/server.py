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

    from mureo.mcp.tool_provider import MCPToolProvider

from mureo.mcp.plugin_audit import record_plugin_call
from mureo.mcp.plugin_semantics import (
    ToolSemantics,
    derive_semantics,
    record_mutation_action_log,
)
from mureo.mcp.tool_provider import collect_plugin_tools, plugin_source
from mureo.mcp.tools_analysis import TOOLS as ANALYSIS_TOOLS
from mureo.mcp.tools_analysis import handle_tool as handle_analysis_tool
from mureo.mcp.tools_analytics_registry import (
    TOOLS as ANALYTICS_REGISTRY_TOOLS,
)
from mureo.mcp.tools_analytics_registry import (
    handle_tool as handle_analytics_registry_tool,
)
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
from mureo.throttle import PLUGIN_THROTTLE, Throttler

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
    *ANALYTICS_REGISTRY_TOOLS,
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
_ANALYTICS_REGISTRY_NAMES: frozenset[str] = frozenset(
    t.name for t in ANALYTICS_REGISTRY_TOOLS
)

# ---------------------------------------------------------------------------
# Third-party plugin tools (entry-point–discovered providers implementing
# MCPToolProvider). Purely additive: built-in platforms keep their static
# TOOLS and are NOT routed here, so there is no double-exposure. If no
# plugins are installed this is a no-op and behaviour is byte-identical to
# before. Built-in tool names are reserved so a plugin can never shadow a
# core tool. Discovery faults are contained (PluginToolWarning), never fatal.
# ---------------------------------------------------------------------------
_PLUGIN_TOOLS: list[Tool]
_PLUGIN_DISPATCH: dict[str, MCPToolProvider]
_PLUGIN_TOOLS, _PLUGIN_DISPATCH = collect_plugin_tools(
    reserved_names=(
        _GOOGLE_ADS_NAMES
        | _META_ADS_NAMES
        | _SEARCH_CONSOLE_NAMES
        | _ROLLBACK_NAMES
        | _ANALYSIS_NAMES
        | _MUREO_CONTEXT_NAMES
        | _ANALYTICS_REGISTRY_NAMES
    ),
)
_ALL_TOOLS.extend(_PLUGIN_TOOLS)
_PLUGIN_NAMES: frozenset[str] = frozenset(_PLUGIN_DISPATCH)

# One conservative shared bucket for all plugin tool calls. Built-in
# platforms keep their own per-platform throttlers; this only gates the
# plugin dispatch branch.
#
# Kept as a module-level attribute because (a) existing tests
# monkey-patch it directly to inject a spy throttler and (b) the lazy
# seeding helper below copies its instance into the resolved
# :class:`ProcessLocalThrottleStore` so the same bucket is observed
# regardless of which path enters the dispatcher.
_PLUGIN_THROTTLER = Throttler(PLUGIN_THROTTLE)

# Phase 2 (#114): per-tool safety semantics derived from STANDARD MCP
# metadata (annotations.readOnlyHint + optional meta["mureo"]). No new
# ABI surface. A declared throttle hint gets its own bucket; everything
# else shares _PLUGIN_THROTTLER. Undeclared ⇒ mutating (conservative).
_PLUGIN_SEMANTICS: dict[str, ToolSemantics] = {
    t.name: derive_semantics(t) for t in _PLUGIN_TOOLS
}
_PLUGIN_TOOL_THROTTLERS: dict[str, Throttler] = {
    name: Throttler(sem.throttle)
    for name, sem in _PLUGIN_SEMANTICS.items()
    if sem.throttle is not None
}


# ---------------------------------------------------------------------------
# Throttle dispatch — bridge legacy module state to the RuntimeContext
# throttle_store so an alternate backend (registered via
# ``mureo.runtime_context_factory``) can take over without each handler
# having to know about it.
# ---------------------------------------------------------------------------


# Sentinel key for the "everything else" bucket installed alongside the
# per-tool buckets when seeding a default ``ProcessLocalThrottleStore``.
# Kept as a module-level constant so the seeding helper and the
# unknown-name fallback both reference the same string.
_PLUGIN_DEFAULT_BUCKET = "__plugin_default__"

# Set of ``id()``s of ``ProcessLocalThrottleStore`` instances we have
# already seeded with the legacy ``_PLUGIN_TOOL_THROTTLERS`` configs.
# Idempotent: re-entry against a previously-seeded store is a no-op.
# Tests that monkey-patch ``_PLUGIN_THROTTLER`` or
# ``_PLUGIN_TOOL_THROTTLERS`` directly must clear this set AND call
# ``reset_runtime_context()`` so the next handler call re-seeds a
# freshly-resolved store with the patched throttlers.
_throttle_store_seeded: set[int] = set()


async def _acquire_plugin_throttle(name: str) -> None:
    """Acquire one throttle slot for plugin tool ``name``.

    Routes through ``get_runtime_context().throttle_store`` so an
    alternate backend can intercept the call. For the default
    file-backed runtime the throttle_store is a
    :class:`ProcessLocalThrottleStore`; this function lazily seeds it
    with the per-tool ``Throttler`` instances built at module load,
    preserving today's per-name bucket semantics. The fallback bucket
    for unknown names is the store's ``default_config`` (=
    ``PLUGIN_THROTTLE`` for the default runtime).

    The legacy ``_PLUGIN_THROTTLER`` / ``_PLUGIN_TOOL_THROTTLERS``
    module attributes are still consulted: tests that monkey-patch
    them continue to observe their spy being invoked, because the
    seeded ``ProcessLocalThrottleStore`` uses those exact instances.

    Alternate backends (non-``ProcessLocalThrottleStore`` returned by a
    ``mureo.runtime_context_factory`` entry-point) receive a single
    ``acquire(name)`` call and own the full per-key + unknown-name
    fallback semantics themselves. The seeding step above is
    deliberately skipped for them: this Protocol exposes only
    ``acquire``, so a backend that wants the "unknown name → shared
    default bucket" behaviour must implement it internally.
    """
    # Lazy import to avoid an import cycle: ``mureo.core.runtime_context``
    # is free to reference MCP types in future without circling back to
    # this module via the top-level import graph.
    from mureo.core.runtime_context import get_runtime_context
    from mureo.core.throttle_store import ProcessLocalThrottleStore

    store = get_runtime_context().throttle_store
    if isinstance(store, ProcessLocalThrottleStore):
        ident = id(store)
        if ident not in _throttle_store_seeded:
            # Install per-tool buckets first.
            for tname, throttler in _PLUGIN_TOOL_THROTTLERS.items():
                store.throttlers.setdefault(tname, throttler)
            # And the conservative fallback bucket for unknown names.
            # We DO NOT call store.register() here because that would
            # rebuild a fresh Throttler from default_config; reusing
            # ``_PLUGIN_THROTTLER`` keeps the singleton state (token
            # bucket) coherent across the legacy and RuntimeContext
            # paths.
            store.throttlers.setdefault(_PLUGIN_DEFAULT_BUCKET, _PLUGIN_THROTTLER)
            _throttle_store_seeded.add(ident)
        # Unknown names go through the default bucket. Resolve here
        # because the Protocol does not expose "give me the throttler
        # for this key" — only acquire(key) — and we want the named
        # bucket for known names but the SHARED bucket for unknown.
        if name not in _PLUGIN_TOOL_THROTTLERS:
            await store.throttlers[_PLUGIN_DEFAULT_BUCKET].acquire()
            return
    await store.acquire(name)


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
    if name in _ANALYTICS_REGISTRY_NAMES:
        return await handle_analytics_registry_tool(name, arguments)
    if name in _PLUGIN_NAMES:
        provider = _PLUGIN_DISPATCH[name]
        source = plugin_source(provider)
        sem = _PLUGIN_SEMANTICS.get(name)
        await _acquire_plugin_throttle(name)
        try:
            result = await provider.handle_mcp_tool(name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001
            # Record the failed call, then re-raise unchanged so the MCP
            # framework surfaces a clean tool error exactly as before
            # (no server crash, no silently-swallowed error).
            record_plugin_call(
                tool=name,
                arguments=arguments,
                source=source,
                ok=False,
                error=repr(exc),
            )
            raise
        record_plugin_call(tool=name, arguments=arguments, source=source, ok=True)
        # Phase 2: promote a *successful mutating* call into STATE.json's
        # action_log (only when a STATE.json exists in cwd) so the agent
        # / strategy review / rollback can see it like a built-in op.
        # Read-only tools stay in the jsonl audit only (no STATE bloat).
        if sem is None or sem.mutating:
            record_mutation_action_log(
                tool=name,
                source=source,
                reversal=None if sem is None else sem.reversal,
                observation_days=None if sem is None else sem.observation_days,
            )
        return result
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
