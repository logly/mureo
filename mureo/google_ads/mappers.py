from __future__ import annotations

from typing import Any, Protocol


class _HasIdAndName(Protocol):
    id: int
    name: str

from google.ads.googleads.v23.enums.types.ad_group_criterion_approval_status import (
    AdGroupCriterionApprovalStatusEnum,
)
from google.ads.googleads.v23.enums.types.ad_strength import AdStrengthEnum
from google.ads.googleads.v23.enums.types.ad_type import AdTypeEnum
from google.ads.googleads.v23.enums.types.bidding_strategy_system_status import (
    BiddingStrategySystemStatusEnum,
)
from google.ads.googleads.v23.enums.types.bidding_strategy_type import (
    BiddingStrategyTypeEnum,
)
from google.ads.googleads.v23.enums.types.campaign_primary_status_reason import (
    CampaignPrimaryStatusReasonEnum,
)
from google.ads.googleads.v23.enums.types.policy_topic_entry_type import (
    PolicyTopicEntryTypeEnum,
)

# ---------------------------------------------------------------------------
# protobuf enum int → 文字列 マッピング定数
# ---------------------------------------------------------------------------

_ENTITY_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "ENABLED",
    3: "PAUSED",
    4: "REMOVED",
}

# protobuf enum から自動生成 — 手動転記ミスを原理的に排除
_BIDDING_STRATEGY_MAP: dict[int, str] = {
    member.value: member.name
    for member in BiddingStrategyTypeEnum.BiddingStrategyType
}
# v23ではMAXIMIZE_CLICKSがTARGET_SPEND(enum=9)に統合されている。
# 管理画面では「クリック数の最大化」と表示されるため、ユーザー向け名称に合わせる。
_BIDDING_STRATEGY_MAP[9] = "MAXIMIZE_CLICKS"

# protobuf enum から自動生成
_AD_TYPE_MAP: dict[int, str] = {
    member.value: member.name
    for member in AdTypeEnum.AdType
}

# protobuf enum から自動生成
_AD_STRENGTH_MAP: dict[int, str] = {
    member.value: member.name
    for member in AdStrengthEnum.AdStrength
}

_SERVING_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "SERVING",
    3: "NONE",
    4: "ENDED",
    5: "PENDING",
    6: "SUSPENDED",
}

# PolicyApprovalStatusEnum 用（広告のポリシー審査に使用）
_APPROVAL_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "DISAPPROVED",
    3: "APPROVED_LIMITED",
    4: "APPROVED",
    5: "AREA_OF_INTEREST_ONLY",
}

# AdGroupCriterionApprovalStatusEnum 用（キーワード等のクライテリアに使用）
# ※ PolicyApprovalStatusEnum とは enum 値が異なるため別マップが必要
_CRITERION_APPROVAL_STATUS_MAP: dict[int, str] = {
    member.value: member.name
    for member in AdGroupCriterionApprovalStatusEnum.AdGroupCriterionApprovalStatus
}

_REVIEW_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "REVIEW_IN_PROGRESS",
    3: "REVIEWED",
    4: "UNDER_APPEAL",
    5: "ELIGIBLE_MAY_SERVE",
}

# protobuf enum から自動生成
_POLICY_TOPIC_TYPE_MAP: dict[int, str] = {
    member.value: member.name
    for member in PolicyTopicEntryTypeEnum.PolicyTopicEntryType
}

_PRIMARY_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "ELIGIBLE",
    3: "PAUSED",
    4: "REMOVED",
    5: "ENDED",
    6: "PENDING",
    7: "MISCONFIGURED",
    8: "LIMITED",
    9: "LEARNING",
    10: "NOT_ELIGIBLE",
}

# protobuf enum から自動生成
_PRIMARY_STATUS_REASON_MAP: dict[int, str] = {
    member.value: member.name
    for member in CampaignPrimaryStatusReasonEnum.CampaignPrimaryStatusReason
}

# protobuf enum から自動生成
_BIDDING_SYSTEM_STATUS_MAP: dict[int, str] = {
    member.value: member.name
    for member in BiddingStrategySystemStatusEnum.BiddingStrategySystemStatus
}


