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
    """A tool with no registered validator (plugins, unknown) is skipped."""
    _validate_tool_input("definitely_not_a_registered_tool", {"x": 1})


def test_plugin_tools_are_not_validated() -> None:
    """Plugin tool names must be excluded from the built-in validator map."""
    from mureo.mcp.server import _PLUGIN_NAMES

    assert _PLUGIN_NAMES.isdisjoint(_TOOL_VALIDATORS)


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
