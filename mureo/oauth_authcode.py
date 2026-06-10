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
import urllib.parse
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

#: Outbound timeout for the token exchange. Matches the conservative
#: default used by the Meta flow in :mod:`mureo.auth_setup`.
_HTTP_TIMEOUT = httpx.Timeout(30.0)


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
) -> AuthCodeResult:
    """Exchange an authorization ``code`` for a ``refresh_token``.

    POSTs ``grant_type=authorization_code`` (form-encoded) to
    ``token_url`` with HTTP Basic client authentication. Raises
    :class:`OAuthExchangeError` on any transport/HTTP failure or when the
    response carries no ``refresh_token`` (the whole point of the flow —
    an access token alone cannot be persisted for later refresh).

    The exception message never includes the code, secret, or token; only
    the failure class is surfaced so a stack trace cannot leak material.
    """
    _require_https(token_url, "token_url")
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            response = client.post(
                token_url, data=body, auth=(client_id, client_secret)
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
]