def _map_enum(value: Any, mapping: dict[int, str]) -> str:
    """protobuf enum int を文字列に変換する汎用ヘルパー"""
    if isinstance(value, int):
        return mapping.get(value, str(value))
    return str(value)


# ---------------------------------------------------------------------------
# 公開 enum 変換関数
# ---------------------------------------------------------------------------


def map_ad_type(ad_type: Any) -> str:
    """AdTypeEnum を文字列に変換"""
    return _map_enum(ad_type, _AD_TYPE_MAP)


def map_ad_strength(strength: Any) -> str:
    """AdStrengthEnum を文字列に変換"""
    return _map_enum(strength, _AD_STRENGTH_MAP)


def map_entity_status(status: Any) -> str:
    """エンティティステータスを文字列に変換（Campaign / AdGroup / Ad 共通）"""
    return _map_enum(status, _ENTITY_STATUS_MAP)


def map_bidding_strategy_type(strategy: Any) -> str:
    """BiddingStrategyTypeEnum を文字列に変換"""
    return _map_enum(strategy, _BIDDING_STRATEGY_MAP)


def map_serving_status(status: Any) -> str:
    """CampaignServingStatusEnum を文字列に変換"""
    return _map_enum(status, _SERVING_STATUS_MAP)


def map_approval_status(status: Any) -> str:
    """PolicyApprovalStatusEnum を文字列に変換（広告のポリシー審査用）"""
    return _map_enum(status, _APPROVAL_STATUS_MAP)


def map_criterion_approval_status(status: Any) -> str:
    """AdGroupCriterionApprovalStatusEnum を文字列に変換（キーワード等の承認ステータス用）"""
    return _map_enum(status, _CRITERION_APPROVAL_STATUS_MAP)


def map_review_status(status: Any) -> str:
    """PolicyReviewStatusEnum を文字列に変換"""
    return _map_enum(status, _REVIEW_STATUS_MAP)


def map_policy_topic_type(type_val: Any) -> str:
    """PolicyTopicEntryTypeEnum を文字列に変換"""
    return _map_enum(type_val, _POLICY_TOPIC_TYPE_MAP)


def map_primary_status(status: Any) -> str:
    """CampaignPrimaryStatusEnum を文字列に変換"""
    return _map_enum(status, _PRIMARY_STATUS_MAP)


def map_primary_status_reason(reason: Any) -> str:
    """CampaignPrimaryStatusReasonEnum を文字列に変換"""
    return _map_enum(reason, _PRIMARY_STATUS_REASON_MAP)


def map_bidding_system_status(status: Any) -> str:
    """BiddingStrategySystemStatusEnum を文字列に変換"""
    return _map_enum(status, _BIDDING_SYSTEM_STATUS_MAP)


# ---------------------------------------------------------------------------
# エンティティ変換関数
# ---------------------------------------------------------------------------


def map_campaign(campaign: Any) -> dict[str, Any]:
    """キャンペーン情報をLLMが理解しやすい形に整形"""
    result: dict[str, Any] = {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": map_entity_status(campaign.status),
        "budget_amount_micros": (
            campaign.campaign_budget if hasattr(campaign, "campaign_budget") else None
        ),
        "bidding_strategy_type": (
            map_bidding_strategy_type(campaign.bidding_strategy_type)
            if hasattr(campaign, "bidding_strategy_type")
            else None
        ),
    }
    if hasattr(campaign, "serving_status"):
        result["serving_status"] = map_serving_status(campaign.serving_status)
    if hasattr(campaign, "primary_status"):
        result["primary_status"] = map_primary_status(campaign.primary_status)
    if hasattr(campaign, "primary_status_reasons"):
        result["primary_status_reasons"] = [
            map_primary_status_reason(r) for r in campaign.primary_status_reasons
        ]
    if hasattr(campaign, "bidding_strategy_system_status"):
        result["bidding_strategy_system_status"] = map_bidding_system_status(
            campaign.bidding_strategy_system_status
        )
    if hasattr(campaign, "start_date") and campaign.start_date:
        result["start_date"] = str(campaign.start_date)
    if hasattr(campaign, "end_date") and campaign.end_date:
        result["end_date"] = str(campaign.end_date)
    return result


