"""Where the exclusion delivery-impact numbers come from, per platform (#547).

The pure estimator lives in :mod:`mureo.analysis.exclusion_impact`. This
module is the I/O half: for each exclusion tool mureo owns the schema for,
it reads the entities the call is about to exclude out of the arguments,
and fetches the account's own recent delivery for the scope those entities
live in.

Per-platform honesty, which is the whole point of the issue:

======================================  =========================================
Surface                                 Delivery attributable?
======================================  =========================================
``google_ads_negative_placements_add``  **Yes** — ``group_placement_view``
                                        gives impressions / clicks / cost /
                                        conversions per website and per mobile
                                        app. A ``mobile_app_category`` entry in
                                        the same batch is **not** attributable —
                                        a category is not itself a placement
                                        that serves — so a mixed batch reports
                                        ``partial``.
``google_ads_negative_keywords_add``    **Yes** — ``search_term_view`` over the
``..._add_to_ad_group``                 same window, matched by the negative's
                                        own match type.
``meta_ads_excluded_placements_set``    **No** — the facets this tool writes
                                        (publisher categories, publisher block
                                        lists, brand-safety content types) have
                                        no insights breakdown that attributes
                                        past delivery to them. Meta breaks
                                        delivery down by ``publisher_platform``
                                        / ``platform_position``, which are a
                                        different exclusion surface
                                        (``meta_ads_ad_sets_update`` targeting).
                                        Reported ``unknown``, never "no impact".
Plugins / bridges                       Whatever they register. mureo registers
(Yahoo, LINE, SmartNews, LOGLY,         nothing on their behalf: guessing a
Amazon)                                 bridged tool's argument shape would
                                        produce a confident wrong number.
======================================  =========================================

Everything here is best-effort by contract. A read that fails yields
``records=None`` with the reason attached — which surfaces as ``unknown``,
and refuses only if the operator asked for that with
``block_exclusions_without_impact_data``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.analysis.exclusion_impact import (
    ENTITY_MOBILE_APPLICATION,
    ENTITY_SEARCH_TERM,
    ENTITY_WEBSITE,
    DeliveryRecord,
    DeliverySample,
    ExclusionSurface,
    ExclusionTarget,
    register_exclusion_surface,
)
from mureo.core import clock

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

GOOGLE_PLACEMENTS_ADD = "google_ads_negative_placements_add"
GOOGLE_NEGATIVE_KEYWORDS_ADD = "google_ads_negative_keywords_add"
GOOGLE_NEGATIVE_KEYWORDS_ADD_AD_GROUP = "google_ads_negative_keywords_add_to_ad_group"
META_EXCLUDED_PLACEMENTS_SET = "meta_ads_excluded_placements_set"

#: What ``group_placement_view`` can attribute delivery to.
_PLACEMENT_ATTRIBUTABLE = frozenset({ENTITY_WEBSITE, ENTITY_MOBILE_APPLICATION})
_SEARCH_TERM_ATTRIBUTABLE = frozenset({ENTITY_SEARCH_TERM})

_PLACEMENT_BASIS = "google_ads_group_placement_view"
_SEARCH_TERM_BASIS = "google_ads_search_term_view"
_META_BASIS = "meta_ads_ad_set_targeting"

_META_UNATTRIBUTABLE = (
    "Meta does not expose an insights breakdown that attributes past "
    "delivery to publisher categories, publisher block lists or "
    "brand-safety content types, so mureo cannot size this exclusion from "
    "the account's own data. (publisher_platform / platform_position ARE "
    "attributable, but they are a different exclusion surface — ad-set "
    "targeting, not these facets.)"
)

_AD_GROUP_STANDING_UNKNOWN = (
    "Standing exclusions were listed at the ad group level only; "
    "campaign-level exclusions covering the same ad group are not visible "
    "from this call's arguments, so the cumulative figure would understate."
)

_CAMPAIGN_NEGATIVES_ONLY = (
    "Google Ads exposes no ad-group-level negative keyword listing, so the "
    "standing negative set for this ad group cannot be read."
)


def _period(window_days: int) -> str:
    """A ``BETWEEN 'start' AND 'end'`` clause covering the last N days.

    Built off :func:`mureo.core.clock.server_now` (the operator's local
    calendar day), not a GAQL ``LAST_30_DAYS`` constant, so an arbitrary
    ``exclusion_impact_window_days`` is expressible.
    """
    from datetime import timedelta

    end = clock.server_now().date()
    start = end - timedelta(days=max(1, window_days) - 1)
    return f"BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


# ---------------------------------------------------------------------------
# Client access (patched wholesale in tests)
# ---------------------------------------------------------------------------


async def google_ads_client(arguments: Mapping[str, Any]) -> Any:
    """A Google Ads client for this call's account, or ``None``."""
    from mureo.mcp._handlers_google_ads import _get_client

    return _get_client(dict(arguments))


