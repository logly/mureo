"""Meta Ads tool definitions — Catalog, products, feeds.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Meta Commerce
Catalogs hold product records that power Dynamic Product Ads (DPA) and
Collection creatives. Products can be added one at a time via the API
or bulk-loaded from a scheduled Feed URL.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments.
_ACCOUNT_ID_PARAM = {
    "type": "string",
    "description": (
        "Meta Ads account ID in the format 'act_XXXXXXXXXX' (e.g. "
        "'act_1234567890'). Optional — falls back to META_ADS_ACCOUNT_ID "
        "from the configured credentials. The leading 'act_' prefix is "
        "required."
    ),
}

TOOLS: list[Tool] = [
    # === Catalog (Product Catalog & DPA) ===
    Tool(
        name="meta_ads_catalogs_list",
        description=(
            "Lists Meta Commerce Catalogs owned by a Business. Returns "
            "id, name, product_count, vertical (commerce / hotels / "
            "flights / home_listings / destinations), and "
            "feed_count per catalog. Read-only. Use this to find a "
            "catalog_id before calling meta_ads_catalogs_get / delete or "
            "managing products / feeds underneath."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "business_id": {
                    "type": "string",
                    "description": (
                        "Meta Business ID that owns the catalogs. "
                        "Catalogs live at the Business level, not the "
                        "ad-account level — the Business ID is required "
                        "here."
                    ),
                },
            },
            "required": ["business_id"],
        },
    ),
    Tool(
        name="meta_ads_catalogs_create",
        description=(
            "Creates a new Product Catalog under a Meta Business. Returns "
            "the new catalog_id. Mutating, reversible via rollback_apply "
            "(rollback deletes the catalog if it has no ads consuming "
            "it). Catalogs are the container — add products individually "
            "via meta_ads_products_add, or schedule bulk imports via "
            "meta_ads_feeds_create."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "business_id": {
                    "type": "string",
                    "description": ("Meta Business ID that will own the new catalog."),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Catalog name shown in Commerce Manager. Must be "
                        "unique within the Business."
                    ),
                },
            },
            "required": ["business_id", "name"],
        },
    ),
    Tool(
        name="meta_ads_catalogs_get",
        description=(
            "Fetches the full detail record for a single Product Catalog. "
            "Returns id, name, product_count, vertical, feed_count, "
            "owner_business_id, and the linked ad_accounts. Read-only. "
            "Call this before meta_ads_catalogs_delete or before building "
            "a Collection creative (meta_ads_creatives_create_collection) "
            "to verify product_count > 0."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": (
                        "Catalog ID as returned by meta_ads_catalogs_list."
                    ),
                },
            },
            "required": ["catalog_id"],
        },
    ),
    Tool(
        name="meta_ads_catalogs_delete",
        description=(
            "Deletes a Product Catalog. Returns a success flag. "
            "Destructive and cascades — all products inside and any DPA "
            "campaigns consuming the catalog lose their product source "
            "and stop serving dynamic ads. Reversible via rollback_apply "
            "only if no ad consuming the catalog has served since "
            "deletion. Always call meta_ads_catalogs_get first to check "
            "product_count and operator-confirm before calling this."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": "Catalog ID to delete.",
                },
            },
            "required": ["catalog_id"],
        },
    ),
    # === Products ===
    Tool(
        name="meta_ads_products_list",
        description=(
            "Lists products in a Product Catalog. Returns id, "
            "retailer_id (advertiser's SKU), name, availability, price, "
            "image_url, brand, and category per product. Read-only. "
            "Default limit 100 (max 1000). Use this to locate product_ids "
            "for use in meta_ads_creatives_create_collection or to audit "
            "feed health (missing price / broken image_url)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": "Catalog whose products to list.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Maximum products returned per call. Default 100, "
                        "max 1000 per Meta Graph API."
                    ),
                },
            },
            "required": ["catalog_id"],
        },
    ),
    Tool(
        name="meta_ads_products_add",
        description=(
            "Adds a single product to a Meta Product Catalog. Returns the "
            "new product_id. Mutating, reversible via rollback_apply. "
            "For bulk ingestion prefer a scheduled feed "
            "(meta_ads_feeds_create) — Meta rate-limits single-product "
            "adds aggressively. Meta requires a stable retailer_id per "
            "product; adding a second product with the same retailer_id "
            "updates the existing record rather than creating a "
            "duplicate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": "Catalog to add the product into.",
                },
                "retailer_id": {
                    "type": "string",
                    "description": (
                        "Advertiser's stable SKU / product identifier. "
                        "Used as the upsert key — a second add with the "
                        "same retailer_id updates the existing product."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Product display name shown in DPA / Collection " "ads."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Product description. Shown on some placements "
                        "and surfaces; Meta also uses it as a weak "
                        "targeting signal."
                    ),
                },
                "availability": {
                    "type": "string",
                    "enum": [
                        "in stock",
                        "out of stock",
                        "preorder",
                        "available for order",
                        "discontinued",
                    ],
                    "description": (
                        "Inventory status. Meta suppresses 'out of stock' "
                        "and 'discontinued' items from DPA delivery."
                    ),
                },
                "condition": {
                    "type": "string",
                    "enum": ["new", "refurbished", "used"],
                    "description": (
                        "Product condition. Required by Meta for catalog "
                        "eligibility in most verticals."
                    ),
                },
                "price": {
                    "type": "string",
                    "description": (
                        "Price as a string with currency code, e.g. "
                        "'1000 JPY', '9.99 USD'. Meta parses the string "
                        "into amount + ISO currency. Must match the "
                        "catalog's supported currencies."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": (
                        "Product landing page URL. Must be HTTPS and "
                        "reachable — Meta periodically probes URLs and "
                        "marks broken ones."
                    ),
                },
                "image_url": {
                    "type": "string",
                    "description": (
                        "Primary product image URL. HTTPS, publicly "
                        "fetchable. Meta recommends at least 500×500px."
                    ),
                },
                "brand": {
                    "type": "string",
                    "description": (
                        "Brand name. Optional but improves match quality "
                        "for broad-intent DPA shoppers."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Category path using Google Product Taxonomy "
                        "format (e.g. 'Apparel & Accessories > "
                        "Clothing > Tops'). Optional but strongly "
                        "recommended for multi-category catalogs."
                    ),
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
        name="meta_ads_products_get",
        description=(
            "Fetches the full detail record for a single catalog product. "
            "Returns id, retailer_id, name, description, availability, "
            "condition, price, currency, url, image_url, brand, category, "
            "review_status (APPROVED / REJECTED / PENDING), and "
            "rejection_reasons when applicable. Read-only. Call this "
            "when DPA delivery stalls for a specific product to check "
            "review_status — rejected products are excluded from ads."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "product_id": {
                    "type": "string",
                    "description": (
                        "Meta-assigned product_id as returned by "
                        "meta_ads_products_list (not the retailer_id)."
                    ),
                },
            },
            "required": ["product_id"],
        },
    ),
    Tool(
        name="meta_ads_products_update",
        description=(
            "Updates one or more fields on an existing catalog product. "
            "Partial update — only supplied fields are changed. Returns "
            "the updated product. Mutating, reversible via rollback_apply "
            "(rollback restores prior field values). For availability "
            "toggles (in stock ↔ out of stock) this is the correct entry "
            "point; for full record replacement call meta_ads.products."
            "add with the same retailer_id (the add is upsert-semantic)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "product_id": {
                    "type": "string",
                    "description": "Meta-assigned product_id to update.",
                },
                "name": {
                    "type": "string",
                    "description": "New product display name.",
                },
                "description": {
                    "type": "string",
                    "description": "New product description.",
                },
                "availability": {
                    "type": "string",
                    "enum": [
                        "in stock",
                        "out of stock",
                        "preorder",
                        "available for order",
                        "discontinued",
                    ],
                    "description": (
                        "New inventory status. Meta suppresses 'out of "
                        "stock' / 'discontinued' from DPA delivery."
                    ),
                },
                "price": {
                    "type": "string",
                    "description": (
                        "New price as 'amount ISO_CURRENCY' (e.g. " "'1200 JPY')."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "New landing page URL (HTTPS).",
                },
                "image_url": {
                    "type": "string",
                    "description": (
                        "New primary image URL (HTTPS, publicly " "fetchable)."
                    ),
                },
                "brand": {
                    "type": "string",
                    "description": "New brand name.",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "New category path in Google Product Taxonomy " "format."
                    ),
                },
            },
            "required": ["product_id"],
        },
    ),
    Tool(
        name="meta_ads_products_delete",
        description=(
            "Deletes a single catalog product. Returns a success flag. "
            "Destructive — DPA / Collection ads that referenced this "
            "product_id will skip it on the next serve cycle. Reversible "
            "via rollback_apply (re-adds with the same retailer_id), but "
            "the Meta-assigned product_id changes on re-add, which can "
            "break hard-coded downstream references. For temporary "
            "suppression use meta_ads_products_update with "
            "availability='out of stock' instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "product_id": {
                    "type": "string",
                    "description": "Product ID to delete.",
                },
            },
            "required": ["product_id"],
        },
    ),
    # === Feeds ===
    Tool(
        name="meta_ads_feeds_list",
        description=(
            "Lists product feeds configured for a Product Catalog. "
            "Returns id, name, schedule (HOURLY / DAILY / WEEKLY), "
            "feed_url, file_name, latest_upload {timestamp, status, "
            "error_count}, and product_count per feed. Read-only. Use "
            "this to audit feed health — a feed with latest_upload.status "
            "= FAILED or high error_count is the most common cause of "
            "missing products in DPA."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": "Catalog whose feeds to list.",
                },
            },
            "required": ["catalog_id"],
        },
    ),
    Tool(
        name="meta_ads_feeds_create",
        description=(
            "Creates a scheduled product feed that imports products into "
            "a catalog from a URL. Returns the new feed_id. Mutating, "
            "reversible via rollback_apply. Feeds run automatically on "
            "the chosen schedule; the first run triggers shortly after "
            "creation. For one-off product adds use "
            "meta_ads_products_add — feeds are for ongoing bulk sync. "
            "Supported feed formats: CSV, TSV, RSS 2.0, Atom 1.0, JSON."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "catalog_id": {
                    "type": "string",
                    "description": "Catalog that will consume the feed.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Feed name shown in Commerce Manager. Should be "
                        "unique within the catalog."
                    ),
                },
                "feed_url": {
                    "type": "string",
                    "description": (
                        "HTTPS URL Meta will fetch on each scheduled run. "
                        "Must be publicly reachable. Meta supports basic "
                        "auth or signed-URL patterns if configured "
                        "separately."
                    ),
                },
                "schedule": {
                    "type": "string",
                    "enum": ["HOURLY", "DAILY", "WEEKLY"],
                    "description": (
                        "How often Meta re-fetches and re-ingests the "
                        "feed. Default DAILY. HOURLY is appropriate for "
                        "fast-moving inventory (fashion flash sales); "
                        "WEEKLY fits evergreen catalogs."
                    ),
                },
            },
            "required": ["catalog_id", "name", "feed_url"],
        },
    ),
]
