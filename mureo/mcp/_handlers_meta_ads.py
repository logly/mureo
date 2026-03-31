"""Meta Ads MCPツール ハンドラー実装

tools_meta_ads.py からハンドラー関数を分離し、ファイルサイズ肥大化を防ぐ。
ツール定義(TOOLS)とハンドラーマッピング(HANDLERS)は tools_meta_ads.py に残る。
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent

from mureo.auth import (
    create_meta_ads_client,
    load_meta_ads_credentials,
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
    "(META_ADS_ACCESS_TOKEN) "
    "または ~/.mureo/credentials.json を設定してください。"
)


def _get_client(arguments: dict[str, Any]) -> Any:
    """認証情報を読み込みクライアントを生成する。Noneの場合は認証エラー。"""
    account_id = _require(arguments, "account_id")
    creds = load_meta_ads_credentials()
    if creds is None:
        return None
    return create_meta_ads_client(creds, account_id)


def _no_meta_creds() -> list[TextContent]:
    """Meta Ads認証情報なしエラーを返す。"""
    return _no_creds_result(_NO_CREDS_MSG)


# ---------------------------------------------------------------------------
# キャンペーン ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_campaigns(
        status_filter=_opt(args, "status_filter"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.get_campaign(campaign_id)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "objective": _require(args, "objective"),
    }
    for key in ("status", "daily_budget", "lifetime_budget"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_campaign(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status", "daily_budget"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_campaign(campaign_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 広告セット ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_sets_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_sets(
        campaign_id=_opt(args, "campaign_id"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "name": _require(args, "name"),
        "daily_budget": _require(args, "daily_budget"),
    }
    for key in ("billing_event", "optimization_goal", "targeting", "status"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_ad_set(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status", "daily_budget", "targeting"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_ad_set(ad_set_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 広告 ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ads(
        ad_set_id=_opt(args, "ad_set_id"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_ads_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "ad_set_id": _require(args, "ad_set_id"),
        "name": _require(args, "name"),
        "creative_id": _require(args, "creative_id"),
    }
    status = _opt(args, "status")
    if status is not None:
        kwargs["status"] = status
    result = await client.create_ad(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ads_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_ad(ad_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# インサイト ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_insights_report(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.get_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "last_7d"),
        level=_opt(args, "level", "campaign"),
    )
    return _json_result(result)


@api_error_handler
async def handle_insights_breakdown(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.get_breakdown_report(
        campaign_id=campaign_id,
        breakdown=_opt(args, "breakdown", "age,gender"),
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# オーディエンス ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_audiences_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_custom_audiences(
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_audiences_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "subtype": _require(args, "subtype"),
    }
    for key in ("description", "retention_days", "pixel_id"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_custom_audience(**kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# コンバージョン (CAPI) ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_conversions_send(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    pixel_id = _require(args, "pixel_id")
    events = _require(args, "events")
    test_event_code = _opt(args, "test_event_code")
    result = await client.send_event(pixel_id, events, test_event_code=test_event_code)
    return _json_result(result)


@api_error_handler
async def handle_conversions_send_purchase(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "pixel_id": _require(args, "pixel_id"),
        "event_time": _require(args, "event_time"),
        "user_data": _require(args, "user_data"),
        "currency": _require(args, "currency"),
        "value": _require(args, "value"),
    }
    for key in ("content_ids", "event_source_url", "test_event_code"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.send_purchase_event(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_conversions_send_lead(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "pixel_id": _require(args, "pixel_id"),
        "event_time": _require(args, "event_time"),
        "user_data": _require(args, "user_data"),
    }
    for key in ("event_source_url", "test_event_code"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.send_lead_event(**kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# カタログ ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_catalogs_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    business_id = _require(args, "business_id")
    result = await client.list_catalogs(business_id)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    business_id = _require(args, "business_id")
    name = _require(args, "name")
    result = await client.create_catalog(business_id, name)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.get_catalog(catalog_id)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_delete(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.delete_catalog(catalog_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 商品 ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_products_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.list_products(
        catalog_id, limit=_opt(args, "limit", 100)
    )
    return _json_result(result)


@api_error_handler
async def handle_products_add(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    product_data: dict[str, Any] = {
        "retailer_id": _require(args, "retailer_id"),
        "name": _require(args, "name"),
        "availability": _require(args, "availability"),
        "condition": _require(args, "condition"),
        "price": _require(args, "price"),
        "url": _require(args, "url"),
        "image_url": _require(args, "image_url"),
    }
    for key in ("description", "brand", "category"):
        val = _opt(args, key)
        if val is not None:
            product_data[key] = val
    result = await client.add_product(catalog_id, product_data)
    return _json_result(result)


@api_error_handler
async def handle_products_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    result = await client.get_product(product_id)
    return _json_result(result)


@api_error_handler
async def handle_products_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    updates: dict[str, Any] = {}
    for key in ("name", "description", "availability", "price", "url", "image_url", "brand", "category"):
        val = _opt(args, key)
        if val is not None:
            updates[key] = val
    result = await client.update_product(product_id, updates)
    return _json_result(result)


@api_error_handler
async def handle_products_delete(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    result = await client.delete_product(product_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# フィード ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_feeds_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.list_product_feeds(catalog_id)
    return _json_result(result)


@api_error_handler
async def handle_feeds_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    name = _require(args, "name")
    feed_url = _require(args, "feed_url")
    schedule = _opt(args, "schedule", "DAILY")
    result = await client.create_product_feed(
        catalog_id, name, feed_url, schedule=schedule
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# リード広告 ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_lead_forms_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    result = await client.list_lead_forms(
        page_id, limit=_opt(args, "limit", 50)
    )
    return _json_result(result)


@api_error_handler
async def handle_lead_forms_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    form_id = _require(args, "form_id")
    result = await client.get_lead_form(form_id)
    return _json_result(result)


@api_error_handler
async def handle_lead_forms_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "page_id": _require(args, "page_id"),
        "name": _require(args, "name"),
        "questions": _require(args, "questions"),
        "privacy_policy_url": _require(args, "privacy_policy_url"),
    }
    follow_up = _opt(args, "follow_up_action_url")
    if follow_up is not None:
        kwargs["follow_up_action_url"] = follow_up
    result = await client.create_lead_form(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_leads_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    form_id = _require(args, "form_id")
    result = await client.get_leads(form_id, limit=_opt(args, "limit", 100))
    return _json_result(result)


@api_error_handler
async def handle_leads_get_by_ad(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    result = await client.get_ad_leads(ad_id, limit=_opt(args, "limit", 100))
    return _json_result(result)


# ---------------------------------------------------------------------------
# 画像アップロード ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_images_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    name = _opt(args, "name")
    result = await client.upload_ad_image_file(file_path, name=name)
    return _json_result(result)


# ---------------------------------------------------------------------------
# 動画・カルーセル・コレクション ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_videos_upload(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    video_url = _require(args, "video_url")
    title = _opt(args, "title")
    result = await client.upload_ad_video(video_url, title=title)
    return _json_result(result)


@api_error_handler
async def handle_videos_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    title = _opt(args, "title")
    result = await client.upload_ad_video_file(file_path, title=title)
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_carousel(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_carousel_creative(
        page_id=_require(args, "page_id"),
        cards=_require(args, "cards"),
        link=_require(args, "link"),
        name=_opt(args, "name"),
    )
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_collection(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_collection_creative(
        page_id=_require(args, "page_id"),
        product_ids=_require(args, "product_ids"),
        link=_require(args, "link"),
        cover_image_hash=_opt(args, "cover_image_hash"),
        cover_video_id=_opt(args, "cover_video_id"),
        name=_opt(args, "name"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# ページ投稿ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_page_posts_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    result = await client.list_page_posts(page_id, limit=_opt(args, "limit", 25))
    return _json_result(result)


@api_error_handler
async def handle_page_posts_boost(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    post_id = _require(args, "post_id")
    ad_set_id = _require(args, "ad_set_id")
    name = _opt(args, "name")
    result = await client.boost_post(
        page_id=page_id, post_id=post_id, ad_set_id=ad_set_id, name=name
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Instagramハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_instagram_accounts(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_instagram_accounts()
    return _json_result(result)


@api_error_handler
async def handle_instagram_media(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ig_user_id = _require(args, "ig_user_id")
    result = await client.list_instagram_media(
        ig_user_id, limit=_opt(args, "limit", 25)
    )
    return _json_result(result)


@api_error_handler
async def handle_instagram_boost(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ig_user_id = _require(args, "ig_user_id")
    media_id = _require(args, "media_id")
    ad_set_id = _require(args, "ad_set_id")
    name = _opt(args, "name")
    result = await client.boost_instagram_post(
        ig_user_id=ig_user_id, media_id=media_id, ad_set_id=ad_set_id, name=name
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Split Test (A/Bテスト) ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_split_tests_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_split_tests(limit=_opt(args, "limit", 50))
    return _json_result(result)


@api_error_handler
async def handle_split_tests_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    study_id = _require(args, "study_id")
    result = await client.get_split_test(study_id)
    return _json_result(result)


@api_error_handler
async def handle_split_tests_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "cells": _require(args, "cells"),
        "objectives": _require(args, "objectives"),
        "start_time": _require(args, "start_time"),
        "end_time": _require(args, "end_time"),
    }
    confidence = _opt(args, "confidence_level")
    if confidence is not None:
        kwargs["confidence_level"] = confidence
    description = _opt(args, "description")
    if description is not None:
        kwargs["description"] = description
    result = await client.create_split_test(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_split_tests_end(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    study_id = _require(args, "study_id")
    result = await client.end_split_test(study_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad Rules (自動ルール) ハンドラー
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_rules_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_rules(limit=_opt(args, "limit", 50))
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    result = await client.get_ad_rule(rule_id)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "evaluation_spec": _require(args, "evaluation_spec"),
        "execution_spec": _require(args, "execution_spec"),
    }
    schedule_spec = _opt(args, "schedule_spec")
    if schedule_spec is not None:
        kwargs["schedule_spec"] = schedule_spec
    status = _opt(args, "status")
    if status is not None:
        kwargs["status"] = status
    result = await client.create_ad_rule(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    updates: dict[str, Any] = {}
    for key in ("name", "evaluation_spec", "execution_spec", "schedule_spec", "status"):
        val = _opt(args, key)
        if val is not None:
            updates[key] = val
    result = await client.update_ad_rule(rule_id, updates)
    return _json_result(result)


@api_error_handler
async def handle_ad_rules_delete(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    rule_id = _require(args, "rule_id")
    result = await client.delete_ad_rule(rule_id)
    return _json_result(result)