def map_ad_group(
    ad_group: Any, campaign: Any | None = None
) -> dict[str, Any]:
    """広告グループ情報を整形"""
    result: dict[str, Any] = {
        "id": str(ad_group.id),
        "name": ad_group.name,
        "status": map_entity_status(ad_group.status),
        "campaign_id": (
            str(ad_group.campaign) if hasattr(ad_group, "campaign") else None
        ),
        "cpc_bid_micros": (
            ad_group.cpc_bid_micros if hasattr(ad_group, "cpc_bid_micros") else None
        ),
    }
    if campaign is not None:
        result["campaign_id"] = str(campaign.id)
        result["campaign_name"] = campaign.name
        result["campaign_status"] = map_entity_status(campaign.status)
    return result


_QUALITY_SCORE_COMPONENT_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "BELOW_AVERAGE",
    3: "AVERAGE",
    4: "ABOVE_AVERAGE",
}


def _map_quality_component(value: Any) -> str:
    """品質スコア構成要素の enum 値を文字列に変換する。

    protobuf int 値と enum 型（.name 属性）の両方に対応。
    """
    if isinstance(value, int):
        return _QUALITY_SCORE_COMPONENT_MAP.get(value, str(value))
    if hasattr(value, "name"):
        return str(value.name)
    return str(value)


def map_keyword_quality_info(
    criterion: Any,
    campaign: _HasIdAndName | None = None,
    ad_group: _HasIdAndName | None = None,
) -> dict[str, Any]:
    """キーワード品質情報を含むキーワード情報を整形"""
    result = map_keyword(criterion, campaign, ad_group)

    # system_serving_status
    if hasattr(criterion, "system_serving_status") and criterion.system_serving_status is not None:
        raw = criterion.system_serving_status
        if isinstance(raw, int):
            serving_map: dict[int, str] = {
                0: "UNSPECIFIED",
                1: "UNKNOWN",
                2: "ELIGIBLE",
                3: "RARELY_SERVED",
            }
            result["system_serving_status"] = serving_map.get(raw, str(raw))
        elif hasattr(raw, "name"):
            result["system_serving_status"] = str(raw.name)
        else:
            result["system_serving_status"] = str(raw)

    # quality_info
    qi = getattr(criterion, "quality_info", None)
    if qi is not None:
        raw_qs = getattr(qi, "quality_score", 0)
        qs = int(raw_qs) if raw_qs else 0
        result["quality_score"] = qs if qs > 0 else None
        result["creative_quality_score"] = _map_quality_component(
            getattr(qi, "creative_quality_score", 0)
        )
        result["post_click_quality_score"] = _map_quality_component(
            getattr(qi, "post_click_quality_score", 0)
        )
        result["search_predicted_ctr"] = _map_quality_component(
            getattr(qi, "search_predicted_ctr", 0)
        )
    else:
        result["quality_score"] = None
        result["creative_quality_score"] = "UNSPECIFIED"
        result["post_click_quality_score"] = "UNSPECIFIED"
        result["search_predicted_ctr"] = "UNSPECIFIED"

    return result


def map_keyword(
    keyword: Any,
    campaign: _HasIdAndName | None = None,
    ad_group: _HasIdAndName | None = None,
) -> dict[str, Any]:
    """キーワード情報を整形"""
    result: dict[str, Any] = {
        "id": (
            str(keyword.criterion_id)
            if hasattr(keyword, "criterion_id")
            else str(keyword.id) if hasattr(keyword, "id") else None
        ),
        "text": keyword.keyword.text if hasattr(keyword, "keyword") else str(keyword),
        "match_type": (
            str(keyword.keyword.match_type) if hasattr(keyword, "keyword") else None
        ),
        "status": map_entity_status(keyword.status) if hasattr(keyword, "status") else None,
    }
    # approval_status=0 (UNSPECIFIED) は protobuf 未設定時のデフォルト値。
    # is not None で 0 を通過させ、明示的に返却する。
    if hasattr(keyword, "approval_status") and keyword.approval_status is not None:
        result["approval_status"] = map_criterion_approval_status(
            keyword.approval_status
        )
    if campaign is not None:
        result["campaign_id"] = str(campaign.id)
        result["campaign_name"] = campaign.name
    if ad_group is not None:
        result["ad_group_id"] = str(ad_group.id)
        result["ad_group_name"] = ad_group.name
    return result


