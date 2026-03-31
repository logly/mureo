"""Meta Ads ツール定義 — インサイト・分析"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === インサイト ===
    Tool(
        name="meta_ads.insights.report",
        description="Meta Ads パフォーマンスレポートを取得する",
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
                "period": {
                    "type": "string",
                    "description": "期間（today, yesterday, last_7d, last_30d等）",
                },
                "level": {
                    "type": "string",
                    "description": "集計レベル（campaign, adset, ad）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "breakdown": {
                    "type": "string",
                    "description": "ブレイクダウン種別（age, gender等）",
                },
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    # === パフォーマンス分析 ===
    Tool(
        name="meta_ads.analysis.performance",
        description="Meta Ads キャンペーンのパフォーマンスを総合分析する（前期比較・インサイト付き）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンID（省略時はアカウント全体）",
                },
                "period": {
                    "type": "string",
                    "description": "期間（today, yesterday, last_7d, last_30d等）",
                },
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.audience",
        description="Meta Ads 年齢×性別のオーディエンス効率を分析する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {
                    "type": "string",
                    "description": "期間（last_7d, last_30d等）",
                },
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.placements",
        description="Meta Ads 配信面別パフォーマンスを分析する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {
                    "type": "string",
                    "description": "期間（last_7d, last_30d等）",
                },
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.cost",
        description="Meta Ads 広告費増加・CPA悪化の原因を調査する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {
                    "type": "string",
                    "description": "期間（last_7d, last_30d等）",
                },
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.compare_ads",
        description="Meta Ads 広告セット内の広告パフォーマンスをA/B比較する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_set_id": {"type": "string", "description": "広告セットID"},
                "period": {
                    "type": "string",
                    "description": "期間（last_7d, last_30d等）",
                },
            },
            "required": ["account_id", "ad_set_id"],
        },
    ),
    Tool(
        name="meta_ads.analysis.suggest_creative",
        description="Meta Ads 広告パフォーマンスに基づくクリエイティブ改善提案を生成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "period": {
                    "type": "string",
                    "description": "期間（last_7d, last_30d等）",
                },
            },
            "required": ["account_id", "campaign_id"],
        },
    ),
]
