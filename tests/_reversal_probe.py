"""A fake plugin whose one tool a plugin-declared reversal can name (#863).

Not a test module (no ``test_`` prefix, so pytest does not collect it).

Shared by the planner tests and the ``mureo rollback`` CLI tests: install it
with ``tests._server_reload.reloaded_server(reversal_probe_discover)`` and the
server publishes :data:`REVERSAL_PROBE_TOOL` to the rollback planner's plugin
reversal registry, bounded to ``{"campaign_id"}``.
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry

#: The one tool the probe plugin serves; a plugin reversal names it.
REVERSAL_PROBE_TOOL = "reversal_probe_resume"

#: The forward action a reversal of :data:`REVERSAL_PROBE_TOOL` undoes.
REVERSAL_PROBE_ACTION = "reversal_probe_pause"


class _ReversalProbePlugin:
    name = "reversal_probe"
    display_name = "Reversal probe"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name=REVERSAL_PROBE_TOOL,
                description="resume",
                inputSchema={
                    "type": "object",
                    "properties": {"campaign_id": {"type": "string"}},
                },
            ),
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        return [TextContent(type="text", text="ok")]


def reversal_probe_discover(**_kw: Any) -> tuple[ProviderEntry, ...]:
    """Discovery that returns only the probe plugin."""
    return (
        ProviderEntry(
            name=_ReversalProbePlugin.name,
            display_name=_ReversalProbePlugin.display_name,
            capabilities=_ReversalProbePlugin.capabilities,
            provider_class=_ReversalProbePlugin,
            source_distribution="reversal-probe-dist",
        ),
    )