def _build_metrics_dict(metrics: Any) -> dict[str, Any]:
    """共通メトリクス辞書を構築"""
    return {
        "impressions": _safe_int(metrics, "impressions"),
        "clicks": _safe_int(metrics, "clicks"),
        "cost_micros": _safe_int(metrics, "cost_micros"),
        "cost": _micros_to_currency(_safe_int(metrics, "cost_micros")),
        "conversions": _safe_float(metrics, "conversions"),
        "ctr": _safe_float(metrics, "ctr"),
        "average_cpc_micros": _safe_int(metrics, "average_cpc"),
        "average_cpc": _micros_to_currency(_safe_int(metrics, "average_cpc")),
        "cost_per_conversion_micros": _safe_int(metrics, "cost_per_conversion"),
        "cost_per_conversion": _micros_to_currency(
            _safe_int(metrics, "cost_per_conversion")
        ),
    }


def map_performance_report(rows: list[Any]) -> list[dict[str, Any]]:
    """パフォーマンスレポートを整形"""
    result = []
    for row in rows:
        metrics = row.metrics if hasattr(row, "metrics") else row
        campaign = row.campaign if hasattr(row, "campaign") else None
        entry: dict[str, Any] = {}
        if campaign:
            entry["campaign_name"] = campaign.name
            entry["campaign_id"] = str(campaign.id)
        entry["metrics"] = _build_metrics_dict(metrics)
        result.append(entry)
    return result


def map_ad_performance_report(rows: list[Any]) -> list[dict[str, Any]]:
    """広告単位パフォーマンスレポートを整形"""
    result = []
    for row in rows:
        metrics = row.metrics if hasattr(row, "metrics") else row
        ad = row.ad_group_ad if hasattr(row, "ad_group_ad") else None
        ad_group = row.ad_group if hasattr(row, "ad_group") else None
        campaign = row.campaign if hasattr(row, "campaign") else None

        entry: dict[str, Any] = {}
        if ad:
            entry["ad_id"] = str(ad.ad.id)
            entry["ad_type"] = map_ad_type(ad.ad.type_)
            entry["status"] = map_entity_status(ad.status)
        if ad_group:
            entry["ad_group_id"] = str(ad_group.id)
            entry["ad_group_name"] = ad_group.name
        if campaign:
            entry["campaign_id"] = str(campaign.id)
            entry["campaign_name"] = campaign.name
        entry["metrics"] = _build_metrics_dict(metrics)
        result.append(entry)
    return result


def _micros_to_currency(micros: int) -> float:
    """micros 単位を通貨単位に変換する（通貨非依存）。"""
    return micros / 1_000_000




def _safe_int(obj: Any, attr: str) -> int:
    val = getattr(obj, attr, 0)
    return int(val) if val else 0


def _safe_float(obj: Any, attr: str) -> float:
    val = getattr(obj, attr, 0.0)
    return float(val) if val else 0.0


def _safe_str(obj: Any, attr: str, default: str = "") -> str:
    val = getattr(obj, attr, default)
    return str(val) if val else default


# === 除外キーワード ===


def map_negative_keyword(criterion: Any) -> dict[str, Any]:
    """除外キーワード情報を整形"""
    return {
        "criterion_id": (
            str(criterion.criterion_id) if hasattr(criterion, "criterion_id") else None
        ),
        "keyword_text": (
            criterion.keyword.text if hasattr(criterion, "keyword") else None
        ),
        "match_type": (
            str(criterion.keyword.match_type) if hasattr(criterion, "keyword") else None
        ),
    }


# === 検索語句レポート ===


def map_search_term(row: Any) -> dict[str, Any]:
    """検索語句レポート行を整形"""
    search_term_view = row.search_term_view if hasattr(row, "search_term_view") else row
    metrics = row.metrics if hasattr(row, "metrics") else row
    return {
        "search_term": _safe_str(search_term_view, "search_term"),
        "metrics": {
            "impressions": _safe_int(metrics, "impressions"),
            "clicks": _safe_int(metrics, "clicks"),
            "cost_micros": _safe_int(metrics, "cost_micros"),
            "cost": _micros_to_currency(_safe_int(metrics, "cost_micros")),
            "conversions": _safe_float(metrics, "conversions"),
            "ctr": _safe_float(metrics, "ctr"),
        },
    }


