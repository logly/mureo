"""Page post operations mixin.

Provides Facebook page post listing and boosting (Boost Post).
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


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
