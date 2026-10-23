"""Generic, library-agnostic OAuth2 authorization-code helpers (#201).

The Google Ads onboarding flow in :mod:`mureo.auth_setup` is built on
``google_auth_oauthlib.Flow`` and is Google-specific. This module is its
provider-neutral counterpart: it builds an authorization-code consent URL
and exchanges the returned ``code`` for a ``refresh_token`` using plain
HTTP, so any standards-compliant OAuth2 provider a plugin declares (via
:class:`mureo.core.providers.AccountOAuthConfig`) works without bespoke
code — Yahoo! JAPAN Ads (``https://biz-oauth.yahoo.co.jp/oauth/v1/...``)
being the first consumer.

Client authentication uses the HTTP Basic scheme (RFC 6749 §2.3.1, the
form Yahoo's token endpoint expects). Secrets — the client secret, the
authorization code, and the obtained tokens — are never written to logs:
errors report only the exception *type*, never request/response bodies.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import httpx

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: Outbound timeout for the token exchange. Matches the conservative
#: default used by the Meta flow in :mod:`mureo.auth_setup`.
_HTTP_TIMEOUT = httpx.Timeout(30.0)

# RFC 7230 §3.2.6 ``token``: the characters an HTTP header name may use.
_HEADER_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
)

# A header value: non-empty visible ASCII, inner spaces allowed, no leading or
# trailing whitespace. Excludes CR/LF (header injection), tabs, NUL and
# non-ASCII.
_HEADER_VALUE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[\x21-\x7e](?:[\x20-\x7e]*[\x21-\x7e])?"
)

# Headers the token request sets itself (transport, body framing, client
# authentication). A declared header with one of these names would replace or
# be silently dropped in favour of the request's own, so it is refused.
_RESERVED_HEADER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "transfer-encoding",
    }
)


class OAuthExchangeError(RuntimeError):
    """Raised when the authorization-code exchange fails or yields no
    ``refresh_token``. The message never contains secret material."""


@dataclass(frozen=True)
class AuthCodeResult:
    """Outcome of a successful authorization-code exchange."""

    refresh_token: str
    access_token: str


def _require_https(url: str, label: str) -> None:
    """Reject anything but a clean ``https://host`` URL.

    Guards against a plugin declaring a plaintext endpoint (the secret
    would traverse the wire unencrypted) and against control characters
    that could smuggle a second header/URL when the value is later placed
    in a redirect. Loopback ``redirect_uri`` values are intentionally not
    routed through here — they are ``http://127.0.0.1:<port>`` by design.
    """
    if any(c in url for c in "\r\n\t") or url.strip() != url:
        raise ValueError(f"{label} contains illegal whitespace/control characters")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an https:// URL, got {parsed.scheme!r}")


def validate_token_headers(headers: object, *, where: str) -> None:
    """Fail loudly on malformed extra headers for a token request.

    ``headers`` must be a tuple of ``(name, value)`` pairs of ``str``
    (``TypeError`` otherwise). Each name must be an RFC 7230 token, not one
    the token request sets itself (``Host``, ``Authorization``, ...) and not
    repeat another case-insensitively; each value must be non-empty visible
    ASCII with no leading/trailing whitespace (``ValueError`` otherwise) — a
    line break would let a value inject further headers. ``where`` prefixes
    every message. Messages name the offending header, never its value.
    """
    if not isinstance(headers, tuple):
        raise TypeError(f"{where} must be a tuple, got {type(headers).__name__}")
    seen: set[str] = set()
    for pair in headers:
        if not (
            isinstance(pair, tuple)
            and len(pair) == 2
            and all(isinstance(part, str) for part in pair)
        ):
            raise TypeError(
                f"{where} entries must be (name, value) str pairs, "
                f"got {type(pair).__name__}"
            )
        name, value = pair
        if not _HEADER_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"{where}: header name {name!r} is not a valid HTTP header name"
            )
        folded = name.lower()
        if folded in _RESERVED_HEADER_NAMES:
            raise ValueError(
                f'{where}: header "{name}" is set by the token request itself'
            )
        if folded in seen:
            raise ValueError(f'{where}: header "{name}" is declared more than once')
        seen.add(folded)
        if not _HEADER_VALUE_PATTERN.fullmatch(value):
            raise ValueError(
                f'{where}: header "{name}" value must be non-empty visible ASCII'
            )


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})


def parse_loopback_callback_url(url: str) -> tuple[str, int, str]:
    """Validate an operator-supplied OAuth callback URL → ``(host, port, path)``.

    The configure server binds a temporary listener on the URL's port to
    receive the authorization code, and sends this exact URL as the
    ``redirect_uri`` (so it must match what the operator pre-registered in
    the provider's console — #216). The URL must therefore be a
    **loopback** ``http://`` URL with an explicit port and a path:

    - scheme ``http`` — the local listener is plaintext (no TLS on
      loopback) and an ``https`` callback cannot be served here;
    - host ``127.0.0.1`` or ``localhost`` — configure cannot receive a
      non-loopback callback, and forwarding a code elsewhere is unsafe;
    - an explicit port (the port the listener binds);
    - a non-empty path (the route the provider redirects to).

    Raises:
        ValueError: not a loopback http URL with an explicit port and
            path. The message is safe to surface to the operator.
    """
    if not url or any(c in url for c in "\r\n\t") or url.strip() != url:
        raise ValueError("callback URL is empty or contains illegal characters")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http":
        raise ValueError("callback URL must be http:// (loopback only)")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            "callback URL host must be 127.0.0.1 or localhost (loopback only)"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("callback URL has an invalid port") from exc
    if port is None:
        raise ValueError("callback URL must include an explicit port")
    if not parsed.path:
        raise ValueError("callback URL must include a path (e.g. /oauth/callback)")
    return parsed.hostname, port, parsed.path


def build_authorization_code_url(
    *,
    authorize_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str,
) -> str:
    """Return the provider consent URL for the authorization-code grant.

    Appends the standard ``response_type=code`` parameter set. ``scope``
    is included only when ``scopes`` is non-empty (some providers reject
    an empty ``scope=``). All values are percent-encoded, so a hostile
    ``redirect_uri`` / ``state`` cannot break out of the query string.
    """
    _require_https(authorize_url, "authorize_url")
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{authorize_url}?{urllib.parse.urlencode(params)}"


def exchange_authorization_code(
    *,
    token_url: str,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    client_auth: str = "basic",
    headers: Mapping[str, str] | None = None,
) -> AuthCodeResult:
    """Exchange an authorization ``code`` for a ``refresh_token``.

    POSTs ``grant_type=authorization_code`` (form-encoded) to
    ``token_url``. Client authentication follows ``client_auth``:

    - ``"basic"`` (default, RFC 6749 §2.3.1) — client id/secret in the
      HTTP ``Authorization`` header; the scheme Google and most providers
      expect.
    - ``"body"`` — client id/secret in the form body (RFC 6749 §2.3.1's
      alternative). Required by providers that reject Basic, e.g. Yahoo!
      JAPAN biz-oauth.

    ``headers``, when given, are sent as extra HTTP headers on the token
    request (e.g. an installation identifier a brokering endpoint requires);
    they are checked with :func:`validate_token_headers` before anything is
    sent (``ValueError`` / ``TypeError`` on a malformed header).

    Raises :class:`OAuthExchangeError` on any transport/HTTP failure or
    when the response carries no ``refresh_token`` (the whole point of the
    flow — an access token alone cannot be persisted for later refresh).

    The exception message never includes the code, secret, or token; only
    the failure class is surfaced so a stack trace cannot leak material.
    """
    _require_https(token_url, "token_url")
    if headers:
        validate_token_headers(tuple(headers.items()), where="headers")
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    # Pick the client-auth transport: Basic header (default) or in-body
    # credentials (Yahoo! JAPAN biz-oauth rejects Basic). httpx's ``auth``
    # parameter has no typed ``None``, so for body style we omit it entirely
    # (the client configures no auth, so nothing is sent).
    basic_auth: tuple[str, str] | None = None
    if client_auth == "body":
        body["client_id"] = client_id
        body["client_secret"] = client_secret
    else:
        basic_auth = (client_id, client_secret)
    # httpx treats ``headers=None`` as "no extra headers".
    extra_headers = dict(headers) if headers else None
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            if basic_auth is None:
                response = client.post(token_url, data=body, headers=extra_headers)
            else:
                response = client.post(
                    token_url, data=body, auth=basic_auth, headers=extra_headers
                )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        # Type only — httpx exceptions can embed the request URL/headers.
        raise OAuthExchangeError(
            f"authorization-code exchange failed: {type(exc).__name__}"
        ) from exc
    except ValueError as exc:  # malformed JSON body
        raise OAuthExchangeError(
            f"token endpoint returned a non-JSON body: {type(exc).__name__}"
        ) from exc

    refresh_token = payload.get("refresh_token") if isinstance(payload, dict) else None
    if not refresh_token:
        raise OAuthExchangeError("token endpoint did not return a refresh_token")
    access_token = payload.get("access_token", "") or ""
    logger.info("authorization-code exchange succeeded (refresh_token obtained)")
    return AuthCodeResult(refresh_token=refresh_token, access_token=access_token)


__all__ = [
    "AuthCodeResult",
    "OAuthExchangeError",
    "build_authorization_code_url",
    "exchange_authorization_code",
    "parse_loopback_callback_url",
    "validate_token_headers",
]