# === サイトリンク ===


def map_sitelink(asset: Any) -> dict[str, Any]:
    """サイトリンクアセット情報を整形"""
    sitelink = (
        asset.asset.sitelink_asset
        if hasattr(asset, "asset") and hasattr(asset.asset, "sitelink_asset")
        else asset
    )
    return {
        "id": str(asset.asset.id) if hasattr(asset, "asset") else None,
        "resource_name": (
            str(asset.asset.resource_name) if hasattr(asset, "asset") else None
        ),
        "link_text": _safe_str(sitelink, "link_text"),
        "description1": _safe_str(sitelink, "description1"),
        "description2": _safe_str(sitelink, "description2"),
        "final_urls": (
            list(asset.asset.final_urls)
            if hasattr(asset, "asset") and hasattr(asset.asset, "final_urls")
            else []
        ),
    }


# === コールアウト ===


def map_callout(asset: Any) -> dict[str, Any]:
    """コールアウトアセット情報を整形"""
    callout = (
        asset.asset.callout_asset
        if hasattr(asset, "asset") and hasattr(asset.asset, "callout_asset")
        else asset
    )
    return {
        "id": str(asset.asset.id) if hasattr(asset, "asset") else None,
        "resource_name": (
            str(asset.asset.resource_name) if hasattr(asset, "asset") else None
        ),
        "callout_text": _safe_str(callout, "callout_text"),
    }


# === コンバージョンアクション ===


def map_conversion_action(action: Any) -> dict[str, Any]:
    """コンバージョンアクション情報を整形"""
    return {
        "id": str(action.id) if hasattr(action, "id") else None,
        "name": _safe_str(action, "name"),
        "type": str(action.type_) if hasattr(action, "type_") else None,
        "status": map_entity_status(action.status) if hasattr(action, "status") else None,
        "category": str(action.category) if hasattr(action, "category") else None,
    }


def map_tag_snippet(snippet: Any) -> dict[str, Any]:
    """コンバージョンタグスニペットを整形"""
    return {
        "type": str(snippet.type_) if hasattr(snippet, "type_") else None,
        "page_header": _safe_str(snippet, "page_header"),
        "event_snippet": _safe_str(snippet, "event_snippet"),
    }


# === 推奨事項 ===


def map_recommendation(rec: Any) -> dict[str, Any]:
    """Google推奨事項を整形"""
    return {
        "resource_name": (
            str(rec.resource_name) if hasattr(rec, "resource_name") else None
        ),
        "type": str(rec.type_) if hasattr(rec, "type_") else None,
        "impact": (
            {
                "base_metrics": {
                    "impressions": (
                        _safe_float(rec.impact.base_metrics, "impressions")
                        if hasattr(rec, "impact")
                        and hasattr(rec.impact, "base_metrics")
                        else 0.0
                    ),
                    "clicks": (
                        _safe_float(rec.impact.base_metrics, "clicks")
                        if hasattr(rec, "impact")
                        and hasattr(rec.impact, "base_metrics")
                        else 0.0
                    ),
                    "cost_micros": (
                        _safe_int(rec.impact.base_metrics, "cost_micros")
                        if hasattr(rec, "impact")
                        and hasattr(rec.impact, "base_metrics")
                        else 0
                    ),
                },
            }
            if hasattr(rec, "impact")
            else None
        ),
        "campaign_id": str(rec.campaign) if hasattr(rec, "campaign") else None,
    }


# === 変更履歴 ===


def map_change_event(event: Any) -> dict[str, Any]:
    """変更履歴イベントを整形"""
    return {
        "change_date_time": _safe_str(event, "change_date_time"),
        "change_resource_type": (
            str(event.change_resource_type)
            if hasattr(event, "change_resource_type")
            else None
        ),
        "resource_change_operation": (
            str(event.resource_change_operation)
            if hasattr(event, "resource_change_operation")
            else None
        ),
        "changed_fields": (
            list(event.changed_fields.paths)
            if hasattr(event, "changed_fields")
            and hasattr(event.changed_fields, "paths")
            else []
        ),
        "user_email": _safe_str(event, "user_email"),
    }
