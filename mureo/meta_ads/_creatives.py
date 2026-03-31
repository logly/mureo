"""Meta Ads creative operations mixin.

Covers AdCreative creation, image upload, and dynamic creative support.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from mureo._image_validation import validate_image_file, validate_video_file

logger = logging.getLogger(__name__)

# Meta Ads image upload limits
_META_MAX_IMAGE_SIZE_BYTES = 30 * 1024 * 1024  # 30MB
_META_ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "bmp", "tiff"})

# Meta Ads video upload limits
_META_MAX_VIDEO_SIZE_BYTES = 100 * 1024 * 1024  # 100MB (practical limit)
_META_ALLOWED_VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "wmv", "mkv"})

# Carousel card count limits
_CAROUSEL_MIN_CARDS = 2
_CAROUSEL_MAX_CARDS = 10

# AdCreative retrieval fields
_CREATIVE_FIELDS = (
    "id,name,status,title,body,image_url,image_hash,"
    "thumbnail_url,object_story_spec,url_tags"
)


class CreativesMixin:
    """Meta Ads creative operations mixin.

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str
    _access_token: str
    BASE_URL: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_ad_creatives(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List AdCreatives

        Returns:
            List of AdCreative information.
        """
        params: dict[str, Any] = {
            "fields": _CREATIVE_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/adcreatives", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def create_ad_creative(
        self,
        name: str,
        page_id: str,
        link_url: str,
        *,
        image_url: str | None = None,
        image_hash: str | None = None,
        message: str | None = None,
        headline: str | None = None,
        description: str | None = None,
        call_to_action: str | None = None,
    ) -> dict[str, Any]:
        """Create an AdCreative (specify image_url or image_hash)

        Args:
            name: Creative name
            page_id: Facebook page ID
            link_url: Destination link URL
            image_url: Image URL (mutually exclusive with image_hash)
            image_hash: Uploaded image hash (mutually exclusive with image_url)
            message: Ad body text
            headline: Headline
            description: Description text
            call_to_action: CTA button type (LEARN_MORE, SIGN_UP, etc.)

        Returns:
            Created AdCreative information.
        """
        link_data: dict[str, Any] = {
            "link": link_url,
        }

        if image_url:
            link_data["image_url"] = image_url
        elif image_hash:
            link_data["image_hash"] = image_hash

        if message:
            link_data["message"] = message
        if headline:
            link_data["name"] = headline
        if description:
            link_data["description"] = description
        if call_to_action:
            link_data["call_to_action"] = {"type": call_to_action}

        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }

        data: dict[str, Any] = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }

        return await self._post(f"/{self._ad_account_id}/adcreatives", data)

    async def upload_ad_image(
        self,
        image_url: str,
    ) -> dict[str, Any]:
        """Upload an image to Meta API from a URL

        Args:
            image_url: Source image URL

        Returns:
            {"hash": "...", "url": "..."} or {"error": "..."}
        """
        data: dict[str, Any] = {
            "url": image_url,
        }

        result = await self._post(f"/{self._ad_account_id}/adimages", data)

        images = result.get("images")
        if not images or not isinstance(images, dict):
            return {"error": "Image upload failed"}

        # images is in {filename: {hash, url}} format
        first_image = next(iter(images.values()))
        return {
            "hash": first_image.get("hash", ""),
            "url": first_image.get("url", ""),
        }

    async def upload_ad_image_file(
        self,
        file_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Upload an image from a local file.

        Args:
            file_path: Local image file path
            name: Image name (defaults to filename)

        Returns:
            {"hash": "...", "url": "..."} or {"error": "..."}

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: Validation error
        """
        path = validate_image_file(
            file_path,
            max_size_bytes=_META_MAX_IMAGE_SIZE_BYTES,
            max_size_label="30MB",
            allowed_extensions=_META_ALLOWED_IMAGE_EXTENSIONS,
        )

        upload_name = name or path.name
        url = f"{self.BASE_URL}/{self._ad_account_id}/adimages"

        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(path, "rb") as f:
                files = {"filename": (upload_name, f, "application/octet-stream")}
                data = {"access_token": self._access_token}
                response = await client.post(url, files=files, data=data)

        response.raise_for_status()
        result = response.json()

        images = result.get("images")
        if not images or not isinstance(images, dict):
            return {"error": "Image upload failed"}

        first_image = next(iter(images.values()))
        return {
            "hash": first_image.get("hash", ""),
            "url": first_image.get("url", ""),
        }

    async def create_dynamic_creative(
        self,
        name: str,
        page_id: str,
        image_hashes: list[str],
        bodies: list[str],
        titles: list[str],
        link_url: str,
        *,
        descriptions: list[str] | None = None,
        call_to_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a dynamic creative AdCreative

        Registers multiple images, body texts, and headlines; Meta auto-optimizes.

        Args:
            name: Creative name
            page_id: Facebook page ID
            image_hashes: List of image hashes (2-10 recommended)
            bodies: List of ad body texts
            titles: List of headlines
            link_url: Destination link URL
            descriptions: List of descriptions (optional)
            call_to_actions: List of CTA types (optional)

        Returns:
            Created AdCreative information.
        """
        object_story_spec = {
            "page_id": page_id,
            "link_data": {
                "link": link_url,
            },
        }

        asset_feed_spec: dict[str, Any] = {
            "images": [{"hash": h} for h in image_hashes],
            "bodies": [{"text": b} for b in bodies],
            "titles": [{"text": t} for t in titles],
            "link_urls": [{"website_url": link_url}],
        }

        if descriptions:
            asset_feed_spec["descriptions"] = [{"text": d} for d in descriptions]
        if call_to_actions:
            asset_feed_spec["call_to_action_types"] = call_to_actions

        data: dict[str, Any] = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
            "asset_feed_spec": json.dumps(asset_feed_spec),
        }

        return await self._post(f"/{self._ad_account_id}/adcreatives", data)

    # ------------------------------------------------------------------
    # Video upload
    # ------------------------------------------------------------------

    async def upload_ad_video(
        self, video_url: str, title: str | None = None
    ) -> dict[str, Any]:
        """Upload a video from URL

        Args:
            video_url: Source video URL
            title: Video title (optional)

        Returns:
            Response in {"id": "..."} format
        """
        data: dict[str, Any] = {
            "file_url": video_url,
        }
        if title:
            data["title"] = title

        return await self._post(f"/{self._ad_account_id}/advideos", data)

    async def upload_ad_video_file(
        self, file_path: str, title: str | None = None
    ) -> dict[str, Any]:
        """Upload a video from a local file

        Args:
            file_path: Local video file path
            title: Video title (optional)

        Returns:
            Response in {"id": "..."} format

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: Validation error
        """
        path = validate_video_file(
            file_path,
            max_size_bytes=_META_MAX_VIDEO_SIZE_BYTES,
            max_size_label="100MB",
            allowed_extensions=_META_ALLOWED_VIDEO_EXTENSIONS,
        )

        url = f"{self.BASE_URL}/{self._ad_account_id}/advideos"
        upload_data: dict[str, str] = {"access_token": self._access_token}
        if title:
            upload_data["title"] = title

        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(path, "rb") as f:
                files = {"source": (path.name, f, "application/octet-stream")}
                response = await client.post(url, files=files, data=upload_data)

        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Carousel creative
    # ------------------------------------------------------------------

    async def create_carousel_creative(
        self,
        page_id: str,
        cards: list[dict[str, Any]],
        link: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Create a carousel creative

        Args:
            page_id: Facebook page ID
            cards: List of cards (each with link, name, image_hash, etc.)
                   2-10 required
            link: Main link URL
            name: Creative name (optional)

        Returns:
            Created AdCreative information.

        Raises:
            ValueError: If card count is outside the 2-10 range.
        """
        if not (_CAROUSEL_MIN_CARDS <= len(cards) <= _CAROUSEL_MAX_CARDS):
            raise ValueError(f"Carousel requires 2-10 cards (specified: {len(cards)})")

        child_attachments = []
        for card in cards:
            attachment: dict[str, Any] = {
                "link": card["link"],
            }
            if "name" in card:
                attachment["name"] = card["name"]
            if "description" in card:
                attachment["description"] = card["description"]
            if "image_hash" in card:
                attachment["image_hash"] = card["image_hash"]
            if "image_url" in card:
                attachment["image_url"] = card["image_url"]
            if "video_id" in card:
                attachment["video_id"] = card["video_id"]
            child_attachments.append(attachment)

        object_story_spec: dict[str, Any] = {
            "page_id": page_id,
            "link_data": {
                "child_attachments": child_attachments,
                "link": link,
            },
        }

        creative_data: dict[str, Any] = {
            "object_story_spec": json.dumps(object_story_spec),
        }
        if name:
            creative_data["name"] = name

        return await self._post(f"/{self._ad_account_id}/adcreatives", creative_data)

    # ------------------------------------------------------------------
    # Collection creative
    # ------------------------------------------------------------------

    async def create_collection_creative(
        self,
        page_id: str,
        product_ids: list[str],
        link: str,
        cover_image_hash: str | None = None,
        cover_video_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Create a collection creative

        Args:
            page_id: Facebook page ID
            product_ids: List of product IDs
            link: Main link URL
            cover_image_hash: Cover image hash (mutually exclusive with cover_video_id)
            cover_video_id: Cover video ID (mutually exclusive with cover_image_hash)
            name: Creative name (optional)

        Returns:
            Created AdCreative information.
        """
        template_data: dict[str, Any] = {
            "call_to_action": {
                "type": "LEARN_MORE",
                "value": {"link": link},
            },
            "retailer_item_ids": product_ids,
        }

        if cover_video_id:
            template_data["format_option"] = "collection_video"
            template_data["video_id"] = cover_video_id
        elif cover_image_hash:
            template_data["format_option"] = "collection_image"
            template_data["image_hash"] = cover_image_hash

        object_story_spec: dict[str, Any] = {
            "page_id": page_id,
            "template_data": template_data,
        }

        collection_data: dict[str, Any] = {
            "object_story_spec": json.dumps(object_story_spec),
        }
        if name:
            collection_data["name"] = name

        return await self._post(f"/{self._ad_account_id}/adcreatives", collection_data)
