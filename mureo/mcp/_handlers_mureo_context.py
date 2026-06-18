"""MCP handlers for mureo's STRATEGY.md / STATE.json surface.

These handlers expose the context layer as MCP tools so that hosts
without direct filesystem access (Claude Desktop chat, claude.ai web,
remote MCP connectors) can read and update mureo's strategic context.

All file paths are resolved against the **active workspace** —
``getattr(get_runtime_context().state_store, "workspace", Path.cwd())``
— and refused if they escape it. The active workspace is CWD by
default (preserving today's single-workspace behaviour), or whatever
filesystem-backed :class:`mureo.core.state_store.StateStore` an
alternate backend registers via the ``mureo.runtime_context_factory``
entry-point group.

The security guard is symmetric with the rollback surface's
``_resolve_state_file`` guard: a prompt-injected agent must not be
able to point mureo at an attacker-crafted file elsewhere on the
filesystem. ``Path.resolve()`` follows symlinks, so a STRATEGY.md
inside the workspace that symlinks to /etc/passwd resolves to the
target and is correctly refused.

Atomic write semantics come from ``mureo.context.state._atomic_write``
and the equivalent path in ``context.strategy``: write to a temp file
in the same directory, then ``os.replace`` over the target. A failure
mid-flight leaves the original intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.context.errors import ContextFileError
from mureo.context.models import ActionLogEntry, CampaignSnapshot, StateDocument
from mureo.context.state import (
    append_action_log,
    read_state_file,
    render_state,
    set_report,
    upsert_campaign,
)
from mureo.context.strategy import RAW_HEADING_TYPE, parse_strategy, write_strategy_file
from mureo.core.runtime_context import get_runtime_context
from mureo.fsutil import backup_file
from mureo.mcp._helpers import _json_result, _require

if TYPE_CHECKING:
    from mcp.types import TextContent


def _resolve_path(
    arguments: dict[str, Any], default_name: str, *, store_attr: str | None = None
) -> Path:
    """Resolve a user-supplied path, refusing anything outside the workspace.

    Resolution rules:

    - ``path`` argument missing or empty (``None`` or ``""``) → the
      workspace-derived default (``getattr(store, store_attr)`` when
      available, otherwise ``workspace / default_name``). Picks up
      any alternate :class:`StateStore` wired via the
      ``mureo.runtime_context_factory`` entry-point group without the
      caller having to know about it. Note: the empty-string case
      used to dispatch to ``Path(".")`` under the old ``_opt``-based
      implementation; the new behaviour is intentional and safer.
    - ``path`` argument present → resolved relative to the workspace
      (not the process CWD — they coincide in the default file-backed
      configuration but may diverge under an alternate runtime),
      then security-checked: ``Path.resolve()`` follows symlinks, so a
      file inside the workspace that symlinks to ``/etc/passwd``
      resolves to the target and is correctly refused.
    """
    store = get_runtime_context().state_store
    workspace = getattr(store, "workspace", Path.cwd()).resolve()
    raw = arguments.get("path")
    if not raw:
        if store_attr is not None:
            attr = getattr(store, store_attr, None)
            if attr is not None:
                # Backend-owned path: trusted output of an installed
                # ``StateStore`` (the entry-point factory is host code,
                # not an untrusted MCP caller). Skip the workspace
                # boundary check so a backend can legitimately point
                # outside ``workspace`` if its design requires it.
                return Path(attr)
        return workspace / default_name

    candidate = Path(raw)
    resolved = (
        workspace / candidate if not candidate.is_absolute() else candidate
    ).resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to read/write outside workspace: "
            f"{resolved} is not inside {workspace}"
        ) from exc
    return resolved


# ---------------------------------------------------------------------------
# STRATEGY.md
# ---------------------------------------------------------------------------


async def handle_strategy_get(arguments: dict[str, Any]) -> list[TextContent]:
    path = _resolve_path(arguments, "STRATEGY.md", store_attr="strategy_path")
    if not path.exists():
        return _json_result({"markdown": "", "exists": False, "path": str(path)})
    text = path.read_text(encoding="utf-8")
    return _json_result({"markdown": text, "exists": True, "path": str(path)})


async def handle_strategy_set(arguments: dict[str, Any]) -> list[TextContent]:
    markdown = _require(arguments, "markdown")
    # Refuse empty / whitespace-only content: a full-replacement write of it
    # would reduce STRATEGY.md to a bare "# Strategy", which a prompt-injected
    # agent could use to wipe the strategy (issue #276). ``_require`` already
    # rejects "" / None; this also catches whitespace-only payloads.
    if not markdown.strip():
        raise ValueError("markdown must not be empty or whitespace-only")
    path = _resolve_path(arguments, "STRATEGY.md", store_attr="strategy_path")
    # Round-trip through parse so callers can't write a STRATEGY.md
    # whose subsequent parse_strategy() call breaks downstream skills.
    # Unrecognized headings are preserved (raw passthrough), not dropped.
    entries = parse_strategy(markdown)
    # Keep a timestamped .bak before this full replacement so a bad
    # round-trip is recoverable.
    backup_file(path, timestamped=True)
    write_strategy_file(path, entries)
    rewritten = path.read_text(encoding="utf-8")
    unrecognized = sum(1 for e in entries if e.context_type == RAW_HEADING_TYPE)
    return _json_result(
        {
            "markdown": rewritten,
            "entries_count": len(entries),
            "unrecognized": unrecognized,
            "path": str(path),
        }
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
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
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
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
    doc = append_action_log(path, entry)
    return _json_result(_state_to_dict(doc))


async def handle_state_upsert_campaign(
    arguments: dict[str, Any],
) -> list[TextContent]:
    raw = _require(arguments, "campaign")
    if not isinstance(raw, dict):
        raise ValueError("campaign must be an object")
    # Platform context is required so the v2 ``platforms`` section (the
    # shape the dashboard reads) is always populated with the account id;
    # without it a per-account override is silently dropped and the
    # client renders as inactive.
    platform = _require(raw, "platform")
    account_id = _require(raw, "account_id")
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
        metrics=raw.get("metrics"),
    )
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
    try:
        doc = upsert_campaign(path, campaign, platform=platform, account_id=account_id)
    except ContextFileError as exc:
        # Surface as ValueError so the MCP dispatcher's standard error
        # path translates this into a clean tool-error response rather
        # than a 500-style server error.
        raise ValueError(str(exc)) from exc
    return _json_result(_state_to_dict(doc))


async def handle_state_report_set(
    arguments: dict[str, Any],
) -> list[TextContent]:
    report = _require(arguments, "report")
    summary = _require(arguments, "summary")
    # The free-form summary must be a JSON object so it round-trips into the
    # reports section and the dashboard can render it. Reject anything else
    # (string / list / number) before it reaches the file.
    if not isinstance(summary, dict):
        raise ValueError("summary must be an object")
    path = _resolve_path(arguments, "STATE.json", store_attr="state_path")
    doc = set_report(path, report, summary)
    return _json_result(_state_to_dict(doc))
