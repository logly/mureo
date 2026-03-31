"""Google Ads ツール定義 — サイトリンク・コールアウト・コンバージョン・ターゲティング"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === サイトリンク ===
    Tool(
        name="google_ads.sitelinks.list",
        description="Google Ads キャンペーンのサイトリンク一覧を取得する",
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
        name="google_ads.sitelinks.create",
        description="Google Ads サイトリンクを作成しキャンペーンにリンクする",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "link_text": {"type": "string", "description": "リンクテキスト"},
                "final_url": {"type": "string", "description": "最終URL"},
                "description1": {"type": "string", "description": "説明文1"},
                "description2": {"type": "string", "description": "説明文2"},
            },
            "required": ["customer_id", "campaign_id", "link_text", "final_url"],
        },
    ),
    Tool(
        name="google_ads.sitelinks.remove",
        description="Google Ads サイトリンクを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "asset_id": {"type": "string", "description": "アセットID"},
            },
            "required": ["customer_id", "campaign_id", "asset_id"],
        },
    ),
    # === コールアウト ===
    Tool(
        name="google_ads.callouts.list",
        description="Google Ads キャンペーンのコールアウト一覧を取得する",
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
        name="google_ads.callouts.create",
        description="Google Ads コールアウトを作成しキャンペーンにリンクする",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "callout_text": {
                    "type": "string",
                    "description": "コールアウトテキスト",
                },
            },
            "required": ["customer_id", "campaign_id", "callout_text"],
        },
    ),
    Tool(
        name="google_ads.callouts.remove",
        description="Google Ads コールアウトを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "asset_id": {"type": "string", "description": "アセットID"},
            },
            "required": ["customer_id", "campaign_id", "asset_id"],
        },
    ),
    # === コンバージョン ===
    Tool(
        name="google_ads.conversions.list",
        description="Google Ads コンバージョンアクション一覧を取得する",
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
    Tool(
        name="google_ads.conversions.get",
        description="Google Ads コンバージョンアクション詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "コンバージョンアクションID",
                },
            },
            "required": ["customer_id", "conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.performance",
        description="Google Ads コンバージョンアクション別の実績を取得する",
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
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.create",
        description="Google Ads コンバージョンアクションを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "name": {
                    "type": "string",
                    "description": "コンバージョンアクション名",
                },
                "type": {
                    "type": "string",
                    "description": "種別（WEBPAGE/UPLOAD_CLICKS等）",
                },
                "category": {
                    "type": "string",
                    "description": "カテゴリ（PURCHASE/SIGNUP等）",
                },
                "default_value": {
                    "type": "number",
                    "description": "デフォルトコンバージョン値",
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": "常にデフォルト値を使用するか",
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "description": "クリックスルー計測期間（1-90日）",
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "description": "ビュースルー計測期間（1-30日）",
                },
            },
            "required": ["customer_id", "name"],
        },
    ),
    Tool(
        name="google_ads.conversions.update",
        description="Google Ads コンバージョンアクションを更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "コンバージョンアクションID",
                },
                "name": {"type": "string", "description": "新しい名前"},
                "category": {"type": "string", "description": "カテゴリ"},
                "status": {
                    "type": "string",
                    "description": "ステータス（ENABLED/HIDDEN/REMOVED）",
                },
                "default_value": {
                    "type": "number",
                    "description": "デフォルトコンバージョン値",
                },
                "always_use_default_value": {
                    "type": "boolean",
                    "description": "常にデフォルト値を使用するか",
                },
                "click_through_lookback_window_days": {
                    "type": "integer",
                    "description": "クリックスルー計測期間（1-90日）",
                },
                "view_through_lookback_window_days": {
                    "type": "integer",
                    "description": "ビュースルー計測期間（1-30日）",
                },
            },
            "required": ["customer_id", "conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.remove",
        description="Google Ads コンバージョンアクションを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "コンバージョンアクションID",
                },
            },
            "required": ["customer_id", "conversion_action_id"],
        },
    ),
    Tool(
        name="google_ads.conversions.tag",
        description="Google Ads コンバージョンアクションのタグスニペットを取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "conversion_action_id": {
                    "type": "string",
                    "description": "コンバージョンアクションID",
                },
            },
            "required": ["customer_id", "conversion_action_id"],
        },
    ),
    # === 推奨事項 ===
    Tool(
        name="google_ads.recommendations.list",
        description="Google Ads Google推奨事項一覧を取得する",
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
                "recommendation_type": {
                    "type": "string",
                    "description": "推奨事項タイプでフィルタ",
                },
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.recommendations.apply",
        description="Google Ads 推奨事項を適用する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "resource_name": {
                    "type": "string",
                    "description": "推奨事項のリソース名",
                },
            },
            "required": ["customer_id", "resource_name"],
        },
    ),
    # === デバイスターゲティング ===
    Tool(
        name="google_ads.device_targeting.get",
        description="Google Ads キャンペーンのデバイスターゲティング設定を取得する",
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
        name="google_ads.device_targeting.set",
        description="Google Ads デバイスターゲティングを設定する（指定デバイスのみ配信）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "enabled_devices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "有効にするデバイスリスト（MOBILE/DESKTOP/TABLET）",
                },
            },
            "required": ["customer_id", "campaign_id", "enabled_devices"],
        },
    ),
    # === 入札調整 ===
    Tool(
        name="google_ads.bid_adjustments.get",
        description="Google Ads キャンペーンの入札調整率を取得する",
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
        name="google_ads.bid_adjustments.update",
        description="Google Ads 入札調整率を更新する",
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
                    "description": "クライテリオンID",
                },
                "bid_modifier": {
                    "type": "number",
                    "description": "入札調整率（0.1〜10.0）",
                },
            },
            "required": ["customer_id", "campaign_id", "criterion_id", "bid_modifier"],
        },
    ),
    # === 地域ターゲティング ===
    Tool(
        name="google_ads.location_targeting.list",
        description="Google Ads キャンペーンの地域ターゲティング一覧を取得する",
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
        name="google_ads.location_targeting.update",
        description="Google Ads 地域ターゲティングを更新する（追加/削除）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "add_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "追加する地域ID（geoTargetConstants/2392 形式）",
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "削除するcriterion IDリスト",
                },
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 広告スケジュール ===
    Tool(
        name="google_ads.schedule_targeting.list",
        description="Google Ads キャンペーンの広告スケジュール一覧を取得する",
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
        name="google_ads.schedule_targeting.update",
        description="Google Ads 広告スケジュールを更新する（追加/削除）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "add_schedules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {
                                "type": "string",
                                "description": "曜日（MONDAY〜SUNDAY）",
                            },
                            "start_hour": {
                                "type": "integer",
                                "description": "開始時間（0-23）",
                            },
                            "end_hour": {
                                "type": "integer",
                                "description": "終了時間（1-24）",
                            },
                        },
                        "required": ["day"],
                    },
                    "description": "追加するスケジュールリスト",
                },
                "remove_criterion_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "削除するcriterion IDリスト",
                },
            },
            "required": ["customer_id", "campaign_id"],
        },
    ),
    # === 変更履歴 ===
    Tool(
        name="google_ads.change_history.list",
        description="Google Ads 変更履歴一覧を取得する（デフォルト直近14日間）",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "start_date": {
                    "type": "string",
                    "description": "開始日（YYYY-MM-DD）",
                },
                "end_date": {
                    "type": "string",
                    "description": "終了日（YYYY-MM-DD）",
                },
            },
            "required": ["customer_id"],
        },
    ),
]
