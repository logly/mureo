"""Meta Ads ツール定義 — コンバージョン (CAPI)"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === コンバージョン (CAPI) ===
    Tool(
        name="meta_ads.conversions.send",
        description="Meta Ads Conversions API でコンバージョンイベントを送信する（汎用）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "events": {
                    "type": "array",
                    "description": "イベントデータのリスト",
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_name": {
                                "type": "string",
                                "description": "イベント名（Purchase, Lead等）",
                            },
                            "event_time": {
                                "type": "integer",
                                "description": "イベント発生時刻（UNIXタイムスタンプ）",
                            },
                            "action_source": {
                                "type": "string",
                                "description": "アクションソース（website等）",
                            },
                            "user_data": {
                                "type": "object",
                                "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）",
                            },
                            "custom_data": {
                                "type": "object",
                                "description": "カスタムデータ（currency, value等）",
                            },
                            "event_source_url": {
                                "type": "string",
                                "description": "イベント発生URL",
                            },
                        },
                        "required": [
                            "event_name",
                            "event_time",
                            "action_source",
                            "user_data",
                        ],
                    },
                },
                "test_event_code": {
                    "type": "string",
                    "description": "テストイベントコード（テストモード用）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {
                    "type": "integer",
                    "description": "イベント発生時刻（UNIXタイムスタンプ）",
                },
                "user_data": {
                    "type": "object",
                    "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）",
                },
                "currency": {
                    "type": "string",
                    "description": "通貨コード（USD, JPY等）",
                },
                "value": {"type": "number", "description": "購入金額"},
                "content_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "商品IDリスト",
                },
                "event_source_url": {
                    "type": "string",
                    "description": "イベント発生URL",
                },
                "test_event_code": {
                    "type": "string",
                    "description": "テストイベントコード",
                },
            },
            "required": [
                "account_id",
                "pixel_id",
                "event_time",
                "user_data",
                "currency",
                "value",
            ],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_lead",
        description="Meta Ads Conversions API でリードイベントを送信する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "pixel_id": {"type": "string", "description": "Meta Pixel ID"},
                "event_time": {
                    "type": "integer",
                    "description": "イベント発生時刻（UNIXタイムスタンプ）",
                },
                "user_data": {
                    "type": "object",
                    "description": "ユーザー情報（em, ph等はSHA-256ハッシュ化される）",
                },
                "event_source_url": {
                    "type": "string",
                    "description": "イベント発生URL",
                },
                "test_event_code": {
                    "type": "string",
                    "description": "テストイベントコード",
                },
            },
            "required": ["account_id", "pixel_id", "event_time", "user_data"],
        },
    ),
]
