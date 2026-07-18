"""Regression: Search Console ``site_url`` must be OPTIONAL at the schema level.

The tenant-scoped single-property auto-resolution in
``_handlers_search_console._resolve_site_url`` is only reachable if the tool's
``inputSchema`` does NOT list ``site_url`` in ``required`` — otherwise
``server.handle_call_tool`` rejects an omitted ``site_url`` at
``_validate_tool_input`` ("'site_url' is a required property") *before* the
handler runs.

This was review finding H1: every SC tool declared ``site_url`` as required, so
the documented single-property auto-resolve was dead code on the real dispatch
path. The existing tenant-scope tests call handlers directly (bypassing the
schema), so they never caught it. These tests exercise the server dispatch
path, where the schema is validated first.

Standalone OSS is unaffected: ``_resolve_site_url`` still ``_require``s
``site_url`` (a clear runtime error), so omitting it there still fails — just
from the handler, not the schema.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.mcp.tools_search_console import TOOLS


@pytest.mark.unit
def test_no_sc_tool_requires_site_url_in_schema() -> None:
    """No Search Console tool may list ``site_url`` in its schema ``required``."""
    offenders = [
        tool.name
        for tool in TOOLS
        if "site_url" in tool.inputSchema.get("required", [])
    ]
    assert offenders == [], f"tools still require site_url in schema: {offenders}"


@pytest.mark.unit
def test_sc_tools_keep_site_url_as_a_property() -> None:
    """``site_url`` stays an accepted (optional) property on every SC tool that
    takes it — dropping it from ``required`` must not drop the property."""
    for tool in TOOLS:
        # Only the tools that take a site_url (all except sites_list).
        if tool.name == "search_console_sites_list":
            continue
        assert "site_url" in tool.inputSchema.get("properties", {}), tool.name


@pytest.mark.asyncio
async def test_server_path_autoresolves_single_site_without_site_url() -> None:
    """Through the schema-validated server dispatch, a tenant-scoped
    single-property client resolves an omitted ``site_url`` instead of a schema
    'required' rejection (the H1 bug)."""
    from mureo.mcp import _handlers_search_console as h
    from mureo.mcp import server

    client = AsyncMock()
    client.get_site.return_value = {"siteUrl": "https://only.example/"}
    with (
        patch.object(h, "load_google_ads_credentials", return_value=MagicMock()),
        patch.object(h, "create_search_console_client", return_value=client),
        patch.object(
            h,
            "runtime_search_console_sites",
            return_value=frozenset({"https://only.example/"}),
        ),
    ):
        result = await server.handle_call_tool("search_console_sites_get", {})

    # Reached the handler and auto-resolved the single configured property.
    client.get_site.assert_awaited_once_with("https://only.example/")
    assert result  # a TextContent result, not a raised schema error


@pytest.mark.asyncio
async def test_server_path_standalone_still_errors_without_site_url() -> None:
    """No regression for standalone OSS: with no tenant scope, an omitted
    ``site_url`` still fails — now from the handler's ``_require`` rather than
    the schema."""
    from mureo.mcp import _handlers_search_console as h
    from mureo.mcp import server

    client = AsyncMock()
    with (
        patch.object(h, "load_google_ads_credentials", return_value=MagicMock()),
        patch.object(h, "create_search_console_client", return_value=client),
        patch.object(h, "runtime_search_console_sites", return_value=None),
        pytest.raises(ValueError),
    ):
        await server.handle_call_tool("search_console_sites_get", {})
    client.get_site.assert_not_awaited()
