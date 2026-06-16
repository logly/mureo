"""Page post operations mixin.

Provides Facebook page post listing and boosting (Boost Post).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from mureo._image_validation import validate_image_file

logger = logging.getLogger(__name__)

# Page-photo upload limits (same envelope as ad-image upload). Superset of
# both existing ad-image lists so a cover image that works for an ad creative
# (e.g. webp) is not rejected here.
_PAGE_PHOTO_MAX_BYTES = 30 * 1024 * 1024  # 30MB
_PAGE_PHOTO_ALLOWED_EXTENSIONS = frozenset(
    {"jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"}
)


class PagePostsMixin:
    """Meta Ads page post operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str
    BASE_URL: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _get_as_page(  # type: ignore[empty-body]
        self, page_id: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def get_page_access_token(  # type: ignore[empty-body]
        self, page_id: str
    ) -> str: ...

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

    async def upload_page_photo(
        self,
        page_id: str,
        *,
        image_url: str | None = None,
        file_path: str | None = None,
        published: bool = False,
    ) -> dict[str, Any]:
        """Upload a photo to a Facebook Page and return its PAGE photo id.

        The Instant Form intro screen (``context_card.cover_photo_id``)
        requires a **Page photo id** — which is DIFFERENT from the ad-account
        ``image_hash`` returned by ``upload_ad_image*``/
        ``meta_ads_images_upload_file`` (that hash is rejected as a cover
        photo). This uploads via ``POST /{page_id}/photos`` using the **Page
        Access Token**, so it needs the ``pages_manage_posts`` permission.
        ``published=False`` stages an unpublished photo (not shown on the page
        timeline) that is still referenceable as a lead-form cover.

        Provide exactly one of ``image_url`` or ``file_path``.

        Returns ``{"photo_id": "<id>"}`` (pass it as
        ``context_card.cover_photo_id``) or ``{"error": "..."}`` on failure.
        """
        if bool(image_url) == bool(file_path):
            raise ValueError(
                "upload_page_photo: provide exactly one of image_url or file_path"
            )

        page_token = await self.get_page_access_token(page_id)
        url = f"{self.BASE_URL}/{page_id}/photos"
        published_str = "true" if published else "false"

        async with httpx.AsyncClient(timeout=60.0) as client:
            if image_url is not None:
                response = await client.post(
                    url,
                    data={
                        "url": image_url,
                        "published": published_str,
                        "access_token": page_token,
                    },
                )
            else:
                assert file_path is not None  # noqa: S101 - xor-guarded above
                path = validate_image_file(
                    file_path,
                    max_size_bytes=_PAGE_PHOTO_MAX_BYTES,
                    max_size_label="30MB",
                    allowed_extensions=_PAGE_PHOTO_ALLOWED_EXTENSIONS,
                )
                with open(path, "rb") as fh:
                    response = await client.post(
                        url,
                        files={"source": (path.name, fh, "application/octet-stream")},
                        data={
                            "published": published_str,
                            "access_token": page_token,
                        },
                    )

        if response.status_code != 200:
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message", "")
            except Exception:
                detail = response.text[:500]
            # Defense-in-depth: the page token is sent in the request body, so
            # Meta does not echo it — but never let the raw-text fallback leak
            # it into a surfaced/logged error string.
            detail = detail.replace(page_token, "***")
            return {
                "error": (
                    f"Page photo upload failed "
                    f"(status={response.status_code}): {detail}"
                )
            }

        photo_id = response.json().get("id", "")
        if not photo_id:
            return {"error": "Page photo upload returned no id"}
        logger.info("Page photo uploaded: page_id=%s photo_id=%s", page_id, photo_id)
        return {"photo_id": photo_id}
