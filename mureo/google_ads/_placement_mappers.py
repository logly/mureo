"""Response mappers for the Google Ads placement surfaces.

Split out of :mod:`mureo.google_ads.mappers` for the same reason
:mod:`mureo.google_ads._placements` was split out of the client: the
placement work is one coherent family, and `mappers.py` had grown past the
project's 800-line file budget.

Two rows are shaped here:

- :func:`map_negative_placement` — a campaign / ad-group negative placement
  criterion (an exclusion that EXISTS), #544.
- :func:`map_placement_performance` — a ``group_placement_view`` row (what a
  placement actually DELIVERED), the denominator for the #547 exclusion
  delivery-impact preview.

Both keep the raw Google Ads enum name alongside mureo's tool-facing
vocabulary, so a row stays readable if Google adds a type mureo does not map
yet.
"""

from __future__ import annotations

from typing import Any

from mureo.google_ads._enum_names import PLACEMENT_TYPE_MAP, map_enum_name
from mureo.google_ads.mappers import (
    CRITERION_TYPE_MAP,
    _HasIdAndName,
    _micros_to_currency,
    _safe_float,
    _safe_int,
    _safe_str,
)

# === Negative Placements (delivery-surface exclusions, #544) ===


def map_negative_placement(
    criterion: Any,
    level: str,
    campaign: _HasIdAndName | None = None,
    ad_group: _HasIdAndName | None = None,
) -> dict[str, Any]:
    """Shape one negative placement / app / app-category criterion row.

    ``level`` is ``"campaign"`` or ``"ad_group"`` — the two are separate
    Google Ads resources and an operator has to know which one an exclusion
    lives on before removing it. ``type`` is mureo's tool-facing exclusion
    vocabulary; ``criterion_type`` keeps the raw Google Ads enum name so a
    row is still readable if Google adds a type mureo does not map yet.
    """
    # Imported here rather than at module import time: the placements mixin
    # imports this module, so a module-level import would close a cycle.
    from mureo.google_ads._placements import CRITERION_TYPE_TO_KIND

    criterion_type = map_enum_name(criterion.type_, CRITERION_TYPE_MAP)
    kind = CRITERION_TYPE_TO_KIND.get(criterion_type)
    if kind == "website":
        value = _safe_str(criterion.placement, "url") or None
    elif kind == "mobile_application":
        value = _safe_str(criterion.mobile_application, "app_id") or None
    elif kind == "mobile_app_category":
        value = (
            _safe_str(criterion.mobile_app_category, "mobile_app_category_constant")
            or None
        )
    else:
        value = None
    app_name = _safe_str(criterion.mobile_application, "name") or None
    result: dict[str, Any] = {
        "level": level,
        "criterion_id": str(criterion.criterion_id),
        "type": kind,
        "criterion_type": criterion_type,
        "value": value,
        "display_name": app_name if kind == "mobile_application" else value,
        "negative": bool(getattr(criterion, "negative", True)),
    }
    if campaign is not None:
        result["campaign_id"] = str(campaign.id)
        result["campaign_name"] = campaign.name
    if ad_group is not None:
        result["ad_group_id"] = str(ad_group.id)
        result["ad_group_name"] = ad_group.name
    return result


# === Placement performance (delivery-impact preview, #547) ===

#: ``group_placement_view.placement_type`` → mureo's exclusion vocabulary.
#: Only the three kinds an exclusion can name are translated; anything else
#: keeps a lower-cased raw enum name so a YouTube channel row is still
#: readable — and, since it matches no exclusion kind, contributes to the
#: denominator without ever being claimed as removed.
_PLACEMENT_TYPE_TO_KIND: dict[str, str] = {
    "WEBSITE": "website",
    "MOBILE_APPLICATION": "mobile_application",
    "MOBILE_APP_CATEGORY": "mobile_app_category",
}


def map_placement_performance(row: Any) -> dict[str, Any]:
    """Shape one ``group_placement_view`` row for the exclusion preview.

    ``placement`` is the value an exclusion would name (a domain, or a
    ``mobileapp::``-prefixed app id); ``display_name`` is the human label.
    """
    view = row.group_placement_view if hasattr(row, "group_placement_view") else row
    metrics = row.metrics if hasattr(row, "metrics") else row
    raw_type = map_enum_name(
        getattr(view, "placement_type", ""), PLACEMENT_TYPE_MAP
    ).upper()
    return {
        "placement": _safe_str(view, "placement"),
        "display_name": _safe_str(view, "display_name"),
        "target_url": _safe_str(view, "target_url"),
        "placement_type": raw_type,
        "type": _PLACEMENT_TYPE_TO_KIND.get(raw_type, raw_type.lower()),
        "impressions": _safe_int(metrics, "impressions"),
        "clicks": _safe_int(metrics, "clicks"),
        "cost_micros": _safe_int(metrics, "cost_micros"),
        "cost": _micros_to_currency(_safe_int(metrics, "cost_micros")),
        "conversions": _safe_float(metrics, "conversions"),
    }


__all__ = ["map_negative_placement", "map_placement_performance"]
