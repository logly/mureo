"""Google Ads ツール定義 — パフォーマンス分析・検索語句・オークション・監視・キャプチャ"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
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
    # === ネットワーク別レポート ===
    Tool(
        name="google_ads.network_performance.report",
        description="Google Ads ネットワーク別パフォーマンスレポート（Google検索 vs 検索パートナー）を取得する",
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
    # === 広告単位レポート ===
    Tool(
        name="google_ads.ad_performance.report",
        description="Google Ads 広告単位のパフォーマンスレポートを取得する",
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
                "campaign_id": {
                    "type": "string",
                    "description": "キャンペーンIDでフィルタ",
                },
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id"],
        },
    ),
    # === 検索語句分析 ===
    Tool(
        name="google_ads.search_terms.analyze",
        description="Google Ads 検索語句とキーワードのオーバーラップ・N-gram分布を分析する",
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
    # === パフォーマンス分析 ===
    Tool(
        name="google_ads.performance.analyze",
        description="Google Ads キャンペーンのパフォーマンスを総合分析する",
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
        name="google_ads.cost_increase.investigate",
        description="Google Ads 広告費増加・CPA悪化の原因を調査する",
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
        name="google_ads.health_check.all",
        description="Google Ads 全有効キャンペーンのヘルスチェックを実行する",
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
        name="google_ads.ad_performance.compare",
        description="Google Ads 広告グループ内の広告パフォーマンスを比較する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "ad_group_id": {"type": "string", "description": "広告グループID"},
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id", "ad_group_id"],
        },
    ),
    # === 予算分析 ===
    Tool(
        name="google_ads.budget.efficiency",
        description="Google Ads 全有効キャンペーンの予算配分効率を分析する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id"],
        },
    ),
    Tool(
        name="google_ads.budget.reallocation",
        description="Google Ads 全キャンペーンの予算再配分案を生成する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "period": {"type": "string", "description": "期間"},
            },
            "required": ["customer_id"],
        },
    ),
    # === オークション分析 ===
    Tool(
        name="google_ads.auction_insights.get",
        description="Google Ads キャンペーンのオークション分析データを取得する",
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
    # === RSA分析 ===
    Tool(
        name="google_ads.rsa_assets.analyze",
        description="Google Ads RSA広告のアセット別パフォーマンスを分析する",
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
        name="google_ads.rsa_assets.audit",
        description="Google Ads RSAアセットの棚卸しを行い差し替え・追加の推奨を生成する",
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
    # === BtoB ===
    Tool(
        name="google_ads.btob.optimizations",
        description="Google Ads BtoBビジネス向けの最適化チェックを実行し改善提案を生成する",
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
    # === クリエイティブ ===
    Tool(
        name="google_ads.landing_page.analyze",
        description="ランディングページを解析し構造化データを返す",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "url": {"type": "string", "description": "ランディングページURL"},
            },
            "required": ["customer_id", "url"],
        },
    ),
    Tool(
        name="google_ads.creative.research",
        description="LP解析+既存広告+検索語句+KW提案を一括収集するクリエイティブリサーチ",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "url": {"type": "string", "description": "ランディングページURL"},
                "ad_group_id": {
                    "type": "string",
                    "description": "広告グループIDでフィルタ",
                },
            },
            "required": ["customer_id", "campaign_id", "url"],
        },
    ),
    # === 監視 ===
    Tool(
        name="google_ads.monitoring.delivery_goal",
        description="Google Ads 配信目標を評価し配信状態・パフォーマンスを統合判定する",
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
        name="google_ads.monitoring.cpa_goal",
        description="Google Ads CPA目標に対する現在のパフォーマンスを評価する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "target_cpa": {"type": "number", "description": "目標CPA"},
            },
            "required": ["customer_id", "campaign_id", "target_cpa"],
        },
    ),
    Tool(
        name="google_ads.monitoring.cv_goal",
        description="Google Ads 日次CV目標に対する現在のパフォーマンスを評価する",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "campaign_id": {"type": "string", "description": "キャンペーンID"},
                "target_cv_daily": {
                    "type": "number",
                    "description": "日次CV目標",
                },
            },
            "required": ["customer_id", "campaign_id", "target_cv_daily"],
        },
    ),
    Tool(
        name="google_ads.monitoring.zero_conversions",
        description="Google Ads ゼロコンバージョンの原因を診断する",
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
    # === キャプチャ ===
    Tool(
        name="google_ads.capture.screenshot",
        description="URLのスクリーンショットをPNGで取得する（メッセージマッチ評価用）",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "キャプチャ対象URL"},
            },
            "required": ["url"],
        },
    ),
]
