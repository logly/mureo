from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, NoReturn

import httpx

from mureo.core.auth_failure import PlatformAuthError
from mureo.meta_ads._ad_rules import AdRulesMixin
from mureo.meta_ads._ad_sets import AdSetsMixin
from mureo.meta_ads._ads import AdsMixin
from mureo.meta_ads._analysis import AnalysisMixin
from mureo.meta_ads._audiences import AudiencesMixin
from mureo.meta_ads._campaigns import CampaignsMixin
from mureo.meta_ads._catalog import CatalogMixin
from mureo.meta_ads._conversions import ConversionsMixin
from mureo.meta_ads._creatives import CreativesMixin
from mureo.meta_ads._insights import InsightsMixin
from mureo.meta_ads._instagram import InstagramMixin
from mureo.meta_ads._leads import LeadsMixin
from mureo.meta_ads._page_posts import PagePostsMixin
from mureo.meta_ads._pixels import PixelsMixin
from mureo.meta_ads._placement_exclusions import PlacementExclusionsMixin
from mureo.meta_ads._split_test import SplitTestMixin
from mureo.meta_ads._targeting import TargetingMixin
from mureo.meta_ads._videos import VideosMixin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mureo.throttle import Throttler

logger = logging.getLogger(__name__)

# Rate limit warning threshold (usage %)
_RATE_LIMIT_WARNING_THRESHOLD = 80

# Retry configuration
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 1.0

# Meta answers an expired or revoked token with HTTP 400, not 401, so the
# status code alone cannot tell a dead credential from a bad request.
# ``OAuthException`` -- and error code 190 with its session sibling 102 -- is
# the discriminator Meta documents, and it is what lets an auth failure reach
# a report skill as a distinct outcome instead of as one more untyped
# ``API error: ...`` string that reads like a quiet account (#580).
_META_OAUTH_ERROR_TYPE = "OAuthException"
_META_AUTH_ERROR_CODES = frozenset({102, 190})
_META_AUTH_HTTP_STATUS = 401

# Longest slice of a Meta error body kept for logs / fallback detail.
_MAX_ERROR_BODY_CHARS = 500


def _meta_error_detail(error: dict[str, Any]) -> str:
    """Join the human-readable parts of a Meta ``error`` object."""
    parts = [
        str(error[key])
        for key in ("message", "error_user_title", "error_user_msg")
        if error.get(key)
    ]
    if error.get("error_subcode"):
        parts.append(f"subcode={error['error_subcode']}")
    if error.get("fbtrace_id"):
        parts.append(f"fbtrace_id={error['fbtrace_id']}")
    return " | ".join(parts)


def _is_meta_auth_failure(status_code: int, error: dict[str, Any]) -> bool:
    """True when Meta refused the credential rather than the request.

    Deliberately narrow. Reporting a validation failure as an auth failure
    would send the operator to re-authorize a healthy account and would
    withhold a report section that had perfectly good data behind it.
    """
    if status_code == _META_AUTH_HTTP_STATUS:
        return True
    if error.get("type") == _META_OAUTH_ERROR_TYPE:
        return True
    code = error.get("code")
    return (
        isinstance(code, int)
        and not isinstance(code, bool)
        and code in _META_AUTH_ERROR_CODES
    )


def _raise_meta_api_error(resp: httpx.Response, method: str, path: str) -> NoReturn:
    """Raise the exception class that matches a non-200 Meta response.

    :class:`~mureo.core.auth_failure.PlatformAuthError` for a refused
    credential, a plain ``RuntimeError`` for everything else.
    """
    error_body = resp.text[:_MAX_ERROR_BODY_CHARS]
    logger.error(
        "Meta API error: method=%s, path=%s, status=%d, body=%s",
        method,
        path,
        resp.status_code,
        error_body,
    )
    error: dict[str, Any] = {}
    try:
        payload = resp.json()
        raw = payload.get("error") if isinstance(payload, dict) else None
        error = raw if isinstance(raw, dict) else {}
        detail = _meta_error_detail(error)
    except Exception:  # noqa: BLE001 - an unparseable body still has to be reported
        detail = error_body
    message = (
        f"Meta API request failed (status={resp.status_code}, path={path}): {detail}"
    )
    if _is_meta_auth_failure(resp.status_code, error):
        raise PlatformAuthError(message)
    raise RuntimeError(message)


