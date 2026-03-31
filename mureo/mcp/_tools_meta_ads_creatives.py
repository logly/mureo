"""Meta Ads ツール定義 — クリエイティブ・画像・動画"""

from __future__ import annotations

from mcp.types import Tool

TOOLS: list[Tool] = [
    # === クリエイティブ list / create / dynamic / upload_image ===
    Tool(
        name="meta_ads.creatives.list",
        description="Meta Ads AdCreative一覧を取得する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "limit": {
                    "type": "integer",
                    "description": "取得件数上限（デフォルト: 50）",
                },
            },
            "required": ["account_id"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create",
        description="Meta Ads AdCreativeを作成する（画像URL or image_hash指定）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "クリエイティブ名"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "link_url": {"type": "string", "description": "リンク先URL"},
                "image_url": {
                    "type": "string",
                    "description": "画像URL（image_hashと排他）",
                },
                "image_hash": {
                    "type": "string",
                    "description": "アップロード済み画像のハッシュ（image_urlと排他）",
                },
                "message": {"type": "string", "description": "広告本文"},
                "headline": {"type": "string", "description": "見出し"},
                "description": {"type": "string", "description": "説明文"},
                "call_to_action": {
                    "type": "string",
                    "description": "CTAボタンタイプ（LEARN_MORE, SIGN_UP等）",
                },
            },
            "required": ["account_id", "name", "page_id", "link_url"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create_dynamic",
        description="Meta Ads ダイナミッククリエイティブ用AdCreativeを作成する（Meta自動最適化）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "name": {"type": "string", "description": "クリエイティブ名"},
                "page_id": {"type": "string", "description": "FacebookページID"},
                "image_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "画像ハッシュのリスト（2〜10枚推奨）",
                },
                "bodies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "広告本文のリスト",
                },
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "見出しのリスト",
                },
                "link_url": {"type": "string", "description": "リンク先URL"},
                "descriptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "説明文のリスト（任意）",
                },
                "call_to_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CTAタイプのリスト（任意）",
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
        description="画像URLを指定してMeta Adsにアップロードする（image_hashを取得）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "image_url": {
                    "type": "string",
                    "description": "アップロード元の画像URL",
                },
            },
            "required": ["account_id", "image_url"],
        },
    ),
    # === カルーセル・コレクション ===
    Tool(
        name="meta_ads.creatives.create_carousel",
        description="Meta Ads カルーセルクリエイティブを作成する（2〜10枚）",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "page_id": {"type": "string", "description": "FacebookページID"},
                "cards": {
                    "type": "array",
                    "description": "カードのリスト（各要素に link, name, image_hash 等を含む）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "link": {"type": "string", "description": "リンクURL"},
                            "name": {"type": "string", "description": "カード名"},
                            "description": {"type": "string", "description": "説明文"},
                            "image_hash": {
                                "type": "string",
                                "description": "画像ハッシュ",
                            },
                            "image_url": {"type": "string", "description": "画像URL"},
                            "video_id": {"type": "string", "description": "動画ID"},
                        },
                        "required": ["link"],
                    },
                },
                "link": {"type": "string", "description": "メインリンクURL"},
                "name": {"type": "string", "description": "クリエイティブ名（省略可）"},
            },
            "required": ["account_id", "page_id", "cards", "link"],
        },
    ),
    Tool(
        name="meta_ads.creatives.create_collection",
        description="Meta Ads コレクションクリエイティブを作成する",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "page_id": {"type": "string", "description": "FacebookページID"},
                "product_ids": {
                    "type": "array",
                    "description": "商品IDのリスト",
                    "items": {"type": "string"},
                },
                "link": {"type": "string", "description": "メインリンクURL"},
                "cover_image_hash": {
                    "type": "string",
                    "description": "カバー画像ハッシュ（省略可）",
                },
                "cover_video_id": {
                    "type": "string",
                    "description": "カバー動画ID（省略可）",
                },
                "name": {"type": "string", "description": "クリエイティブ名（省略可）"},
            },
            "required": ["account_id", "page_id", "product_ids", "link"],
        },
    ),
    # === 画像アップロード ===
    Tool(
        name="meta_ads.images.upload_file",
        description="ローカルファイルから画像をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "file_path": {"type": "string", "description": "画像ファイルのパス"},
                "name": {"type": "string", "description": "画像名（省略可）"},
            },
            "required": ["account_id", "file_path"],
        },
    ),
    # === 動画アップロード ===
    Tool(
        name="meta_ads.videos.upload",
        description="URL指定で動画をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "video_url": {"type": "string", "description": "動画URL"},
                "title": {"type": "string", "description": "動画タイトル（省略可）"},
            },
            "required": ["account_id", "video_url"],
        },
    ),
    Tool(
        name="meta_ads.videos.upload_file",
        description="ローカルファイルから動画をMeta Adsにアップロードする",
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "広告アカウントID（act_XXXX形式）",
                },
                "file_path": {"type": "string", "description": "動画ファイルのパス"},
                "title": {"type": "string", "description": "動画タイトル（省略可）"},
            },
            "required": ["account_id", "file_path"],
        },
    ),
]
