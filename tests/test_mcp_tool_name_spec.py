"""Regression guard: every registered MCP tool name must match the
MCP spec regex ``^[a-zA-Z0-9_-]{1,64}$``.

The original mureo MCP server registered tool names with dots
(``google_ads.campaigns.list``). Claude Code accepted them; Claude
Desktop rejected the entire server at registration time. This test
prevents that regression from coming back: any future tool added with
a non-spec name fails CI immediately.
"""

from __future__ import annotations

import re

import pytest

MCP_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _all_registered_tools():
    """Return every Tool registered across all mureo tool surface modules."""
    from mureo.mcp import (
        tools_analysis,
        tools_google_ads,
        tools_meta_ads,
        tools_mureo_context,
        tools_rollback,
        tools_search_console,
    )

    out = []
    for mod in (
        tools_analysis,
        tools_google_ads,
        tools_meta_ads,
        tools_mureo_context,
        tools_rollback,
        tools_search_console,
    ):
        out.extend(mod.TOOLS)
    return out


@pytest.mark.unit
def test_all_registered_tools_match_mcp_spec() -> None:
    """Every tool name fits the MCP spec regex.

    Pinning this is the single highest-value regression guard for the
    Claude Desktop registration bug — any tool whose name violates
    the spec would cause Claude Desktop to reject the entire mureo
    server, the same failure mode that motivated the rename in the
    first place.
    """
    bad = [
        t.name for t in _all_registered_tools() if not MCP_TOOL_NAME_RE.match(t.name)
    ]
    assert not bad, (
        f"Tool names violating MCP spec ^[a-zA-Z0-9_-]{{1,64}}$: {bad}. "
        "Use underscore-separated names (google_ads_campaigns_list), "
        "not dots."
    )


@pytest.mark.unit
def test_no_duplicate_tool_names_across_surfaces() -> None:
    """Each tool name registers at most once across the union of surfaces.

    A duplicate would cause undefined dispatch behavior — handle_call_tool
    would resolve to whichever surface module loaded last.
    """
    tools = _all_registered_tools()
    seen: dict[str, int] = {}
    for t in tools:
        seen[t.name] = seen.get(t.name, 0) + 1
    dupes = {n: c for n, c in seen.items() if c > 1}
    assert not dupes, f"Duplicate tool names registered: {dupes}"
