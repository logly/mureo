"""Page post operations mixin.

Provides Facebook page post listing and boosting (Boost Post), plus the
Page-photo read an Instant Form cover is picked from.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Fields requested per Page photo. ``images`` is the array of renditions Meta
#: stores of the same picture; only the largest is surfaced (see
#: :func:`_summarize_page_photo`).
_PAGE_PHOTO_FIELDS = "id,name,created_time,images"


def _largest_rendition(images: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the biggest of the renditions Meta stores of one photo.

    Meta commonly returns them largest-first but does not document that order,
    so the size is measured rather than assumed; a rendition with no
    dimensions sorts last and only wins when it is the only one.
    """
    return max(
        images, key=lambda img: (img.get("width") or 0) * (img.get("height") or 0)
    )


def _summarize_page_photo(photo: dict[str, Any]) -> dict[str, Any] | None:
    """Reduce a Graph photo row to what choosing a cover needs.

    ``images`` holds every rendition Meta stores of the same picture, which is
    noise in a picker; only the largest is worth showing. Returns ``None`` for
    a row with no id — that row cannot be passed as ``cover_photo_id``, so
    offering it could only waste a pick.
    """
    photo_id = photo.get("id")
    if not photo_id:
        return None
    summary: dict[str, Any] = {"id": photo_id}
    for key in ("name", "created_time"):
        if photo.get(key):
            summary[key] = photo[key]
    images = photo.get("images") or []
    if images:
        largest = _largest_rendition(images)
        for src, dest in (("width", "width"), ("height", "height"), ("source", "url")):
            if largest.get(src):
                summary[dest] = largest[src]
    return summary


class PagePostsMixin:
    """Meta Ads page post operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _get_as_page(  # type: ignore[empty-body]
        self, page_id: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    _PAGE_POST_FIELDS = (
        "id,message,created_time,permalink_url,"
        "attachments{media,title,url,type,subattachments}"
    )

    async def list_page_posts(
        self, page_id: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        """List page posts.

        Uses Page Access Token (required by Meta API for new-design pages).

        Args:
            page_id: Facebook page ID
            limit: Maximum number of results (default: 25)

        Returns:
            List of post information
        """
        params: dict[str, Any] = {
            "fields": self._PAGE_POST_FIELDS,
            "limit": limit,
        }
        result = await self._get_as_page(page_id, f"/{page_id}/posts", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def boost_post(
        self,
        page_id: str,
        post_id: str,
        ad_set_id: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Boost a page post (Boost Post).

        Creates an ad by referencing an existing page post via object_story_id.

        Args:
            page_id: Facebook page ID
            post_id: Post ID
            ad_set_id: Parent ad set ID
            name: Ad name (auto-generated if not specified)

        Returns:
            Created ad information
        """
        object_story_id = f"{page_id}_{post_id}"
        ad_name = name if name is not None else f"Boost: {object_story_id}"

        data: dict[str, Any] = {
            "name": ad_name,
            "adset_id": ad_set_id,
            "creative": json.dumps({"object_story_id": object_story_id}),
            "status": "PAUSED",
        }
        return await self._post(f"/{self._ad_account_id}/ads", data)

    async def list_page_photos(
        self, page_id: str, *, limit: int = 25
    ) -> list[dict[str, Any]]:
        """List photos the Page has already uploaded, to pick a cover from.

        The Instant Form intro screen (``context_card.cover_photo_id``)
        requires a **Page photo id** — which is DIFFERENT from the ad-account
        ``image_hash`` returned by ``upload_ad_image*``/
        ``meta_ads_images_upload_file`` (that hash is rejected as a cover
        photo). mureo used to mint one by uploading a new Page photo, which
        needed ``pages_manage_posts``; selecting an existing photo reads with
        ``pages_read_engagement`` + ``pages_show_list`` and a Page Access
        Token (resolved by :meth:`_get_as_page`) instead.

        ``type=uploaded`` is what limits the read to photos the Page owns —
        the default also returns photos the Page was merely tagged in, which
        are not usable as a cover.

        Args:
            page_id: Facebook page ID
            limit: Maximum number of results (default: 25)

        Returns:
            One row per photo: ``id`` always, plus ``name`` / ``created_time``
            and the largest rendition's ``width`` / ``height`` / ``url`` when
            Meta supplies them. Absent fields are omitted rather than nulled.
        """
        params: dict[str, Any] = {
            "type": "uploaded",
            "fields": _PAGE_PHOTO_FIELDS,
            "limit": limit,
        }
        result = await self._get_as_page(page_id, f"/{page_id}/photos", params)
        return [
            summary
            for photo in result.get("data", [])
            if (summary := _summarize_page_photo(photo)) is not None
        ]
