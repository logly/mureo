"""Meta Ads MCPツール定義・ハンドラーマッピング

ツール定義（MCP Tool）とハンドラーディスパッチを提供する。
ハンドラー実装は _handlers_meta_ads.py に分離。
server.py からディスパッチされる。
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import TextContent, Tool

from mureo.mcp._handlers_meta_ads import (
    handle_ad_rules_create,
    handle_ad_rules_delete,
    handle_ad_rules_get,
    handle_ad_rules_list,
    handle_ad_rules_update,
    handle_ad_sets_create,
    handle_ad_sets_list,
    handle_ad_sets_update,
    handle_ads_create,
    handle_ads_list,
    handle_ads_update,
    handle_audiences_create,
    handle_audiences_list,
    handle_campaigns_create,
    handle_campaigns_get,
    handle_campaigns_list,
    handle_campaigns_update,
    handle_catalogs_create,
    handle_catalogs_delete,
    handle_catalogs_get,
    handle_catalogs_list,
    handle_conversions_send,
    handle_conversions_send_lead,
    handle_conversions_send_purchase,
    handle_creatives_create_carousel,
    handle_creatives_create_collection,
    handle_feeds_create,
    handle_feeds_list,
    handle_images_upload_file,
    handle_insights_breakdown,
    handle_insights_report,
    handle_instagram_accounts,
    handle_instagram_boost,
    handle_instagram_media,
    handle_lead_forms_create,
    handle_lead_forms_get,
    handle_lead_forms_list,
    handle_leads_get,
    handle_leads_get_by_ad,
    handle_page_posts_boost,
    handle_page_posts_list,
    handle_products_add,
    handle_products_delete,
    handle_products_get,
    handle_products_list,
    handle_products_update,
    handle_split_tests_create,
    handle_split_tests_end,
    handle_split_tests_get,
    handle_split_tests_list,
    handle_videos_upload,
    handle_videos_upload_file,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # === キャンペーン ===
    Tool(
        name="meta_ads.campaigns.list",
        description="Meta Ads キャンペーン一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "status_filter": {"type": "string", "description": "ステータスフィルター（ACTIVE/PAUSED等）"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.get",
        description="Meta Ads キャンペーン詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.create",
        description="Meta Ads キャンペーンを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "name": {"type": "string", "description": "キャンペーン名"},
                "objective": {"type": "string", "description": "キャンペーン目的（CONVERSIONS, LINK_CLICKS等）"},
                "status": {"type": "string", "description": "初期ステータス（デフォルト: PAUSED）"},
                "daily_budget": {"type": "integer", "description": "日次予算（セント単位）"},
                "lifetime_budget": {"type": "integer", "description": "通算予算（セント単位）"},
            },
            "required": ["account_id", "name", "objective"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.update",
        description="Meta Ads キャンペーンを更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "name": {"type": "string", "description": "新しいキャンペーン名"},
                "status": {"type": "string", "description": "ステータス"},
                "daily_budget": {"type": "integer", "description": "日次予算（セント単位）"},
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    # === 広告セット ===
    Tool(
        name="meta_ads.ad_sets.list",
        description="Meta Ads 広告セット一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "キャンペーンIDでフィルタ"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.create",
        description="Meta Ads 広告セットを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "所属キャンペーンID"},
                "name": {"type": "string", "description": "広告セット名"},
                "daily_budget": {"type": "integer", "description": "日次予算（セント単位）"},
                "billing_event": {"type": "string", "description": "課金イベント（デフォルト: IMPRESSIONS）"},
                "optimization_goal": {"type": "string", "description": "最適化目標（デフォルト: REACH）"},
                "targeting": {"type": "object", "description": "ターゲティング設定"},
                "status": {"type": "string", "description": "初期ステータス（デフォルト: PAUSED）"},
            },
            "required": ["account_id", "campaign_id", "name", "daily_budget"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.update",
        description="Meta Ads 広告セットを更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ad_set_id": {"type": "string", "description": "広告セットID"},
                "name": {"type": "string", "description": "新しい名前"},
                "status": {"type": "string", "description": "ステータス"},
                "daily_budget": {"type": "integer", "description": "日次予算（セント単位）"},
                "targeting": {"type": "object", "description": "ターゲティング設定"},
            },
            "required": ["account_id", "ad_set_id"],
        },
    ),
    # === 広告 ===
    Tool(
        name="meta_ads.ads.list",
        description="Meta Ads 広告一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ad_set_id": {"type": "string", "description": "広告セットIDでフィルタ"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.create",
        description="Meta Ads 広告を作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ad_set_id": {"type": "string", "description": "所属広告セットID"},
                "name": {"type": "string", "description": "広告名"},
                "creative_id": {"type": "string", "description": "クリエイティブID"},
                "status": {"type": "string", "description": "初期ステータス（デフォルト: PAUSED）"},
            },
            "required": ["account_id", "ad_set_id", "name", "creative_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.update",
        description="Meta Ads 広告を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ad_id": {"type": "string", "description": "広告ID"},
                "name": {"type": "string", "description": "新しい名前"},
                "status": {"type": "string", "description": "ステータス"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
    # === インサイト ===
    Tool(
        name="meta_ads.insights.report",
        description="Meta Ads パフォーマンスレポートを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "キャンペーンIDでフィルタ"},
                "period": {"type": "string", "description": "期間（today, yesterday, last_7d, last_30d等）"},
                "level": {"type": "string", "description": "集計レベル（campaign, adset, ad）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.insights.breakdown",
        description="Meta Ads ブレイクダウン付きレポートを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "breakdown": {"type": "string", "description": "ブレイクダウン種別（age, gender等）"},
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    # === オーディエンス ===
    Tool(
        name="meta_ads.audiences.list",
        description="Meta Ads カスタムオーディエンス一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.create",
        description="Meta Ads カスタムオーディエンスを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "name": {"type": "string", "description": "オーディエンス名"},
                "subtype": {"type": "string", "description": "サブタイプ（WEBSITE, CUSTOM, APP等）"},
                "description": {"type": "string", "description": "説明"},
                "retention_days": {"type": "integer", "description": "リテンション期間（日数）"},
                "pixel_id": {"type": "string", "description": "Meta PixelID"},
            },
            "required": ["account_id", "name", "subtype"],
        },
    ),
    # === コンバージョン (CAPI) ===
    Tool(
        name="meta_ads.conversions.send",
        description="Meta Ads Conversions API でコンバージョンイベントを送信する（汎用）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "events": {
                    "type": "array",
                    "description": "イベントデータのリスト",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_name": {"type": "string", "description": "イベント名（Purchase, Lead等）"},
                            "event_time": {"type": "integer", "description": "イベント発生時刻（UNIXタイムスタンプ）"},
                            "action_source": {"type": "string", "description": "アクションソース（website等）"},
                            "user_data": {"type": "object", "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）"},
                            "custom_data": {"type": "object", "description": "カスタムデータ（currency, value等）"},
                            "event_source_url": {"type": "string", "description": "イベント発生URL"},
                        },
                        "required": ["event_name", "event_time", "action_source", "user_data"],
                    },
                },
                "test_event_code": {"type": "string", "description": "テストイベントコード（テストモード用）"},
            },
            "required": ["account_id", "pixel_id", "events"],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_purchase",
        description="Meta Ads Conversions API で購入イベントを送信する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {"type": "integer", "description": "イベント発生時刻（UNIXタイムスタンプ）"},
                "user_data": {"type": "object", "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）"},
                "currency": {"type": "string", "description": "通貨コード（USD, JPY等）"},
                "value": {"type": "number", "description": "購入金額"},
                "content_ids": {"type": "array", "items": {"type": "string"}, "description": "商品IDリスト"},
                "event_source_url": {"type": "string", "description": "イベント発生URL"},
                "test_event_code": {"type": "string", "description": "テストイベントコード"},
            },
            "required": ["account_id", "pixel_id", "event_time", "user_data", "currency", "value"],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_lead",
        description="Meta Ads Conversions API でリードイベントを送信する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {"type": "integer", "description": "イベント発生時刻（UNIXタイムスタンプ）"},
                "user_data": {"type": "object", "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）"},
                "event_source_url": {"type": "string", "description": "イベント発生URL"},
                "test_event_code": {"type": "string", "description": "テストイベントコード"},
            },
            "required": ["account_id", "pixel_id", "event_time", "user_data"],
        },
    ),
    # === カタログ（商品カタログ & DPA） ===
    Tool(
        name="meta_ads.catalogs.list",
        description="Meta Ads 商品カタログ一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "business_id": {"type": "string", "description": "ビジネスID"},
            },
            "required": ["account_id", "business_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.create",
        description="Meta Ads 商品カタログを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "business_id": {"type": "string", "description": "ビジネスID"},
                "name": {"type": "string", "description": "カタログ名"},
            },
            "required": ["account_id", "business_id", "name"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.get",
        description="Meta Ads 商品カタログ詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.delete",
        description="Meta Ads 商品カタログを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.products.list",
        description="Meta Ads カタログ内の商品一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 100）"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.products.add",
        description="Meta Ads カタログに商品を追加する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
                "retailer_id": {"type": "string", "description": "商品SKU/ID"},
                "name": {"type": "string", "description": "商品名"},
                "description": {"type": "string", "description": "商品説明"},
                "availability": {"type": "string", "description": "在庫状況（in stock, out of stock等）"},
                "condition": {"type": "string", "description": "商品状態（new, refurbished, used）"},
                "price": {"type": "string", "description": "価格（例: '1000 JPY'）"},
                "url": {"type": "string", "description": "商品URL"},
                "image_url": {"type": "string", "description": "商品画像URL"},
                "brand": {"type": "string", "description": "ブランド名"},
                "category": {"type": "string", "description": "カテゴリ（例: '衣類 > トップス'）"},
            },
            "required": ["account_id", "catalog_id", "retailer_id", "name", "availability", "condition", "price", "url", "image_url"],
        },
    ),
    Tool(
        name="meta_ads.products.get",
        description="Meta Ads 商品詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "product_id": {"type": "string", "description": "商品ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.update",
        description="Meta Ads 商品を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "product_id": {"type": "string", "description": "商品ID"},
                "name": {"type": "string", "description": "商品名"},
                "description": {"type": "string", "description": "商品説明"},
                "availability": {"type": "string", "description": "在庫状況"},
                "price": {"type": "string", "description": "価格"},
                "url": {"type": "string", "description": "商品URL"},
                "image_url": {"type": "string", "description": "商品画像URL"},
                "brand": {"type": "string", "description": "ブランド名"},
                "category": {"type": "string", "description": "カテゴリ"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.delete",
        description="Meta Ads 商品を削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "product_id": {"type": "string", "description": "商品ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.feeds.list",
        description="Meta Ads カタログのフィード一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.feeds.create",
        description="Meta Ads カタログにフィードを作成する（URL指定、スケジュール自動取込）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "catalog_id": {"type": "string", "description": "カタログID"},
                "name": {"type": "string", "description": "フィード名"},
                "feed_url": {"type": "string", "description": "フィードURL"},
                "schedule": {"type": "string", "description": "取込スケジュール（DAILY, HOURLY, WEEKLY。デフォルト: DAILY）"},
            },
            "required": ["account_id", "catalog_id", "name", "feed_url"],
        },
    ),
    # === リード広告 (Lead Ads) ===
    Tool(
        name="meta_ads.lead_forms.list",
        description="Meta Ads リードフォーム一覧を取得する（Page単位）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "Facebook ページID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id", "page_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.get",
        description="Meta Ads リードフォーム詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "form_id": {"type": "string", "description": "リードフォームID"},
            },
            "required": ["account_id", "form_id"],
        },
    ),
    Tool(
        name="meta_ads.lead_forms.create",
        description="Meta Ads リードフォームを作成する（Page単位）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "Facebook ページID"},
                "name": {"type": "string", "description": "フォーム名"},
                "questions": {
                    "type": "array",
                    "description": "質問リスト（FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, CUSTOM等）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "description": "質問タイプ"},
                            "key": {"type": "string", "description": "カスタム質問キー（CUSTOM時のみ）"},
                            "label": {"type": "string", "description": "カスタム質問ラベル（CUSTOM時のみ）"},
                            "options": {
                                "type": "array",
                                "description": "選択肢（CUSTOM時のみ）",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "string"},
                                    },
                                },
                            },
                        },
                        "required": ["type"],
                    },
                },
                "privacy_policy_url": {"type": "string", "description": "プライバシーポリシーURL"},
                "follow_up_action_url": {"type": "string", "description": "フォーム送信後のリダイレクトURL"},
            },
            "required": ["account_id", "page_id", "name", "questions", "privacy_policy_url"],
        },
    ),
    Tool(
        name="meta_ads.leads.get",
        description="Meta Ads リードデータを取得する（フォーム単位）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "form_id": {"type": "string", "description": "リードフォームID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 100）"},
            },
            "required": ["account_id", "form_id"],
        },
    ),
    Tool(
        name="meta_ads.leads.get_by_ad",
        description="Meta Ads 広告別リードデータを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ad_id": {"type": "string", "description": "広告ID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 100）"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
    # === 動画アップロード ===
    Tool(
        name="meta_ads.videos.upload",
        description="URL指定で動画をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "video_url": {"type": "string", "description": "動画URL"},
                "title": {"type": "string", "description": "動画タイトル（省略可）"},
            },
            "required": ["account_id", "video_url"],
        },
    ),
    Tool(
        name="meta_ads.videos.upload_file",
        description="ローカルファイルから動画をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "file_path": {"type": "string", "description": "動画ファイルのパス"},
                "title": {"type": "string", "description": "動画タイトル（省略可）"},
            },
            "required": ["account_id", "file_path"],
        },
    ),
    # === カルーセル・コレクション ===
    Tool(
        name="meta_ads.creatives.create_carousel",
        description="Meta Ads カルーセルクリエイティブを作成する（2〜10枚）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "cards": {
                    "type": "array",
                    "description": "カードのリスト（各要素に link, name, image_hash 等を含む）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "link": {"type": "string", "description": "リンクURL"},
                            "name": {"type": "string", "description": "カード名"},
                            "description": {"type": "string", "description": "説明文"},
                            "image_hash": {"type": "string", "description": "画像ハッシュ"},
                            "image_url": {"type": "string", "description": "画像URL"},
                            "video_id": {"type": "string", "description": "動画ID"},
                        },
                        "required": ["link"],
                    },
                },
                "link": {"type": "string", "description": "メインリンクURL"},
                "name": {"type": "string", "description": "クリエイティブ名（省略可）"},
            },
            "required": ["account_id", "page_id", "cards", "link"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create_collection",
        description="Meta Ads コレクションクリエイティブを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "product_ids": {
                    "type": "array",
                    "description": "商品IDのリスト",
                    "items": {"type": "string"},
                },
                "link": {"type": "string", "description": "メインリンクURL"},
                "cover_image_hash": {"type": "string", "description": "カバー画像ハッシュ（省略可）"},
                "cover_video_id": {"type": "string", "description": "カバー動画ID（省略可）"},
                "name": {"type": "string", "description": "クリエイティブ名（省略可）"},
            },
            "required": ["account_id", "page_id", "product_ids", "link"],
        },
    ),
    # === 画像アップロード ===
    Tool(
        name="meta_ads.images.upload_file",
        description="ローカルファイルから画像をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "file_path": {"type": "string", "description": "画像ファイルのパス"},
                "name": {"type": "string", "description": "画像名（省略可）"},
            },
            "required": ["account_id", "file_path"],
        },
    ),
    # === スプリットテスト (A/Bテスト) ===
    Tool(
        name="meta_ads.split_tests.list",
        description="Meta Ads スプリットテスト（A/Bテスト）一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.split_tests.get",
        description="Meta Ads スプリットテスト詳細・結果を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "study_id": {"type": "string", "description": "スタディID"},
            },
            "required": ["account_id", "study_id"],
        },
    ),
    Tool(
        name="meta_ads.split_tests.create",
        description="Meta Ads スプリットテスト（A/Bテスト）を作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "name": {"type": "string", "description": "テスト名"},
                "cells": {
                    "type": "array",
                    "description": "セル定義（各セルにname, adsetsを含む）",
                    "items": {"type": "object"},
                },
                "objectives": {
                    "type": "array",
                    "description": "目的（例: [{\"type\": \"COST_PER_RESULT\"}]）",
                    "items": {"type": "object"},
                },
                "start_time": {"type": "string", "description": "開始日時（ISO 8601形式）"},
                "end_time": {"type": "string", "description": "終了日時（ISO 8601形式）"},
                "confidence_level": {"type": "integer", "description": "信頼度（デフォルト: 95）"},
                "description": {"type": "string", "description": "テスト説明"},
            },
            "required": ["account_id", "name", "cells", "objectives", "start_time", "end_time"],
        },
    ),
    Tool(
        name="meta_ads.split_tests.end",
        description="Meta Ads スプリットテストを終了する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "study_id": {"type": "string", "description": "スタディID"},
            },
            "required": ["account_id", "study_id"],
        },
    ),
    # === 自動ルール (Ad Rules) ===
    Tool(
        name="meta_ads.ad_rules.list",
        description="Meta Ads 自動ルール一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 50）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.get",
        description="Meta Ads 自動ルール詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "rule_id": {"type": "string", "description": "ルールID"},
            },
            "required": ["account_id", "rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.create",
        description="Meta Ads 自動ルールを作成する（CPA高騰アラート・自動停止等）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "name": {"type": "string", "description": "ルール名"},
                "evaluation_spec": {"type": "object", "description": "評価条件（evaluation_type, trigger, filters）"},
                "execution_spec": {"type": "object", "description": "実行アクション（execution_type: NOTIFICATION, PAUSE_CAMPAIGN等）"},
                "schedule_spec": {"type": "object", "description": "スケジュール設定"},
                "status": {"type": "string", "description": "初期ステータス"},
            },
            "required": ["account_id", "name", "evaluation_spec", "execution_spec"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.update",
        description="Meta Ads 自動ルールを更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "rule_id": {"type": "string", "description": "ルールID"},
                "name": {"type": "string", "description": "ルール名"},
                "evaluation_spec": {"type": "object", "description": "評価条件"},
                "execution_spec": {"type": "object", "description": "実行アクション"},
                "schedule_spec": {"type": "object", "description": "スケジュール設定"},
                "status": {"type": "string", "description": "ステータス"},
            },
            "required": ["account_id", "rule_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_rules.delete",
        description="Meta Ads 自動ルールを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "rule_id": {"type": "string", "description": "ルールID"},
            },
            "required": ["account_id", "rule_id"],
        },
    ),
    # === ページ投稿 ===
    Tool(
        name="meta_ads.page_posts.list",
        description="Facebookページの投稿一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 25）"},
            },
            "required": ["account_id", "page_id"],
        },
    ),
    Tool(
        name="meta_ads.page_posts.boost",
        description="Facebookページの投稿を広告化する（Boost Post）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "post_id": {"type": "string", "description": "投稿ID"},
                "ad_set_id": {"type": "string", "description": "所属広告セットID"},
                "name": {"type": "string", "description": "広告名（省略時は自動生成）"},
            },
            "required": ["account_id", "page_id", "post_id", "ad_set_id"],
        },
    ),
    # === Instagram ===
    Tool(
        name="meta_ads.instagram.accounts",
        description="連携Instagramアカウント一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.instagram.media",
        description="Instagram投稿一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ig_user_id": {"type": "string", "description": "InstagramユーザーID"},
                "limit": {"type": "integer", "description": "取得件数上限（デフォルト: 25）"},
            },
            "required": ["account_id", "ig_user_id"],
        },
    ),
    Tool(
        name="meta_ads.instagram.boost",
        description="Instagram投稿を広告化する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "広告アカウントID（act_XXXX形式）"},
                "ig_user_id": {"type": "string", "description": "InstagramユーザーID"},
                "media_id": {"type": "string", "description": "メディアID"},
                "ad_set_id": {"type": "string", "description": "所属広告セットID"},
                "name": {"type": "string", "description": "広告名（省略時は自動生成）"},
            },
            "required": ["account_id", "ig_user_id", "media_id", "ad_set_id"],
        },
    ),
]

# ツール名→インデックスのルックアップテーブル
_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


# ---------------------------------------------------------------------------
# ハンドラーディスパッチ
# ---------------------------------------------------------------------------


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """ツール名に対応するハンドラーを実行する。

    Raises:
        ValueError: 未知のツール名、または必須パラメータの欠損
    """
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")

    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)


# ---------------------------------------------------------------------------
# ハンドラーマッピング
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    # キャンペーン
    "meta_ads.campaigns.list": handle_campaigns_list,
    "meta_ads.campaigns.get": handle_campaigns_get,
    "meta_ads.campaigns.create": handle_campaigns_create,
    "meta_ads.campaigns.update": handle_campaigns_update,
    # 広告セット
    "meta_ads.ad_sets.list": handle_ad_sets_list,
    "meta_ads.ad_sets.create": handle_ad_sets_create,
    "meta_ads.ad_sets.update": handle_ad_sets_update,
    # 広告
    "meta_ads.ads.list": handle_ads_list,
    "meta_ads.ads.create": handle_ads_create,
    "meta_ads.ads.update": handle_ads_update,
    # インサイト
    "meta_ads.insights.report": handle_insights_report,
    "meta_ads.insights.breakdown": handle_insights_breakdown,
    # オーディエンス
    "meta_ads.audiences.list": handle_audiences_list,
    "meta_ads.audiences.create": handle_audiences_create,
    # コンバージョン
    "meta_ads.conversions.send": handle_conversions_send,
    "meta_ads.conversions.send_purchase": handle_conversions_send_purchase,
    "meta_ads.conversions.send_lead": handle_conversions_send_lead,
    # カタログ
    "meta_ads.catalogs.list": handle_catalogs_list,
    "meta_ads.catalogs.create": handle_catalogs_create,
    "meta_ads.catalogs.get": handle_catalogs_get,
    "meta_ads.catalogs.delete": handle_catalogs_delete,
    # 商品
    "meta_ads.products.list": handle_products_list,
    "meta_ads.products.add": handle_products_add,
    "meta_ads.products.get": handle_products_get,
    "meta_ads.products.update": handle_products_update,
    "meta_ads.products.delete": handle_products_delete,
    # フィード
    "meta_ads.feeds.list": handle_feeds_list,
    "meta_ads.feeds.create": handle_feeds_create,
    # リード広告
    "meta_ads.lead_forms.list": handle_lead_forms_list,
    "meta_ads.lead_forms.get": handle_lead_forms_get,
    "meta_ads.lead_forms.create": handle_lead_forms_create,
    "meta_ads.leads.get": handle_leads_get,
    "meta_ads.leads.get_by_ad": handle_leads_get_by_ad,
    # 画像アップロード
    "meta_ads.images.upload_file": handle_images_upload_file,
    # 動画
    "meta_ads.videos.upload": handle_videos_upload,
    "meta_ads.videos.upload_file": handle_videos_upload_file,
    # カルーセル・コレクション
    "meta_ads.creatives.create_carousel": handle_creatives_create_carousel,
    "meta_ads.creatives.create_collection": handle_creatives_create_collection,
    # Split Test (A/Bテスト)
    "meta_ads.split_tests.list": handle_split_tests_list,
    "meta_ads.split_tests.get": handle_split_tests_get,
    "meta_ads.split_tests.create": handle_split_tests_create,
    "meta_ads.split_tests.end": handle_split_tests_end,
    # Ad Rules (自動ルール)
    "meta_ads.ad_rules.list": handle_ad_rules_list,
    "meta_ads.ad_rules.get": handle_ad_rules_get,
    "meta_ads.ad_rules.create": handle_ad_rules_create,
    "meta_ads.ad_rules.update": handle_ad_rules_update,
    "meta_ads.ad_rules.delete": handle_ad_rules_delete,
    # ページ投稿
    "meta_ads.page_posts.list": handle_page_posts_list,
    "meta_ads.page_posts.boost": handle_page_posts_boost,
    # Instagram
    "meta_ads.instagram.accounts": handle_instagram_accounts,
    "meta_ads.instagram.media": handle_instagram_media,
    "meta_ads.instagram.boost": handle_instagram_boost,
}
