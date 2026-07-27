"""Meta Ads creative operations mixin.

Covers AdCreative creation, image upload, and dynamic creative support.

The AdVideo node (upload / status / thumbnails) lives in the sibling
:mod:`mureo.meta_ads._videos`. The video-creative *build* helpers below
(``_validate_video_creative_mode`` / ``_build_video_data``) stay here because
they shape an ``/adcreatives`` payload, not an ``/advideos`` request -- which
is why neither module imports the other.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, cast

import httpx

from mureo._image_validation import validate_image_file

logger = logging.getLogger(__name__)

# Meta Ads image upload limits
_META_MAX_IMAGE_SIZE_BYTES = 30 * 1024 * 1024  # 30MB
_META_ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "gif", "bmp", "tiff"})

# Per-request timeout for image uploads. The file may be up to 30MB (base64 of
# that is ~40MB of request body), so this overrides the shared client's shorter
# default to avoid timing out large uploads on slow links.
_META_UPLOAD_TIMEOUT_SECONDS = 60.0

# Max redirect hops when downloading a remote image (each hop is SSRF-validated
# before it is followed; see upload_ad_image).
_MAX_IMAGE_REDIRECTS = 5

# Carousel card count limits
_CAROUSEL_MIN_CARDS = 2
_CAROUSEL_MAX_CARDS = 10

# AdCreative retrieval fields
_CREATIVE_FIELDS = (
    "id,name,status,title,body,image_url,image_hash,"
    "thumbnail_url,object_story_spec,url_tags"
)


def _validate_video_creative_mode(
    *,
    video_id: str | None,
    image_url: str | None,
    image_hash: str | None,
    thumbnail_image_hash: str | None,
    thumbnail_image_url: str | None,
    call_to_action: str | None,
) -> None:
    """Reject ambiguous or incomplete image/video parameter combinations.

    Runs before any network call so a mis-specified creative never reaches
    Meta -- and never triggers the image auto-upload, which would persist an
    asset for a request that cannot succeed.

    Raises:
        ValueError: Both thumbnail forms supplied; a thumbnail without
            ``video_id``; ``video_id`` combined with image parameters; a
            video without a thumbnail (Meta requires one); or a video
            without ``call_to_action`` (the only carrier of the link).
    """
    if thumbnail_image_hash and thumbnail_image_url:
        raise ValueError(
            "video_thumbnail_image_hash and video_thumbnail_image_url "
            "are mutually exclusive — supply exactly one"
        )
    if (thumbnail_image_hash or thumbnail_image_url) and not video_id:
        raise ValueError(
            "video_thumbnail_image_hash / video_thumbnail_image_url "
            "require video_id — they are only used for video creatives"
        )
    if not video_id:
        return

    conflicting = [
        key
        for key, value in (("image_url", image_url), ("image_hash", image_hash))
        if value
    ]
    if conflicting:
        raise ValueError(
            f"video_id cannot be combined with {', '.join(conflicting)} — "
            f"a creative is either a video or an image. Use "
            f"video_thumbnail_image_hash / video_thumbnail_image_url for "
            f"the video thumbnail."
        )
    if not (thumbnail_image_hash or thumbnail_image_url):
        raise ValueError(
            "video creatives require a thumbnail — supply "
            "video_thumbnail_image_hash or video_thumbnail_image_url "
            "(list candidates via list_ad_video_thumbnails)"
        )
    if not call_to_action:
        raise ValueError(
            "video creatives require call_to_action — video_data carries "
            "the destination link only inside call_to_action.value.link, "
            "so without it the required link_url would be silently "
            "discarded and the video would render with no clickable "
            "destination"
        )


def _build_video_data(
    *,
    video_id: str,
    link_url: str,
    thumbnail_image_hash: str | None,
    thumbnail_image_url: str | None,
    message: str | None,
    headline: str | None,
    description: str | None,
    call_to_action: str,
) -> dict[str, Any]:
    """Build ``object_story_spec.video_data`` for a video creative.

    Follows the same idiom as the Lead Ad video branch
    (:meth:`CreativesMixin.create_lead_ad_creative`) minus the lead-form
    specifics: the destination link rides inside
    ``call_to_action.value.link``, which is the only slot Meta's
    ``video_data`` offers for it. ``link_url`` is injected there
    automatically -- the caller passes only the CTA type, exactly as on the
    image path. ``call_to_action`` is mandatory here; the caller is expected
    to have run :func:`_validate_video_creative_mode` first.
    """
    video_data: dict[str, Any] = {"video_id": video_id}
    if thumbnail_image_hash:
        video_data["image_hash"] = thumbnail_image_hash
    else:
        video_data["image_url"] = thumbnail_image_url
    if headline:
        video_data["title"] = headline
    if message:
        video_data["message"] = message
    if description:
        video_data["link_description"] = description
    video_data["call_to_action"] = {
        "type": call_to_action,
        "value": {"link": link_url},
    }
    return video_data


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
        self,
        path: str,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
        files: dict[str, Any] | None = None,
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
        video_id: str | None = None,
        video_thumbnail_image_hash: str | None = None,
        video_thumbnail_image_url: str | None = None,
        message: str | None = None,
        headline: str | None = None,
        description: str | None = None,
        call_to_action: str | None = None,
    ) -> dict[str, Any]:
        """Create a single-image or single-video AdCreative.

        Image mode (default): builds ``object_story_spec.link_data``.

        Video mode (``video_id`` supplied): builds
        ``object_story_spec.video_data``. Two parameters that are
        optional in image mode become **mandatory** here:

        * a thumbnail — exactly one of ``video_thumbnail_image_hash`` /
          ``video_thumbnail_image_url``, because Meta requires one on
          every video creative;
        * ``call_to_action`` — ``video_data`` has no ``link`` field, so
          the destination travels inside
          ``call_to_action.value.link`` and there is nowhere else to put
          it. ``link_url`` is injected there automatically; the caller
          passes only the CTA type, exactly as on the image path.

        Args:
            name: Creative name
            page_id: Facebook page ID
            link_url: Destination link URL
            image_url: Image URL (mutually exclusive with image_hash).
                Image mode only — auto-uploaded to an image_hash.
            image_hash: Uploaded image hash (mutually exclusive with
                image_url). Image mode only.
            video_id: Pre-uploaded, fully processed video ID from
                ``upload_ad_video`` / ``upload_ad_video_file``. Poll
                ``get_ad_video`` until ``status.video_status`` is ready
                before creating the creative. Mutually exclusive with
                ``image_url`` / ``image_hash``.
            video_thumbnail_image_hash: Thumbnail image hash for video
                mode (from ``upload_ad_image`` / ``upload_ad_image_file``).
                Mutually exclusive with ``video_thumbnail_image_url``.
            video_thumbnail_image_url: Thumbnail image URL for video mode
                — e.g. a ``uri`` from ``list_ad_video_thumbnails``.
                Mutually exclusive with ``video_thumbnail_image_hash``.
            message: Ad body text
            headline: Headline. Mapped to ``link_data.name`` in image
                mode and ``video_data.title`` in video mode.
            description: Description text. Mapped to
                ``link_data.description`` in image mode and
                ``video_data.link_description`` in video mode.
            call_to_action: CTA button type (LEARN_MORE, SIGN_UP, etc.).
                Optional in image mode; **required** in video mode,
                where it also carries the destination link.

        Returns:
            Created AdCreative information.

        Raises:
            ValueError: ``video_id`` combined with image parameters; a
                video without a thumbnail; a video without
                ``call_to_action``; both thumbnail forms supplied; or a
                thumbnail supplied without ``video_id``.
        """
        _validate_video_creative_mode(
            video_id=video_id,
            image_url=image_url,
            image_hash=image_hash,
            thumbnail_image_hash=video_thumbnail_image_hash,
            thumbnail_image_url=video_thumbnail_image_url,
            call_to_action=call_to_action,
        )

        if video_id:
            video_data = _build_video_data(
                video_id=video_id,
                link_url=link_url,
                thumbnail_image_hash=video_thumbnail_image_hash,
                thumbnail_image_url=video_thumbnail_image_url,
                message=message,
                headline=headline,
                description=description,
                # cast: the validator above rejects a video creative
                # without a CTA, so it is a str on this path.
                call_to_action=cast("str", call_to_action),
            )
            video_story_spec = {
                "page_id": page_id,
                "video_data": video_data,
            }
            video_creative_data: dict[str, Any] = {
                "name": name,
                "object_story_spec": json.dumps(video_story_spec),
            }
            return await self._post(
                f"/{self._ad_account_id}/adcreatives", video_creative_data
            )

        link_data: dict[str, Any] = {
            "link": link_url,
        }

        if image_url and not image_hash:
            # image_url is no longer supported in link_data.
            # Auto-upload to get image_hash instead.
            upload_result = await self.upload_ad_image(image_url)
            if "hash" in upload_result:
                image_hash = upload_result["hash"]
            else:
                logger.warning(
                    "Auto-upload failed for %s: %s", image_url, upload_result
                )

        if image_hash:
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

    async def create_lead_ad_creative(
        self,
        name: str,
        page_id: str,
        form_id: str,
        link_url: str,
        *,
        image_url: str | None = None,
        image_hash: str | None = None,
        video_id: str | None = None,
        message: str | None = None,
        headline: str | None = None,
        description: str | None = None,
        call_to_action: str = "SIGN_UP",
    ) -> dict[str, Any]:
        """Create an AdCreative wired to a Meta Instant Form (Lead Ad).

        Image mode (default): builds
        ``object_story_spec.link_data.lead_gen_form_id`` so the
        creative can be attached to an Ad whose Ad Set uses
        ``optimization_goal=LEAD_GENERATION`` under a campaign with
        ``objective=OUTCOME_LEADS``.

        Video mode (``video_id`` supplied): builds
        ``object_story_spec.video_data`` with ``lead_gen_form_id``
        nested under ``call_to_action.value`` — Meta routes Instant
        Form attachments for video creatives through that path, not
        ``link_data``.

        Args:
            name: Internal creative label shown in Ads Manager.
            page_id: Facebook Page that owns the Lead Form (the form
                must belong to this Page).
            form_id: Lead Form ID to attach. Get it from
                ``list_lead_forms`` / ``create_lead_form``.
            link_url: Destination URL used as the fallback landing
                page on placements where the in-app form cannot
                render. Required by the API even for pure Lead Ads.
            image_url: Optional public HTTPS image URL — triggers
                auto-upload to ``image_hash``. Image mode only;
                supplying both ``image_url`` and ``video_id`` raises
                ``ValueError`` (caller intent ambiguous).
            image_hash: Optional pre-uploaded image hash from
                ``upload_ad_image`` / ``upload_ad_image_file``. In
                video mode, used as the video thumbnail.
            video_id: Optional pre-uploaded video ID from
                ``upload_ad_video`` / ``upload_ad_video_file``.
                When supplied, the creative becomes a video Lead Ad.
            message: Primary body text shown above the creative.
            headline: Headline text. In image mode mapped to
                ``link_data.name``; in video mode mapped to
                ``video_data.title``.
            description: Link-caption / description.
            call_to_action: CTA button label. Defaults to
                ``"SIGN_UP"`` (canonical Lead Ad CTA). Other commonly
                supported values: ``LEARN_MORE``, ``APPLY_NOW``,
                ``GET_QUOTE``, ``SUBSCRIBE``, ``CONTACT_US``,
                ``DOWNLOAD``, ``BOOK_TRAVEL``. Meta's published list
                also includes ``GET_OFFER`` / ``ORDER_NOW`` /
                ``REGISTER``; mureo passes the value through
                untouched, and Meta validates server-side. Note that
                ``SHOP_NOW`` (valid for normal link creatives) is
                explicitly **not** allowed on Lead Ads — Meta rejects
                it with a 400.

        Returns:
            Created AdCreative info dict (id, ...).

        Raises:
            ValueError: ``video_id`` and ``image_url`` are both set.
                Supply ``image_hash`` directly for the video
                thumbnail instead.
        """
        if video_id and image_url:
            raise ValueError(
                "video_id and image_url cannot be combined — supply "
                "image_hash directly for the video thumbnail"
            )

        if video_id:
            video_data: dict[str, Any] = {
                "video_id": video_id,
                "call_to_action": {
                    "type": call_to_action,
                    "value": {
                        "lead_gen_form_id": form_id,
                        "link": link_url,
                    },
                },
            }
            if image_hash:
                # Meta's video_data thumbnail accepts either
                # ``image_url`` or ``image_hash`` (per Marketing API
                # docs, exactly one). We use ``image_hash`` for
                # consistency with link_data and the upload helpers
                # (``upload_ad_image`` returns ``{"hash": ..., "url": ...}``).
                video_data["image_hash"] = image_hash
            if message:
                video_data["message"] = message
            if headline:
                video_data["title"] = headline
            if description:
                video_data["description"] = description
            object_story_spec = {
                "page_id": page_id,
                "video_data": video_data,
            }
            data: dict[str, Any] = {
                "name": name,
                "object_story_spec": json.dumps(object_story_spec),
            }
            return await self._post(f"/{self._ad_account_id}/adcreatives", data)

        link_data: dict[str, Any] = {
            "link": link_url,
            "lead_gen_form_id": form_id,
            "call_to_action": {"type": call_to_action},
        }

        if image_url and not image_hash:
            upload_result = await self.upload_ad_image(image_url)
            if "hash" in upload_result:
                image_hash = upload_result["hash"]
            else:
                logger.warning(
                    "Auto-upload failed for %s: %s", image_url, upload_result
                )

        if image_hash:
            link_data["image_hash"] = image_hash
        if message:
            link_data["message"] = message
        if headline:
            link_data["name"] = headline
        if description:
            link_data["description"] = description

        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }

        data = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }

        return await self._post(f"/{self._ad_account_id}/adcreatives", data)

    async def upload_ad_image(
        self,
        image_url: str,
    ) -> dict[str, Any]:
        """Upload an image to Meta API from a URL.

        Downloads the image from the URL, converts to base64, and uploads
        via the adimages endpoint (which requires base64 bytes, not URLs).

        Args:
            image_url: Source image URL

        Returns:
            {"hash": "...", "url": "..."} or {"error": "..."}
        """
        from mureo.core.url_guard import UnsafeUrlError, validate_public_url

        # SSRF guard: image_url originates from LLM/MCP tool arguments, so a
        # prompt-injection payload could point it at an internal host (e.g. the
        # cloud metadata endpoint) and exfiltrate the bytes into a Meta ad
        # account. Validate before fetching, and follow redirects MANUALLY so
        # each hop is validated before it is followed (httpx auto-follow would
        # hit an internal redirect target before we could re-check it).
        try:
            validate_public_url(image_url)
        except UnsafeUrlError as exc:
            return {"error": f"Refusing to fetch image URL: {exc}"}

        # Download the image
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as http:
                current_url = image_url
                resp = None
                for _ in range(_MAX_IMAGE_REDIRECTS + 1):
                    resp = await http.get(current_url)
                    # has_redirect_location (not is_redirect) is True only for a
                    # 3xx that carries a Location, so a 304/300 without one is a
                    # terminal response rather than a phantom redirect hop.
                    if not resp.has_redirect_location:
                        break
                    next_url = str(
                        httpx.URL(current_url).join(resp.headers["location"])
                    )
                    validate_public_url(next_url)
                    current_url = next_url
                else:
                    return {
                        "error": (f"Too many redirects fetching image from {image_url}")
                    }
                resp.raise_for_status()
                image_bytes = base64.b64encode(resp.content).decode("utf-8")
        except UnsafeUrlError as exc:
            return {"error": f"Refusing to follow image redirect: {exc}"}
        except Exception as exc:
            return {"error": f"Failed to download image from {image_url}: {exc}"}

        data: dict[str, Any] = {
            "bytes": image_bytes,
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
            name: Accepted for API compatibility but NOT sent on the wire. The
                base64 ``bytes`` form of /adimages has no documented ``name``
                field, so Meta assigns the image identifier itself.

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

        # Multipart uploads to /adimages were rejected by Meta with
        # ``FileTypeNotSupported`` (error_subcode 1487411) even when the
        # multipart body was provably well-formed (correct boundary, image/png
        # part header, raw magic bytes, no double base64), so the multipart
        # approach is a dead end for this endpoint. Instead we use the base64
        # ``bytes`` form-body variant -- the same shape the URL-based
        # ``upload_ad_image`` path above already uses successfully in production.
        # Routing through the shared ``_post``/``_request`` machinery adds Meta's
        # error JSON surfacing, retries, 429 and rate-limit handling, and puts
        # auth on the Bearer header (no access_token form field).
        with open(path, "rb") as f:
            image_bytes = base64.b64encode(f.read()).decode("utf-8")

        data: dict[str, Any] = {"bytes": image_bytes}

        # The file is validated up to 30MB; base64 of that is ~40MB of body, so
        # keep a 60s timeout rather than the shared client's 30s default so a
        # large image on a slow link does not time out.
        result = await self._post(
            f"/{self._ad_account_id}/adimages",
            data,
            timeout=_META_UPLOAD_TIMEOUT_SECONDS,
        )

        images = result.get("images")
        if not images or not isinstance(images, dict):
            return {"error": "Image upload failed"}

        # images is in {<key>: {hash, url}} format; parse by value (the single
        # entry), so the response key does not matter.
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
