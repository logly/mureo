"""Meta Ads ツール定義 — オーディエンス・ピクセル"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === オーディエンス ===
    Tool(
        name="meta_ads.audiences.list",
        description="Meta Ads カスタムオーディエンス一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
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
        name="meta_ads.audiences.create",
        description="Meta Ads カスタムオーディエンスを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "オーディエンス名"},
                "subtype": {
                    "type": "string",
                    "description": "サブタイプ（WEBSITE, CUSTOM, APP等）",
                },
                "description": {"type": "string", "description": "説明"},
                "retention_days": {
                    "type": "integer",
                    "description": "リテンション期間（日数）",
                },
                "pixel_id": {"type": "string", "description": "Meta PixelID"},
            },
            "required": ["account_id", "name", "subtype"],
        },
    ),
    # === オーディエンス get / delete / lookalike ===
    Tool(
        name="meta_ads.audiences.get",
        description="Meta Ads カスタムオーディエンス詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "audience_id": {"type": "string", "description": "オーディエンスID"},
            },
            "required": ["account_id", "audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.delete",
        description="Meta Ads カスタムオーディエンスを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "audience_id": {"type": "string", "description": "オーディエンスID"},
            },
            "required": ["account_id", "audience_id"],
        },
    ),
    Tool(
        name="meta_ads.audiences.create_lookalike",
        description="Meta Ads 類似オーディエンスを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "オーディエンス名"},
                "source_audience_id": {
                    "type": "string",
                    "description": "ソースとなるカスタムオーディエンスID",
                },
                "country": {
                    "description": "対象国コード（文字列 or 配列）",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                },
                "ratio": {
                    "type": "number",
                    "description": "類似度（0.01=上位1%, 最大0.20）",
                },
                "starting_ratio": {
                    "type": "number",
                    "description": "類似度の開始位置（デフォルト: 0.0）",
                },
            },
            "required": [
                "account_id",
                "name",
                "source_audience_id",
                "country",
                "ratio",
            ],
        },
    ),
    # === ピクセル ===
    Tool(
        name="meta_ads.pixels.list",
        description="Meta Ads ピクセル一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
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
        name="meta_ads.pixels.get",
        description="Meta Ads ピクセル詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "ピクセルID"},
            },
            "required": ["account_id", "pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.stats",
        description="Meta Ads ピクセルのイベント統計を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "ピクセルID"},
                "period": {
                    "type": "string",
                    "description": "集計期間（last_7d, last_14d, last_30d, last_90d）",
                },
            },
            "required": ["account_id", "pixel_id"],
        },
    ),
    Tool(
        name="meta_ads.pixels.events",
        description="Meta Ads ピクセルで受信しているイベント種別一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "ピクセルID"},
            },
            "required": ["account_id", "pixel_id"],
        },
    ),
]
