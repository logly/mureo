"""MCP dispatch-layer JSON Schema validation (issue #277).

The MCP framework does not enforce a tool's ``inputSchema``, so declared
bounds (``minimum``, ``required``, ``type``) are advisory until checked
server-side. ``mureo.mcp.server._validate_tool_input`` is the single guard
that makes them real before any handler / real-spend API call runs.
"""

from __future__ import annotations

import pytest

from mureo.mcp.server import (
    _TOOL_VALIDATORS,
    _validate_tool_input,
    handle_call_tool,
)

pytestmark = pytest.mark.unit

_BUDGET_TOOL = "google_ads_budget_update"
_budget_registered = pytest.mark.skipif(
    _BUDGET_TOOL not in _TOOL_VALIDATORS,
    reason="google_ads tools disabled in this environment",
)


def test_unknown_tool_is_noop() -> None:
    """A tool with no registered validator (unknown name, or a tool with no
    schema) is skipped."""
    _validate_tool_input("definitely_not_a_registered_tool", {"x": 1})


def test_plugin_tools_are_validated() -> None:
    """Guardrail parity (#114 follow-up): a plugin tool that declares a valid
    ``inputSchema`` is compiled into the validator map too, so its declared
    bounds are enforced server-side exactly like a built-in. (Previously
    ``_PLUGIN_NAMES`` were intentionally excluded — that exclusion is removed.)

    Exercised with a synthetic plugin so the assertion does not depend on
    which third-party providers happen to be installed in the environment.
    """
    import importlib
    from typing import Any

    from mcp.types import TextContent, Tool

    from mureo.core.providers.capabilities import Capability
    from mureo.core.providers.registry import ProviderEntry

    class _SchemaPlugin:
        name = "iv_schema_plugin"
        display_name = "IV"
        capabilities = frozenset({Capability.READ_CAMPAIGNS})

        def mcp_tools(self) -> tuple[Tool, ...]:
            return (
                Tool(
                    name="iv_schema_plugin_spend",
                    description="x",
                    inputSchema={
                        "type": "object",
                        "properties": {"budget": {"type": "integer", "minimum": 1}},
                        "required": ["budget"],
                    },
                ),
            )

        async def handle_mcp_tool(
            self, name: str, arguments: dict[str, Any]
        ) -> list[Any]:
            return [TextContent(type="text", text="ok")]

    def _disc(**_kw: Any) -> tuple[ProviderEntry, ...]:
        return (
            ProviderEntry(
                name=_SchemaPlugin.name,
                display_name=_SchemaPlugin.display_name,
                capabilities=_SchemaPlugin.capabilities,
                provider_class=_SchemaPlugin,
                source_distribution="iv-dist",
            ),
        )

    import mureo.core.providers.registry as registry
    from mureo.mcp import server as mod

    original = registry.discover_providers
    registry.discover_providers = _disc
    try:
        mod = importlib.reload(mod)
        assert "iv_schema_plugin_spend" in mod._PLUGIN_NAMES
        assert "iv_schema_plugin_spend" in mod._TOOL_VALIDATORS
    finally:
        registry.discover_providers = original
        importlib.reload(mod)


@_budget_registered
class TestBudgetUpdateSchema:
    def test_rejects_amount_below_minimum(self) -> None:
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(_BUDGET_TOOL, {"budget_id": "1", "amount": 0})

    def test_rejects_negative_amount(self) -> None:
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(_BUDGET_TOOL, {"budget_id": "1", "amount": -5})

    def test_requires_amount_or_amount_micros(self) -> None:
        with pytest.raises(ValueError, match="Invalid arguments"):
            _validate_tool_input(_BUDGET_TOOL, {"budget_id": "1"})

    def test_accepts_valid_amount(self) -> None:
        _validate_tool_input(_BUDGET_TOOL, {"budget_id": "1", "amount": 5000})

    def test_accepts_amount_micros(self) -> None:
        _validate_tool_input(
            _BUDGET_TOOL, {"budget_id": "1", "amount_micros": 5_000_000}
        )

    async def test_dispatch_rejects_before_handler(self) -> None:
        """An out-of-bounds budget is refused at dispatch — no creds touched."""
        with pytest.raises(ValueError, match="Invalid arguments"):
            await handle_call_tool(_BUDGET_TOOL, {"budget_id": "1", "amount": 0})
