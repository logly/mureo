"""Meta Ads ツール定義 — キャンペーン・広告セット・広告"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === キャンペーン ===
    Tool(
        name="meta_ads.campaigns.list",
        description="Meta Ads キャンペーン一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "status_filter": {
                    "type": "string",
                    "description": "ステータスフィルター（ACTIVE/PAUSED等）",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 50）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "キャンペーン名"},
                "objective": {
                    "type": "string",
                    "description": "キャンペーン目的（CONVERSIONS, LINK_CLICKS等）",
                },
                "status": {
                    "type": "string",
                    "description": "初期ステータス（デフォルト: PAUSED）",
                },
                "daily_budget": {
                    "type": "integer",
                    "description": "日次予算（セント単位）",
                },
                "lifetime_budget": {
                    "type": "integer",
                    "description": "通算予算（セント単位）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "name": {"type": "string", "description": "新しいキャンペーン名"},
                "status": {"type": "string", "description": "ステータス"},
                "daily_budget": {
                    "type": "integer",
                    "description": "日次予算（セント単位）",
                },
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    # === キャンペーン pause / enable ===
    Tool(
        name="meta_ads.campaigns.pause",
        description="Meta Ads キャンペーンを一時停止する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.campaigns.enable",
        description="Meta Ads キャンペーンを有効化（ACTIVE）する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 50）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "所属キャンペーンID"},
                "name": {"type": "string", "description": "広告セット名"},
                "daily_budget": {
                    "type": "integer",
                    "description": "日次予算（セント単位）",
                },
                "billing_event": {
                    "type": "string",
                    "description": "課金イベント（デフォルト: IMPRESSIONS）",
                },
                "optimization_goal": {
                    "type": "string",
                    "description": "最適化目標（デフォルト: REACH）",
                },
                "targeting": {"type": "object", "description": "ターゲティング設定"},
                "status": {
                    "type": "string",
                    "description": "初期ステータス（デフォルト: PAUSED）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "広告セットID"},
                "name": {"type": "string", "description": "新しい名前"},
                "status": {"type": "string", "description": "ステータス"},
                "daily_budget": {
                    "type": "integer",
                    "description": "日次予算（セント単位）",
                },
                "targeting": {"type": "object", "description": "ターゲティング設定"},
            },
            "required": ["account_id", "ad_set_id"],
        },
    ),
    # === 広告セット get / pause / enable ===
    Tool(
        name="meta_ads.ad_sets.get",
        description="Meta Ads 広告セット詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "広告セットID"},
            },
            "required": ["account_id", "ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.pause",
        description="Meta Ads 広告セットを一時停止する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "広告セットID"},
            },
            "required": ["account_id", "ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.ad_sets.enable",
        description="Meta Ads 広告セットを有効化（ACTIVE）する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "広告セットID"},
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {
                    "type": "string",
                    "description": "広告セットIDでフィルタ",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 50）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "所属広告セットID"},
                "name": {"type": "string", "description": "広告名"},
                "creative_id": {"type": "string", "description": "クリエイティブID"},
                "status": {
                    "type": "string",
                    "description": "初期ステータス（デフォルト: PAUSED）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_id": {"type": "string", "description": "広告ID"},
                "name": {"type": "string", "description": "新しい名前"},
                "status": {"type": "string", "description": "ステータス"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
    # === 広告 get / pause / enable ===
    Tool(
        name="meta_ads.ads.get",
        description="Meta Ads 広告詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_id": {"type": "string", "description": "広告ID"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.pause",
        description="Meta Ads 広告を一時停止する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_id": {"type": "string", "description": "広告ID"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
    Tool(
        name="meta_ads.ads.enable",
        description="Meta Ads 広告を有効化（ACTIVE）する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_id": {"type": "string", "description": "広告ID"},
            },
            "required": ["account_id", "ad_id"],
        },
    ),
]
