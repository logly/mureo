"""HTTP client for OpenAI's Advertiser API (the API behind ChatGPT Ads).

GET only. One client lives for one tool call: it carries the bearer header,
retries 429 / 5xx with exponential backoff the way
:mod:`mureo.meta_ads.client` does, follows list cursors, and caches the ad
account's time zone so a report and its period agree on what "today" is.

Credential hygiene: the key is sent as a default header on the underlying
``httpx.AsyncClient``, and one private copy is kept for a single purpose —
replacing the key's exact value in an error body before the body is read, so
a platform answer that echoes the key ("Incorrect API key provided: …")
cannot carry it into a tool result. An httpx transport error can carry the
request, headers included, so it is never quoted or chained: the client
records only the error's class name inside the ``except`` and raises its own
:class:`ChatGPTAdsAPIError` after the block, which leaves ``__context__``
empty.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from datetime import timezone, tzinfo
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from mureo.chatgpt_ads._api import (
    BASE_URL,
    INITIAL_BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    MAX_PAGES_PER_CALL,
    MAX_RETRY_AFTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)
from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError, error_from_response

if TYPE_CHECKING:
    from types import TracebackType

#: Query parameters as ordered pairs: the API reads repeated bracket-suffixed
#: keys (``fields[]``, ``include[]``, ``time_ranges[]``), which a dict cannot
#: hold.
Params = Sequence[tuple[str, str]]
Sleep = Callable[[float], Awaitable[None]]

#: What replaces the API key's value in an error body; the mask
#: :mod:`mureo.core.scrub` writes for a secret value.
_KEY_MARKER = "***"


def _retryable(status: int) -> bool:
    """429 and every 5xx are worth another attempt; other answers are final."""
    return status == 429 or status >= 500


def _retry_delay(response: httpx.Response, attempt: int) -> float | None:
    """Seconds to wait before the next attempt, or ``None`` to stop now.

    A numeric ``Retry-After`` within :data:`MAX_RETRY_AFTER_SECONDS` is
    honoured; one above it (``inf`` included) means the answer is reported
    as it is rather than slept through. A missing, negative, ``nan`` or
    non-numeric value falls back to exponential backoff.
    """
    try:
        value = float(response.headers.get("Retry-After", "nan"))
    except ValueError:
        value = math.nan
    if math.isnan(value) or value < 0:
        return float(INITIAL_BACKOFF_SECONDS * (2**attempt))
    return value if value <= MAX_RETRY_AFTER_SECONDS else None


def _decode(response: httpx.Response) -> Any:
    """The JSON body of a success answer; an unreadable body is an API error."""
    try:
        return response.json()
    except (ValueError, RecursionError):  # not JSON, or nested past the limit
        pass
    raise ChatGPTAdsAPIError(
        f"HTTP {response.status_code}: the response body is not JSON",
        status=response.status_code,
    )


def _page_rows(response: httpx.Response) -> tuple[dict[str, Any], list[Any]]:
    """``(body, data)`` of one list page; a page without ``data`` is an error."""
    body = _decode(response)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ChatGPTAdsAPIError(
            f"HTTP {response.status_code}: the list answer has no data array",
            status=response.status_code,
        )
    return body, data


def _zone(value: object) -> tzinfo:
    """``value`` as an IANA zone; UTC when absent or not a valid zone name."""
    if not isinstance(value, str) or not value:
        return timezone.utc
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


class ChatGPTAdsClient:
    """GET access to one ad account, as scoped by its API key."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )
        # Kept only to redact its exact value from error bodies.
        self._api_key = api_key
        self._sleep = sleep
        self._timezone: tzinfo | None = None

    async def __aenter__(self) -> ChatGPTAdsClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    def _redacted(self, body_text: str) -> str:
        if not self._api_key:
            return body_text
        return body_text.replace(self._api_key, _KEY_MARKER)

    async def _send(self, path: str, params: Params) -> httpx.Response:
        """One GET. A transport failure becomes an API error naming its class."""
        failure = ""
        try:
            return await self._http.get(path, params=list(params))
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            failure = type(exc).__name__
        raise ChatGPTAdsAPIError(f"transport error ({failure})", status=0)

    async def _request(self, path: str, params: Params) -> httpx.Response:
        """One GET, retried on 429 / 5xx; a non-success answer raises."""
        for attempt in range(MAX_ATTEMPTS):
            response = await self._send(path, params)
            if not _retryable(response.status_code) or attempt == MAX_ATTEMPTS - 1:
                break
            delay = _retry_delay(response, attempt)
            if delay is None:
                break
            await self._sleep(delay)
        if response.is_success:
            return response
        body = self._redacted(response.text)
        raise error_from_response(response.status_code, body)

    async def get(self, path: str, params: Params = ()) -> Any:
        """The decoded JSON body of ``GET path``."""
        return _decode(await self._request(path, params))

    async def list_all(
        self, path: str, params: Params, *, limit: int, page_max: int
    ) -> list[Any]:
        """Up to ``limit`` rows of a cursor-paged list, as one flat list.

        Pages are requested with ``limit=min(remaining, page_max)`` and
        followed through ``last_id`` → ``after`` while ``has_more`` holds. An
        empty page ends the walk. A page that claims more rows without a
        usable, advancing cursor, or a walk longer than
        :data:`MAX_PAGES_PER_CALL` pages, is an error: returning the rows
        collected so far would report a short list as complete.
        """
        collected: list[Any] = []
        after: str | None = None
        for _ in range(MAX_PAGES_PER_CALL):
            size = min(limit - len(collected), page_max)
            cursor = [("after", after)] if after else []
            response = await self._request(
                path, [*params, ("limit", str(size)), *cursor]
            )
            body, data = _page_rows(response)
            collected.extend(data[: limit - len(collected)])
            if len(collected) >= limit or not data or not body.get("has_more"):
                return collected
            last_id = body.get("last_id")
            if not isinstance(last_id, str) or not last_id or last_id == after:
                raise ChatGPTAdsAPIError(
                    f"HTTP {response.status_code}: the list says more rows "
                    "follow but its cursor is missing or did not advance",
                    status=response.status_code,
                )
            after = last_id
        raise ChatGPTAdsAPIError(
            f"the list needed more than {MAX_PAGES_PER_CALL} pages; lower "
            "limit or narrow the filters",
            status=0,
        )

    async def account_timezone(self) -> tzinfo:
        """The ad account's time zone, read once per client.

        Falls back to UTC when ``GET /ad_account`` names no zone or one
        ``zoneinfo`` does not know.
        """
        if self._timezone is None:
            account = await self.get("/ad_account")
            value = account.get("timezone") if isinstance(account, dict) else None
            self._timezone = _zone(value)
        return self._timezone


__all__ = ["ChatGPTAdsClient", "Params"]
