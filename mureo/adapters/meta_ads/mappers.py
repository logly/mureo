"""Pure ``dict`` → frozen-dataclass converters for the Meta Ads adapter.

Every function in this module is side-effect-free: it consumes the raw
``dict`` / ``list[dict]`` returned by ``MetaAdsApiClient`` mixins and
returns a frozen dataclass from :mod:`mureo.core.providers.models`.

Module foundation rule
----------------------
Imports are restricted to stdlib plus
:mod:`mureo.core.providers.models` /
:mod:`mureo.core.providers.capabilities`. No ``mureo.meta_ads.*`` import
— the mapper is intentionally decoupled from the heavyweight client
package so it can be exercised in isolation.

Phase 1 conversions
-------------------
- Budget: Meta returns ``daily_budget`` as a **cents** string; this
  mapper converts to **micros** (``int(cents) * 10_000``).
- Spend: Meta returns ``spend`` as a **dollars** string; this mapper
  converts to **micros** (``int(round(float(s) * 1_000_000))``).
- Status: Meta wire-strings (``ACTIVE`` / ``PAUSED`` / ``DELETED`` /
  ``ARCHIVED`` / ``CAMPAIGN_PAUSED`` / ``ADSET_PAUSED``) map to the
  canonical ``CampaignStatus`` / ``AdStatus`` enum members.
- Unknown / unparseable values raise :class:`ValueError` — no silent
  fallback to a default member.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Audience,
    AudienceStatus,
    Campaign,
    CampaignStatus,
    DailyReportRow,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


# ---------------------------------------------------------------------------
# Status mapping (Meta wire-string → canonical enum)
# ---------------------------------------------------------------------------


_CAMPAIGN_STATUS_MAP: dict[str, CampaignStatus] = {
    "ACTIVE": CampaignStatus.ENABLED,
    "PAUSED": CampaignStatus.PAUSED,
    "CAMPAIGN_PAUSED": CampaignStatus.PAUSED,
    "ADSET_PAUSED": CampaignStatus.PAUSED,
    "DELETED": CampaignStatus.REMOVED,
    "ARCHIVED": CampaignStatus.REMOVED,
}


_AD_STATUS_MAP: dict[str, AdStatus] = {
    "ACTIVE": AdStatus.ENABLED,
    "PAUSED": AdStatus.PAUSED,
    "CAMPAIGN_PAUSED": AdStatus.PAUSED,
    "ADSET_PAUSED": AdStatus.PAUSED,
    "DELETED": AdStatus.REMOVED,
    "ARCHIVED": AdStatus.REMOVED,
}


# Conversion-like Meta action_types (Phase 1). The full Meta catalogue
# is enormous; Phase 1 recognises the most common purchase-style event
# and treats it as the canonical ``conversions`` source. A future
# refactor can broaden this (lead, complete_registration, etc.).
_CONVERSION_ACTION_TYPES: frozenset[str] = frozenset({"purchase"})


def map_campaign_status(meta_wire: Any) -> CampaignStatus:
    """Return the canonical :class:`CampaignStatus` for ``meta_wire``.

    Raises:
        ValueError: ``meta_wire`` is ``None`` or not a known Meta value.
            The error message embeds the offending value for debuggability.
    """
    if meta_wire is None:
        raise ValueError("missing campaign status (got None)")
    key = str(meta_wire).upper()
    try:
        return _CAMPAIGN_STATUS_MAP[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown campaign status: {meta_wire!r} "
            f"(expected one of {sorted(_CAMPAIGN_STATUS_MAP)})"
        ) from exc


def map_ad_status(meta_wire: Any) -> AdStatus:
    """Return the canonical :class:`AdStatus` for ``meta_wire``.

    Raises:
        ValueError: ``meta_wire`` is ``None`` or not a known Meta value.
    """
    if meta_wire is None:
        raise ValueError("missing ad status (got None)")
    key = str(meta_wire).upper()
    try:
        return _AD_STATUS_MAP[key]
    except KeyError as exc:
        raise ValueError(
            f"unknown ad status: {meta_wire!r} "
            f"(expected one of {sorted(_AD_STATUS_MAP)})"
        ) from exc


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------


def to_campaign(raw: dict[str, Any], *, account_id: str) -> Campaign:
    """Build a :class:`Campaign` from a Meta campaign row.

    ``daily_budget`` is returned by Meta as a cents-denominated string
    (e.g. ``"1500"`` for 15.00 USD). This mapper converts to micros via
    ``int(cents) * 10_000`` — exact integer arithmetic, no float
    round-trip.
    """
    return Campaign(
        id=str(raw["id"]),
        account_id=account_id,
        name=str(raw["name"]),
        status=map_campaign_status(raw.get("status")),
        daily_budget_micros=_cents_to_micros(raw.get("daily_budget")),
    )


def to_campaigns(
    rows: Iterable[dict[str, Any]], *, account_id: str
) -> tuple[Campaign, ...]:
    """Build a tuple of :class:`Campaign` from any iterable of rows."""
    return tuple(to_campaign(row, account_id=account_id) for row in rows)


def _cents_to_micros(cents_value: Any) -> int:
    """Convert a Meta cents value (str or int, possibly missing) to micros.

    Returns 0 when the field is absent (e.g. lifetime-budget campaigns).
    """
    if cents_value is None or cents_value == "":
        return 0
    return int(cents_value) * 10_000


# ---------------------------------------------------------------------------
# Ad
# ---------------------------------------------------------------------------


def to_ad(raw: dict[str, Any], *, account_id: str, campaign_id: str) -> Ad:
    """Build an :class:`Ad` from a Meta ad row.

    ``final_url`` is extracted from
    ``creative.object_story_spec.link_data.link`` when present (the
    standard Meta shape for a single-link ad creative); absent → ``""``.

    ``headlines`` / ``descriptions`` are always empty tuples in Phase 1 —
    Meta does NOT expose the creative's headline / description text on
    the ad resource (it lives on the AdCreative resource and is not yet
    fetched). The Protocol contract is satisfied via empty tuples.
    """
    return Ad(
        id=str(raw["id"]),
        account_id=account_id,
        campaign_id=campaign_id,
        status=map_ad_status(raw.get("status")),
        headlines=(),
        descriptions=(),
        final_url=_extract_creative_link(raw.get("creative")),
    )


def _extract_creative_link(creative: Any) -> str:
    """Return the ``link_data.link`` from a Meta creative dict; ``""`` on miss."""
    if not isinstance(creative, dict):
        return ""
    spec = creative.get("object_story_spec")
    if not isinstance(spec, dict):
        return ""
    link_data = spec.get("link_data")
    if not isinstance(link_data, dict):
        return ""
    link = link_data.get("link")
    return str(link) if link else ""


# ---------------------------------------------------------------------------
# Audience
# ---------------------------------------------------------------------------


def to_audience(raw: dict[str, Any], *, account_id: str) -> Audience:
    """Build an :class:`Audience` from a Meta custom-audience row.

    Phase 1 status mapping: Meta's ``delivery_status.code == 200``
    (or any healthy code) → :class:`AudienceStatus.ENABLED`. There is no
    PAUSED audience status in the canonical model — Phase 1 collapses
    all live audiences to ENABLED. Deleted audiences are returned by
    Meta as 404 and surface as :class:`KeyError` at the adapter layer.
    """
    return Audience(
        id=str(raw["id"]),
        account_id=account_id,
        name=str(raw.get("name") or ""),
        status=AudienceStatus.ENABLED,
        size_estimate=_extract_size_estimate(raw),
    )


def _extract_size_estimate(raw: dict[str, Any]) -> int | None:
    """Return the average of lower/upper bounds, or ``None`` when absent.

    Phase 1 treats a missing size estimate as ``None`` rather than 0
    (zero is a meaningful "no audience matched" value distinct from
    "Meta did not return the field at all").
    """
    lower = raw.get("approximate_count_lower_bound")
    upper = raw.get("approximate_count_upper_bound")
    if lower is None and upper is None:
        return None
    if lower is None:
        return int(upper) if upper is not None else None
    if upper is None:
        return int(lower)
    return (int(lower) + int(upper)) // 2


# ---------------------------------------------------------------------------
# DailyReportRow
# ---------------------------------------------------------------------------


def to_daily_report_row(raw: dict[str, Any]) -> DailyReportRow:
    """Build a :class:`DailyReportRow` from a Meta insights row.

    Field conventions
    -----------------
    - ``date_start``: ``YYYY-MM-DD`` ISO date string.
    - ``impressions`` / ``clicks``: integer-valued strings.
    - ``spend``: dollar-valued string (e.g. ``"12.34"``). Converted to
      micros via ``int(round(float(spend) * 1_000_000))``.
    - ``actions``: optional list of ``{"action_type", "value"}`` dicts;
      the ``purchase`` action_type value populates ``conversions``.
    """
    return DailyReportRow(
        date=_parse_iso_date(raw.get("date_start")),
        impressions=int(raw.get("impressions") or 0),
        clicks=int(raw.get("clicks") or 0),
        cost_micros=_spend_to_micros(raw.get("spend")),
        conversions=_extract_conversions(raw.get("actions")),
    )


def _parse_iso_date(value: Any) -> date:
    """Parse an ISO ``YYYY-MM-DD`` date; raise :class:`ValueError` otherwise."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        # ``datetime.strptime`` rejects malformed strings with a clean
        # ``ValueError`` — exactly the contract the mapper tests rely on.
        return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007
    raise ValueError(f"unparseable date value: {value!r}")


def _spend_to_micros(spend_value: Any) -> int:
    """Convert a Meta dollar-string spend to micros (rounded to nearest int)."""
    if spend_value is None or spend_value == "":
        return 0
    return int(round(float(spend_value) * 1_000_000))


def _extract_conversions(actions: Any) -> float:
    """Sum the ``value`` field of every Phase 1 conversion-style action."""
    if not isinstance(actions, list):
        return 0.0
    total = 0.0
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = action.get("action_type")
        if action_type in _CONVERSION_ACTION_TYPES:
            try:
                total += float(action.get("value") or 0)
            except (TypeError, ValueError):
                continue
    return total


__all__ = [
    "map_ad_status",
    "map_campaign_status",
    "to_ad",
    "to_audience",
    "to_campaign",
    "to_campaigns",
    "to_daily_report_row",
]
