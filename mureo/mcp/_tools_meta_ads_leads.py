"""Meta Ads ツール定義 — リードフォーム・リード"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === リード広告 (Lead Ads) ===
    Tool(
        name="meta_ads.lead_forms.list",
        description="Meta Ads リードフォーム一覧を取得する（Page単位）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "page_id": {"type": "string", "description": "Facebook ページID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 50）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "page_id": {"type": "string", "description": "Facebook ページID"},
                "name": {"type": "string", "description": "フォーム名"},
                "questions": {
                    "type": "array",
                    "description": "質問リスト（FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, CUSTOM等）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "description": "質問タイプ"},
                            "key": {
                                "type": "string",
                                "description": "カスタム質問キー（CUSTOM時のみ）",
                            },
                            "label": {
                                "type": "string",
                                "description": "カスタム質問ラベル（CUSTOM時のみ）",
                            },
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
                "privacy_policy_url": {
                    "type": "string",
                    "description": "プライバシーポリシーURL",
                },
                "follow_up_action_url": {
                    "type": "string",
                    "description": "フォーム送信後のリダイレクトURL",
                },
            },
            "required": [
                "account_id",
                "page_id",
                "name",
                "questions",
                "privacy_policy_url",
            ],
        },
    ),
    Tool(
        name="meta_ads.leads.get",
        description="Meta Ads リードデータを取得する（フォーム単位）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "form_id": {"type": "string", "description": "リードフォームID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 100）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ad_id": {"type": "string", "description": "広告ID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 100）",
                },
            },
            "required": ["account_id", "ad_id"],
        },
    ),
]