def _rewind_file_parts(files: dict[str, Any] | None) -> None:
    """Seek every seekable part in an httpx ``files`` mapping back to byte 0.

    Multipart callers (``upload_ad_video_file``) hand httpx an OPEN file object
    rather than materialized bytes, so a 1GB upload streams instead of sitting
    in memory. ``_request`` re-sends the same mapping on a 429 / transport
    retry, and a handle left at EOF by the previous attempt would make the
    retry POST an empty body.

    Values may be a bare file-like object or an httpx part tuple
    (``(filename, fileobj, content_type)``); anything without ``seek`` (e.g. a
    ``bytes`` part) is left untouched -- immutable bytes re-render identically
    on every attempt and need no rewind.

    A part that cannot be rewound is a hard error, NOT something to skip past:
    resuming a retry from a stale cursor would have httpx render a truncated or
    empty multipart body, Meta can accept that upload and only surface the
    damage later as an async video-processing failure. Failing here instead
    turns a corrupt upload into a clear local error. Raising before the first
    attempt (rather than only on retries) makes the failure deterministic for
    such a caller instead of a heisenbug that appears only under rate limiting.

    Raises:
        RuntimeError: A file part reports ``seekable() is False``. Any other
            exception from ``seek`` propagates unchanged, for the same reason.
    """
    if not files:
        return
    for value in files.values():
        candidates = value if isinstance(value, (tuple, list)) else (value,)
        for candidate in candidates:
            seek = getattr(candidate, "seek", None)
            if not callable(seek):
                continue
            seekable = getattr(candidate, "seekable", None)
            if callable(seekable) and seekable() is False:
                raise RuntimeError(
                    "Cannot retry multipart upload: file part is not seekable"
                )
            seek(0)


