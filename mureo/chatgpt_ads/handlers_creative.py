"""One coroutine per ChatGPT Ads image upload, ad preview and location search
tool (#995).

Merged into :data:`mureo.chatgpt_ads.handlers.HANDLERS`. The local file is
read by :func:`mureo._image_validation.read_image_file`, the shared image
check in the form that returns the bytes it checked: the file goes to the
platform, so what is sent must be what was checked, and a file whose content
is not identified as the image format its extension names is not sent at
all. Its ``ValueError`` / ``FileNotFoundError`` propagate unchanged. The
check and the read run off the event loop: an image can be tens of
megabytes.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mureo._image_validation import (
    LOCAL_UPLOAD_MAX_IMAGE_BYTES,
    LOCAL_UPLOAD_MAX_IMAGE_LABEL,
    read_image_file,
)
from mureo.chatgpt_ads._validation import integer, path_id
from mureo.chatgpt_ads.tools_creative import (
    DEFAULT_LOCATION_LIMIT,
    MAX_LOCATION_LIMIT,
    MAX_LOCATION_QUERY_CHARS,
    UPLOAD_CONTENT_TYPES,
)

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient
    from mureo.chatgpt_ads.handlers_mutations import Handler

_UPLOAD_EXTENSIONS = frozenset(UPLOAD_CONTENT_TYPES)


async def _images_upload_file(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    file_path = arguments.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        raise ValueError("file_path is required: the path of a local image file")
    path, content = await asyncio.to_thread(
        read_image_file,
        file_path,
        max_size_bytes=LOCAL_UPLOAD_MAX_IMAGE_BYTES,
        max_size_label=LOCAL_UPLOAD_MAX_IMAGE_LABEL,
        allowed_extensions=_UPLOAD_EXTENSIONS,
    )
    return await client.post_file(
        "/upload",
        filename=path.name,
        content=content,
        content_type=UPLOAD_CONTENT_TYPES[path.suffix.lower().lstrip(".")],
    )


async def _ads_preview(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    return await client.post_read(f"/ads/{path_id(arguments, 'ad_id')}/preview")


async def _locations_search(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    query = arguments.get("query")
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > MAX_LOCATION_QUERY_CHARS
    ):
        raise ValueError(
            f"query is required: up to {MAX_LOCATION_QUERY_CHARS} characters, "
            "not all spaces"
        )
    limit = integer(
        arguments.get("limit", DEFAULT_LOCATION_LIMIT), "limit", 1, MAX_LOCATION_LIMIT
    )
    return await client.get("/geo_lookup/search", [("q", query), ("limit", str(limit))])


CREATIVE_HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_images_upload_file": _images_upload_file,
    "chatgpt_ads_ads_preview": _ads_preview,
    "chatgpt_ads_locations_search": _locations_search,
}

__all__ = ["CREATIVE_HANDLERS"]
