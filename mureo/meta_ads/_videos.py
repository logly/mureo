"""Meta Ads AdVideo operations mixin.

Covers the AdVideo node: uploading a video (by URL or from a local file) and
reading back its processing status and auto-generated thumbnails.

Split out of :mod:`mureo.meta_ads._creatives` to keep both modules within the
project file-size budget. The boundary is the Graph node each module talks to:
this module owns ``/advideos`` and ``/{video-id}``, while ``_creatives`` owns
``/adcreatives`` -- including the video-creative *build* helpers
(``_build_video_data`` / ``_validate_video_creative_mode``), which shape an
AdCreative payload rather than an AdVideo request. That line leaves the two
modules with no imports of each other in either direction.
"""

from __future__ import annotations

import logging
from typing import Any

from mureo._image_validation import validate_video_file

logger = logging.getLogger(__name__)

# Meta Ads video upload limits. 1GB is Graph's documented ceiling for the
# non-resumable (single-request) /advideos upload; larger files require the
# chunked resumable upload protocol, which mureo does not implement yet.
_META_MAX_VIDEO_SIZE_BYTES = 1024 * 1024 * 1024  # 1GB
_META_MAX_VIDEO_SIZE_LABEL = "1GB"
_META_ALLOWED_VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "wmv", "mkv"})

# Real container MIME per allowed extension. Meta inspects the multipart part
# header, so a generic ``application/octet-stream`` risks the same
# ``FileTypeNotSupported`` rejection the /adimages multipart attempt hit.
_META_VIDEO_MIME_TYPES: dict[str, str] = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "avi": "video/x-msvideo",
    "wmv": "video/x-ms-wmv",
    "mkv": "video/x-matroska",
}

# Per-request timeout for video uploads. A file may be up to 1GB, so this
# overrides the shared client's 30s default by a wide margin.
_META_VIDEO_UPLOAD_TIMEOUT_SECONDS = 600.0

# AdVideo retrieval fields. ``status`` is a nested object carrying
# ``video_status`` ("processing" / "ready" / "error") and ``processing_phase``.
_VIDEO_FIELDS = "status,id,title,length,created_time"

# AdVideo thumbnail fields.
_VIDEO_THUMBNAIL_FIELDS = "id,uri,is_preferred,height,width"


class VideosMixin:
    """Meta Ads AdVideo operations mixin.

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
        """Upload a video from a local file (multipart /advideos).

        Routes through the shared ``_post``/``_request`` machinery instead of a
        one-off ``httpx.AsyncClient``, so Meta's error JSON (message /
        error_subcode / fbtrace_id), retries, 429 handling and rate-limit
        monitoring all apply, and auth rides the Bearer header rather than an
        ``access_token`` form field.

        Files up to 1GB are accepted -- Graph's documented ceiling for this
        non-resumable single-request form. Larger files need the chunked
        resumable upload protocol, which is not implemented.

        The file is **streamed**: the open handle is handed to httpx rather
        than a materialized ``bytes`` object, so a 1GB upload does not sit in
        memory in full. ``_request`` rewinds every seekable ``files`` part
        before each attempt, so a 429 / transport retry still re-sends an
        identical body.

        Args:
            file_path: Local video file path
            title: Video title (optional)

        Returns:
            Response in {"id": "..."} format

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: Validation error
            RuntimeError: If the API request fails.
        """
        path = validate_video_file(
            file_path,
            max_size_bytes=_META_MAX_VIDEO_SIZE_BYTES,
            max_size_label=_META_MAX_VIDEO_SIZE_LABEL,
            allowed_extensions=_META_ALLOWED_VIDEO_EXTENSIONS,
        )

        extension = path.suffix.lower().lstrip(".")
        # validate_video_file already restricted the extension to the allowed
        # set, which is exactly the MIME map's key set.
        mime_type = _META_VIDEO_MIME_TYPES[extension]

        data: dict[str, Any] = {}
        if title:
            data["title"] = title

        # Hand httpx the OPEN handle so the body streams off disk instead of
        # being read into memory in full (a 1GB video would otherwise be a 1GB
        # allocation). The handle must therefore stay open for the whole
        # ``_post`` call, which is why the ``with`` block wraps the await and
        # not just the ``open()``; ``_request`` rewinds it before every attempt
        # so a retry re-sends the same bytes.
        #
        # ``source`` is the documented field name for the non-resumable
        # /advideos upload; the real filename and container MIME travel with it
        # so Meta can identify the format.
        with open(path, "rb") as video_file:
            files = {"source": (path.name, video_file, mime_type)}

            return await self._post(
                f"/{self._ad_account_id}/advideos",
                data,
                timeout=_META_VIDEO_UPLOAD_TIMEOUT_SECONDS,
                files=files,
            )

    # ------------------------------------------------------------------
    # Video read operations (node-level paths -- NOT act_-scoped)
    # ------------------------------------------------------------------

    async def get_ad_video(self, video_id: str) -> dict[str, Any]:
        """Get an uploaded video's processing status and metadata.

        Meta processes uploads asynchronously; a creative referencing a video
        that is still processing is rejected. Poll this until
        ``status.video_status`` reports the video is ready.

        Args:
            video_id: Video ID from ``upload_ad_video`` /
                ``upload_ad_video_file``.

        Returns:
            ``{"id", "status", "title", "length", "created_time"}``. ``status``
            is returned raw -- it is a nested object carrying ``video_status``
            and ``processing_phase``, and Meta has extended its shape over
            time, so it is passed through rather than flattened.
        """
        return await self._get(f"/{video_id}", {"fields": _VIDEO_FIELDS})

    async def list_ad_video_thumbnails(self, video_id: str) -> list[dict[str, Any]]:
        """List the auto-generated thumbnails for an uploaded video.

        Args:
            video_id: Video ID from ``upload_ad_video`` /
                ``upload_ad_video_file``.

        Returns:
            List of ``{"id", "uri", "is_preferred", "height", "width"}``.
            Meta flags one entry with ``is_preferred: true``; its ``uri`` is
            the natural input for ``create_ad_creative``'s
            ``video_thumbnail_image_url``.
        """
        result = await self._get(
            f"/{video_id}/thumbnails", {"fields": _VIDEO_THUMBNAIL_FIELDS}
        )
        return result.get("data", [])  # type: ignore[no-any-return]
