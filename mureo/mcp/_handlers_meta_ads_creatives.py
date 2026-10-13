"""Meta Ads MCP tool handler implementation -- image / video uploads, Page
photos, and carousel / collection creatives.

Separated from _handlers_meta_ads.py to maintain the 800-line limit;
re-exported there for backward compatibility.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    api_error_handler,
)
from mureo.mcp._meta_ads_client import _get_client, _no_meta_creds

# ---------------------------------------------------------------------------
# Image upload handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_images_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")
    _allowed_image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    if not file_path.lower().endswith(_allowed_image_ext):
        raise ValueError(
            f"Unsupported image format. Allowed: {', '.join(_allowed_image_ext)}"
        )
    name = _opt(args, "name")
    result = await client.upload_ad_image_file(file_path, name=name)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Page photo handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_pages_list_photos(args: dict[str, Any]) -> list[TextContent]:
    """List a Page's existing photos to pick a cover_photo_id from (#703).

    Distinct from meta_ads_images_upload_file (ad-account image_hash): an
    Instant Form ``context_card.cover_photo_id`` needs a PAGE photo id.
    """
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    result = await client.list_page_photos(page_id, limit=_opt(args, "limit", 25))
    return _json_result(result)


# ---------------------------------------------------------------------------
# Video, carousel, collection handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_videos_upload(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    video_url = _require(args, "video_url")
    title = _opt(args, "title")
    result = await client.upload_ad_video(video_url, title=title)
    return _json_result(result)


@api_error_handler
async def handle_videos_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")
    # Mirrors mureo.meta_ads._videos._META_ALLOWED_VIDEO_EXTENSIONS, which is
    # the source of truth. ``.flv`` used to be listed here only, so an .flv file
    # passed this gate and was then rejected one layer deeper.
    _allowed_video_ext = (".mp4", ".mov", ".avi", ".wmv", ".mkv")
    if not file_path.lower().endswith(_allowed_video_ext):
        raise ValueError(
            f"Unsupported video format. Allowed: {', '.join(_allowed_video_ext)}"
        )
    title = _opt(args, "title")
    result = await client.upload_ad_video_file(file_path, title=title)
    return _json_result(result)


@api_error_handler
async def handle_videos_get(args: dict[str, Any]) -> list[TextContent]:
    """Get a video's processing status (poll before creating a creative)."""
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    video_id = _require(args, "video_id")
    result = await client.get_ad_video(video_id)
    return _json_result(result)


@api_error_handler
async def handle_videos_thumbnails(args: dict[str, Any]) -> list[TextContent]:
    """List a video's auto-generated thumbnails."""
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    video_id = _require(args, "video_id")
    result = await client.list_ad_video_thumbnails(video_id)
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_carousel(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_carousel_creative(
        page_id=_require(args, "page_id"),
        cards=_require(args, "cards"),
        link=_require(args, "link"),
        name=_opt(args, "name"),
    )
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_collection(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_collection_creative(
        page_id=_require(args, "page_id"),
        product_ids=_require(args, "product_ids"),
        link=_require(args, "link"),
        cover_image_hash=_opt(args, "cover_image_hash"),
        cover_video_id=_opt(args, "cover_video_id"),
        name=_opt(args, "name"),
    )
    return _json_result(result)
