"""MCP tool exposing the analytics-module registry (Issue #120, Phase 2).

Workflow skills (``daily-check``, ``rescue``, …) need to know, from
inside the MCP host, which platforms have an analytics module
registered so they can honestly report unavailability for external
integrations that ship none.

A single read-only tool ``mureo_analytics_modules_list`` returns that
information. The handler is intentionally tiny: no parameters, no
network, no filesystem — just a snapshot of the in-process registry.

The tool is also routed through the standard analysis dispatcher so it
participates in the same handler-call audit path as other analysis
tools, with zero new ABI surface for plugins.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from mureo.analytics.protocol import AnalyticsCapability
from mureo.analytics.registry import (
    default_analytics_registry,
    discover_analytics_modules,
    plugin_source,
)

TOOLS: list[Tool] = [
    Tool(
        name="mureo_analytics_modules_list",
        description=(
            "List analytics modules registered for each integrated "
            "platform. Returns one entry per platform with its "
            "advertised capabilities (detect_anomalies, "
            "diagnose_performance, audit_creative, "
            "analyze_budget_efficiency). Workflow skills consult this "
            "to decide whether to run deep analytics for a platform or "
            "honestly report `analytics_not_available_for_<platform>`. "
            "Built-in (google_ads, meta_ads) and plugin-supplied "
            "modules appear in the same shape."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def _handle_modules_list(
    _arguments: dict[str, Any],
) -> list[TextContent]:
    """Return registered analytics modules as JSON text."""
    # Trigger entry-point discovery (idempotent, cached).
    discover_analytics_modules()

    registry = default_analytics_registry()
    all_capabilities = sorted(c.value for c in AnalyticsCapability)
    payload: list[dict[str, Any]] = []
    for platform in registry.platforms():
        module = registry.get(platform)
        if module is None:  # pragma: no cover — defensive
            continue
        caps = module.capabilities()
        payload.append(
            {
                "platform": platform,
                "capabilities": sorted(c.value for c in caps),
                "source_distribution": plugin_source(module),
                "all_capabilities": all_capabilities,
            }
        )

    return [TextContent(type="text", text=json.dumps({"modules": payload}))]


_HANDLERS = {
    "mureo_analytics_modules_list": _handle_modules_list,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch an analytics-registry tool call."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


__all__ = ["TOOLS", "handle_tool"]
