"""Google Ads ツール定義 — キャンペーン・広告グループ・広告・予算・アカウント"""

from __future__ import annotations

from mcp.types import Tool

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
    # === 広告ポリシー詳細 ===
    Tool(
        name="google_ads.ads.policy_details",
        description="Google Ads 広告のポリシー詳細（不承認理由等）を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "ad_id": {"type": "string", "description": "広告ID"},
            },
            "required": ["customer_id", "ad_group_id", "ad_id"],
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
    # === 予算作成 ===
    Tool(
        name="google_ads.budget.create",
        description="Google Ads キャンペーン予算を新規作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "name": {"type": "string", "description": "予算名"},
                "amount": {"type": "number", "description": "日次予算額"},
            },
            "required": ["customer_id", "name", "amount"],
        },
    ),
    # === アカウント ===
    Tool(
        name="google_ads.accounts.list",
        description="Google Ads 管理アカウント一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
            },
            "required": ["customer_id"],
        },
    ),
]
