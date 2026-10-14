"""The ``decisions`` and ``ops_history`` sources of ``mureo_history_query`` (#848).

Both answer from the same join :mod:`mureo.context.ops_history_view` builds
for the dashboard: one item per decision with the changes that carried it
out and their evaluation. ``ops_history`` also includes the changes no
decision covers (``decision`` ``None``); ``decisions`` is only the items
that have one. An agent reads them to learn how its earlier decisions
turned out before it proposes the next one.

``since`` / ``until`` bound an item by the date of its timestamp exactly
as they bound an ``action_log`` entry, through
:func:`mureo.context.ops_history_query.ops_history_items`, which the
dashboard feed reads too.

Kept out of :mod:`mureo.mcp._handlers_history`, which is near the repo's
file-size limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.context.ops_history_query import ops_history_items
from mureo.context.state import read_state_file
from mureo.core import clock

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.mcp._handlers_history import HistoryQuery


def _values(item: dict[str, Any], key: str) -> set[Any]:
    """``key`` on the decision and on every action of one item."""
    found = {action.get(key) for action in item["actions"]}
    if item["decision"] is not None:
        found.add(item["decision"].get(key))
    return found


def _matches(item: dict[str, Any], query: HistoryQuery) -> bool:
    for key in ("platform", "campaign_id", "batch_id"):
        wanted = getattr(query, key)
        if wanted is not None and wanted not in _values(item, key):
            return False
    if query.entity_type is None:
        return True
    pairs = {(a.get("entity_type"), a.get("entity_id")) for a in item["actions"]}
    if item["decision"] is not None:
        decision = item["decision"]
        pairs.add((decision.get("entity_type"), decision.get("entity_id")))
    return (query.entity_type, query.entity_id) in pairs


def _section(path: Path, query: HistoryQuery, *, decided_only: bool) -> dict[str, Any]:
    items = ops_history_items(
        read_state_file(path, strict=False),
        today=clock.server_now().date(),
        since=query.since,
        until=query.until,
    )
    matched = [
        item
        for item in items
        if _matches(item, query) and (item["decision"] is not None or not decided_only)
    ]
    returned = matched[: query.limit]
    section: dict[str, Any] = {
        "items": returned,
        "matched": len(matched),
        "returned": len(returned),
        "truncated": len(matched) > query.limit,
    }
    if not path.exists():
        section["state"] = "missing"
    return section


def ops_history_section(path: Path, query: HistoryQuery) -> dict[str, Any]:
    """Every item, newest first, including changes no decision covers."""
    return _section(path, query, decided_only=False)


def decisions_section(path: Path, query: HistoryQuery) -> dict[str, Any]:
    """Only the items that have a decision, newest first."""
    return _section(path, query, decided_only=True)


__all__ = ["decisions_section", "ops_history_section"]
