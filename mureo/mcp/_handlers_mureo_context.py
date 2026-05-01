"""MCP handlers for mureo's STRATEGY.md / STATE.json surface.

These handlers expose the context layer as MCP tools so that hosts
without direct filesystem access (Claude Desktop chat, claude.ai web,
remote MCP connectors) can read and update mureo's strategic context.

All file paths are resolved against the MCP server's current working
directory and refused if they escape it — symmetric with the rollback
surface's ``_resolve_state_file`` guard. A prompt-injected agent must
not be able to point mureo at an attacker-crafted file elsewhere on
the filesystem.

Atomic write semantics come from ``mureo.context.state._atomic_write``
and the equivalent path in ``context.strategy``: write to a temp file
in the same directory, then ``os.replace`` over the target. A failure
mid-flight leaves the original intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    StateDocument,
)
from mureo.context.state import (
    append_action_log,
    read_state_file,
    render_state,
    upsert_campaign,
)
from mureo.context.strategy import (
    parse_strategy,
    write_strategy_file,
)
from mureo.mcp._helpers import _json_result, _opt, _require

if TYPE_CHECKING:
    from mcp.types import TextContent


def _resolve_path(arguments: dict[str, Any], default_name: str) -> Path:
    """Resolve a user-supplied path, refusing anything outside cwd.

    The MCP caller is untrusted (a prompt-injected agent could point at
    an attacker-crafted file elsewhere on the filesystem). We require
    the argument to resolve to a path inside the current working
    directory so the agent cannot smuggle in a rogue STRATEGY.md or
    STATE.json. ``Path.resolve()`` follows symlinks, so a STRATEGY.md
    inside cwd that symlinks to /etc/passwd resolves to the target and
    is correctly refused. Mirrors ``_handlers_rollback._resolve_state_file``.
    """
    raw = _opt(arguments, "path", default_name)
    candidate = Path(raw)
    cwd = Path.cwd().resolve()
    resolved = (cwd / candidate if not candidate.is_absolute() else candidate).resolve()
    try:
        resolved.relative_to(cwd)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to read/write outside cwd: {resolved} is not inside {cwd}"
        ) from exc
    return resolved


# ---------------------------------------------------------------------------
# STRATEGY.md
# ---------------------------------------------------------------------------


async def handle_strategy_get(arguments: dict[str, Any]) -> list[TextContent]:
    path = _resolve_path(arguments, "STRATEGY.md")
    if not path.exists():
        return _json_result({"markdown": "", "exists": False, "path": str(path)})
    text = path.read_text(encoding="utf-8")
    return _json_result({"markdown": text, "exists": True, "path": str(path)})


async def handle_strategy_set(arguments: dict[str, Any]) -> list[TextContent]:
    markdown = _require(arguments, "markdown")
    path = _resolve_path(arguments, "STRATEGY.md")
    # Round-trip through parse so callers can't write a STRATEGY.md
    # whose subsequent parse_strategy() call breaks downstream skills.
    entries = parse_strategy(markdown)
    write_strategy_file(path, entries)
    rewritten = path.read_text(encoding="utf-8")
    return _json_result(
        {"markdown": rewritten, "entries_count": len(entries), "path": str(path)}
    )


# ---------------------------------------------------------------------------
# STATE.json
# ---------------------------------------------------------------------------


def _state_to_dict(doc: StateDocument) -> dict[str, Any]:
    """Serialize a StateDocument back to the dict shape callers expect."""
    import json as _json

    parsed: dict[str, Any] = _json.loads(render_state(doc))
    return parsed


async def handle_state_get(arguments: dict[str, Any]) -> list[TextContent]:
    path = _resolve_path(arguments, "STATE.json")
    # read_state_file already returns an empty default StateDocument when
    # the file is absent; round-trip through render_state to keep the
    # missing-file and present-file branches in lockstep.
    doc = read_state_file(path)
    return _json_result(_state_to_dict(doc))


async def handle_state_action_log_append(
    arguments: dict[str, Any],
) -> list[TextContent]:
    raw = _require(arguments, "entry")
    if not isinstance(raw, dict):
        raise ValueError("entry must be an object")
    # Required per ActionLogEntry contract.
    timestamp = _require(raw, "timestamp")
    action = _require(raw, "action")
    platform = _require(raw, "platform")
    entry = ActionLogEntry(
        timestamp=timestamp,
        action=action,
        platform=platform,
        campaign_id=raw.get("campaign_id"),
        summary=raw.get("summary"),
        command=raw.get("command"),
        metrics_at_action=raw.get("metrics_at_action"),
        observation_due=raw.get("observation_due"),
        reversible_params=raw.get("reversible_params"),
        rollback_of=raw.get("rollback_of"),
    )
    path = _resolve_path(arguments, "STATE.json")
    doc = append_action_log(path, entry)
    return _json_result(_state_to_dict(doc))


async def handle_state_upsert_campaign(
    arguments: dict[str, Any],
) -> list[TextContent]:
    raw = _require(arguments, "campaign")
    if not isinstance(raw, dict):
        raise ValueError("campaign must be an object")
    device_targeting = (
        tuple(raw["device_targeting"]) if raw.get("device_targeting") else None
    )
    campaign = CampaignSnapshot(
        campaign_id=_require(raw, "campaign_id"),
        campaign_name=_require(raw, "campaign_name"),
        status=_require(raw, "status"),
        bidding_strategy_type=raw.get("bidding_strategy_type"),
        bidding_details=raw.get("bidding_details"),
        daily_budget=raw.get("daily_budget"),
        device_targeting=device_targeting,
        campaign_goal=raw.get("campaign_goal"),
        notes=raw.get("notes"),
    )
    path = _resolve_path(arguments, "STATE.json")
    try:
        doc = upsert_campaign(path, campaign)
    except ContextFileError as exc:
        # Surface as ValueError so the MCP dispatcher's standard error
        # path translates this into a clean tool-error response rather
        # than a 500-style server error.
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))
