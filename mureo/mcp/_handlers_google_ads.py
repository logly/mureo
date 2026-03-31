"""Google Ads MCPツール ハンドラー実装

tools_google_ads.py から呼び出される各ツールのハンドラー関数群。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.auth import (
    create_google_ads_client,
    load_google_ads_credentials,
)
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    _require,
    api_error_handler,
)

logger = logging.getLogger(__name__)

_NO_CREDS_MSG = (
    "認証情報が見つかりません。環境変数 "
    "(GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CLIENT_ID, "
    "GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN) "
    "または ~/.mureo/credentials.json を設定してください。"
)


def _get_client(arguments: dict[str, Any]) -> Any:
    """認証情報を読み込みクライアントを生成する。Noneの場合は認証エラー。"""
    customer_id = _require(arguments, "customer_id")
    creds = load_google_ads_credentials()
    if creds is None:
        return None
    return create_google_ads_client(creds, customer_id)


def _no_google_creds() -> list[TextContent]:
    """Google Ads認証情報なしエラーを返す。"""
    return _no_creds_result(_NO_CREDS_MSG)


# ---------------------------------------------------------------------------
# キャンペーン
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_campaigns(status_filter=_opt(args, "status_filter"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_campaign(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"name": _require(args, "name")}
    for key in ("bidding_strategy", "budget_id"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.create_campaign(params)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"campaign_id": _require(args, "campaign_id")}
    for key in ("name", "bidding_strategy"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_campaign(params)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update_status(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.update_campaign_status(
        _require(args, "campaign_id"), _require(args, "status")
    )
    return _json_result(result)


@api_error_handler
async def handle_campaigns_diagnose(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_campaign_delivery(_require(args, "campaign_id"))
    return _json_result(result)


# ---------------------------------------------------------------------------
# 広告グループ
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_groups_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ad_groups(
        campaign_id=_opt(args, "campaign_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_groups_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "name": _require(args, "name"),
    }
    cpc = _opt(args, "cpc_bid_micros")
    if cpc is not None:
        params["cpc_bid_micros"] = cpc
    result = await client.create_ad_group(params)
    return _json_result(result)


@api_error_handler
async def handle_ad_groups_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"ad_group_id": _require(args, "ad_group_id")}
    for key in ("name", "status", "cpc_bid_micros"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_ad_group(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 広告
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ads(
        ad_group_id=_opt(args, "ad_group_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ads_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "headlines": _require(args, "headlines"),
        "descriptions": _require(args, "descriptions"),
    }
    for key in ("final_url", "path1", "path2"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.create_ad(params)
    return _json_result(result)


@api_error_handler
async def handle_ads_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "ad_id": _require(args, "ad_id"),
    }
    for key in ("headlines", "descriptions"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_ad(params)
    return _json_result(result)


@api_error_handler
async def handle_ads_update_status(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "ad_id": _require(args, "ad_id"),
        "status": _require(args, "status"),
    }
    result = await client.update_ad_status(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# キーワード
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_keywords_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_keywords(
        campaign_id=_opt(args, "campaign_id"),
        ad_group_id=_opt(args, "ad_group_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_keywords_add(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_keywords(params)
    return _json_result(result)


@api_error_handler
async def handle_keywords_remove(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "criterion_id": _require(args, "criterion_id"),
    }
    result = await client.remove_keyword(params)
    return _json_result(result)


@api_error_handler
async def handle_keywords_suggest(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    seed = _require(args, "seed_keywords")
    result = await client.suggest_keywords(
        seed,
        language_id=_opt(args, "language_id", "1005"),
        geo_id=_opt(args, "geo_id", "2392"),
    )
    return _json_result(result)


@api_error_handler
async def handle_keywords_diagnose(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_negative_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_add(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_negative_keywords(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 予算
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_budget_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_budget(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_budget_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "budget_id": _require(args, "budget_id"),
        "amount": _require(args, "amount"),
    }
    result = await client.update_budget(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_performance_report(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_search_terms_report(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_search_terms_report(
        campaign_id=_opt(args, "campaign_id"),
        ad_group_id=_opt(args, "ad_group_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_search_terms_review(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    kwargs: dict[str, Any] = {"campaign_id": _require(args, "campaign_id")}
    period = _opt(args, "period")
    if period:
        kwargs["period"] = period
    target_cpa = _opt(args, "target_cpa")
    if target_cpa is not None:
        kwargs["target_cpa"] = target_cpa
    result = await client.review_search_terms(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_auction_insights(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_auction_insights(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_cpc_detect_trend(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.detect_cpc_trend(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_device_analyze(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_device_performance(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# 画像アセット
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_assets_upload_image(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    file_path = _require(args, "file_path")
    name = _opt(args, "name")
    result = await client.upload_image_asset(file_path, name=name)
    return _json_result(result)


# ---------------------------------------------------------------------------
# ハンドラーマッピング
# ---------------------------------------------------------------------------

HANDLERS: dict[str, Any] = {
    "google_ads.campaigns.list": handle_campaigns_list,
    "google_ads.campaigns.get": handle_campaigns_get,
    "google_ads.campaigns.create": handle_campaigns_create,
    "google_ads.campaigns.update": handle_campaigns_update,
    "google_ads.campaigns.update_status": handle_campaigns_update_status,
    "google_ads.campaigns.diagnose": handle_campaigns_diagnose,
    "google_ads.ad_groups.list": handle_ad_groups_list,
    "google_ads.ad_groups.create": handle_ad_groups_create,
    "google_ads.ad_groups.update": handle_ad_groups_update,
    "google_ads.ads.list": handle_ads_list,
    "google_ads.ads.create": handle_ads_create,
    "google_ads.ads.update": handle_ads_update,
    "google_ads.ads.update_status": handle_ads_update_status,
    "google_ads.keywords.list": handle_keywords_list,
    "google_ads.keywords.add": handle_keywords_add,
    "google_ads.keywords.remove": handle_keywords_remove,
    "google_ads.keywords.suggest": handle_keywords_suggest,
    "google_ads.keywords.diagnose": handle_keywords_diagnose,
    "google_ads.negative_keywords.list": handle_negative_keywords_list,
    "google_ads.negative_keywords.add": handle_negative_keywords_add,
    "google_ads.budget.get": handle_budget_get,
    "google_ads.budget.update": handle_budget_update,
    "google_ads.performance.report": handle_performance_report,
    "google_ads.search_terms.report": handle_search_terms_report,
    "google_ads.search_terms.review": handle_search_terms_review,
    "google_ads.auction_insights.analyze": handle_auction_insights,
    "google_ads.cpc.detect_trend": handle_cpc_detect_trend,
    "google_ads.device.analyze": handle_device_analyze,
    "google_ads.assets.upload_image": handle_assets_upload_image,
}
