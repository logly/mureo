"""mureo's STRATEGY.md / STATE.json MCP tool surface.

Five tools that expose mureo's context layer over MCP, so any MCP host
(Claude Desktop chat, claude.ai web, Codex/Cursor, …) can read and
update STRATEGY.md / STATE.json without direct filesystem access.

The Claude Code path keeps working through its built-in ``Read`` tool;
these MCP tools are additive — they unlock the same capability for
hosts that lack ``Read``. Workflow skills can be migrated to call
these tools (Phase 2/3) so a single skill prompt runs everywhere.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.types import Tool

from mureo.mcp._handlers_mureo_context import (
    handle_state_action_log_append,
    handle_state_get,
    handle_state_upsert_campaign,
    handle_strategy_get,
    handle_strategy_set,
)

if TYPE_CHECKING:
    from mcp.types import TextContent


_PATH_PROPERTY = {
    "type": "string",
    "description": (
        "Optional path to the file. Defaults to STRATEGY.md / STATE.json "
        "in the MCP server's current working directory. Paths outside "
        "cwd are refused."
    ),
}


_ACTION_LOG_ENTRY_PROPERTY = {
    "type": "object",
    "description": (
        "An action_log entry. Required: timestamp (ISO 8601), action "
        "(short description), platform (google_ads / meta_ads / etc.). "
        "Optional: campaign_id, summary, command, metrics_at_action, "
        "observation_due, reversible_params, rollback_of."
    ),
    "properties": {
        "timestamp": {"type": "string"},
        "action": {"type": "string"},
        "platform": {"type": "string"},
        "campaign_id": {"type": "string"},
        "summary": {"type": "string"},
        "command": {"type": "string"},
        "metrics_at_action": {"type": "object"},
        "observation_due": {"type": "string"},
        "reversible_params": {"type": "object"},
        "rollback_of": {"type": "integer"},
    },
    "required": ["timestamp", "action", "platform"],
}


_CAMPAIGN_PROPERTY = {
    "type": "object",
    "description": (
        "A CampaignSnapshot for STATE.json. Required: campaign_id, "
        "campaign_name, status. Optional fields mirror the snapshot "
        "schema in docs/strategy-context.md."
    ),
    "properties": {
        "campaign_id": {"type": "string"},
        "campaign_name": {"type": "string"},
        "status": {"type": "string"},
        "bidding_strategy_type": {"type": "string"},
        "bidding_details": {"type": "object"},
        "daily_budget": {"type": "number"},
        "device_targeting": {"type": "array"},
        "campaign_goal": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["campaign_id", "campaign_name", "status"],
}


TOOLS: list[Tool] = [
    Tool(
        name="mureo_strategy_get",
        description=(
            "Read STRATEGY.md and return its raw markdown text plus an "
            "exists flag. Returns empty markdown when the file is "
            "absent (skills should treat that as 'no strategy yet', "
            "not as an error). Use this when the host has no direct "
            "filesystem access (Claude Desktop chat, web, remote MCP)."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
        },
    ),
    Tool(
        name="mureo_strategy_set",
        description=(
            "Atomically replace STRATEGY.md with the provided markdown. "
            "The content is parsed via parse_strategy() before writing "
            "to ensure it is well-formed; a malformed input raises "
            "rather than corrupts the file. Use this to update goals, "
            "constraints, or operation mode from a chat-only host."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "markdown": {
                    "type": "string",
                    "description": "The full new content of STRATEGY.md.",
                },
                "path": _PATH_PROPERTY,
            },
            "required": ["markdown"],
        },
    ),
    Tool(
        name="mureo_state_get",
        description=(
            "Read STATE.json and return its parsed v2 document: "
            "version, last_synced_at, platforms (per-platform "
            "campaigns), legacy v1 campaigns, and action_log. Returns "
            "an empty default doc when the file is absent."
        ),
        inputSchema={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
        },
    ),
    Tool(
        name="mureo_state_action_log_append",
        description=(
            "Atomically append a single action_log entry to STATE.json. "
            "Use this whenever a workflow takes an action that should "
            "be evaluable later (budget changes, campaign pauses, "
            "negative-keyword adds). Returns the updated state document."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entry": _ACTION_LOG_ENTRY_PROPERTY,
                "path": _PATH_PROPERTY,
            },
            "required": ["entry"],
        },
    ),
    Tool(
        name="mureo_state_upsert_campaign",
        description=(
            "Atomically upsert a CampaignSnapshot into STATE.json (root "
            "campaigns array). Use this to keep STATE.json in sync with "
            "campaign metadata changes the agent observes via vendor "
            "MCPs or BYOD imports."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "campaign": _CAMPAIGN_PROPERTY,
                "path": _PATH_PROPERTY,
            },
            "required": ["campaign"],
        },
    ),
]


_HANDLERS = {
    "mureo_strategy_get": handle_strategy_get,
    "mureo_strategy_set": handle_strategy_set,
    "mureo_state_get": handle_state_get,
    "mureo_state_action_log_append": handle_state_action_log_append,
    "mureo_state_upsert_campaign": handle_state_upsert_campaign,
}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool call to its handler.

    Raises:
        ValueError: when the tool name is unknown or required parameters
            are missing.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)
