"""Google Ads tool definitions — Image assets"""

from __future__ import annotations

from mcp.types import Tool

_CUSTOMER_ID_PARAM = {
    "type": "string",
    "description": (
        "Google Ads customer ID as a 10-digit string without dashes "
        "(e.g. '1234567890'). Optional — falls back to "
        "GOOGLE_ADS_CUSTOMER_ID / GOOGLE_ADS_LOGIN_CUSTOMER_ID from the "
        "configured credentials when omitted."
    ),
}

TOOLS: list[Tool] = [
    # === Image Assets ===
    Tool(
        name="google_ads_assets_upload_image",
        description=(
            "Upload a local image file to Google Ads as an image Asset "
            "for use in Responsive Display Ads or image extensions. "
            "Returns {resource_name ('customers/<cid>/assets/<aid>'), "
            "id (asset id as string), name (asset display name or "
            "basename)}. Mutating — creates a new Asset row in the "
            "customer account; removal must be done through the Google "
            "Ads UI (there is no corresponding delete tool). The file "
            "is validated before upload: max 5 MB, extensions must be "
            "jpg/jpeg/png/gif. Side effect: reads file_path from the "
            "local filesystem of the MCP server host and POSTs the raw "
            "bytes to Google. For creating the ad that references this "
            "asset afterwards use google_ads.ads.create_display."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": _CUSTOMER_ID_PARAM,
                "file_path": {
                    "type": "string",
                    "description": (
                        "Absolute or MCP-server-relative path to the "
                        "image file on the host running mureo "
                        "(e.g. '/Users/me/ads/hero.png'). Must have "
                        "a .jpg/.jpeg/.png/.gif extension and be "
                        "<= 5 MB."
                    ),
                },
                "name": {
                    "type": "string",
                    "maxLength": 128,
                    "description": (
                        "Optional display name for the asset as shown "
                        "in the Google Ads UI. Defaults to the file's "
                        "basename when omitted."
                    ),
                },
            },
            "required": ["file_path"],
        },
    ),
]
