"""HTTP client for OpenAI's Advertiser API (the API behind ChatGPT Ads).

GET and POST through one request path. One client lives for one tool call: it
carries the bearer header, retries with exponential backoff the way
:mod:`mureo.meta_ads.client` does, follows list cursors, and caches the ad
account's time zone so a report and its period agree on what "today" is.

Every request states two things about itself (:class:`_Policy`): whether a
5xx answer is worth another attempt, and what its failure message adds when
the answer was lost. A 429 is always retried (the request was not processed).

- ``get`` and ``post_read`` are retried on 5xx and add nothing.
  ``post_read`` is the ad preview (a POST that changes no campaign, ad group
  or ad: the platform renders and saves an expiring preview snapshot) and
  the conversion report (a POST that carries the report's filters), so both
  are treated as reads.
- ``post`` changes something, so a 5xx or a transport error is final: the
  change may have been applied before the answer was lost, and the message
  ends with :data:`MAY_HAVE_BEEN_APPLIED`. ``post_file`` (an upload, which
  is not idempotent) holds the same rule.
- ``post`` with an idempotency key is retried on 5xx, because the platform
  returns the existing object for a repeat with the same key when it can see
  the matching earlier create, and its message ends with
  :data:`REPEAT_WITH_IDEMPOTENCY_KEY` naming the key.
- ``post_operation`` (an audience membership add or remove, where the key is
  required) follows the same rule with
  :data:`REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY`: a repeat with the key
  returns or resumes the first accepted operation. Its body carries audience
  identifiers, so its policy also masks digest- and advertising-id-shaped
  text in the platform's error message. Both keyed requests go through one
  private method; the two public ones differ only in the policy they build.

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
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timezone, tzinfo
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from mureo.chatgpt_ads._api import (
    AD_ACCOUNT_PATH,
    BASE_URL,
    INITIAL_BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    MAX_PAGES_PER_CALL,
    MAX_RETRY_AFTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)
from mureo.chatgpt_ads._errors import (
    MAY_HAVE_BEEN_APPLIED,
    REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY,
    REPEAT_WITH_IDEMPOTENCY_KEY,
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
#: The request header that carries a create's idempotency key.
_IDEMPOTENCY_HEADER = "Idempotency-Key"
#: The multipart form field an upload sends its file in.
_FILE_FIELD = "file"

#: A JSON request body.
Body = dict[str, Any]


@dataclass(frozen=True)
class _Policy:
    """The decisions one request makes about a failed answer.

    ``retry_server_errors``: is a 5xx worth another attempt? Only when
    repeating the request cannot apply a change twice. ``lost_answer_note``:
    the sentence a 5xx, a transport error or an unreadable success answer
    adds, because the platform may have acted before the answer was lost.
    ``hide_identifiers``: mask digest- and advertising-id-shaped text in the
    platform's error message, for a request whose body carries audience
    identifiers the answer could echo.
    """

    retry_server_errors: bool
    lost_answer_note: str
    hide_identifiers: bool = False


#: A read, whatever its HTTP method.
_READ = _Policy(retry_server_errors=True, lost_answer_note="")
#: A change that a repeat could apply twice.
_CHANGE = _Policy(retry_server_errors=False, lost_answer_note=MAY_HAVE_BEEN_APPLIED)


def _idempotent(sentence: str, key: str, *, hide_identifiers: bool = False) -> _Policy:
    """A request the platform deduplicates by ``key``: safe to repeat.

    ``sentence`` is the lost-answer note naming the key: a create's
    (:data:`REPEAT_WITH_IDEMPOTENCY_KEY`) or an audience operation's
    (:data:`REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY`).
    """
    note = sentence.format(key=key)
    return _Policy(
        retry_server_errors=True,
        lost_answer_note=note,
        hide_identifiers=hide_identifiers,
    )


def _retryable(policy: _Policy, status: int) -> bool:
    """Is another attempt worth making?

    429 always: the platform refused the request without processing it. A 5xx
    only where the policy says a repeat is safe.
    """
    return status == 429 or (policy.retry_server_errors and status >= 500)


def _final_message(policy: _Policy, message: str) -> str:
    """``message``, ending with the policy's note when it has one."""
    note = policy.lost_answer_note
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


def _decode(response: httpx.Response, policy: _Policy = _READ) -> Any:
    """The JSON body of a success answer; an unreadable body is an API error.

    For a change the error ends with the policy's note: a 2xx says the
    platform took the change, but an intermediary can answer 200 with a page
    of its own, so "may" is as far as the answer goes.
    """
    try:
        return response.json()
    except (ValueError, RecursionError):  # not JSON, or nested past the limit
        pass
    raise ChatGPTAdsAPIError(
        _final_message(
            policy, f"HTTP {response.status_code}: the response body is not JSON"
        ),
        status=response.status_code,
    )