async def meta_ads_client(arguments: Mapping[str, Any]) -> Any:
    """A Meta Ads client for this call's account, or ``None``."""
    from mureo.mcp._handlers_meta_ads import _get_client

    return await _get_client(dict(arguments))


# ---------------------------------------------------------------------------
# Google Ads — negative placements
# ---------------------------------------------------------------------------


def google_placement_targets(
    arguments: Mapping[str, Any],
) -> tuple[ExclusionTarget, ...]:
    """The websites / apps / app categories this call excludes."""
    placements = arguments.get("placements") or []
    targets: list[ExclusionTarget] = []
    for item in placements:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        kind = str(item.get("type") or "").strip()
        if value and kind:
            targets.append(ExclusionTarget(value=value, entity_type=kind))
    return tuple(targets)


def _placement_records(rows: Any) -> tuple[DeliveryRecord, ...]:
    return tuple(
        DeliveryRecord(
            entity=str(row.get("placement") or ""),
            entity_type=str(row.get("type") or ""),
            impressions=float(row.get("impressions") or 0),
            clicks=float(row.get("clicks") or 0),
            cost=float(row.get("cost") or 0),
            conversions=float(row.get("conversions") or 0),
        )
        for row in rows
        if isinstance(row, dict)
    )


def _standing_placements(rows: Any) -> tuple[ExclusionTarget, ...]:
    return tuple(
        ExclusionTarget(
            value=str(row.get("value") or ""),
            entity_type=str(row.get("type") or ""),
        )
        for row in rows
        if isinstance(row, dict) and row.get("value") and row.get("type")
    )


async def _standing_placement_set(
    client: Any, campaign_id: Any, ad_group_id: Any
) -> tuple[tuple[ExclusionTarget, ...] | None, str]:
    """Standing exclusions on this scope, for the cumulative figure.

    Withheld (``None``) for an ad-group-level write: campaign-level
    exclusions cover the same ad group and are not reachable from this
    call's arguments, so including only the ad group's own would report a
    cumulative figure that is quietly too small.
    """
    if ad_group_id and not campaign_id:
        return None, _AD_GROUP_STANDING_UNKNOWN
    try:
        rows = await client.list_negative_placements(
            campaign_id=str(campaign_id) if campaign_id else None,
            ad_group_id=str(ad_group_id) if ad_group_id else None,
        )
    except Exception:  # noqa: BLE001 — a missing cumulative is not a failure
        logger.debug("standing negative placements unreadable", exc_info=True)
        return None, "The standing exclusion list could not be read."
    return _standing_placements(rows), ""


