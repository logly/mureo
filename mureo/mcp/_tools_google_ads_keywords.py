"""Google Ads ツール定義 — キーワード・除外キーワード"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
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
    # === キーワード一時停止 ===
    Tool(
        name="google_ads.keywords.pause",
        description="Google Ads キーワードを一時停止する",
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
    # === 除外キーワード削除 ===
    Tool(
        name="google_ads.negative_keywords.remove",
        description="Google Ads 除外キーワードを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "criterion_id": {
                    "type": "string",
                    "description": "除外キーワードのcriterion ID",
                },
            },
            "required": ["customer_id", "campaign_id", "criterion_id"],
        },
    ),
    # === 広告グループレベル除外キーワード追加 ===
    Tool(
        name="google_ads.negative_keywords.add_to_ad_group",
        description="Google Ads 広告グループレベルの除外キーワードを追加する",
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
                    "description": "追加する除外キーワードリスト",
                },
            },
            "required": ["customer_id", "ad_group_id", "keywords"],
        },
    ),
    # === 除外キーワード自動提案 ===
    Tool(
        name="google_ads.negative_keywords.suggest",
        description="Google Ads 除外キーワード候補を自動提案する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {"type": "string", "description": "期間"},
                "target_cpa": {"type": "number", "description": "目標CPA"},
                "ad_group_id": {
                    "type": "string",
                    "description": "広告グループIDでフィルタ",
                },
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === キーワード棚卸し ===
    Tool(
        name="google_ads.keywords.audit",
        description="Google Ads キーワードの棚卸しを行い改善アクションを提案する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {"type": "string", "description": "期間"},
                "target_cpa": {"type": "number", "description": "目標CPA"},
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 広告グループ間キーワード重複検出 ===
    Tool(
        name="google_ads.keywords.cross_adgroup_duplicates",
        description="Google Ads 広告グループ間のキーワード重複を検出し統合・削除の推奨を返す",
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
]
