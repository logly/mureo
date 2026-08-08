"""MCP handler for ``mureo_external_changes_import`` (#545).

Turns the core importer into one tool call a workflow skill can make.
``/daily-check`` runs it before it diffs anything, so a change an operator
made in a platform's UI is a recorded fact by the time the report is written
rather than an unexplained movement in the numbers.

The response is shaped around the question the operator actually has, which
is not "how many changes were imported". It is *what did mureo look at, and
where is it still blind* — so every configured platform appears in the
response, including the ones with no change feed, and the ``blind_spots``
list names them explicitly. A platform that is not polled must never be
absent from the answer; absence reads as "fine".

Path resolution uses the shared
:func:`mureo.mcp._helpers.resolve_workspace_path`. It is a security boundary
— an MCP caller must not be able to point this at a STATE.json outside the
active workspace — and a second copy of that check is a place for the two to
drift apart silently.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mureo.change_import import (
    ChangeImportStatus,
    import_external_changes,
    list_change_feed_platforms,
)
from mureo.core.clock import server_now_iso
from mureo.mcp._helpers import _json_result, resolve_workspace_path

if TYPE_CHECKING:
    from mcp.types import TextContent

    from mureo.change_import import ChangeImportOutcome


def _parse_since(raw: Any) -> datetime | None:
    """Validate a caller-supplied ``since``, or ``None`` when omitted.

    Rejected rather than coerced: a value mureo cannot parse would silently
    fall back to the default lookback, and the caller would read the result
    as covering the window they asked for.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("since must be an ISO 8601 date or datetime string")
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ValueError(
            f"since must be an ISO 8601 date or datetime string; got {raw!r}"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_platforms(raw: Any) -> list[str] | None:
    """Validate the optional platform filter."""
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ValueError("platforms must be an array of platform key strings")
    cleaned = [p.strip() for p in raw if p.strip()]
    if not cleaned:
        raise ValueError("platforms must name at least one platform key")
    return cleaned


def _outcome_to_dict(outcome: ChangeImportOutcome) -> dict[str, Any]:
    """Serialize one platform's outcome."""
    payload: dict[str, Any] = {
        "platform": outcome.platform,
        "status": outcome.status.value,
        "imported_indices": list(outcome.imported),
        "imported": len(outcome.imported),
        "already_imported": outcome.already_imported,
        "attributed_to_mureo": outcome.attributed_to_mureo,
        "since": outcome.since,
        "until": outcome.until,
        "truncated": outcome.truncated,
        "notes": list(outcome.notes),
    }
    if outcome.reason:
        payload["reason"] = outcome.reason
    return payload


async def handle_external_changes_import(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Poll every configured platform's change feed and record what is new."""
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    since = _parse_since(arguments.get("since"))
    platforms = _parse_platforms(arguments.get("platforms"))

    outcomes = await import_external_changes(path, platforms=platforms, since=since)
    # Named separately from the per-platform list because a reader scanning
    # the response for a verdict must not have to notice the ABSENCE of a
    # platform, or the difference between UNAVAILABLE and a quiet feed.
    blind_spots = [
        o.platform
        for o in outcomes
        if o.status in (ChangeImportStatus.UNAVAILABLE, ChangeImportStatus.ERROR)
    ]
    return _json_result(
        {
            "server_now": server_now_iso(),
            "platforms": [_outcome_to_dict(o) for o in outcomes],
            "imported_total": sum(len(o.imported) for o in outcomes),
            "blind_spots": blind_spots,
            "truncated_platforms": [o.platform for o in outcomes if o.truncated],
            "feeds_available_for": list(list_change_feed_platforms()),
        }
    )


__all__ = ["handle_external_changes_import"]
