"""Login-with-Amazon access-token refresh (#113 Phase 2A).

Spec verified from the official Amazon Ads authorization docs
(2026-05-19):

- Regional token hosts (resulting tokens are valid globally):
    NA https://api.amazon.com/auth/o2/token
    EU https://api.amazon.co.uk/auth/o2/token
    FE https://api.amazon.co.jp/auth/o2/token
- POST form: ``grant_type=refresh_token`` + ``refresh_token`` +
  ``client_id`` + ``client_secret``.
- 200 → JSON ``{access_token, token_type, expires_in, refresh_token}``
  (the same refresh token is returned).
- A dead refresh token → HTTP 400 ``{"error":"invalid_grant",…}``;
  this is NOT auto-recoverable — the advertiser must re-authorize.

Tokens / secrets are never placed in exception text or logs.
"""

from __future__ import annotations

import logging
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
_TIMEOUT = 30.0

# (url, form-data) -> response with ``.status_code`` and ``.json()``.
HttpPost = Callable[[str, dict[str, str]], Any]


class AmazonAuthError(RuntimeError):
    """LwA token refresh could not produce a usable access token."""


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
    "AmazonAuthError",
    "LwaTokens",
    "refresh_access_token",
    "token_endpoint",
]
