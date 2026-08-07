"""Shared plumbing for the CSV-backed BYOD clients.

Split out of :mod:`mureo.byod.clients` (#546) so neither client module
carries the other's weight: CSV coercion, the date helpers, the
read-only mutation guard, and the day-grain delivery projection are used
by both and belong to neither.

Every name here is re-exported from :mod:`mureo.byod.clients`, which
stays the public import path.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from mureo.analysis.delivery_collapse import fill_missing_delivery_days

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_int(v: Any, default: int = 0) -> int:
    # Tolerate float-formatted strings like "98.0" emitted by the Google
    # Ads Apps Script bundle (and by Sheets exports in general). The
    # strict ``int()`` parser raises on the dot, which used to silently
    # zero out impressions/clicks for Google Ads BYOD — breaking CTR,
    # CPC, and search-term diagnostics downstream even though the CSV
    # itself was complete.
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_date(v: str) -> date | None:
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _max_date(rows: list[dict[str, Any]], key: str = "date") -> date | None:
    """Latest parseable ``key`` value across ``rows`` (``None`` if none)."""
    best: date | None = None
    for r in rows:
        d = _parse_date(r.get(key, ""))
        if d is not None and (best is None or d > best):
            best = d
    return best


#: Mirrors the live clients' default collapse-detection window.
_DAILY_DELIVERY_DEFAULT_DAYS = 60


def _byod_delivery_rows(
    metrics: list[dict[str, Any]],
    campaigns: list[dict[str, Any]],
    *,
    days: int,
    name_key: str,
) -> list[dict[str, Any]]:
    """Shared day-grain delivery projection for both BYOD clients (#546).

    The window is anchored on the BUNDLE's own latest date, not on wall
    clock: a bundle imported last month must keep returning its most
    recent ``days`` rather than going silently empty — the same rebasing
    ``_period_to_range`` does.
    """
    anchor = _max_date(metrics)
    if anchor is None:
        return []
    start = anchor - timedelta(days=max(1, days))
    attributes = {
        str(c.get("campaign_id")): (
            str(c.get(name_key, "") or ""),
            str(c.get("status", "") or ""),
        )
        for c in campaigns
    }
    out: list[dict[str, Any]] = []
    for row in metrics:
        day = _parse_date(row.get("date", ""))
        campaign_id = str(row.get("campaign_id") or "")
        if day is None or day < start or day > anchor or campaign_id not in attributes:
            continue
        name, status = attributes[campaign_id]
        out.append(
            {
                "campaign_id": campaign_id,
                "campaign_name": name,
                "status": status,
                "end_date": "",
                "date": day.isoformat(),
                "impressions": _to_int(row.get("impressions")),
                "clicks": _to_int(row.get("clicks")),
                "cost": _to_float(row.get("cost_jpy")),
            }
        )
    # A bundle can omit a campaign's zero-delivery days just as the live
    # APIs do — the exporter only writes the rows it was given. The
    # bundle's own last date is inferred from the rows (a bundle cannot
    # be "behind" on itself), so no explicit bound is passed.
    return fill_missing_delivery_days(out)


def _period_to_range(period: str, *, anchor: date | None = None) -> tuple[date, date]:
    """Resolve a relative ``period`` to a concrete ``(start, end)``.

    ``anchor=None`` preserves the legacy wall-clock behaviour (windows
    end *yesterday* relative to ``date.today()``) — unchanged for any
    caller that does not opt in.

    When ``anchor`` is given (the BYOD/demo dataset's own latest date),
    the window is rebased to END at ``anchor`` with the same span, so a
    fixed historical demo dataset keeps returning its most-recent N days
    no matter how far wall-clock time has drifted past it. ``YESTERDAY``
    / ``TODAY`` collapse to the anchor day itself (the latest data we
    have). This is what stops the demo silently going empty over time.
    """
    if anchor is None:
        today = date.today()
        if period == "LAST_14_DAYS":
            return today - timedelta(days=14), today - timedelta(days=1)
        if period == "LAST_30_DAYS":
            return today - timedelta(days=30), today - timedelta(days=1)
        if period == "YESTERDAY":
            d = today - timedelta(days=1)
            return d, d
        if period == "TODAY":
            return today, today
        # LAST_7_DAYS and the default fall-through.
        return today - timedelta(days=7), today - timedelta(days=1)

    span = {
        "LAST_7_DAYS": 7,
        "LAST_14_DAYS": 14,
        "LAST_30_DAYS": 30,
    }.get(period)
    if span is not None:
        return anchor - timedelta(days=span - 1), anchor
    if period in ("YESTERDAY", "TODAY"):
        return anchor, anchor
    return anchor - timedelta(days=6), anchor  # default: last 7 days


# Verb prefixes that should never silently no-op in BYOD mode.
# Anything matching one of these returns ``skipped_in_byod_readonly``
# instead of an empty list, so a curious agent never mistakes a mutation
# for a successful call.
_MUTATION_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "send_",
    "upload_",
    "pause_",
    "resume_",
    "enable_",
    "disable_",
    "apply_",
    "publish_",
    "submit_",
    "attach_",
    "detach_",
    "approve_",
    "reject_",
    "cancel_",
    "set_",
    "patch_",
    # Meta-specific mutation verbs whose method names do not match any
    # of the generic prefixes above: boost_post / boost_instagram_post,
    # end_split_test, duplicate_lead_form, and export_leads_to_csv (the
    # last writes a local file only, but is still a state-producing
    # operation that must not silently no-op as an empty read).
    "boost_",
    "end_",
    "duplicate_",
    "export_",
)


def _async_empty_list() -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> list[Any]:
        return []

    return _stub


def _async_byod_blocked(name: str) -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "status": "skipped_in_byod_readonly",
            "operation": name,
            "note": (
                "BYOD mode is analysis-only. "
                "This call would have written to a real ad account."
            ),
        }

    return _stub
