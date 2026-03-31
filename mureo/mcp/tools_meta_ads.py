"""Meta Ads MCPツール定義・ハンドラーマッピング

ツール定義（MCP Tool）とハンドラーディスパッチを提供する。
ハンドラー実装は _handlers_meta_ads.py / _handlers_meta_ads_extended.py に分離。
server.py からディスパッチされる。

ツール定義はカテゴリ別サブモジュールに分割:
  _tools_meta_ads_campaigns.py   — キャンペーン・広告セット・広告
  _tools_meta_ads_creatives.py   — クリエイティブ・画像・動画
  _tools_meta_ads_audiences.py   — オーディエンス・ピクセル
  _tools_meta_ads_insights.py    — インサイト・分析
  _tools_meta_ads_catalog.py     — カタログ・商品・フィード
  _tools_meta_ads_leads.py       — リードフォーム・リード
  _tools_meta_ads_other.py       — スプリットテスト・自動ルール・ページ投稿・Instagram
  _tools_meta_ads_conversions.py — コンバージョン (CAPI)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

from mureo.mcp._handlers_meta_ads import (
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
    handle_lead_forms_create,
    handle_lead_forms_get,
    handle_lead_forms_list,
    handle_leads_get,
    handle_leads_get_by_ad,
    handle_products_add,
    handle_products_delete,
    handle_products_get,
    handle_products_list,
    handle_products_update,
    handle_videos_upload,
    handle_videos_upload_file,
)
from mureo.mcp._handlers_meta_ads_extended import (
    handle_ad_sets_enable,
    handle_ad_sets_get,
    handle_ad_sets_pause,
    handle_ads_enable,
    handle_ads_get,
    handle_ads_pause,
    handle_analysis_audience,
    handle_analysis_compare_ads,
    handle_analysis_cost,
    handle_analysis_performance,
    handle_analysis_placements,
    handle_analysis_suggest_creative,
    handle_audiences_create_lookalike,
    handle_audiences_delete,
    handle_audiences_get,
    handle_campaigns_enable,
    handle_campaigns_pause,
    handle_creatives_create,
    handle_creatives_create_dynamic,
    handle_creatives_list,
    handle_creatives_upload_image,
    handle_pixels_events,
    handle_pixels_get,
    handle_pixels_list,
    handle_pixels_stats,
)
from mureo.mcp._handlers_meta_ads_other import (
    handle_ad_rules_create,
    handle_ad_rules_delete,
    handle_ad_rules_get,
    handle_ad_rules_list,
    handle_ad_rules_update,
    handle_instagram_accounts,
    handle_instagram_boost,
    handle_instagram_media,
    handle_page_posts_boost,
    handle_page_posts_list,
    handle_split_tests_create,
    handle_split_tests_end,
    handle_split_tests_get,
    handle_split_tests_list,
)

# カテゴリ別ツール定義をインポート
from mureo.mcp._tools_meta_ads_audiences import TOOLS as _TOOLS_AUDIENCES
from mureo.mcp._tools_meta_ads_campaigns import TOOLS as _TOOLS_CAMPAIGNS
from mureo.mcp._tools_meta_ads_catalog import TOOLS as _TOOLS_CATALOG
from mureo.mcp._tools_meta_ads_conversions import TOOLS as _TOOLS_CONVERSIONS
from mureo.mcp._tools_meta_ads_creatives import TOOLS as _TOOLS_CREATIVES
from mureo.mcp._tools_meta_ads_insights import TOOLS as _TOOLS_INSIGHTS
from mureo.mcp._tools_meta_ads_leads import TOOLS as _TOOLS_LEADS
from mureo.mcp._tools_meta_ads_other import TOOLS as _TOOLS_OTHER

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ツール定義 — サブモジュールを集約
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = (
    _TOOLS_CAMPAIGNS
    + _TOOLS_INSIGHTS
    + _TOOLS_AUDIENCES
    + _TOOLS_CONVERSIONS
    + _TOOLS_CATALOG
    + _TOOLS_LEADS
    + _TOOLS_CREATIVES
    + _TOOLS_OTHER
)

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
    return await handler(arguments)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# ハンドラーマッピング
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    # キャンペーン
    "meta_ads.campaigns.list": handle_campaigns_list,
    "meta_ads.campaigns.get": handle_campaigns_get,
    "meta_ads.campaigns.create": handle_campaigns_create,
    "meta_ads.campaigns.update": handle_campaigns_update,
    "meta_ads.campaigns.pause": handle_campaigns_pause,
    "meta_ads.campaigns.enable": handle_campaigns_enable,
    # 広告セット
    "meta_ads.ad_sets.list": handle_ad_sets_list,
    "meta_ads.ad_sets.get": handle_ad_sets_get,
    "meta_ads.ad_sets.create": handle_ad_sets_create,
    "meta_ads.ad_sets.update": handle_ad_sets_update,
    "meta_ads.ad_sets.pause": handle_ad_sets_pause,
    "meta_ads.ad_sets.enable": handle_ad_sets_enable,
    # 広告
    "meta_ads.ads.list": handle_ads_list,
    "meta_ads.ads.get": handle_ads_get,
    "meta_ads.ads.create": handle_ads_create,
    "meta_ads.ads.update": handle_ads_update,
    "meta_ads.ads.pause": handle_ads_pause,
    "meta_ads.ads.enable": handle_ads_enable,
    # インサイト
    "meta_ads.insights.report": handle_insights_report,
    "meta_ads.insights.breakdown": handle_insights_breakdown,
    # オーディエンス
    "meta_ads.audiences.list": handle_audiences_list,
    "meta_ads.audiences.get": handle_audiences_get,
    "meta_ads.audiences.create": handle_audiences_create,
    "meta_ads.audiences.delete": handle_audiences_delete,
    "meta_ads.audiences.create_lookalike": handle_audiences_create_lookalike,
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
    # クリエイティブ
    "meta_ads.creatives.list": handle_creatives_list,
    "meta_ads.creatives.create": handle_creatives_create,
    "meta_ads.creatives.create_dynamic": handle_creatives_create_dynamic,
    "meta_ads.creatives.upload_image": handle_creatives_upload_image,
    "meta_ads.creatives.create_carousel": handle_creatives_create_carousel,
    "meta_ads.creatives.create_collection": handle_creatives_create_collection,
    # ピクセル
    "meta_ads.pixels.list": handle_pixels_list,
    "meta_ads.pixels.get": handle_pixels_get,
    "meta_ads.pixels.stats": handle_pixels_stats,
    "meta_ads.pixels.events": handle_pixels_events,
    # 分析
    "meta_ads.analysis.performance": handle_analysis_performance,
    "meta_ads.analysis.audience": handle_analysis_audience,
    "meta_ads.analysis.placements": handle_analysis_placements,
    "meta_ads.analysis.cost": handle_analysis_cost,
    "meta_ads.analysis.compare_ads": handle_analysis_compare_ads,
    "meta_ads.analysis.suggest_creative": handle_analysis_suggest_creative,
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
