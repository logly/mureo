"""Accessible-account discovery for the Meta Marketing API.

Public surface for tooling that needs to enumerate the Meta ad accounts a
given access token can reach, so configure-UI consumers (in-tree and
third-party) can build account pickers without reaching into the wizard's
internal module. ``mureo.auth_setup.list_meta_ad_accounts`` stays valid as
a thin re-export.

The return value is a list of dicts, as the :class:`MetaAdAccountList`
subclass that adds a ``truncated`` flag and compares equal to a plain list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Final
from urllib.parse import quote, urlparse

import httpx

from mureo.logging_setup import one_log_line, truncate_text
from mureo.meta_ads._api_version import GRAPH_API_BASE
from mureo.meta_ads._graph_error import GRAPH_ERROR_NO_DETAIL, format_graph_error

logger = logging.getLogger(__name__)

# The single source of the Meta OAuth scopes and the Graph HTTP timeout.
# ``mureo.auth_setup`` (the interactive wizard) imports both from here, so
# the dependency points one way: ``meta_ads`` never imports ``auth_setup``
# or ``auth`` (#863). The Graph API version pin itself lives in
# :mod:`mureo.meta_ads._api_version` (#770).
META_OAUTH_SCOPES: Final = (
    "ads_management,ads_read,business_management,"
    "pages_show_list,pages_manage_ads,pages_read_engagement,leads_retrieval"
)
META_HTTP_TIMEOUT_SECONDS: Final = 30.0

# Largest page size Graph API will accept without truncation for the
# ``adaccounts`` edge. Defaults to 25 when omitted — too small for any
# Business Manager with more than a handful of accounts.
_PAGE_SIZE = 100

# The ``adaccounts`` fields mureo asks Graph for. ``id,name,account_status``
# alone cannot tell two ad accounts apart when both are called "Brand" —
# which is the normal state of a Business Manager holding one account per
# market. The owning business, the currency and the timezone are what an
# operator recognises an account by; ``disable_reason`` and
# ``end_advertiser_name`` say why a disabled account is disabled and who it
# runs for. ``business{id,name}`` is a nested-object selector: Graph returns
# it as an object, and it is passed through as-is rather than flattened, so
# a consumer reads ``row["business"]["name"]``.
_ADACCOUNT_FIELDS = (
    "id,name,account_status,business{id,name},currency,timezone_name,"
    "disable_reason,end_advertiser_name"
)

# ``GET /me/adaccounts`` returns the ad accounts the person holds a role on
# directly. Accounts assigned through a Business Portfolio are often absent
# from it, so each portfolio from ``GET /me/businesses`` is walked on these
# edges as well: the accounts it owns and the ones it was given access to.
_BUSINESS_FIELDS = "id,name"
_BUSINESS_AD_ACCOUNT_EDGES = ("owned_ad_accounts", "client_ad_accounts")

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
    """Replace ``secret`` in ``message`` with a fixed marker, in the form it
    was given and in the percent-encoded form httpx writes into URLs."""

    if not secret:
        return message
    for form in {secret, quote(secret, safe="")}:
        message = message.replace(form, "***REDACTED***")
    return message


class MetaAdAccountList(list[dict[str, Any]]):
    """The ad accounts a token can reach, plus whether that list is whole.

    Compares, iterates, indexes and slices exactly like the plain
    ``list[dict[str, Any]]`` :func:`list_meta_ad_accounts` used to return —
    ``MetaAdAccountList([row]) == [row]`` — so no existing caller has to
    change. The one addition is :attr:`truncated`.

    Attributes:
        truncated: True when the walk stopped before Graph ran out of
            cursors, so accounts the token can reach are missing from this
            list. False (the default) means the list is complete. Before
            #746 a truncated walk only wrote a warning to the operator log,
            which no UI reads — a partial dropdown was indistinguishable
            from a full one.
    """

    truncated: bool = False


def _normalise_account_row(row: Any) -> Any:
    """Return ``row`` with an explicit ``name`` key.

    Graph omits ``name`` entirely for an ad account that has none. The key
    is always present on the way out, ``None`` when Graph gave nothing, so
    a consumer can tell "unnamed" from "named after its own id" — the old
    behaviour copied the id into ``name`` and the two collapsed (#746).

    Everything else Graph returned is passed through untouched, nested
    objects (``business``) included.
    """

    if not isinstance(row, dict):
        return row
    return {**row, "name": row.get("name")}


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
    """The token is valid but the ad accounts could not be listed."""


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


#: Cap on Graph's ``debug_token`` ``type`` before it is echoed to a caller.
#: Graph documents a short enum (``USER``, ``PAGE``, ``APP``, …), but it is
#: still platform-authored text crossing into a response body, and the UI
#: that renders it has not been written yet.
_TOKEN_TYPE_MAX_CHARS = 200


def _required_oauth_scopes() -> list[str]:
    """The OAuth scopes a fully-provisioned Meta token should carry.

    Read from :data:`META_OAUTH_SCOPES`, the single definition of "required
    scopes" that the interactive wizard in ``mureo.auth_setup`` requests too.
    """
    return [s.strip() for s in META_OAUTH_SCOPES.split(",") if s.strip()]


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
#: ``request.url`` at INFO through the ``httpx`` logger; httpcore logs its
#: connection trace at DEBUG through one logger PER TRANSPORT LAYER.
#:
#: The children are listed individually on purpose. A ``logging.Filter``
#: attached with ``Logger.addFilter`` is consulted only for records logged
#: through that exact logger object — unlike handlers and levels, filters
#: are NOT inherited down the hierarchy. So a filter on ``httpcore`` alone
#: would never see a single ``httpcore.http11`` record, and a host
#: application running httpcore at DEBUG would still get the token.
#: ``httpcore`` and ``httpx`` stay in the list because either package may
#: log through its own root name in a future release.
_HTTP_LOGGER_NAMES = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


class _TokenQueryLogFilter(logging.Filter):
    """Drop any record quoting a URL with a token in its query string.

    ``debug_token`` is GET-only (#740), so the inspected token has to travel
    in the URL — and httpx logs ``request.url`` at INFO, which
    ``MUREO_LOG_LEVEL`` does not bound because it only governs mureo's own
    loggers. Rather than guess at the host application's logging config, the
    inspection installs this on every logger in
    :data:`_HTTP_LOGGER_NAMES` for the duration of the one call and removes
    it in a ``finally``. That list names httpcore's per-layer child loggers
    one by one, because filters are not inherited by child loggers.

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
    token does not: it goes in an ``Authorization: Bearer`` header, and
    every httpx/httpcore logger named in :data:`_HTTP_LOGGER_NAMES` is
    filtered for the duration of the call (:class:`_TokenQueryLogFilter`) so
    neither reaches a log record (#605).

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
        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{GRAPH_API_BASE}/debug_token",
                params={"input_token": access_token},
                # The app access token authenticates the call. In the header,
                # not the query: the inspected token already has to be in the
                # URL, and there is no reason to put a second secret there.
                headers={"Authorization": f"Bearer {app_id}|{app_secret}"},
            )
            try:
                payload: Any = response.json()
            except ValueError:  # not JSON: no error detail and no data
                payload = None
            if response.status_code != 200:
                detail = _scrub(
                    format_graph_error(payload, fallback=GRAPH_ERROR_NO_DETAIL)
                )
                raise MetaTokenInspectError(f"Meta token inspection failed: {detail}")
    except MetaTokenInspectError:
        raise
    except Exception as exc:  # noqa: BLE001 — re-raised as MetaTokenInspectError
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
            truncate_text(one_log_line(str(token_type)), _TOKEN_TYPE_MAX_CHARS)
            if token_type
            else None
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
    * :func:`list_meta_ad_accounts` (direct and Business Portfolio edges) —
      the ad accounts the token can reach, reduced to ``{id, name}``.
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
            /me/permissions probe fails or returns a body that is not
            JSON). The message carries Meta's ``error.message`` plus
            ``subcode`` / ``fbtrace_id`` when present, with the access
            token scrubbed out.
        MetaAccountFetchError: When the token is valid but the ad-account
            listing (:func:`list_meta_ad_accounts`) fails — a distinct
            condition so the caller does not mislabel it as an invalid token.
    """

    if not access_token:
        raise MetaTokenInvalidError(
            "Meta token validation failed: access_token is required"
        )

    granted: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{GRAPH_API_BASE}/me/permissions",
                params={"access_token": access_token},
            )
            try:
                payload: Any = response.json()
            except ValueError:  # a non-JSON body is a failed probe
                payload = None
            if response.status_code != 200:
                detail = _redact(
                    format_graph_error(payload, fallback=GRAPH_ERROR_NO_DETAIL),
                    access_token,
                )
                raise MetaTokenInvalidError(f"Meta token validation failed: {detail}")
            if not isinstance(payload, dict):
                raise MetaTokenInvalidError(
                    f"Meta token validation failed: {GRAPH_ERROR_NO_DETAIL}"
                )
            for row in payload.get("data", []) or []:
                if row.get("status") == "granted" and row.get("permission"):
                    granted.append(row["permission"])
    except MetaTokenInvalidError:
        # Already scrubbed + framed above — do not re-wrap.
        raise
    except Exception as exc:  # noqa: BLE001 — re-raised as MetaTokenInvalidError
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
    except Exception as exc:  # noqa: BLE001 — re-raised as MetaAccountFetchError
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


def _graph_error_code(exc: BaseException) -> int | None:
    """The Graph ``error.code`` of an HTTP error response; ``None`` when the
    exception is another kind, the body is not JSON or the code is not an int."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    try:
        payload: Any = exc.response.json()
    except ValueError:  # a non-JSON body carries no code
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    return None


def _is_permission_error(code: int | None) -> bool:
    """Graph refused for lack of permission: ``(#10) ... requires
    business_management`` or a ``#2xx`` permissions error. The portfolio
    walk is skipped quietly for these, so a token stored before
    ``business_management`` was requested keeps its direct list unchanged."""
    return code == 10 or (code is not None and 200 <= code <= 299)


async def _fetch_page(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None
) -> tuple[list[Any], str | None]:
    """One page of a Graph edge: its normalised rows and the next cursor."""
    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    rows = [_normalise_account_row(row) for row in payload.get("data", []) or []]
    return rows, (payload.get("paging") or {}).get("next")


async def _walk_edge(
    client: httpx.AsyncClient,
    path: str,
    *,
    fields: str,
    access_token: str,
) -> MetaAdAccountList:
    """Walk one Graph edge (``path`` below the base URL); errors propagate.

    ``truncated`` is set when the walk stopped with rows left behind.
    """
    rows = MetaAdAccountList()
    next_url: str | None = f"{GRAPH_API_BASE}{path}"
    # Sent on the first request only: a ``paging.next`` URL already carries
    # every query parameter (token and cursor), so resending would corrupt it.
    first_request_params: dict[str, Any] | None = {
        "fields": fields,
        "limit": _PAGE_SIZE,
        "access_token": access_token,
    }
    for _ in range(_MAX_PAGES):
        if not next_url:
            break
        if not _is_safe_graph_url(next_url):
            logger.warning(
                "Refusing to follow non-Graph paging.next URL; "
                "truncating Meta ad-account list."
            )
            # The refusal is the right call, but it leaves the list
            # partial — say so to the caller as well as the log.
            rows.truncated = True
            break
        page, next_url = await _fetch_page(client, next_url, first_request_params)
        rows.extend(page)
        first_request_params = None
    else:
        # Loop exhausted the cap. A walk whose final page carried no cursor
        # is complete, cap or not; only a pending cursor means accounts were
        # left behind — logged, and flagged so the UI can say so too.
        if next_url:
            logger.warning(
                "Meta ad-account pagination hit the %d-page cap; some "
                "accounts may be missing from the configure UI.",
                _MAX_PAGES,
            )
            rows.truncated = True
    return rows


async def _walk_business_edges(
    client: httpx.AsyncClient, business_id: str, access_token: str
) -> MetaAdAccountList:
    """The ad accounts one Business Portfolio owns or was given access to.

    One edge failing does not hide the other, nor the portfolios after
    this one. A permission error means the person's role in the portfolio
    does not reach that edge, so nothing reachable is missing and the edge
    is skipped quietly; any other failure flags the result ``truncated``.
    """
    result = MetaAdAccountList()
    for edge in _BUSINESS_AD_ACCOUNT_EDGES:
        try:
            rows = await _walk_edge(
                client,
                f"/{business_id}/{edge}",
                fields=_ADACCOUNT_FIELDS,
                access_token=access_token,
            )
        except Exception as exc:  # noqa: BLE001 — the other edges stand without it
            scrubbed = _redact(str(exc), access_token)
            if _is_permission_error(_graph_error_code(exc)):
                logger.debug(
                    "Meta business %s edge %s skipped: %s", business_id, edge, scrubbed
                )
                continue
            logger.warning(
                "Meta business %s edge %s failed; the list is returned without it: %s",
                business_id,
                edge,
                scrubbed,
            )
            result.truncated = True
            continue
        result.extend(rows)
        result.truncated = result.truncated or rows.truncated
    return result


async def _list_business_ad_accounts(
    client: httpx.AsyncClient, access_token: str
) -> MetaAdAccountList:
    """The ad accounts reached through the token's Business Portfolios.

    Never raises: the direct list must survive any portfolio failure. A
    token without ``business_management`` yields an empty, complete list;
    a portfolio listing that fails otherwise yields an empty list flagged
    ``truncated``. Per-edge failures are handled in
    :func:`_walk_business_edges`.
    """
    result = MetaAdAccountList()
    try:
        businesses = await _walk_edge(
            client, "/me/businesses", fields=_BUSINESS_FIELDS, access_token=access_token
        )
    except Exception as exc:  # noqa: BLE001 — the direct list stands without it
        scrubbed = _redact(str(exc), access_token)
        if _is_permission_error(_graph_error_code(exc)):
            logger.debug("Meta business listing skipped: %s", scrubbed)
            return result
        logger.warning(
            "Meta business listing failed; the direct list is returned "
            "without it: %s",
            scrubbed,
        )
        result.truncated = True
        return result
    result.truncated = businesses.truncated
    for business in businesses:
        business_id = business.get("id") if isinstance(business, dict) else None
        if not isinstance(business_id, str):
            continue
        rows = await _walk_business_edges(client, business_id, access_token)
        result.extend(rows)
        result.truncated = result.truncated or rows.truncated
    return result


async def list_meta_ad_accounts(access_token: str) -> MetaAdAccountList:
    """Retrieve the list of Meta ad accounts the access token can reach.

    Walks three Graph edges, each through its ``paging.next`` cursor so
    every account is returned, not just the first 25: ``GET
    /me/adaccounts`` (the accounts the person holds a role on directly),
    then ``GET /me/businesses`` and, for each Business Portfolio in Graph's
    order, its ``owned_ad_accounts`` and ``client_ad_accounts``. The result
    is the union keyed by account ``id``: the direct accounts first, in
    cursor order, then each portfolio account not already listed. A row
    already present is kept as it is; a portfolio row without an ``id`` is
    dropped. The order is therefore stable across runs, so the
    configure-UI dropdown ranks accounts consistently.

    Listing portfolios needs ``business_management``, which is part of
    :data:`META_OAUTH_SCOPES`. A token without it (Graph error ``#10`` or a
    ``#2xx`` permissions error on ``/me/businesses``) gets the direct
    accounts alone, not flagged as truncated.

    Args:
        access_token: Meta Ads access token (System User or User token).

    Returns:
        A :class:`MetaAdAccountList` — a plain list of ad account dicts
        that also carries a ``truncated`` flag. Each dict is the row Graph
        returned for the fields in :data:`_ADACCOUNT_FIELDS`: ``id``,
        ``name`` (``None`` when the account has none), ``account_status``,
        ``business`` (a nested ``{"id", "name"}`` object, passed through
        unflattened), ``currency``, ``timezone_name``, ``disable_reason``
        and ``end_advertiser_name``. Graph omits a field it has no value
        for, so only ``id`` and ``name`` are guaranteed present.

        ``truncated`` is True when a walk stopped early — the page cap
        was reached, a ``paging.next`` URL was refused, or a Business
        Portfolio edge failed — meaning reachable accounts are missing
        from the list.

    Raises:
        RuntimeError: When the ``/me/adaccounts`` call fails (network
            error or non-2xx response). A Business Portfolio failure never
            raises; it sets ``truncated`` instead.
    """
    try:
        async with httpx.AsyncClient(timeout=META_HTTP_TIMEOUT_SECONDS) as client:
            direct = await _walk_edge(
                client,
                "/me/adaccounts",
                fields=_ADACCOUNT_FIELDS,
                access_token=access_token,
            )
            business = await _list_business_ad_accounts(client, access_token)
    except Exception as exc:  # noqa: BLE001 — re-raised with the token redacted
        # Scrub the access token before it lands in operator logs or UI.
        # From page 2 onward the token lives in ``next_url`` itself, so
        # an HTTPStatusError from httpx (which embeds the request URL in
        # its ``__str__``) would otherwise leak it verbatim.
        scrubbed = _redact(str(exc), access_token)
        # ``from None`` breaks the exception chain so the original
        # exception's ``__cause__`` (which still carries the unscrubbed
        # URL) is not printed by default traceback formatting.
        raise RuntimeError(f"Failed to retrieve ad account list: {scrubbed}") from None

    accounts = MetaAdAccountList(direct)
    seen = {row.get("id") for row in direct if isinstance(row, dict)}
    for row in business:
        row_id = row.get("id") if isinstance(row, dict) else None
        if row_id and row_id not in seen:
            accounts.append(row)
            seen.add(row_id)
    accounts.truncated = direct.truncated or business.truncated
    return accounts


__all__ = [
    "META_HTTP_TIMEOUT_SECONDS",
    "META_OAUTH_SCOPES",
    "MetaAccountFetchError",
    "MetaAdAccountList",
    "MetaTokenInspectError",
    "MetaTokenInspectUnavailable",
    "MetaTokenInvalidError",
    "MetaTokenValidationError",
    "inspect_meta_access_token",
    "list_meta_ad_accounts",
    "validate_meta_access_token",
]