class MetaAdsApiClient(
    CampaignsMixin,
    AdSetsMixin,
    PlacementExclusionsMixin,
    AdsMixin,
    CreativesMixin,
    VideosMixin,
    AudiencesMixin,
    PixelsMixin,
    InsightsMixin,
    AnalysisMixin,
    CatalogMixin,
    ConversionsMixin,
    LeadsMixin,
    PagePostsMixin,
    InstagramMixin,
    SplitTestMixin,
    AdRulesMixin,
    TargetingMixin,
):
    """Meta Marketing API client.

    Operates Meta Ads (Facebook/Instagram) using Graph API v21.0.
    Includes built-in rate limit monitoring and exponential backoff retry.
    Provides campaigns, ad sets, ads, and insights operations via mixin multiple inheritance.
    """

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        throttler: Throttler | None = None,
    ) -> None:
        """
        Args:
            access_token: Meta Graph API access token (plaintext)
            ad_account_id: Ad account ID ("act_XXXX" format)
            throttler: Optional rate-limit throttler
        """
        if not access_token:
            raise ValueError("access_token is required")
        if not ad_account_id:
            raise ValueError("ad_account_id is required")
        if not ad_account_id.startswith("act_"):
            raise ValueError(f"ad_account_id must start with 'act_': {ad_account_id}")

        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._http = httpx.AsyncClient(timeout=30.0)
        self._throttler = throttler
        self._page_tokens: dict[str, str] = {}  # Cache: page_id -> page_access_token

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET request (with rate limit handling).

        Args:
            path: API path (e.g. "/{ad_account_id}/campaigns")
            params: Query parameters

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the API request fails
        """
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST request (with rate limit handling).

        Args:
            path: API path
            data: Request body (form fields)
            timeout: Optional per-request timeout in seconds. ``None`` uses the
                shared client default; a value overrides it for this call (e.g.
                large image uploads need a longer window than the default).
            files: Optional httpx ``files`` mapping. Supplying it turns the
                request into a multipart upload, with ``data`` carried as the
                accompanying form fields (see ``upload_ad_video_file``).

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the API request fails
        """
        return await self._request(
            "POST", path, data=data, timeout=timeout, files=files
        )

    async def _delete(self, path: str) -> dict[str, Any]:
        """DELETE request (with rate limit handling)."""
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an HTTP request (with rate limit handling and exponential backoff retry).

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            data: Request body (form fields)
            timeout: Optional per-request timeout in seconds. ``None`` uses the
                shared client's default; a value overrides it for this call
                (httpx per-request timeout override semantics).
            files: Optional httpx ``files`` mapping (POST only). Passed
                straight through so the request is encoded as multipart with
                ``data`` as the accompanying form fields. Parts may carry an
                open file object so large uploads stream instead of being
                buffered: the same mapping is re-sent on every retry attempt
                below, and every file part is rewound to byte 0 before each
                attempt so the retry sends an identical body. A part that
                cannot be rewound is rejected rather than sent truncated.

        Returns:
            API response JSON

        Raises:
            RuntimeError: If the maximum retry count is exceeded, or if a
                ``files`` part is not seekable (see ``_rewind_file_parts``).
        """
        if self._throttler is not None:
            await self._throttler.acquire()

        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        if params is None:
            params = {}

        # httpx treats ``timeout=None`` as "disable timeout"; to mean "use the
        # client default" the kwarg must be omitted entirely. So only forward a
        # timeout when the caller explicitly set one.
        extra: dict[str, Any] = {}
        if timeout is not None:
            extra["timeout"] = timeout

        # Same rule for ``files``: httpx encodes multipart only when the kwarg
        # is actually supplied, so non-multipart callers must not receive it.
        post_extra: dict[str, Any] = dict(extra)
        if files is not None:
            post_extra["files"] = files

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            # Before EVERY attempt, not just retries: on the first pass the
            # handle is already at 0 and this is a no-op, and doing it
            # unconditionally keeps the invariant in one place.
            _rewind_file_parts(files)
            try:
                if method == "GET":
                    resp = await self._http.get(
                        url, params=params, headers=headers, **extra
                    )
                elif method == "POST":
                    resp = await self._http.post(
                        url, params=params, data=data, headers=headers, **post_extra
                    )
                elif method == "DELETE":
                    resp = await self._http.delete(
                        url, params=params, headers=headers, **extra
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Monitor rate limit headers
                self._check_rate_limit(resp)

                # 429 Too Many Requests -> backoff retry
                if resp.status_code == 429:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API rate limit (429): retrying in %ss (attempt %d/%d)",
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if resp.status_code != 200:
                    _raise_meta_api_error(resp, method, path)

                return resp.json()  # type: ignore[no-any-return]

            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API communication error: %s. Retrying in %ss (attempt %d/%d)",
                        exc,
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise RuntimeError(
                    f"Meta API request failed (path={path}): {exc}"
                ) from exc

        raise RuntimeError(
            f"Meta API request exceeded maximum retry count ({_MAX_RETRIES}): "
            f"path={path}"
        ) from last_error

    def _check_rate_limit(self, resp: httpx.Response) -> None:
        """Check rate limit usage from response headers.

        Parses the x-business-use-case-usage header and logs a warning
        if usage exceeds the threshold.

        Args:
            resp: HTTP response
        """
        usage_header = resp.headers.get("x-business-use-case-usage")
        if not usage_header:
            return

        try:
            usage_data = json.loads(usage_header)
            for business_id, usage_list in usage_data.items():
                if not isinstance(usage_list, list):
                    continue
                for usage in usage_list:
                    call_count = usage.get("call_count", 0)
                    total_cputime = usage.get("total_cputime", 0)
                    total_time = usage.get("total_time", 0)

                    max_usage = max(call_count, total_cputime, total_time)
                    if max_usage >= _RATE_LIMIT_WARNING_THRESHOLD:
                        logger.warning(
                            "Meta API rate limit usage is high: "
                            "business_id=%s, call_count=%d%%, "
                            "cputime=%d%%, time=%d%%",
                            business_id,
                            call_count,
                            total_cputime,
                            total_time,
                        )
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.debug(
                "Failed to parse x-business-use-case-usage header: %s",
                usage_header[:200],
            )

    async def _iter_page_batches(
        self, fields: str
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield batches of accessible pages, personal source first.

        Shared two-step page discovery used by both
        :meth:`get_page_access_token` (which short-circuits once it finds
        its target) and :meth:`list_pages` (which consumes every batch):
        ``/me/accounts`` (personal pages) then ``/me/businesses`` ->
        ``/{business_id}/owned_pages`` (business-owned pages). Lazy so the
        token lookup can stop before the business calls are made.

        Args:
            fields: Comma-separated Graph field list to request per page.
        """
        result = await self._get("/me/accounts", {"fields": fields})
        yield result.get("data", [])

        biz_result = await self._get("/me/businesses", {"fields": "id"})
        for biz in biz_result.get("data", []):
            pages_result = await self._get(
                f"/{biz['id']}/owned_pages",
                {"fields": fields},
            )
            yield pages_result.get("data", [])

    async def get_page_access_token(self, page_id: str) -> str:
        """Get a Page Access Token for the given page.

        Tries /me/accounts first (personal pages), then falls back to
        business-owned pages via /me/businesses -> /{business_id}/owned_pages.
        A page discovered only through the business-owned edge carries no
        access_token, so it yields RuntimeError rather than a token.

        Args:
            page_id: Facebook page ID

        Returns:
            Page Access Token string

        Raises:
            RuntimeError: If the page is not accessible or token retrieval fails
        """
        if page_id in self._page_tokens:
            return self._page_tokens[page_id]

        async for batch in self._iter_page_batches("id,access_token"):
            for page in batch:
                # Business-owned pages from /{business_id}/owned_pages come
                # back without an access_token, so cache only well-formed
                # entries: a token-less page must fall through to the
                # documented RuntimeError below, not raise KeyError at the
                # caller.
                entry_id = page.get("id")
                token = page.get("access_token")
                if entry_id and token:
                    self._page_tokens[entry_id] = token
            # Short-circuit: stop before the business calls if we already
            # have the token from the personal-pages batch.
            if page_id in self._page_tokens:
                return self._page_tokens[page_id]

        raise RuntimeError(
            f"Page {page_id} not accessible with current token. "
            f"Ensure the user has admin access to this page "
            f"and the page is owned by a connected business portfolio."
        )

    async def list_pages(self) -> list[dict[str, Any]]:
        """List Facebook Pages the current token can manage.

        Aggregates personal (``/me/accounts``) and business-owned
        (``/me/businesses`` -> ``/{business_id}/owned_pages``) pages via
        the shared :meth:`_iter_page_batches` helper. Read-only.

        Returns:
            A list of ``{"id", "name", "category"?}`` dicts (``category``
            is included only when Graph returns it for that page). A Page
            that appears in both sources (a common overlap when the user
            has a role on a Page that a Business Portfolio also owns) is
            listed once, keyed on id, preserving first-seen order.
        """
        pages: dict[str, dict[str, Any]] = {}
        async for batch in self._iter_page_batches("id,name,category"):
            for page in batch:
                # Skip malformed Graph entries: an id-less page cannot be
                # keyed or acted on, so drop it rather than raise KeyError.
                page_id = page.get("id")
                if not page_id:
                    continue
                entry: dict[str, Any] = {"id": page_id, "name": page.get("name")}
                if "category" in page:
                    entry["category"] = page["category"]
                # setdefault keeps the first-seen entry (personal batch
                # wins) and dedupes ids shared across both sources.
                pages.setdefault(page_id, entry)
        return list(pages.values())

    async def _get_as_page(
        self, page_id: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET request using Page Access Token instead of User Access Token.

        Args:
            page_id: Facebook page ID (used to resolve Page Access Token)
            path: API path
            params: Query parameters

        Returns:
            API response JSON
        """
        page_token = await self.get_page_access_token(page_id)
        url = f"{self.BASE_URL}{path}"
        if params is None:
            params = {}
        headers = {"Authorization": f"Bearer {page_token}"}

        if self._throttler is not None:
            await self._throttler.acquire()

        resp = await self._http.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            detail = ""
            try:
                err = resp.json().get("error", {})
                parts = [v for k in ("message",) if (v := err.get(k))]
                detail = " | ".join(parts) if parts else resp.text[:500]
            except Exception:
                detail = resp.text[:500]
            raise RuntimeError(
                f"Meta API request failed "
                f"(status={resp.status_code}, path={path}): {detail}"
            )
        return resp.json()  # type: ignore[no-any-return]

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> MetaAdsApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
