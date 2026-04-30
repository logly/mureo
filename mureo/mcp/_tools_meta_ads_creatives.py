"""Meta Ads tool definitions — Creatives, images, videos.

Tool descriptions follow ``docs/tdqs-style-guide.md``. Creatives are the
visual+copy payload attached to Meta ads; images and videos are the
underlying media assets. Flow: upload media → obtain image_hash /
video_id → create creative → attach creative to an ad via
meta_ads.ads.create.
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

_PAGE_ID_PARAM = {
    "type": "string",
    "description": (
        "Facebook Page ID that the ad will be published as. Must be a "
        "page the authenticated user has permission to post from. "
        "Required by Meta for every creative — ads cannot run without a "
        "page identity."
    ),
}

_CTA_DESCRIPTION = (
    "Call-to-action button label. Valid values include LEARN_MORE, "
    "SIGN_UP, SHOP_NOW, DOWNLOAD, CONTACT_US, SUBSCRIBE, GET_QUOTE, "
    "BOOK_TRAVEL, APPLY_NOW. Omit to render no button (link tap still "
    "works). The valid set depends on the parent campaign's objective."
)

TOOLS: list[Tool] = [
    # === Creative list / create / dynamic / upload_image ===
    Tool(
        name="meta_ads_creatives_list",
        description=(
            "Lists AdCreative resources in a Meta Ads account. Returns id, "
            "name, status, object_story_id, call_to_action_type, and "
            "thumbnail_url per creative. Read-only — does not modify the "
            "account. Default limit is 50 creatives per call (max 1000); "
            "for larger inventories use smaller limits and filter client-"
            "side. Use this to audit creative inventory or to find a "
            "creative_id for reuse in meta_ads.ads.create. To list the ads "
            "that consume these creatives, use meta_ads.ads.list."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Max creatives returned in a single call. Default "
                        "50, maximum 1000 per Meta Graph API."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads_creatives_create",
        description=(
            "Creates a single-image Meta Ads AdCreative. Returns the new "
            "creative's id and object_story_id. Mutating, reversible via "
            "rollback_apply (rollback soft-deletes the creative). Supply "
            "exactly one of image_url or image_hash — image_url triggers "
            "Meta to fetch and host the image; image_hash references an "
            "image already uploaded via meta_ads_creatives_upload_image or "
            "meta_ads.images.upload_file. For multi-image carousels use "
            "meta_ads_creatives_create_carousel; for dynamic / automatic "
            "optimization use meta_ads.creatives.create_dynamic."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": (
                        "Creative name shown in Ads Manager. Internal "
                        "label — not visible to end users."
                    ),
                },
                "page_id": _PAGE_ID_PARAM,
                "link_url": {
                    "type": "string",
                    "description": (
                        "Destination URL the ad links to when tapped. "
                        "Must be HTTPS and domain-verified on the ad "
                        "account."
                    ),
                },
                "image_url": {
                    "type": "string",
                    "description": (
                        "Public HTTPS image URL. Meta fetches and hosts "
                        "the asset. Mutually exclusive with image_hash — "
                        "supply exactly one of them."
                    ),
                },
                "image_hash": {
                    "type": "string",
                    "description": (
                        "Image hash returned from "
                        "meta_ads_creatives_upload_image / "
                        "meta_ads.images.upload_file. Mutually exclusive "
                        "with image_url."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": (
                        "Primary ad body text shown above the image. "
                        "Plain text, emoji allowed. Meta recommends ≤125 "
                        "characters to avoid truncation on mobile."
                    ),
                },
                "headline": {
                    "type": "string",
                    "description": (
                        "Headline shown below the image. ~40 characters "
                        "fits most placements without truncation."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Description / link-caption text shown below the "
                        "headline. Optional; not all placements render it."
                    ),
                },
                "call_to_action": {
                    "type": "string",
                    "enum": [
                        "LEARN_MORE",
                        "SIGN_UP",
                        "SHOP_NOW",
                        "DOWNLOAD",
                        "CONTACT_US",
                        "SUBSCRIBE",
                        "GET_QUOTE",
                        "BOOK_TRAVEL",
                        "APPLY_NOW",
                    ],
                    "description": _CTA_DESCRIPTION,
                },
            },
            "required": ["name", "page_id", "link_url"],
        },
    ),
    Tool(
        name="meta_ads_creatives_create_dynamic",
        description=(
            "Creates a Dynamic Creative — Meta auto-generates and "
            "optimises combinations from multiple images, headlines, "
            "bodies, and CTAs. Returns the new creative id. Mutating, "
            "reversible via rollback.apply. Use when you want Meta to "
            "learn the best-performing asset mix rather than testing "
            "manually. For static single-image ads use "
            "meta_ads_creatives_create; for explicitly-controlled multi-"
            "card layouts use meta_ads.creatives.create_carousel. Supply "
            "2–10 images, 1–5 of each text field; Meta combines them at "
            "serve time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "name": {
                    "type": "string",
                    "description": "Creative name shown in Ads Manager.",
                },
                "page_id": _PAGE_ID_PARAM,
                "image_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                    "description": (
                        "Image hashes to include in the rotation. 2–10 "
                        "recommended for meaningful optimization; Meta "
                        "accepts up to 10. Upload via "
                        "meta_ads_creatives_upload_image / "
                        "meta_ads_images_upload_file first."
                    ),
                },
                "bodies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Primary body text variants. 1–5 accepted. Meta "
                        "recommends ≤125 characters per body."
                    ),
                },
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Headline variants. 1–5 accepted. ~40 characters "
                        "fits most placements."
                    ),
                },
                "link_url": {
                    "type": "string",
                    "description": (
                        "Destination URL shared across all combinations. "
                        "Must be HTTPS and domain-verified."
                    ),
                },
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": (
                        "Optional link-caption variants (0–5). Not all "
                        "placements render these."
                    ),
                },
                "call_to_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5,
                    "description": (
                        "Optional CTA variants (0–5). Values drawn from "
                        "the same set as meta_ads_creatives_create "
                        "(LEARN_MORE / SIGN_UP / SHOP_NOW / etc.)."
                    ),
                },
            },
            "required": [
                "account_id",
                "name",
                "page_id",
                "image_hashes",
                "bodies",
                "titles",
                "link_url",
            ],
        },
    ),
    Tool(
        name="meta_ads_creatives_upload_image",
        description=(
            "Uploads an image to the Meta Ads account by fetching it from "
            "a public HTTPS URL. Returns the image_hash that can be "
            "referenced in meta_ads_creatives_create / create_dynamic / "
            "create_carousel. Mutating — the image is persisted in the "
            "account library. For uploads from local files (not URLs) use "
            "meta_ads_images_upload_file instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "image_url": {
                    "type": "string",
                    "description": (
                        "Public HTTPS URL of the image. Meta fetches it "
                        "once at upload time — subsequent changes to the "
                        "source URL do not affect the stored asset."
                    ),
                },
            },
            "required": ["image_url"],
        },
    ),
    # === Carousel & Collection ===
    Tool(
        name="meta_ads_creatives_create_carousel",
        description=(
            "Creates a Carousel AdCreative with 2–10 swipeable cards. "
            "Returns the new creative id. Mutating, reversible via "
            "rollback.apply. Each card carries its own image (or video), "
            "name, description, and link — useful for product catalogs or "
            "multi-step narratives. For auto-optimized asset rotation use "
            "meta_ads_creatives_create_dynamic; for product-feed-driven "
            "carousels use meta_ads.creatives.create_collection."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": _PAGE_ID_PARAM,
                "cards": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 10,
                    "description": (
                        "Carousel cards (2–10). Each card must have a "
                        "link; image_hash, image_url, or video_id is "
                        "required for the media."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "link": {
                                "type": "string",
                                "description": (
                                    "Destination URL for this card. HTTPS " "required."
                                ),
                            },
                            "name": {
                                "type": "string",
                                "description": ("Card headline shown under the media."),
                            },
                            "description": {
                                "type": "string",
                                "description": ("Card subtitle / link caption."),
                            },
                            "image_hash": {
                                "type": "string",
                                "description": (
                                    "Uploaded image hash for this card. "
                                    "Mutually exclusive with image_url "
                                    "and video_id."
                                ),
                            },
                            "image_url": {
                                "type": "string",
                                "description": (
                                    "Public HTTPS image URL. Mutually "
                                    "exclusive with image_hash and "
                                    "video_id."
                                ),
                            },
                            "video_id": {
                                "type": "string",
                                "description": (
                                    "Uploaded video ID for this card. "
                                    "Mutually exclusive with image_hash "
                                    "and image_url."
                                ),
                            },
                        },
                        "required": ["link"],
                    },
                },
                "link": {
                    "type": "string",
                    "description": (
                        "Main destination URL — used for the See More "
                        "card and as fallback when a card has no "
                        "explicit link."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": ("Creative name shown in Ads Manager. Optional."),
                },
            },
            "required": ["page_id", "cards", "link"],
        },
    ),
    Tool(
        name="meta_ads_creatives_create_collection",
        description=(
            "Creates a Collection AdCreative that pulls products from a "
            "catalog into a mobile-optimized storefront layout. Returns "
            "the new creative id. Mutating, reversible via rollback.apply. "
            "Requires a Meta product catalog with the referenced "
            "product_ids — set up the catalog via meta_ads.catalogs.* "
            "tools first. For static card decks (non-catalog) use "
            "meta_ads_creatives_create_carousel instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "page_id": _PAGE_ID_PARAM,
                "product_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": (
                        "Product IDs drawn from the linked Meta catalog. "
                        "List via meta_ads.products.list."
                    ),
                },
                "link": {
                    "type": "string",
                    "description": (
                        "Main destination URL for the collection. HTTPS " "required."
                    ),
                },
                "cover_image_hash": {
                    "type": "string",
                    "description": (
                        "Cover image hash shown above the product grid. "
                        "Mutually exclusive with cover_video_id — supply "
                        "one or neither."
                    ),
                },
                "cover_video_id": {
                    "type": "string",
                    "description": (
                        "Cover video ID shown above the product grid. "
                        "Mutually exclusive with cover_image_hash."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": ("Creative name shown in Ads Manager. Optional."),
                },
            },
            "required": ["page_id", "product_ids", "link"],
        },
    ),
    # === Image upload ===
    Tool(
        name="meta_ads_images_upload_file",
        description=(
            "Uploads an image from a local file path to the Meta Ads "
            "account library. Returns the image_hash to reference in "
            "creative-construction tools. Mutating — the asset is "
            "persisted. Use this when the image lives on the agent's "
            "local disk; for public-URL uploads use "
            "meta_ads_creatives_upload_image instead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to the image file on the agent's filesystem. "
                        "Meta accepts JPG, PNG, and GIF up to 30 MB."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Optional label stored with the uploaded asset. "
                        "Used only for library organization."
                    ),
                },
            },
            "required": ["file_path"],
        },
    ),
    # === Video Upload ===
    Tool(
        name="meta_ads_videos_upload",
        description=(
            "Uploads a video to the Meta Ads account by fetching it from "
            "a public HTTPS URL. Returns the video_id to reference in "
            "creative-construction tools. Mutating — the asset is "
            "persisted. Meta performs asynchronous processing after "
            "upload; newly-uploaded videos may take a few minutes before "
            "they can be attached to ads. For uploads from local files "
            "use meta_ads.videos.upload_file."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "video_url": {
                    "type": "string",
                    "description": (
                        "Public HTTPS URL of the video. Meta fetches it "
                        "once at upload time. Supported formats: MP4, "
                        "MOV. Recommended max 4 GB."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Optional title stored with the uploaded video. "
                        "Used for library organization; not shown in ads."
                    ),
                },
            },
            "required": ["video_url"],
        },
    ),
    Tool(
        name="meta_ads_videos_upload_file",
        description=(
            "Uploads a video from a local file path to the Meta Ads "
            "account library. Returns the video_id to reference in "
            "creative-construction tools. Mutating. Meta processes the "
            "video asynchronously after upload — allow a few minutes "
            "before attaching the video to ads. For uploads from public "
            "URLs use meta_ads.videos.upload."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to the video file on the agent's filesystem. "
                        "Supported formats: MP4, MOV. Recommended max 4 GB."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Optional title stored with the uploaded video. "
                        "Used for library organization; not shown in ads."
                    ),
                },
            },
            "required": ["file_path"],
        },
    ),
]
