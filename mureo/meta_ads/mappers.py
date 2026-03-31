from __future__ import annotations

from typing import Any


def _cents_to_amount(cents_str: str | int | None) -> float:
    """Convert a cent-denominated amount to a real currency value.

    Meta API returns budget amounts in cents (integer strings).
    Divide by 100 regardless of currency to get the real value.

    Args:
        cents_str: Amount in cents (string or integer)

    Returns:
        Amount in account currency units
    """
    if cents_str is None:
        return 0.0
    return int(cents_str) / 100


def _safe_float(value: str | int | float | None) -> float:
    """Safely convert a value to float."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value: str | int | None) -> int:
    """Safely convert a value to int."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _extract_conversions(actions: list[dict[str, Any]] | None) -> float:
    """Extract conversion count from actions.

    Meta API actions are an array in [{"action_type": "...", "value": "..."}] format.
    Aggregates conversion-related action_types.

    Args:
        actions: Actions data

    Returns:
        Total conversion count
    """
    if not actions:
        return 0.0

    # action_types treated as conversions
    cv_action_types = {
        "offsite_conversion.fb_pixel_purchase",
        "offsite_conversion.fb_pixel_lead",
        "offsite_conversion.fb_pixel_complete_registration",
        "offsite_conversion.fb_pixel_add_to_cart",
        "offsite_conversion.fb_pixel_initiate_checkout",
        "offsite_conversion.fb_pixel_custom",
        "onsite_conversion.purchase",
        "onsite_conversion.lead_grouped",
        "lead",
        "purchase",
        "complete_registration",
    }

    total = 0.0
    for action in actions:
        action_type = action.get("action_type", "")
        if action_type in cv_action_types:
            total += _safe_float(action.get("value"))

    return total


def _extract_cost_per_conversion(
    cost_per_action_type: list[dict[str, Any]] | None,
) -> float | None:
    """Extract CPA from cost_per_action_type.

    Args:
        cost_per_action_type: Cost data

    Returns:
        CPA (cost per acquisition). None if no matching data is found.
    """
    if not cost_per_action_type:
        return None

    cv_action_types = {
        "offsite_conversion.fb_pixel_purchase",
        "offsite_conversion.fb_pixel_lead",
        "offsite_conversion.fb_pixel_complete_registration",
        "lead",
        "purchase",
        "complete_registration",
    }

    for entry in cost_per_action_type:
        action_type = entry.get("action_type", "")
        if action_type in cv_action_types:
            return _safe_float(entry.get("value"))

    return None


def map_campaign(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Meta API campaign response to a common format.

    Args:
        raw: Meta API raw response

    Returns:
        Formatted campaign information
    """
    return {
        "campaign_id": raw.get("id", ""),
        "campaign_name": raw.get("name", ""),
        "status": raw.get("status", ""),
        "objective": raw.get("objective", ""),
        "daily_budget": _cents_to_amount(raw.get("daily_budget")),
        "lifetime_budget": _cents_to_amount(raw.get("lifetime_budget")),
        "budget_remaining": _cents_to_amount(raw.get("budget_remaining")),
        "bid_strategy": raw.get("bid_strategy", ""),
        "special_ad_categories": raw.get("special_ad_categories", []),
        "created_time": raw.get("created_time", ""),
        "updated_time": raw.get("updated_time", ""),
        "start_time": raw.get("start_time", ""),
        "stop_time": raw.get("stop_time", ""),
    }


def map_ad_set(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Meta API ad set response to a common format.

    Args:
        raw: Meta API raw response

    Returns:
        Formatted ad set information
    """
    return {
        "ad_set_id": raw.get("id", ""),
        "ad_set_name": raw.get("name", ""),
        "status": raw.get("status", ""),
        "campaign_id": raw.get("campaign_id", ""),
        "daily_budget": _cents_to_amount(raw.get("daily_budget")),
        "lifetime_budget": _cents_to_amount(raw.get("lifetime_budget")),
        "billing_event": raw.get("billing_event", ""),
        "optimization_goal": raw.get("optimization_goal", ""),
        "targeting": raw.get("targeting"),
        "bid_amount": _cents_to_amount(raw.get("bid_amount")),
        "created_time": raw.get("created_time", ""),
        "updated_time": raw.get("updated_time", ""),
        "start_time": raw.get("start_time", ""),
        "end_time": raw.get("end_time", ""),
    }


def map_ad(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Meta API ad response to a common format.

    Args:
        raw: Meta API raw response

    Returns:
        Formatted ad information
    """
    creative = raw.get("creative", {})
    return {
        "ad_id": raw.get("id", ""),
        "ad_name": raw.get("name", ""),
        "status": raw.get("status", ""),
        "ad_set_id": raw.get("adset_id", ""),
        "campaign_id": raw.get("campaign_id", ""),
        "creative_id": creative.get("id", ""),
        "creative_name": creative.get("name", ""),
        "created_time": raw.get("created_time", ""),
        "updated_time": raw.get("updated_time", ""),
    }


def map_insights(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a Meta API Insights response to a common format.

    Extracts conversion count from actions and CPA from cost_per_action_type.

    Args:
        raw: Meta API raw response

    Returns:
        Formatted insights information
    """
    actions = raw.get("actions")
    cost_per_action_type = raw.get("cost_per_action_type")

    conversions = _extract_conversions(actions)
    cpa = _extract_cost_per_conversion(cost_per_action_type)

    return {
        "campaign_id": raw.get("campaign_id", ""),
        "campaign_name": raw.get("campaign_name", ""),
        "adset_id": raw.get("adset_id", ""),
        "adset_name": raw.get("adset_name", ""),
        "ad_id": raw.get("ad_id", ""),
        "ad_name": raw.get("ad_name", ""),
        "impressions": _safe_int(raw.get("impressions")),
        "clicks": _safe_int(raw.get("clicks")),
        "spend": _safe_float(raw.get("spend")),
        "cpc": _safe_float(raw.get("cpc")),
        "cpm": _safe_float(raw.get("cpm")),
        "ctr": _safe_float(raw.get("ctr")),
        "reach": _safe_int(raw.get("reach")),
        "frequency": _safe_float(raw.get("frequency")),
        "conversions": conversions,
        "cpa": cpa,
        # Breakdown fields (only when present)
        **({"age": raw["age"]} if "age" in raw else {}),
        **({"gender": raw["gender"]} if "gender" in raw else {}),
        **({"country": raw["country"]} if "country" in raw else {}),
        **({"region": raw["region"]} if "region" in raw else {}),
        **(
            {"publisher_platform": raw["publisher_platform"]}
            if "publisher_platform" in raw
            else {}
        ),
    }
