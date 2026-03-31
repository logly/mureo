"""Meta Ads ツール定義 — カタログ・商品・フィード"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === カタログ（商品カタログ & DPA） ===
    Tool(
        name="meta_ads.catalogs.list",
        description="Meta Ads 商品カタログ一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "business_id": {"type": "string", "description": "ビジネスID"},
            },
            "required": ["account_id", "business_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.create",
        description="Meta Ads 商品カタログを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "business_id": {"type": "string", "description": "ビジネスID"},
                "name": {"type": "string", "description": "カタログ名"},
            },
            "required": ["account_id", "business_id", "name"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.get",
        description="Meta Ads 商品カタログ詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.delete",
        description="Meta Ads 商品カタログを削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    # === 商品 ===
    Tool(
        name="meta_ads.products.list",
        description="Meta Ads カタログ内の商品一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 100）",
                },
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.products.add",
        description="Meta Ads カタログに商品を追加する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
                "retailer_id": {"type": "string", "description": "商品SKU/ID"},
                "name": {"type": "string", "description": "商品名"},
                "description": {"type": "string", "description": "商品説明"},
                "availability": {
                    "type": "string",
                    "description": "在庫状況（in stock, out of stock等）",
                },
                "condition": {
                    "type": "string",
                    "description": "商品状態（new, refurbished, used）",
                },
                "price": {"type": "string", "description": "価格（例: '1000 JPY'）"},
                "url": {"type": "string", "description": "商品URL"},
                "image_url": {"type": "string", "description": "商品画像URL"},
                "brand": {"type": "string", "description": "ブランド名"},
                "category": {
                    "type": "string",
                    "description": "カテゴリ（例: '衣類 > トップス'）",
                },
            },
            "required": [
                "account_id",
                "catalog_id",
                "retailer_id",
                "name",
                "availability",
                "condition",
                "price",
                "url",
                "image_url",
            ],
        },
    ),
    Tool(
        name="meta_ads.products.get",
        description="Meta Ads 商品詳細を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "product_id": {"type": "string", "description": "商品ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.update",
        description="Meta Ads 商品を更新する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "product_id": {"type": "string", "description": "商品ID"},
                "name": {"type": "string", "description": "商品名"},
                "description": {"type": "string", "description": "商品説明"},
                "availability": {"type": "string", "description": "在庫状況"},
                "price": {"type": "string", "description": "価格"},
                "url": {"type": "string", "description": "商品URL"},
                "image_url": {"type": "string", "description": "商品画像URL"},
                "brand": {"type": "string", "description": "ブランド名"},
                "category": {"type": "string", "description": "カテゴリ"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.delete",
        description="Meta Ads 商品を削除する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "product_id": {"type": "string", "description": "商品ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    # === フィード ===
    Tool(
        name="meta_ads.feeds.list",
        description="Meta Ads カタログのフィード一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.feeds.create",
        description="Meta Ads カタログにフィードを作成する（URL指定、スケジュール自動取込）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "catalog_id": {"type": "string", "description": "カタログID"},
                "name": {"type": "string", "description": "フィード名"},
                "feed_url": {"type": "string", "description": "フィードURL"},
                "schedule": {
                    "type": "string",
                    "description": "取込スケジュール（DAILY, HOURLY, WEEKLY。デフォルト: DAILY）",
                },
            },
            "required": ["account_id", "catalog_id", "name", "feed_url"],
        },
    ),
]
