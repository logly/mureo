"""Reloading ``mureo.mcp.server`` must not leak a fake plugin (#760).

Plugin-wiring tests patch ``registry.discover_providers``, reload
``mureo.mcp.server`` so the fake provider is collected, and then "restore"
the module with a second reload. Done with ``monkeypatch``, that second
reload runs while the patch is STILL ACTIVE — ``monkeypatch`` undoes its
patches at fixture teardown, i.e. after the test body and after any fixture
that requested it. The restoring reload therefore re-collects the fake
plugin into ``_ALL_TOOLS`` / ``_PLUGIN_NAMES`` / ``_PLUGIN_DISPATCH``, where
it stays for every later test module that imports ``server`` without
reloading it. ``tests/_server_reload.reloaded_server`` closes that hole by
undoing the patches BEFORE the restoring reload.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from mcp.types import TextContent, Tool

from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry
from tests._server_reload import DISCOVER_TARGET, reloaded_server

pytestmark = pytest.mark.unit

_FAKE_TOOL = "hygiene_probe_echo"


class _HygieneProbePlugin:
    name = "hygiene_probe"
    display_name = "Hygiene probe"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name=_FAKE_TOOL,
                description="echo",
                inputSchema={"type": "object", "properties": {}},
            ),
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        return [TextContent(type="text", text="ok")]


def _fake_discover(**_kw: Any) -> tuple[ProviderEntry, ...]:
    return (
        ProviderEntry(
            name=_HygieneProbePlugin.name,
            display_name=_HygieneProbePlugin.display_name,
            capabilities=_HygieneProbePlugin.capabilities,
            provider_class=_HygieneProbePlugin,
            source_distribution="hygiene-dist",
        ),
    )


def _live_tool_names() -> set[str]:
    """Tool names the imported server module is serving RIGHT NOW."""
    from mureo.mcp import server as mod

    return {t.name for t in mod._ALL_TOOLS}


def _server_tool_names() -> set[str]:
    """Reload ``mureo.mcp.server`` with no patches active and read its tools."""
    from mureo.mcp import server as mod

    mod = importlib.reload(mod)
    return {t.name for t in mod._ALL_TOOLS}


def test_a_monkeypatched_discovery_reload_leaks_without_the_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHARACTERISATION, not a regression guard.

    It pins the failure mode #760 is about: with the old
    ``monkeypatch`` + reload + reload shape, the restoring reload happens
    under the still-active patch, so the fake tool survives it. Asserting
    that the leak IS present is the point — do not "fix" this test if the
    helper changes; the guard below is what must stay green.
    """
    monkeypatch.setattr(DISCOVER_TARGET, _fake_discover)
    from mureo.mcp import server as mod

    mod = importlib.reload(mod)
    assert _FAKE_TOOL in _live_tool_names()

    importlib.reload(mod)  # the old "restore" — still under the patch
    monkeypatch.undo()  # what fixture teardown would do, one step too late
    assert _FAKE_TOOL in _live_tool_names(), "the leak this issue is about"

    # A third reload, now genuinely unpatched, is what it took to clean up.
    assert _FAKE_TOOL not in _server_tool_names()


def test_reloaded_server_restores_discovery_before_the_restoring_reload() -> None:
    """REGRESSION GUARD for #760: no extra reload needed after the block."""
    with reloaded_server(_fake_discover) as mod:
        assert _FAKE_TOOL in {t.name for t in mod._ALL_TOOLS}
        assert _FAKE_TOOL in mod._PLUGIN_NAMES

    from mureo.mcp import server as live

    assert _FAKE_TOOL not in _live_tool_names()
    assert _FAKE_TOOL not in live._PLUGIN_NAMES
    assert _FAKE_TOOL not in live._PLUGIN_DISPATCH


def test_the_live_server_module_matches_a_clean_reload() -> None:
    """Whatever ran before this module must have left ``server`` clean.

    Order-independent by construction: it compares the live module against a
    freshly reloaded one rather than against a hard-coded set, so a genuinely
    installed third-party provider is present in both and never fails it.
    Collected alphabetically, this module runs after every plugin-wiring file
    named in #760, so a leak from any of them shows up here.
    """
    live = _live_tool_names()

    assert live == _server_tool_names()
