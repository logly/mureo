"""Login-with-Amazon token minting (#113 Phase 2A, #121 phase B).

Spec verified from the official Amazon Ads authorization docs
(refresh 2026-05-19, authorization code 2026-07-31):

- Regional token hosts (resulting tokens are valid globally):
    NA https://api.amazon.com/auth/o2/token
    EU https://api.amazon.co.uk/auth/o2/token
    FE https://api.amazon.co.jp/auth/o2/token
- Refresh: POST form ``grant_type=refresh_token`` + ``refresh_token`` +
  ``client_id`` + ``client_secret``.
- 200 → JSON ``{access_token, token_type, expires_in, refresh_token}``
  (the same refresh token is returned).
- A dead refresh token → HTTP 400 ``{"error":"invalid_grant",…}``;
  this is NOT auto-recoverable — the advertiser must re-authorize.

Authorization-code half (the paste-code wizard):

- Regional authorize URL prefixes:
    NA https://www.amazon.com/ap/oa
    EU https://eu.account.amazon.com/ap/oa
    FE https://apac.account.amazon.com/ap/oa
  Query: ``client_id`` + ``scope=advertising::campaign_management`` +
  ``response_type=code`` + ``redirect_uri``. The redirect URI must be
  listed in the LwA security profile's Allowed Return URLs; the
  documented direct-advertiser pattern is any valid URL (default
  ``https://amazon.com``) from whose address bar the advertiser copies
  the returned ``code``.
- Exchange: POST form ``grant_type=authorization_code`` + ``code`` +
  ``redirect_uri`` + ``client_id`` + ``client_secret`` to the SAME
  regional token host, answering with both tokens.
- Authorization codes expire **5 minutes** after consent, which is the
  overwhelmingly likely cause of a rejected code — hence its own error
  type so the UI can say so.

Tokens / secrets are never placed in exception text or logs.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.auth import AmazonAdsCredentials

logger = logging.getLogger(__name__)

_TOKEN_HOST = {
    "na": "https://api.amazon.com/auth/o2/token",
    "eu": "https://api.amazon.co.uk/auth/o2/token",
    "fe": "https://api.amazon.co.jp/auth/o2/token",
}
_AUTHORIZE_HOST = {
    "na": "https://www.amazon.com/ap/oa",
    "eu": "https://eu.account.amazon.com/ap/oa",
    "fe": "https://apac.account.amazon.com/ap/oa",
}
_TIMEOUT = 30.0

#: The Amazon Ads scope the bridge's tools operate under.
ADVERTISING_SCOPE = "advertising::campaign_management"

#: Amazon's documented direct-advertiser return URL: consent redirects
#: here and the advertiser copies ``?code=…`` out of the address bar. It
#: must be listed in the LwA security profile's Allowed Return URLs.
DEFAULT_REDIRECT_URI = "https://amazon.com"

#: Lifetime of an authorization code, per Amazon's docs.
AUTHORIZATION_CODE_TTL_MINUTES = 5

#: LwA ``error`` codes that mean "the code you sent is no good": expired
#: (the 5-minute window), already redeemed, or paired with a different
#: redirect_uri than the consent URL carried.
_CODE_REJECTED_ERRORS = frozenset({"invalid_grant", "invalid_request"})

# (url, form-data) -> response with ``.status_code`` and ``.json()``.
HttpPost = Callable[[str, dict[str, str]], Any]


class AmazonAuthError(RuntimeError):
    """LwA token minting could not produce a usable access token."""


class AmazonAuthCodeError(AmazonAuthError):
    """The pasted authorization code was rejected by Amazon.

    A distinct type (still an :class:`AmazonAuthError`) because the
    remedy differs from every other failure: codes die 5 minutes after
    consent and are single-use, so the operator must re-authorize rather
    than check their credentials.
    """


@dataclass(frozen=True)
class LwaTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def token_endpoint(region: str) -> str:
    """Regional LwA token URL. Raises ValueError for an unknown region."""
    try:
        return _TOKEN_HOST[region]
    except KeyError:
        raise ValueError(
            f"unknown Amazon region for LwA token endpoint: {region!r}"
        ) from None


def authorize_endpoint(region: str) -> str:
    """Regional LwA authorize URL prefix.

    Same contract as :func:`token_endpoint` and
    :func:`mureo.amazon_ads.endpoints.endpoint_url`: an unknown region is
    a programming error, not a silent default. Callers holding raw
    operator input normalize with :func:`normalize_region` first.

    Raises:
        ValueError: region is not one of ``na`` / ``eu`` / ``fe``.
    """
    try:
        return _AUTHORIZE_HOST[region]
    except KeyError:
        raise ValueError(
            f"unknown Amazon region for LwA authorize endpoint: {region!r}"
        ) from None


def normalize_region(value: object) -> str:
    """Coerce raw input to ``na`` / ``eu`` / ``fe`` (default ``na``).

    Mirrors the credentials loader's rule (``mureo.auth._amazon_region``)
    so a region typed into the configure UI resolves to the same endpoint
    set the bridge will later use — an unknown value degrades to ``na``
    rather than failing the request.
    """
    region = str(value if value is not None else "na").strip().lower()
    return region if region in _AUTHORIZE_HOST else "na"


def build_authorization_url(*, client_id: str, region: str, redirect_uri: str) -> str:
    """Build the LwA consent URL the advertiser opens in a browser.

    Pure: no network, no credentials beyond the (non-secret) client id.

    Raises:
        ValueError: blank ``client_id`` / ``redirect_uri``, or an unknown
            ``region``.
    """
    client = client_id.strip()
    redirect = redirect_uri.strip()
    if not client:
        raise ValueError("client_id is required to build the authorization URL")
    if not redirect:
        raise ValueError("redirect_uri is required to build the authorization URL")
    query = urllib.parse.urlencode(
        {
            "client_id": client,
            "scope": ADVERTISING_SCOPE,
            "response_type": "code",
            "redirect_uri": redirect,
        }
    )
    return f"{authorize_endpoint(region)}?{query}"


def exchange_authorization_code(
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    region: str,
    http_post: HttpPost | None = None,
) -> LwaTokens:
    """Trade a pasted authorization code for access + refresh tokens.

    ``redirect_uri`` must be byte-identical to the one the consent URL
    carried — Amazon rejects the exchange otherwise.

    Raises:
        AmazonAuthCodeError: Amazon rejected the code itself (expired —
            they live 5 minutes — reused, or mismatched redirect_uri).
        AmazonAuthError: missing inputs, any other non-200 response, a
            response without both tokens, or a network failure. The
            message never contains token/secret material.
        ValueError: unknown ``region``.
    """
    url = token_endpoint(region)
    _require_exchange_inputs(
        code=code, client_id=client_id, client_secret=client_secret
    )
    post = http_post or _default_post
    data = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": redirect_uri.strip(),
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
    }
    try:
        resp = post(url, data)
    except Exception as exc:  # noqa: BLE001 — never echo code/secret text
        raise AmazonAuthError(
            f"LwA authorization-code exchange request failed: {type(exc).__name__}"
        ) from None

    status, body = _read_response(resp)
    _raise_for_exchange_status(status, body)

    access = body.get("access_token")
    refresh = body.get("refresh_token")
    if not access:
        raise AmazonAuthError("LwA code-exchange response missing access_token")
    if not refresh:
        raise AmazonAuthError("LwA code-exchange response missing refresh_token")
    return LwaTokens(
        access_token=access,
        refresh_token=refresh,
        expires_in=int(body.get("expires_in") or 3600),
    )


def _require_exchange_inputs(*, code: str, client_id: str, client_secret: str) -> None:
    """Fail before any network call when an input is blank."""
    if not code.strip():
        raise AmazonAuthError("cannot exchange: no authorization code was given")
    if not client_id.strip():
        raise AmazonAuthError("cannot exchange: no client_id in amazon_ads credentials")
    if not client_secret.strip():
        raise AmazonAuthError(
            "cannot exchange: no client_secret in amazon_ads credentials"
        )


def _raise_for_exchange_status(status: int | None, body: dict[str, Any]) -> None:
    """Turn a non-200 exchange response into the right error type.

    Only the machine-readable ``error`` code is quoted —
    ``error_description`` is Amazon-authored free text that can echo back
    the credential material it rejected.
    """
    if status == 400 and body.get("error") in _CODE_REJECTED_ERRORS:
        raise AmazonAuthCodeError(
            "Amazon rejected the authorization code (error="
            f"{body.get('error')!r}). Codes are single-use and expire "
            f"{AUTHORIZATION_CODE_TTL_MINUTES} minutes after consent — "
            "authorize again and paste the new code promptly."
        )
    if status != 200:
        raise AmazonAuthError(
            "LwA authorization-code exchange failed "
            f"(HTTP {status}, error={body.get('error')!r})"
        )


def _read_response(resp: Any) -> tuple[int | None, dict[str, Any]]:
    """``(status, json-body)`` from a transport response, tolerating junk."""
    status = getattr(resp, "status_code", None)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — tolerate non-JSON error bodies
        body = {}
    return status, body if isinstance(body, dict) else {}


def _default_post(url: str, data: dict[str, str]) -> Any:
    import httpx

    return httpx.post(url, data=data, timeout=_TIMEOUT)


def refresh_access_token(
    creds: AmazonAdsCredentials, *, http_post: HttpPost | None = None
) -> LwaTokens:
    """Exchange the stored refresh token for a fresh access token.

    Raises:
        AmazonAuthError: refresh_token/client_secret absent, the token
            is ``invalid_grant`` (re-authorize), a non-200 response, or
            a network failure. The message never contains token/secret
            material.
    """
    if not creds.refresh_token:
        raise AmazonAuthError(
            "cannot refresh: no refresh_token in amazon_ads credentials"
        )
    if not creds.client_secret:
        raise AmazonAuthError(
            "cannot refresh: no client_secret in amazon_ads credentials"
        )

    post = http_post or _default_post
    url = token_endpoint(creds.region)
    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }
    try:
        resp = post(url, data)
    except Exception as exc:  # noqa: BLE001 — never echo token/secret text
        raise AmazonAuthError(
            f"LwA token refresh request failed: {type(exc).__name__}"
        ) from None

    status = getattr(resp, "status_code", None)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — tolerate non-JSON error bodies
        body = {}
    if not isinstance(body, dict):
        body = {}

    if status == 400 and body.get("error") == "invalid_grant":
        raise AmazonAuthError(
            "LwA refresh token is invalid_grant — the advertiser must "
            "re-authorize (see docs/amazon-ads.md)"
        )
    if status != 200:
        raise AmazonAuthError(
            f"LwA token refresh failed (HTTP {status}, error={body.get('error')!r})"
        )

    access = body.get("access_token")
    if not access:
        raise AmazonAuthError("LwA token refresh response missing access_token")
    return LwaTokens(
        access_token=access,
        refresh_token=body.get("refresh_token") or creds.refresh_token,
        expires_in=int(body.get("expires_in") or 3600),
    )


__all__ = [
    "ADVERTISING_SCOPE",
    "AUTHORIZATION_CODE_TTL_MINUTES",
    "DEFAULT_REDIRECT_URI",
    "AmazonAuthCodeError",
    "AmazonAuthError",
    "LwaTokens",
    "authorize_endpoint",
    "build_authorization_url",
    "exchange_authorization_code",
    "normalize_region",
    "refresh_access_token",
    "token_endpoint",
]