async def google_placement_delivery(
    arguments: Mapping[str, Any], window_days: int
) -> DeliverySample:
    """Placement-attributed delivery for the scope this call writes to."""
    from mureo.mcp._helpers import _close_clients

    campaign_id = arguments.get("campaign_id") or None
    ad_group_id = arguments.get("ad_group_id") or None
    client = await google_ads_client(arguments)
    if client is None:
        return DeliverySample(
            records=None,
            basis=_PLACEMENT_BASIS,
            attributable_types=_PLACEMENT_ATTRIBUTABLE,
            reason="No Google Ads credentials are configured for this account.",
        )
    try:
        rows = await client.get_placement_performance(
            campaign_id=str(campaign_id) if campaign_id else None,
            ad_group_id=str(ad_group_id) if ad_group_id else None,
            period=_period(window_days),
        )
        standing, standing_reason = await _standing_placement_set(
            client, campaign_id, ad_group_id
        )
    finally:
        await _close_clients([client])
    return DeliverySample(
        records=_placement_records(rows),
        basis=_PLACEMENT_BASIS,
        attributable_types=_PLACEMENT_ATTRIBUTABLE,
        standing=standing,
        standing_reason=standing_reason,
    )


# ---------------------------------------------------------------------------
# Google Ads — negative keywords
# ---------------------------------------------------------------------------


def google_negative_keyword_targets(
    arguments: Mapping[str, Any],
) -> tuple[ExclusionTarget, ...]:
    keywords = arguments.get("keywords") or []
    targets: list[ExclusionTarget] = []
    for item in keywords:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            targets.append(
                ExclusionTarget(
                    value=text,
                    entity_type=ENTITY_SEARCH_TERM,
                    match_type=str(item.get("match_type") or "BROAD"),
                )
            )
    return tuple(targets)


