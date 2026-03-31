from __future__ import annotations

from typing import Any


def _cents_to_amount(cents_str: str | int | None) -> float:
    """セント単位の金額をアカウント通貨の実数値に変換する

    Meta APIは予算等の金額をセント単位（整数文字列）で返す。
    通貨に関わらず100で割って実数値にする。

    Args:
        cents_str: セント単位の金額（文字列または整数）

    Returns:
        アカウント通貨単位の金額
    """
    if cents_str is None:
        return 0.0
    return int(cents_str) / 100


def _safe_float(value: str | int | float | None) -> float:
    """安全にfloatに変換する"""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(value: str | int | None) -> int:
    """安全にintに変換する"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _extract_conversions(actions: list[dict[str, Any]] | None) -> float:
    """actionsからコンバージョン数を抽出する

    Meta APIのactionsは配列で [{"action_type": "...", "value": "..."}] 形式。
    コンバージョン関連のaction_typeを集計する。

    Args:
        actions: actionsデータ

    Returns:
        コンバージョン数合計
    """
    if not actions:
        return 0.0

    # コンバージョンとして扱うaction_type
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
    """cost_per_action_typeからCPAを抽出する

    Args:
        cost_per_action_type: コスト情報データ

    Returns:
        CPA（コンバージョン単価）。該当データがない場合はNone
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
    """Meta APIのキャンペーンレスポンスを共通フォーマットに変換する

    Args:
        raw: Meta API生レスポンス

    Returns:
        整形済みキャンペーン情報
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
    """Meta APIの広告セットレスポンスを共通フォーマットに変換する

    Args:
        raw: Meta API生レスポンス

    Returns:
        整形済み広告セット情報
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
    """Meta APIの広告レスポンスを共通フォーマットに変換する

    Args:
        raw: Meta API生レスポンス

    Returns:
        整形済み広告情報
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
    """Meta APIのInsightsレスポンスを共通フォーマットに変換する

    actionsからCV数を抽出し、cost_per_action_typeからCPAを抽出する。

    Args:
        raw: Meta API生レスポンス

    Returns:
        整形済みインサイト情報
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
        # ブレイクダウンフィールド（存在する場合のみ）
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