def _post_answer(response: httpx.Response, policy: _Policy) -> Any:
    """The decoded body of a POST answer; an empty one (a 204, or only
    whitespace) is ``{}``: the platform acted and had nothing to add."""
    if not response.content.strip():
        return {}
    return _decode(response, policy)


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
        """``body_text`` with the key replaced, as sent and as decoded.

        The error parser JSON-decodes the body, and a ``\\uXXXX`` escape can
        spell the key without the raw text containing it. So a JSON body is
        also re-serialised with the escapes resolved and replaced again; any
        other body is returned with the raw replacement only.
        """
        if not self._api_key:
            return body_text
        raw = body_text.replace(self._api_key, _KEY_MARKER)
        try:
            decoded = json.dumps(json.loads(raw), ensure_ascii=False)
        except (ValueError, RecursionError):  # not JSON, or nested past the limit
            return raw
        return decoded.replace(self._api_key, _KEY_MARKER)

    async def _send(
        self,
        method: str,
        path: str,
        params: Params,
        policy: _Policy,
        payload: Mapping[str, Any],
    ) -> httpx.Response:
        """One request; ``payload`` holds its httpx body and header keywords
        (empty = no body). A transport failure becomes an API error naming
        its class."""
        failure = ""
        try:
            return await self._http.request(
                method, path, params=list(params), **payload
            )
        except (httpx.RequestError, httpx.InvalidURL) as exc:
            failure = type(exc).__name__
        raise ChatGPTAdsAPIError(
            _final_message(policy, f"transport error ({failure})"), status=0
        )

    async def _request(
        self,
        path: str,
        params: Params,
        *,
        method: str = _GET,
        policy: _Policy = _READ,
        payload: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        """One request, retried while :func:`_retryable`; a non-success
        answer raises, its body redacted before it is read."""
        for attempt in range(MAX_ATTEMPTS):
            response = await self._send(method, path, params, policy, payload or {})
            retry = _retryable(policy, response.status_code)
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
            note=policy.lost_answer_note if status >= 500 else "",
            hide_identifiers=policy.hide_identifiers,
        )

    async def get(self, path: str, params: Params = ()) -> Any:
        """The decoded JSON body of ``GET path``."""
        return _decode(await self._request(path, params))

    async def post(
        self, path: str, body: Body | None = None, *, idempotency_key: str | None = None
    ) -> Any:
        """The decoded JSON body of ``POST path``; ``body=None`` sends none.

        With ``idempotency_key`` the request carries the ``Idempotency-Key``
        header and a 5xx is retried with the same key and body. An empty key
        is refused: the header is never valid empty, and reading it as "no
        key" would drop the retry rule the caller asked for. An empty success
        body is ``{}``.
        """
        if idempotency_key is not None:
            policy = _idempotent(REPEAT_WITH_IDEMPOTENCY_KEY, idempotency_key)
            return await self._keyed_post(path, body, idempotency_key, policy)
        payload = {} if body is None else {"json": body}
        response = await self._request(
            path, (), method=_POST, policy=_CHANGE, payload=payload
        )
        return _post_answer(response, _CHANGE)

    async def post_operation(
        self, path: str, body: Body, *, idempotency_key: str
    ) -> Any:
        """``POST path`` for an audience membership add or remove.

        The API requires the ``Idempotency-Key`` header here, and a repeat
        with the same key returns or resumes the first accepted operation, so
        a 5xx is retried with the same key and body, and a lost answer ends
        with :data:`REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY` naming the key. The
        body carries audience identifiers, so an error message that echoes
        them is masked before it is read. An empty key is refused, as
        :meth:`post` refuses it.
        """
        policy = _idempotent(
            REPEAT_OPERATION_WITH_IDEMPOTENCY_KEY,
            idempotency_key,
            hide_identifiers=True,
        )
        return await self._keyed_post(path, body, idempotency_key, policy)

    async def _keyed_post(
        self, path: str, body: Body | None, key: str, policy: _Policy
    ) -> Any:
        """``POST path`` with the ``Idempotency-Key`` header, under ``policy``.

        The one keyed request path behind :meth:`post` and
        :meth:`post_operation`; each only builds its policy.
        """
        if not key:
            raise ValueError("idempotency_key must not be empty")
        payload: dict[str, Any] = {"headers": {_IDEMPOTENCY_HEADER: key}}
        if body is not None:
            payload["json"] = body
        response = await self._request(
            path, (), method=_POST, policy=policy, payload=payload
        )
        return _post_answer(response, policy)

    async def post_read(self, path: str, body: Body | None = None) -> Any:
        """``POST path`` for an endpoint that changes no campaign, ad group,
        ad or audience (the ad preview, which renders and saves an expiring
        snapshot; the conversion report, which only reads): retried like a
        GET, and its failures never say a change may have been applied."""
        payload = {} if body is None else {"json": body}
        response = await self._request(
            path, (), method=_POST, policy=_READ, payload=payload
        )
        return _post_answer(response, _READ)

    async def post_file(
        self, path: str, *, filename: str, content: bytes, content_type: str
    ) -> Any:
        """``POST path`` with ``content`` as the multipart field ``file``.

        An upload is not idempotent, so it follows the change rule: a 5xx or
        a transport error is final and may have been applied (a 429 is
        retried, like every request).
        """
        payload = {"files": {_FILE_FIELD: (filename, content, content_type)}}
        response = await self._request(
            path, (), method=_POST, policy=_CHANGE, payload=payload
        )
        return _post_answer(response, _CHANGE)

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
            account = await self.get(AD_ACCOUNT_PATH)
            value = account.get("timezone") if isinstance(account, dict) else None
            self._timezone = _zone(value)
        return self._timezone


__all__ = ["ChatGPTAdsClient", "Params"]