def _search_term_records(rows: Any) -> tuple[DeliveryRecord, ...]:
    records: list[DeliveryRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        metrics = row.get("metrics") or {}
        records.append(
            DeliveryRecord(
                entity=str(row.get("search_term") or ""),
                entity_type=ENTITY_SEARCH_TERM,
                impressions=float(metrics.get("impressions") or 0),
                clicks=float(metrics.get("clicks") or 0),
                cost=float(metrics.get("cost") or 0),
                conversions=float(metrics.get("conversions") or 0),
            )
        )
    return tuple(records)


async def _standing_negative_keywords(
    client: Any, campaign_id: Any
) -> tuple[tuple[ExclusionTarget, ...] | None, str]:
    if not campaign_id:
        return None, _CAMPAIGN_NEGATIVES_ONLY
    try:
        rows = await client.list_negative_keywords(str(campaign_id))
    except Exception:  # noqa: BLE001 — a missing cumulative is not a failure
        logger.debug("standing negative keywords unreadable", exc_info=True)
        return None, "The standing negative keyword list could not be read."
    return (
        tuple(
            ExclusionTarget(
                value=str(row.get("text") or row.get("keyword") or ""),
                entity_type=ENTITY_SEARCH_TERM,
                match_type=str(row.get("match_type") or "BROAD"),
            )
            for row in rows
            if isinstance(row, dict)
        ),
        "",
    )


async def google_negative_keyword_delivery(
    arguments: Mapping[str, Any], window_days: int
) -> DeliverySample:
    """Search-term delivery for the campaign / ad group being negated."""
    from mureo.mcp._helpers import _close_clients

    campaign_id = arguments.get("campaign_id") or None
    ad_group_id = arguments.get("ad_group_id") or None
    client = await google_ads_client(arguments)
    if client is None:
        return DeliverySample(
            records=None,
            basis=_SEARCH_TERM_BASIS,
            attributable_types=_SEARCH_TERM_ATTRIBUTABLE,
            reason="No Google Ads credentials are configured for this account.",
        )
    try:
        rows = await client.get_search_terms_report(
            campaign_id=str(campaign_id) if campaign_id else None,
            ad_group_id=str(ad_group_id) if ad_group_id else None,
            period=_period(window_days),
        )
        standing, standing_reason = await _standing_negative_keywords(
            client, campaign_id
        )
    finally:
        await _close_clients([client])
    return DeliverySample(
        records=_search_term_records(rows),
        basis=_SEARCH_TERM_BASIS,
        attributable_types=_SEARCH_TERM_ATTRIBUTABLE,
        standing=standing,
        standing_reason=standing_reason,
    )


# ---------------------------------------------------------------------------
# Meta Ads — ad-set publisher exclusions
# ---------------------------------------------------------------------------

#: Argument key → the entity kind mureo names it by. Kept in lockstep with
#: ``mureo.meta_ads._placement_exclusions.EXCLUSION_KEYS``.
_META_FACETS: dict[str, str] = {
    "excluded_publisher_categories": "publisher_category",
    "excluded_publisher_list_ids": "publisher_block_list",
    "excluded_brand_safety_content_types": "brand_safety_content_type",
}


def meta_excluded_placement_targets(
    arguments: Mapping[str, Any],
) -> tuple[ExclusionTarget, ...]:
    targets: list[ExclusionTarget] = []
    for key, entity_type in _META_FACETS.items():
        for value in arguments.get(key) or []:
            text = str(value).strip()
            if text:
                targets.append(ExclusionTarget(value=text, entity_type=entity_type))
    return tuple(targets)


async def meta_excluded_placement_delivery(
    arguments: Mapping[str, Any], window_days: int
) -> DeliverySample:
    """Always unknown — and it says so rather than reading nothing as zero."""
    return DeliverySample(
        records=None,
        basis=_META_BASIS,
        attributable_types=frozenset(),
        reason=_META_UNATTRIBUTABLE,
        standing_reason=_META_UNATTRIBUTABLE,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_BUILTIN_SURFACES: tuple[ExclusionSurface, ...] = (
    ExclusionSurface(
        tool=GOOGLE_PLACEMENTS_ADD,
        platform="google_ads",
        targets=google_placement_targets,
        delivery=google_placement_delivery,
        note=(
            "Denominator is placement-attributed delivery in the named "
            "campaign / ad group, not the campaign's total delivery."
        ),
    ),
    ExclusionSurface(
        tool=GOOGLE_NEGATIVE_KEYWORDS_ADD,
        platform="google_ads",
        targets=google_negative_keyword_targets,
        delivery=google_negative_keyword_delivery,
        note=(
            "Negative keywords do not match close variants, and neither "
            "does this estimate — a term differing only by a plural is not "
            "counted, so the share is a lower bound."
        ),
    ),
    ExclusionSurface(
        tool=GOOGLE_NEGATIVE_KEYWORDS_ADD_AD_GROUP,
        platform="google_ads",
        targets=google_negative_keyword_targets,
        delivery=google_negative_keyword_delivery,
        note=(
            "Ad-group scope. Google Ads exposes no ad-group-level negative "
            "keyword listing, so no cumulative figure is reported."
        ),
    ),
    ExclusionSurface(
        tool=META_EXCLUDED_PLACEMENTS_SET,
        platform="meta_ads",
        targets=meta_excluded_placement_targets,
        delivery=meta_excluded_placement_delivery,
        note=_META_UNATTRIBUTABLE,
    ),
)


def register_builtin_exclusion_surfaces() -> None:
    """Register every exclusion surface mureo owns the schema for."""
    for surface in _BUILTIN_SURFACES:
        register_exclusion_surface(surface)


register_builtin_exclusion_surfaces()


__all__ = [
    "GOOGLE_NEGATIVE_KEYWORDS_ADD",
    "GOOGLE_NEGATIVE_KEYWORDS_ADD_AD_GROUP",
    "GOOGLE_PLACEMENTS_ADD",
    "META_EXCLUDED_PLACEMENTS_SET",
    "google_ads_client",
    "google_negative_keyword_delivery",
    "google_negative_keyword_targets",
    "google_placement_delivery",
    "google_placement_targets",
    "meta_ads_client",
    "meta_excluded_placement_delivery",
    "meta_excluded_placement_targets",
    "register_builtin_exclusion_surfaces",
]
