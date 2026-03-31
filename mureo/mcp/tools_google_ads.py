"""Google Ads MCPツール定義

29ツールのツール定義（MCP Tool）を提供する。
ハンドラー実装は _handlers_google_ads.py に分離。
"""

from __future__ import annotations

from typing import Any

from mcp.types import TextContent, Tool

# ハンドラーモジュールを公開（テストからpatch可能にする）
from mureo.mcp._handlers_google_ads import (  # noqa: F401
    HANDLERS as _HANDLERS,
)

# ---------------------------------------------------------------------------
# ツール定義（29個）
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # === キャンペーン ===
    Tool(
        name="google_ads.campaigns.list",
        description="Google Ads キャンペーン一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "status_filter": {
                    "type": "string",
                    "description": "ステータスフィルター（ENABLED/PAUSED）",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.campaigns.get",
        description="Google Ads キャンペーン詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.campaigns.create",
        description="Google Ads キャンペーンを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "name": {"type": "string", "description": "キャンペーン名"},
                "bidding_strategy": {
                    "type": "string",
                    "description": "入札戦略（MAXIMIZE_CLICKS等）",
                },
                "budget_id": {"type": "string", "description": "予算ID"},
            },
            "required": ["customer_id", "name"],
        },
    ),
    Tool(
        name="google_ads.campaigns.update",
        description="Google Ads キャンペーンの設定を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "name": {"type": "string", "description": "新しいキャンペーン名"},
                "bidding_strategy": {"type": "string", "description": "入札戦略"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.campaigns.update_status",
        description="Google Ads キャンペーンのステータスを変更する（ENABLED/PAUSED/REMOVED）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "status": {
                    "type": "string",
                    "description": "新ステータス（ENABLED/PAUSED/REMOVED）",
                },
            },
            "required": ["customer_id", "campaign_id", "status"],
        },
    ),
    Tool(
        name="google_ads.campaigns.diagnose",
        description="Google Ads キャンペーンの配信状態を総合診断する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 広告グループ ===
    Tool(
        name="google_ads.ad_groups.list",
        description="Google Ads 広告グループ一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "status_filter": {
                    "type": "string",
                    "description": "ステータスフィルター",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.ad_groups.create",
        description="Google Ads 広告グループを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "所属キャンペーンID"},
                "name": {"type": "string", "description": "広告グループ名"},
                "cpc_bid_micros": {
                    "type": "integer",
                    "description": "CPC入札額（マイクロ単位）",
                },
            },
            "required": ["customer_id", "campaign_id", "name"],
        },
    ),
    Tool(
        name="google_ads.ad_groups.update",
        description="Google Ads 広告グループを更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "name": {"type": "string", "description": "新しい名前"},
                "status": {
                    "type": "string",
                    "description": "ステータス（ENABLED/PAUSED）",
                },
                "cpc_bid_micros": {
                    "type": "integer",
                    "description": "CPC入札額（マイクロ単位）",
                },
            },
            "required": ["customer_id", "ad_group_id"],
        },
    ),
    # === 広告 ===
    Tool(
        name="google_ads.ads.list",
        description="Google Ads 広告一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {
                    "type": "string",
                    "description": "広告グループIDでフィルタ",
                },
                "status_filter": {
                    "type": "string",
                    "description": "ステータスフィルター",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.ads.create",
        description="Google Ads レスポンシブ検索広告（RSA）を作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "見出しリスト（3個以上15個以下）",
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "説明文リスト（2個以上4個以下）",
                },
                "final_url": {"type": "string", "description": "最終URL"},
                "path1": {"type": "string", "description": "表示パス1"},
                "path2": {"type": "string", "description": "表示パス2"},
            },
            "required": ["customer_id", "ad_group_id", "headlines", "descriptions"],
        },
    ),
    Tool(
        name="google_ads.ads.update",
        description="Google Ads 広告を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "ad_id": {"type": "string", "description": "広告ID"},
                "headlines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "見出しリスト",
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "説明文リスト",
                },
            },
            "required": ["customer_id", "ad_group_id", "ad_id"],
        },
    ),
    Tool(
        name="google_ads.ads.update_status",
        description="Google Ads 広告のステータスを変更する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "ad_id": {"type": "string", "description": "広告ID"},
                "status": {
                    "type": "string",
                    "description": "新ステータス（ENABLED/PAUSED）",
                },
            },
            "required": ["customer_id", "ad_group_id", "ad_id", "status"],
        },
    ),
    # === キーワード ===
    Tool(
        name="google_ads.keywords.list",
        description="Google Ads キーワード一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "ad_group_id": {
                    "type": "string",
                    "description": "広告グループIDでフィルタ",
                },
                "status_filter": {
                    "type": "string",
                    "description": "ステータスフィルター",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.keywords.add",
        description="Google Ads キーワードを追加する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "match_type": {
                                "type": "string",
                                "description": "BROAD/PHRASE/EXACT",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "追加するキーワードリスト",
                },
            },
            "required": ["customer_id", "ad_group_id", "keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.remove",
        description="Google Ads キーワードを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "criterion_id": {
                    "type": "string",
                    "description": "キーワードのcriterion ID",
                },
            },
            "required": ["customer_id", "ad_group_id", "criterion_id"],
        },
    ),
    Tool(
        name="google_ads.keywords.suggest",
        description="Google Ads キーワード提案（Keyword Planner）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "seed_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "シードキーワードリスト",
                },
                "language_id": {
                    "type": "string",
                    "description": "言語ID（デフォルト: 1005=日本語）",
                },
                "geo_id": {
                    "type": "string",
                    "description": "地域ID（デフォルト: 2392=日本）",
                },
            },
            "required": ["customer_id", "seed_keywords"],
        },
    ),
    Tool(
        name="google_ads.keywords.diagnose",
        description="Google Ads キーワードの品質スコア・配信状況を診断する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 除外キーワード ===
    Tool(
        name="google_ads.negative_keywords.list",
        description="Google Ads 除外キーワード一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.negative_keywords.add",
        description="Google Ads 除外キーワードを追加する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "keywords": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "match_type": {
                                "type": "string",
                                "description": "BROAD/PHRASE/EXACT",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": "追加する除外キーワードリスト",
                },
            },
            "required": ["customer_id", "campaign_id", "keywords"],
        },
    ),
    # === 予算 ===
    Tool(
        name="google_ads.budget.get",
        description="Google Ads キャンペーン予算を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.budget.update",
        description="Google Ads 予算を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "budget_id": {"type": "string", "description": "予算ID"},
                "amount": {"type": "number", "description": "新しい日次予算額"},
            },
            "required": ["customer_id", "budget_id", "amount"],
        },
    ),
    # === 分析 ===
    Tool(
        name="google_ads.performance.report",
        description="Google Ads パフォーマンスレポートを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "period": {
                    "type": "string",
                    "description": "期間（LAST_7_DAYS, LAST_30_DAYS等）",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.search_terms.report",
        description="Google Ads 検索語句レポートを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "ad_group_id": {
                    "type": "string",
                    "description": "広告グループIDでフィルタ",
                },
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.search_terms.review",
        description="Google Ads 検索語句を多段階ルールでレビューし追加・除外候補を提案する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {
                    "type": "string",
                    "description": "期間（デフォルト: LAST_7_DAYS）",
                },
                "target_cpa": {"type": "number", "description": "目標CPA"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.auction_insights.analyze",
        description="Google Ads オークションインサイトを分析する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.cpc.detect_trend",
        description="Google Ads CPC上昇トレンドを検出する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    Tool(
        name="google_ads.device.analyze",
        description="Google Ads デバイス別パフォーマンスを分析する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 画像アセット ===
    Tool(
        name="google_ads.assets.upload_image",
        description="ローカルファイルから画像アセットをGoogle Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "file_path": {"type": "string", "description": "画像ファイルのパス"},
                "name": {"type": "string", "description": "アセット名（省略可）"},
            },
            "required": ["customer_id", "file_path"],
        },
    ),
]

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
