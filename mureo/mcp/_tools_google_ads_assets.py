"""Google Ads ツール定義 — 画像アセット"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === 画像アセット ===
    Tool(
        name="google_ads.assets.upload_image",
        description="ローカルファイルから画像アセットをGoogle Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Google Ads カスタマーID",
                },
                "file_path": {"type": "string", "description": "画像ファイルのパス"},
                "name": {"type": "string", "description": "アセット名（省略可）"},
            },
            "required": ["customer_id", "file_path"],
        },
    ),
]
