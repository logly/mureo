"""Meta Ads ツール定義 — スプリットテスト・自動ルール・ページ投稿・Instagram"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === スプリットテスト (A/Bテスト) ===
    Tool(
        name="meta_ads.split_tests.list",
        description="Meta Ads スプリットテスト（A/Bテスト）一覧を取得する",
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
        name="meta_ads.split_tests.get",
        description="Meta Ads スプリットテスト詳細・結果を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "テスト名"},
                "cells": {
                    "type": "array",
                    "description": "セル定義（各セルにname, adsetsを含む）",
                    "items": {"type": "object"},
                },
                "objectives": {
                    "type": "array",
                    "description": '目的（例: [{"type": "COST_PER_RESULT"}]）',
                    "items": {"type": "object"},
                },
                "start_time": {
                    "type": "string",
                    "description": "開始日時（ISO 8601形式）",
                },
                "end_time": {
                    "type": "string",
                    "description": "終了日時（ISO 8601形式）",
                },
                "confidence_level": {
                    "type": "integer",
                    "description": "信頼度（デフォルト: 95）",
                },
                "description": {"type": "string", "description": "テスト説明"},
            },
            "required": [
                "account_id",
                "name",
                "cells",
                "objectives",
                "start_time",
                "end_time",
            ],
        },
    ),
    Tool(
        name="meta_ads.split_tests.end",
        description="Meta Ads スプリットテストを終了する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
        name="meta_ads.ad_rules.get",
        description="Meta Ads 自動ルール詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "ルール名"},
                "evaluation_spec": {
                    "type": "object",
                    "description": "評価条件（evaluation_type, trigger, filters）",
                },
                "execution_spec": {
                    "type": "object",
                    "description": "実行アクション（execution_type: NOTIFICATION, PAUSE_CAMPAIGN等）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "page_id": {"type": "string", "description": "FacebookページID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 25）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ig_user_id": {"type": "string", "description": "InstagramユーザーID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 25）",
                },
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
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "ig_user_id": {"type": "string", "description": "InstagramユーザーID"},
                "media_id": {"type": "string", "description": "メディアID"},
                "ad_set_id": {"type": "string", "description": "所属広告セットID"},
                "name": {"type": "string", "description": "広告名（省略時は自動生成）"},
            },
            "required": ["account_id", "ig_user_id", "media_id", "ad_set_id"],
        },
    ),
]
