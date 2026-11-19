"""HTTP client for OpenAI's Advertiser API (the API behind ChatGPT Ads).

GET and POST through one request path. One client lives for one tool call: it
carries the bearer header, retries with exponential backoff the way
:mod:`mureo.meta_ads.client` does, follows list cursors, and caches the ad
account's time zone so a report and its period agree on what "today" is.

Retries differ by method. A GET is retried on 429 and on every 5xx. A POST
changes something, so it is retried on 429 only (the request was not
processed); a 5xx or a transport error on a POST is final, because the change
may have been applied before the answer was lost, and its message ends with
:data:`MAY_HAVE_BEEN_APPLIED`.

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
from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    ChatGPTAdsAPIError,
    error_from_response,
)

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

_GET = "GET"
_POST = "POST"

#: A JSON request body.
Body = dict[str, Any]


def _retryable(method: str, status: int) -> bool:
    """Is another attempt worth making?

    429 always: the platform refused the request without processing it. A 5xx
    only for a GET; a POST answered with 5xx may have been applied, and
    repeating it could apply the change twice.
    """
    return status == 429 or (method == _GET and status >= 500)


def _applied_note(method: str) -> str:
    """What a failed answer adds: for a POST, that the change may have been
    applied; for a GET, nothing."""
    return MAY_HAVE_BEEN_APPLIED if method == _POST else ""


def _final_message(method: str, message: str) -> str:
    """``message``, flagged when a POST ended without a readable answer."""
    note = _applied_note(method)
    return f"{message} {note}" if note else message


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


def _decode(response: httpx.Response, method: str = _GET) -> Any:
    """The JSON body of a success answer; an unreadable body is an API error.

    For a POST the error ends with :data:`MAY_HAVE_BEEN_APPLIED`: a 2xx says
    the platform took the change, but an intermediary can answer 200 with a
    page of its own, so "may" is as far as the answer goes.
    """
    try:
        return response.json()
    except (ValueError, RecursionError):  # not JSON, or nested past the limit
        pass
    raise ChatGPTAdsAPIError(
        _final_message(
            method, f"HTTP {response.status_code}: the response body is not JSON"
        ),
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
    """Access to one ad account, as scoped by its API key."""

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

    async def _send(
        self, method: str, path: str, params: Params, body: Body | None
    ) -> httpx.Response:
        """One request; ``body=None`` sends none. A transport failure becomes
        an API error naming its class."""
        failure = ""
        try:
            return await self._http.request(
                method, path, params=list(params), json=body
            )
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            failure = type(exc).__name__
        raise ChatGPTAdsAPIError(
            _final_message(method, f"transport error ({failure})"), status=0
        )

    async def _request(
        self,
        path: str,
        params: Params,
        *,
        method: str = _GET,
        body: Body | None = None,
    ) -> httpx.Response:
        """One request, retried while :func:`_retryable`; a non-success
        answer raises."""
        for attempt in range(MAX_ATTEMPTS):
            response = await self._send(method, path, params, body)
            retry = _retryable(method, response.status_code)
            if not retry or attempt == MAX_ATTEMPTS - 1:
                break
            delay = _retry_delay(response, attempt)
            if delay is None:
                break
            await self._sleep(delay)
        if response.is_success:
            return response
        status = response.status_code
        raise error_from_response(
            status,
            self._redacted(response.text),
            note=_applied_note(method) if status >= 500 else "",
        )

    async def get(self, path: str, params: Params = ()) -> Any:
        """The decoded JSON body of ``GET path``."""
        return _decode(await self._request(path, params))

    async def post(self, path: str, body: Body | None = None) -> Any:
        """The decoded JSON body of ``POST path``; ``body=None`` sends none.

        An empty success body (a 204, or only whitespace) is ``{}``: the
        platform took the change and had nothing to add.
        """
        response = await self._request(path, (), method=_POST, body=body)
        if not response.content.strip():
            return {}
        return _decode(response, _POST)

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
