"""Meta Ads tool definitions — Creatives, images, videos"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Creative list / create / dynamic / upload_image ===
    Tool(
        name="meta_ads.creatives.list",
        description="List Meta Ads AdCreatives",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 50)",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="meta_ads.creatives.create",
        description="Create a Meta Ads AdCreative (specify image URL or image_hash)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Creative name"},
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "link_url": {"type": "string", "description": "Destination URL"},
                "image_url": {
                    "type": "string",
                    "description": "Image URL (mutually exclusive with image_hash)",
                },
                "image_hash": {
                    "type": "string",
                    "description": "Uploaded image hash (mutually exclusive with image_url)",
                },
                "message": {"type": "string", "description": "Ad body text"},
                "headline": {"type": "string", "description": "Headline"},
                "description": {"type": "string", "description": "Description"},
                "call_to_action": {
                    "type": "string",
                    "description": "CTA button type (LEARN_MORE, SIGN_UP etc.)",
                },
            },
            "required": ["name", "page_id", "link_url"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create_dynamic",
        description="Create a Meta Ads dynamic creative AdCreative (Meta auto-optimization)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "name": {"type": "string", "description": "Creative name"},
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "image_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of image hashes (2 to 10 recommended)",
                },
                "bodies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ad body texts",
                },
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of headlines",
                },
                "link_url": {"type": "string", "description": "Destination URL"},
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of descriptions (optional)",
                },
                "call_to_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of CTA types (optional)",
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
        name="meta_ads.creatives.upload_image",
        description="Upload an image to Meta Ads by URL (to get image_hash)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "image_url": {
                    "type": "string",
                    "description": "Source image URL",
                },
            },
            "required": ["image_url"],
        },
    ),
    # === Carousel & Collection ===
    Tool(
        name="meta_ads.creatives.create_carousel",
        description="Create a Meta Ads carousel creative (2 to 10 cards)",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "cards": {
                    "type": "array",
                    "description": "List of cards (each containing link, name, image_hash etc.)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "link": {"type": "string", "description": "Link URL"},
                            "name": {"type": "string", "description": "Card name"},
                            "description": {
                                "type": "string",
                                "description": "Description",
                            },
                            "image_hash": {
                                "type": "string",
                                "description": "Image hash",
                            },
                            "image_url": {"type": "string", "description": "Image URL"},
                            "video_id": {"type": "string", "description": "Video ID"},
                        },
                        "required": ["link"],
                    },
                },
                "link": {"type": "string", "description": "Main link URL"},
                "name": {"type": "string", "description": "Creative name (optional)"},
            },
            "required": ["page_id", "cards", "link"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create_collection",
        description="Create a Meta Ads collection creative",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "page_id": {"type": "string", "description": "Facebook page ID"},
                "product_ids": {
                    "type": "array",
                    "description": "List of product IDs",
                    "items": {"type": "string"},
                },
                "link": {"type": "string", "description": "Main link URL"},
                "cover_image_hash": {
                    "type": "string",
                    "description": "Cover image hash (optional)",
                },
                "cover_video_id": {
                    "type": "string",
                    "description": "Cover video ID (optional)",
                },
                "name": {"type": "string", "description": "Creative name (optional)"},
            },
            "required": ["page_id", "product_ids", "link"],
        },
    ),
    # === Image upload ===
    Tool(
        name="meta_ads.images.upload_file",
        description="Upload an image to Meta Ads from a local file",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "file_path": {"type": "string", "description": "Image file path"},
                "name": {"type": "string", "description": "Image name (optional)"},
            },
            "required": ["file_path"],
        },
    ),
    # === Video Upload ===
    Tool(
        name="meta_ads.videos.upload",
        description="Upload a video to Meta Ads by URL",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "video_url": {"type": "string", "description": "Video URL"},
                "title": {"type": "string", "description": "Video title (optional)"},
            },
            "required": ["video_url"],
        },
    ),
    Tool(
        name="meta_ads.videos.upload_file",
        description="Upload a video to Meta Ads from a local file",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Ad account ID (act_XXXX format)",
                },
                "file_path": {"type": "string", "description": "Video file path"},
                "title": {"type": "string", "description": "Video title (optional)"},
            },
            "required": ["file_path"],
        },
    ),
]
