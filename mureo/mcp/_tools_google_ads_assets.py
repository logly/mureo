"""Google Ads tool definitions — Image assets"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === Image Assets ===
    Tool(
        name="google_ads.assets.upload_image",
        description="Upload an image asset to Google Ads from a local file",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads customer ID",
                },
                "file_path": {"type": "string", "description": "Image file path"},
                "name": {"type": "string", "description": "Asset name (optional)"},
            },
            "required": ["file_path"],
        },
    ),
]
