"""Meta Ads tool definitions — Catalog, products, feeds"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Catalog (Product Catalog & DPA) ===
    Tool(
        name="meta_ads.catalogs.list",
        description="List Meta Ads product catalogs",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "business_id": {"type": "string", "description": "Business ID"},
            },
            "required": ["account_id", "business_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.create",
        description="Create a Meta Ads product catalog",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "business_id": {"type": "string", "description": "Business ID"},
                "name": {"type": "string", "description": "Catalog name"},
            },
            "required": ["account_id", "business_id", "name"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.get",
        description="Get Meta Ads product catalog details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.catalogs.delete",
        description="Delete a Meta Ads product catalog",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    # === Products ===
    Tool(
        name="meta_ads.products.list",
        description="List products in a Meta Ads catalog",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 100)",
                },
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.products.add",
        description="Add a product to a Meta Ads catalog",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
                "retailer_id": {"type": "string", "description": "Product SKU/ID"},
                "name": {"type": "string", "description": "Product name"},
                "description": {"type": "string", "description": "Product description"},
                "availability": {
                    "type": "string",
                    "description": "Availability (in stock, out of stock etc.)",
                },
                "condition": {
                    "type": "string",
                    "description": "Product condition (new, refurbished, used)",
                },
                "price": {"type": "string", "description": "Price (e.g. '1000 JPY')"},
                "url": {"type": "string", "description": "Product URL"},
                "image_url": {"type": "string", "description": "Product image URL"},
                "brand": {"type": "string", "description": "Brand name"},
                "category": {
                    "type": "string",
                    "description": "Category (e.g. 'Clothing > Tops')",
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
        description="Get Meta Ads product details",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "product_id": {"type": "string", "description": "Product ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.update",
        description="Update a Meta Ads product",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "product_id": {"type": "string", "description": "Product ID"},
                "name": {"type": "string", "description": "Product name"},
                "description": {"type": "string", "description": "Product description"},
                "availability": {"type": "string", "description": "Availability"},
                "price": {"type": "string", "description": "Price"},
                "url": {"type": "string", "description": "Product URL"},
                "image_url": {"type": "string", "description": "Product image URL"},
                "brand": {"type": "string", "description": "Brand name"},
                "category": {"type": "string", "description": "Category"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    Tool(
        name="meta_ads.products.delete",
        description="Delete a Meta Ads product",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "product_id": {"type": "string", "description": "Product ID"},
            },
            "required": ["account_id", "product_id"],
        },
    ),
    # === Feeds ===
    Tool(
        name="meta_ads.feeds.list",
        description="List feeds in a Meta Ads catalog",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
            },
            "required": ["account_id", "catalog_id"],
        },
    ),
    Tool(
        name="meta_ads.feeds.create",
        description="Create a feed in a Meta Ads catalog (by URL, with scheduled import)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "catalog_id": {"type": "string", "description": "Catalog ID"},
                "name": {"type": "string", "description": "Feed name"},
                "feed_url": {"type": "string", "description": "Feed URL"},
                "schedule": {
                    "type": "string",
                    "description": "Import schedule (DAILY, HOURLY, WEEKLY. Default: DAILY)",
                },
            },
            "required": ["account_id", "catalog_id", "name", "feed_url"],
        },
    ),
]
