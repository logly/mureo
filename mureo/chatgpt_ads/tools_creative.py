"""The ChatGPT Ads image upload, ad preview and location search tools (#995).

Pure data, built by :func:`mureo.chatgpt_ads.tools.build_tool`. The location
search reads. The preview is a POST that changes no campaign, ad group or ad:
the platform renders and saves an expiring preview snapshot, which is why it
is treated as a read (``readOnlyHint``, retried on a 5xx). The upload adds a
file to the account, so it is marked as a change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo._image_validation import LOCAL_UPLOAD_MAX_IMAGE_LABEL
from mureo.chatgpt_ads.tools import build_tool, id_param
from mureo.chatgpt_ads.tools_mutations import MUTATES

if TYPE_CHECKING:
    from mcp.types import Tool

#: Local image files the upload accepts → the content type it sends. The
#: platform takes JPEG, PNG and WebP for creative images.
UPLOAD_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
MAX_LOCATION_QUERY_CHARS = 200
DEFAULT_LOCATION_LIMIT = 20
#: Largest ``limit`` the location search endpoint accepts.
MAX_LOCATION_LIMIT = 100

_IMAGES_UPLOAD_FILE = build_tool(
    "chatgpt_ads_images_upload_file",
    "Uploads one local image file to the ChatGPT Ads account. Returns the "
    "platform object unchanged: file_id, which goes into creative.file_id of "
    "chatgpt_ads_ads_create. Mutates the account (adds a file); not undone by "
    "rollback. Creative images must be JPEG, PNG or WebP and at least 640x640 "
    f"pixels; mureo refuses other extensions and files over "
    f"{LOCAL_UPLOAD_MAX_IMAGE_LABEL} and files whose content is not that "
    "image format before sending anything; the bytes checked are the bytes "
    "sent. An upload is not retried on a 5xx or a transport error.",
    {
        "file_path": {
            "type": "string",
            "minLength": 1,
            "description": (
                "Path of a local .jpg, .jpeg, .png or .webp file (e.g. "
                "'/Users/me/ads/card.png'). Only the file name is sent with "
                "the bytes."
            ),
        }
    },
    ["file_path"],
    annotations=MUTATES,
)

_ADS_PREVIEW = build_tool(
    "chatgpt_ads_ads_preview",
    "Gets a rendered preview of one ChatGPT Ads ad. Returns the platform "
    "object unchanged: data[].body is an HTML iframe snippet that expires "
    "after 24 hours. Changes no campaign, ad group or ad: the platform "
    "renders and saves an expiring preview snapshot. An ad still in draft "
    "cannot be previewed. Use "
    "chatgpt_ads_ads_get for the ad's settings and review status.",
    {"ad_id": id_param("Ad", "ad_123")},
    ["ad_id"],
)

_LOCATIONS_SEARCH = build_tool(
    "chatgpt_ads_locations_search",
    "Searches the ChatGPT Ads location catalog by name. Returns the platform "
    "object unchanged: query, count and results with id, name, "
    "canonical_name, type, country_code and parent fields. Read-only. Pass a "
    "result's id in targeting.locations.include (or excluded_locations) of "
    "chatgpt_ads_campaigns_create; whole countries use ISO codes in "
    "targeting.locations.countries instead.",
    {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_LOCATION_QUERY_CHARS,
            "pattern": r"\S",
            "description": (
                "Location name or part of it (e.g. 'California'), up to "
                f"{MAX_LOCATION_QUERY_CHARS} characters, not all spaces."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_LOCATION_LIMIT,
            "description": (
                f"Maximum results. Default {DEFAULT_LOCATION_LIMIT}. "
                f"Maximum {MAX_LOCATION_LIMIT}."
            ),
        },
    },
    ["query"],
)

CREATIVE_TOOLS: tuple[Tool, ...] = (
    _IMAGES_UPLOAD_FILE,
    _ADS_PREVIEW,
    _LOCATIONS_SEARCH,
)

__all__ = [
    "CREATIVE_TOOLS",
    "DEFAULT_LOCATION_LIMIT",
    "MAX_LOCATION_LIMIT",
    "MAX_LOCATION_QUERY_CHARS",
    "UPLOAD_CONTENT_TYPES",
]
