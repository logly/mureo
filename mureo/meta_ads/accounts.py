"""Accessible-account discovery for the Meta Marketing API.

Public surface for tooling that needs to enumerate the Meta ad
accounts a given access token can reach.

The function was previously defined inside :mod:`mureo.auth_setup`
for the interactive OAuth wizard's account-picker step. Promoting it
to ``mureo.meta_ads.accounts`` exposes the same logic as a stable
public API so configure-UI consumers (in-tree and third-party) can
build account pickers without reaching into the wizard's internal
module.

The original import path ``mureo.auth_setup.list_meta_ad_accounts``
remains valid via a thin re-export there — existing callers do not
need to change.

The returned shape stays ``list[dict[str, Any]]`` (the same dict
shape the auth-setup wizard has always produced). A future minor
release MAY introduce a frozen-dataclass parallel return type; the
dict shape will remain supported for at least one minor.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Same surface as ``mureo.auth_setup`` — mirrored here so the public
# module does not depend on private constants in the auth-setup
# module. Keep in sync if either side bumps the Graph API version.
_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_HTTP_TIMEOUT = 30.0

# Largest page size Graph API will accept without truncation for the
# ``adaccounts`` edge. Defaults to 25 when omitted — too small for any
# Business Manager with more than a handful of accounts.
_PAGE_SIZE = 100

# Defensive upper bound on the cursor walk. 50 pages × 100 = 5000 ad
# accounts — well past anything seen in practice. Caps a buggy Graph
# response that keeps returning a ``paging.next`` cursor so the
# configure UI never spins forever.
_MAX_PAGES = 50

# Host pinning for ``paging.next`` URLs. Graph echoes the URL back to
# us in the response body — refusing to follow anything other than the
# Graph API host stops a tampered response (broken TLS pinning, proxy
# mis-route, etc.) from exfiltrating the access token (which travels in
# the cursor URL's query string from page 2 onward).
_GRAPH_HOST = "graph.facebook.com"


def _is_safe_graph_url(url: str) -> bool:
    """Return True iff ``url`` is an https URL pointing at the Graph host."""

    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == _GRAPH_HOST


def _redact(message: str, secret: str) -> str:
    """Replace ``secret`` in ``message`` with a fixed token marker.

    Used to scrub access tokens out of error messages before they reach
    operator logs or UI surfaces. The original exception chain is broken
    with ``raise ... from None`` separately — see the raise site.
    """

    if not secret:
        return message
    return message.replace(secret, "***REDACTED***")


class MetaTokenValidationError(RuntimeError):
    """Base class for :func:`validate_meta_access_token` failures.

    Subclasses ``RuntimeError`` so existing callers (and tests) that catch
    ``RuntimeError`` keep working, while the two subclasses below let the
    configure handler distinguish an invalid token from a valid token whose
    account listing failed.
    """


class MetaTokenInvalidError(MetaTokenValidationError):
    """The token itself is invalid/expired — the /me/permissions probe failed."""


class MetaAccountFetchError(MetaTokenValidationError):
    """The token is valid but /me/adaccounts could not be listed."""


class MetaTokenInspectError(MetaTokenValidationError):
    """``debug_token`` could not describe the token (#726).

    Never fatal on its own: Meta requires an app access token (or an app
    developer's user access token) to inspect a token, so a refusal is a
    routine outcome. It costs mureo the expiry date, not the credential —
    :func:`validate_meta_access_token` reports it beside the scopes and the
    caller saves anyway.
    """


class MetaTokenInspectUnavailable(MetaTokenInspectError):  # noqa: N818
    """There is no app access token to inspect with, so nothing was asked
    (#740).

    The name says the condition, not the failure — mureo asked nothing, so
    there is nothing that errored. ``N818`` is suppressed locally, the same
    way ``adapters.meta_ads.errors.UnsupportedOperation`` does it.

    Distinct from its parent because "mureo could not check" and "Meta
    refused" are different sentences for the operator: the first is fixed by
    entering the app ID and secret, the second is not. Every caller that
    treats an inspection failure as best-effort treats this the same way —
    the difference is only in what it says.
    """


#: Bounds on platform-authored text that reaches a raised message or a log
#: record. Same numbers as ``mureo.auth``, whose ``_truncate`` /
#: ``_one_log_line`` this module reuses — see :func:`_bounded`.
_GRAPH_ERROR_MESSAGE_MAX_CHARS = 200
_GRAPH_ERROR_CODE_MAX_CHARS = 32

#: Cap on Graph's ``debug_token`` ``type`` before it is echoed to a caller.
#: Graph documents a short enum (``USER``, ``PAGE``, ``APP``, …), but it is
#: still platform-authored text crossing into a response body, and the UI
#: that renders it has not been written yet.
_TOKEN_TYPE_MAX_CHARS = 200


def _bounded(value: str, limit: int) -> str:
    """One log line, at most ``limit`` characters.

    Reuses ``mureo.auth._truncate`` / ``_one_log_line`` rather than
    re-deriving them — one definition of "what mureo does to text a platform
    wrote" (#605). Imported at call time, not module scope: this module is
    re-exported by ``mureo.meta_ads`` as a stable public API, and a top-level
    import would make loading it drag in the whole credential stack. The
    deferred-import idiom is the same one :func:`_required_oauth_scopes`
    uses below.
    """

    from mureo.auth import _one_log_line, _truncate

    return _truncate(_one_log_line(value), limit)


def _required_oauth_scopes() -> list[str]:
    """The OAuth scopes a fully-provisioned Meta token should carry.

    Sourced lazily from :data:`mureo.auth_setup._META_OAUTH_SCOPES` (the
    single source of truth for the interactive wizard) so this module has
    exactly one definition of "required scopes". The import is deferred to
    call time because ``mureo.auth_setup`` imports *this* module at load —
    a top-level import here would be circular.
    """

    from mureo.auth_setup import _META_OAUTH_SCOPES

    return [s.strip() for s in _META_OAUTH_SCOPES.split(",") if s.strip()]


def _format_graph_error(payload: Any, fallback: str) -> str:
    """Render a Meta Graph API error body the way ``client._request`` does.

    Prefers ``error.message`` and appends ``subcode=`` / ``fbtrace_id=``
    when Graph supplies them so operators can quote them in a support
    ticket. Falls back to ``fallback`` (typically the raw response text)
    when the body is not the expected error envelope.

    Every part is bounded and collapsed to one line first. This string ends
    up in a raised message and, via
    :func:`validate_meta_access_token`, in a ``logger.info`` record — and
    ``error.message`` is text Meta chose, of unbounded length, that may
    contain newlines. Unbounded it floods the log; with newlines it can
    forge a second log record. Same treatment, same limits, as
    ``mureo.auth._graph_error_detail`` (#605).
    """

    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(err, dict):
        return _bounded(fallback, _GRAPH_ERROR_MESSAGE_MAX_CHARS)
    parts: list[str] = []
    if err.get("message"):
        parts.append(
            _bounded(str(err["message"]), _GRAPH_ERROR_MESSAGE_MAX_CHARS),
        )
    for field_name, label in (
        ("error_subcode", "subcode"),
        ("fbtrace_id", "fbtrace_id"),
    ):
        value = err.get(field_name)
        if value:
            parts.append(f"{label}={_bounded(str(value), _GRAPH_ERROR_CODE_MAX_CHARS)}")
    if parts:
        return " | ".join(parts)
    return _bounded(fallback, _GRAPH_ERROR_MESSAGE_MAX_CHARS)


#: The ``debug_token`` fields mureo keeps. The response also carries
#: ``scopes``, ``granular_scopes``, ``user_id``, ``app_id`` and
#: ``application``; none of them are echoed to the UI or written to a log,
#: so the Graph envelope never travels verbatim out of this module (#605).
#: ``scopes`` in particular is already reported — from ``/me/permissions``,
#: the probe that also proves the token works.
_DEBUG_TOKEN_TIMESTAMP_FIELDS = ("expires_at", "data_access_expires_at", "issued_at")


def _unix_to_iso(raw: Any) -> str | None:
    """Render a Graph unixtime as ISO 8601 UTC, or ``None`` when unusable.

    Graph stamps a non-expiring token's ``expires_at`` with ``0`` and omits
    the field entirely on some token types; ``issued_at`` is documented as
    present only for long-lived tokens. Neither zero nor a missing field is
    a date, and rendering epoch-zero as "expires 1970-01-01" would show a
    healthy credential as decades dead — so anything that is not a positive
    integer reads as "unknown".
    """

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw <= 0:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


#: Query-parameter names that carry a Meta token. A log record naming one of
#: them is quoting a URL that contains the credential itself — see
#: :class:`_TokenQueryLogFilter`.
_TOKEN_QUERY_PARAM_NAMES = ("input_token", "access_token")

#: The third-party loggers that print a request URL. httpx logs
#: ``request.url`` at INFO; httpcore logs the connection trace at DEBUG.
_HTTP_LOGGER_NAMES = ("httpx", "httpcore")


class _TokenQueryLogFilter(logging.Filter):
    """Drop any record quoting a URL with a token in its query string.

    ``debug_token`` is GET-only (#740), so the inspected token has to travel
    in the URL — and httpx logs ``request.url`` at INFO, which
    ``MUREO_LOG_LEVEL`` does not bound because it only governs mureo's own
    loggers. Rather than guess at the host application's logging config, the
    inspection installs this on the HTTP loggers for the duration of the one
    call and removes it in a ``finally``.

    It matches on the parameter NAME, not on the token: a filter that
    compared against the secret would need the secret, and every record it
    dropped would be one it had already read.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — a record that cannot render is not ours
            return True
        return not any(name in message for name in _TOKEN_QUERY_PARAM_NAMES)


def _is_never_expires(raw: Any) -> bool:
    """Return True only for Graph's literal ``expires_at: 0``.

    Zero is Graph's way of saying "this token does not expire" — the Access
    Token Debugger renders it as "Expires: Never". Everything else, including
    an absent field, is an UNKNOWN expiry: the two used to be
    indistinguishable, which is how a permanent token ended up on the 53-day
    age clock and got exchanged for a 60-day one (#740). ``bool`` is excluded
    because ``False == 0`` in Python and a JSON ``false`` is not a promise.
    """

    return isinstance(raw, int) and not isinstance(raw, bool) and raw == 0


async def inspect_meta_access_token(
    access_token: str,
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> dict[str, Any]:
    """Describe a Meta access token via Graph ``debug_token`` (#726/#740).

    Three facts, established against a real Business Manager system-user
    token, decide the shape of this call:

    1. ``debug_token`` is GET-only. The POST form #726 used — chosen to keep
       the token out of the URL — is refused with "Unsupported post request"
       (``subcode=33``), which is why the whole feature recorded nothing in
       the field.
    2. A token cannot inspect itself. ``GET /debug_token?input_token=T``
       authenticated with ``T`` is refused with "(#100) You must provide an
       app access token, or a user access token that is an owner or
       developer of the app". So mureo authenticates with the **app access
       token** ``"<app_id>|<app_secret>"`` of the app that issued the token
       (https://developers.facebook.com/docs/graph-api/reference/debug_token/),
       and without that pair there is no call to make at all —
       :class:`MetaTokenInspectUnavailable`, raised before any request.
    3. Graph reports a permanent token as ``expires_at: 0``. That is a
       promise, not a date and not a gap, so it comes back as
       ``never_expires`` with ``expires_at`` still ``None``.

    The inspected token therefore rides in the query string. The app access
    token does not: it goes in an ``Authorization: Bearer`` header, and the
    HTTP loggers are filtered for the duration of the call
    (:class:`_TokenQueryLogFilter`) so neither reaches a log record (#605).

    Args:
        access_token: the Meta access token to describe.
        app_id: app ID of the app that issued ``access_token``.
        app_secret: that app's secret. Together they form the app access
            token this call authenticates with.

    Returns:
        ``{"type", "expires_at", "data_access_expires_at", "issued_at",
        "never_expires"}``. ``type`` is Graph's own string (``"USER"``,
        ``"SYSTEM_USER"``, …) or ``None``; the three timestamps are ISO 8601
        UTC strings, or ``None`` when Graph reported no usable value;
        ``never_expires`` is True only for Graph's literal ``expires_at: 0``.
        Nothing else from the response is returned — see
        :data:`_DEBUG_TOKEN_TIMESTAMP_FIELDS`.

    Raises:
        MetaTokenInspectUnavailable: when ``app_id``/``app_secret`` are not
            both supplied, so no inspection was attempted.
        MetaTokenInspectError: on an empty token, a non-200 response, or a
            transport failure. The message carries Meta's ``error.message``
            plus ``subcode`` / ``fbtrace_id`` when present, with the access
            token and the app secret scrubbed out.
    """

    if not access_token:
        raise MetaTokenInspectError(
            "Meta token inspection failed: access_token is required"
        )

    app_id = (app_id or "").strip()
    app_secret = (app_secret or "").strip()
    if not app_id or not app_secret:
        raise MetaTokenInspectUnavailable(
            "Meta token inspection skipped: app ID and app secret are "
            "required to inspect a token"
        )

    def _scrub(message: str) -> str:
        return _redact(_redact(message, access_token), app_secret)

    log_filter = _TokenQueryLogFilter()
    http_loggers = [logging.getLogger(name) for name in _HTTP_LOGGER_NAMES]
    for http_logger in http_loggers:
        http_logger.addFilter(log_filter)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/debug_token",
                params={"input_token": access_token},
                # The app access token authenticates the call. In the header,
                # not the query: the inspected token already has to be in the
                # URL, and there is no reason to put a second secret there.
                headers={"Authorization": f"Bearer {app_id}|{app_secret}"},
            )
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if response.status_code != 200:
                detail = _scrub(_format_graph_error(payload, response.text[:500]))
                raise MetaTokenInspectError(f"Meta token inspection failed: {detail}")
    except MetaTokenInspectError:
        raise
    except Exception as exc:
        raise MetaTokenInspectError(
            f"Meta token inspection failed: {_scrub(str(exc))}"
        ) from None
    finally:
        for http_logger in http_loggers:
            http_logger.removeFilter(log_filter)

    data = payload.get("data") if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}
    token_type = data.get("type")
    info: dict[str, Any] = {
        "type": (
            _bounded(str(token_type), _TOKEN_TYPE_MAX_CHARS) if token_type else None
        ),
    }
    for field in _DEBUG_TOKEN_TIMESTAMP_FIELDS:
        info[field] = _unix_to_iso(data.get(field))
    info["never_expires"] = _is_never_expires(data.get("expires_at"))
    return info


async def validate_meta_access_token(
    access_token: str,
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> dict[str, Any]:
    """Validate a Meta access token and report scopes + reachable accounts.

    Backs the configure-UI "paste a system-user token" path. Runs two
    read-only Graph calls:

    * ``GET /me/permissions`` — the scopes actually granted to the token,
      compared against :func:`_required_oauth_scopes` to compute what is
      missing (e.g. a token minted without ``ads_management`` cannot create
      creatives).
    * ``GET /me/adaccounts`` — the ad accounts the token can reach, reduced
      to ``{id, name}`` so the UI can render an account picker.
    * ``GET /debug_token`` — when the token dies, or that it does not
      (#726/#740). Best-effort and only possible with the app pair (see
      :func:`inspect_meta_access_token`), so both "could not ask" and "Meta
      refused" are *reported*, never raised. The other two probes have
      already established whether the credential works.

    Args:
        access_token: Meta Ads access token (System User or User token).
        app_id: app ID of the app that issued ``access_token``, when known.
        app_secret: that app's secret, when known. Both are needed to
            inspect the token at all; neither is used for anything else
            here.

    Returns:
        ``{"scopes": [...granted...], "missing_scopes": [...],
        "accounts": [{"id", "name"}, ...], "token_info": {...} | None,
        "token_inspect_error": str | None, "token_inspect_skipped": bool}``.
        ``token_info`` is :func:`inspect_meta_access_token`'s curated dict;
        it and ``token_inspect_error`` are mutually exclusive.
        ``token_inspect_skipped`` is True when there was no app pair to
        inspect with, which is a different thing to tell the operator than
        an inspection Graph turned down.

    Raises:
        MetaTokenInvalidError: When the token is invalid/expired (the
            /me/permissions probe fails). The message carries Meta's
            ``error.message`` plus ``subcode`` / ``fbtrace_id`` when present,
            with the access token scrubbed out.
        MetaAccountFetchError: When the token is valid but the ad-account
            listing (/me/adaccounts) fails — a distinct condition so the
            caller does not mislabel it as an invalid token.
    """

    if not access_token:
        raise MetaTokenInvalidError(
            "Meta token validation failed: access_token is required"
        )

    granted: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/me/permissions",
                params={"access_token": access_token},
            )
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if response.status_code != 200:
                detail = _redact(
                    _format_graph_error(payload, response.text[:500]), access_token
                )
                raise MetaTokenInvalidError(f"Meta token validation failed: {detail}")
            for row in payload.get("data", []) or []:
                if row.get("status") == "granted" and row.get("permission"):
                    granted.append(row["permission"])
    except MetaTokenInvalidError:
        # Already scrubbed + framed above — do not re-wrap.
        raise
    except Exception as exc:
        scrubbed = _redact(str(exc), access_token)
        raise MetaTokenInvalidError(
            f"Meta token validation failed: {scrubbed}"
        ) from None

    required = _required_oauth_scopes()
    missing = [scope for scope in required if scope not in granted]

    # Reuse the paginated account walk. The permissions probe above already
    # proved the token is valid, so any failure here is an account-listing
    # problem (permissions, transient Graph error) — surfaced as a DISTINCT
    # error type so the caller never mislabels it as an invalid token.
    try:
        raw_accounts = await list_meta_ad_accounts(access_token)
    except Exception as exc:
        scrubbed = _redact(str(exc), access_token)
        raise MetaAccountFetchError(
            f"Meta ad-account listing failed: {scrubbed}"
        ) from None
    accounts = [
        {"id": acct.get("id"), "name": acct.get("name")}
        for acct in raw_accounts
        if acct.get("id")
    ]

    # Last, and never fatal: by here the token has already proved it works.
    token_info: dict[str, Any] | None = None
    token_inspect_error: str | None = None
    token_inspect_skipped = False
    try:
        token_info = await inspect_meta_access_token(
            access_token, app_id=app_id, app_secret=app_secret
        )
    except MetaTokenInspectUnavailable as exc:
        # Not an error: nothing was asked, because there was nothing to ask
        # with. Kept off ``token_inspect_error`` so the caller can say "add
        # the app ID and secret" instead of "Meta refused" (#740).
        token_inspect_skipped = True
        logger.info("Meta token inspection skipped: %s", str(exc))
    except Exception as exc:  # noqa: BLE001 — an unknown expiry is not a failure
        token_inspect_error = _redact(_redact(str(exc), access_token), app_secret or "")
        logger.info("Meta token inspection unavailable: %s", token_inspect_error)

    return {
        "scopes": granted,
        "missing_scopes": missing,
        "accounts": accounts,
        "token_info": token_info,
        "token_inspect_error": token_inspect_error,
        "token_inspect_skipped": token_inspect_skipped,
    }


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Retrieve the list of Meta ad accounts the access token can reach.

    Calls ``GET /me/adaccounts`` on the Graph API and walks the
    ``paging.next`` cursor until exhausted so every account under a
    Business Manager is returned, not just the first 25. Pages are
    concatenated in cursor order (== Graph's natural order) so the
    configure-UI dropdown ranks accounts consistently across runs.

    Args:
        access_token: Meta Ads access token (System User or User token).

    Returns:
        List of ad account dicts (``id``, ``name``, ``account_status``).

    Raises:
        RuntimeError: When the Graph API call fails (network error or
            non-2xx response).
    """
    accounts: list[dict[str, Any]] = []
    next_url: str | None = f"{_META_GRAPH_API_BASE}/me/adaccounts"
    # ``params`` is only sent on the first request — subsequent
    # ``paging.next`` URLs already carry every query parameter Graph
    # needs (including ``access_token`` and ``after`` cursor), so
    # resending them would corrupt the cursor.
    first_request_params: dict[str, Any] | None = {
        "fields": "id,name,account_status",
        "limit": _PAGE_SIZE,
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for _ in range(_MAX_PAGES):
                if not next_url:
                    break
                if not _is_safe_graph_url(next_url):
                    logger.warning(
                        "Refusing to follow non-Graph paging.next URL; "
                        "truncating Meta ad-account list."
                    )
                    break
                response = await client.get(next_url, params=first_request_params)
                response.raise_for_status()
                payload = response.json()
                accounts.extend(payload.get("data", []) or [])
                next_url = (payload.get("paging") or {}).get("next")
                first_request_params = None
            else:
                # Loop exhausted the cap — log so the gap is visible in
                # operator logs even though the UI sees a finite list.
                logger.warning(
                    "Meta ad-account pagination hit the %d-page cap; some "
                    "accounts may be missing from the configure UI.",
                    _MAX_PAGES,
                )
        return accounts
    except Exception as exc:
        # Scrub the access token before it lands in operator logs or UI.
        # From page 2 onward the token lives in ``next_url`` itself, so
        # an HTTPStatusError from httpx (which embeds the request URL in
        # its ``__str__``) would otherwise leak it verbatim.
        scrubbed = _redact(str(exc), access_token)
        # ``from None`` breaks the exception chain so the original
        # exception's ``__cause__`` (which still carries the unscrubbed
        # URL) is not printed by default traceback formatting.
        raise RuntimeError(f"Failed to retrieve ad account list: {scrubbed}") from None


__all__ = [
    "MetaAccountFetchError",
    "MetaTokenInspectError",
    "MetaTokenInspectUnavailable",
    "MetaTokenInvalidError",
    "MetaTokenValidationError",
    "inspect_meta_access_token",
    "list_meta_ad_accounts",
    "validate_meta_access_token",
]
