"""Credential loading module

Load Google Ads / Meta Ads credentials from ~/.mureo/credentials.json.
Falls back to environment variables if the file does not exist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from google.oauth2.credentials import Credentials

from mureo.core.secret_store import FilesystemSecretStore, SecretStore
from mureo.google_ads import GoogleAdsApiClient
from mureo.meta_ads import MetaAdsApiClient
from mureo.search_console import SearchConsoleApiClient

if TYPE_CHECKING:
    from mureo.throttle import Throttler

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoogleAdsCredentials:
    """Google Ads credentials (immutable).

    For accounts reached via an MCC (manager account), `login_customer_id`
    holds the MCC ID (used as the login header for API calls) and
    `customer_id` holds the actual target account ID. For directly
    accessible accounts, both typically hold the same value.
    """

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None
    customer_id: str | None = None


@dataclass(frozen=True)
class MetaAdsCredentials:
    """Meta Ads credentials (immutable)."""

    access_token: str
    app_id: str | None = None
    app_secret: str | None = None
    token_obtained_at: str | None = None  # ISO 8601 timestamp
    account_id: str | None = None  # act_XXXX format


# ---------------------------------------------------------------------------
# Loading functions
# ---------------------------------------------------------------------------


def load_credentials(path: Path | None = None) -> dict[str, Any]:
    """Load credentials from ~/.mureo/credentials.json.

    Args:
        path: Path to credentials.json. Uses default path if None.

    Returns:
        Credential dict. Returns empty dict if file is missing or invalid JSON.
    """
    resolved = path if path is not None else _resolve_default_path()

    if not resolved.exists():
        logger.debug("credentials.json not found: %s", resolved)
        return {}

    try:
        text = resolved.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read credentials.json: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("credentials.json root is not an object")
        return {}

    return data


def load_google_ads_credentials(
    path: Path | None = None,
) -> GoogleAdsCredentials | None:
    """Load Google Ads credentials with environment variable fallback.

    Priority:
        1. ``google_ads`` section from the resolved
           :class:`mureo.core.secret_store.SecretStore`. When ``path``
           is supplied, the store is a one-shot
           :class:`FilesystemSecretStore` reading that file directly
           (preserves the long-standing test contract). When ``path``
           is ``None``, the store is the process-wide one returned by
           :func:`mureo.core.runtime_context.get_runtime_context` —
           ``FilesystemSecretStore(~/.mureo/credentials.json)`` by
           default, or whatever an installed alternate backend
           registers via the ``mureo.runtime_context_factory``
           entry-point group.
        2. Environment variables (``GOOGLE_ADS_*``).

    Returns:
        GoogleAdsCredentials or None if required fields are missing.
    """
    google_section = _resolve_secret_store(path).load("google_ads")

    if isinstance(google_section, dict) and google_section:
        developer_token = google_section.get("developer_token", "")
        client_id = google_section.get("client_id", "")
        client_secret = google_section.get("client_secret", "")
        refresh_token = google_section.get("refresh_token", "")
        login_customer_id = google_section.get("login_customer_id")
        # Fall back to login_customer_id when customer_id is not present
        # (preserves behavior for credentials.json files created by
        # earlier mureo versions).
        customer_id = google_section.get("customer_id") or login_customer_id

        if developer_token and client_id and client_secret and refresh_token:
            return GoogleAdsCredentials(
                developer_token=developer_token,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                login_customer_id=login_customer_id,
                customer_id=customer_id,
            )

    # Environment variable fallback
    return _load_google_ads_from_env()


def load_meta_ads_credentials(
    path: Path | None = None,
) -> MetaAdsCredentials | None:
    """Load Meta Ads credentials with environment variable fallback.

    Priority:
        1. ``meta_ads`` section from the resolved
           :class:`mureo.core.secret_store.SecretStore` (see
           :func:`load_google_ads_credentials` for the full resolution
           rules — same shape).
        2. Environment variables (``META_ADS_*``).

    Returns:
        MetaAdsCredentials or None if required fields are missing.
    """
    meta_section = _resolve_secret_store(path).load("meta_ads")

    if isinstance(meta_section, dict) and meta_section:
        access_token = meta_section.get("access_token", "")
        if access_token:
            return MetaAdsCredentials(
                access_token=access_token,
                app_id=meta_section.get("app_id"),
                app_secret=meta_section.get("app_secret"),
                token_obtained_at=meta_section.get("token_obtained_at"),
                account_id=meta_section.get("account_id"),
            )

    # Environment variable fallback
    return _load_meta_ads_from_env()


# ---------------------------------------------------------------------------
# Client factory helpers
# ---------------------------------------------------------------------------


def create_google_ads_client(
    credentials: GoogleAdsCredentials,
    customer_id: str,
    throttler: Throttler | None = None,
) -> GoogleAdsApiClient:
    """Create a GoogleAdsApiClient from credentials.

    Args:
        credentials: Google Ads credentials
        customer_id: Target Google Ads account (customer_id)
        throttler: Optional rate-limit throttler

    Returns:
        GoogleAdsApiClient instance
    """
    oauth_credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri=_TOKEN_URI,
    )

    return GoogleAdsApiClient(
        credentials=oauth_credentials,
        customer_id=customer_id,
        developer_token=credentials.developer_token,
        login_customer_id=credentials.login_customer_id,
        throttler=throttler,
    )


def create_search_console_client(
    credentials: GoogleAdsCredentials,
    throttler: Throttler | None = None,
) -> SearchConsoleApiClient:
    """Create a SearchConsoleApiClient from Google Ads credentials.

    Search Console uses the same OAuth2 credentials (client_id,
    client_secret, refresh_token) as Google Ads.

    Args:
        credentials: Google Ads credentials (reused for OAuth2)
        throttler: Optional rate-limit throttler

    Returns:
        SearchConsoleApiClient instance
    """
    oauth_credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri=_TOKEN_URI,
        scopes=[
            "https://www.googleapis.com/auth/webmasters",
        ],
    )

    return SearchConsoleApiClient(
        credentials=oauth_credentials,
        throttler=throttler,
    )


def create_meta_ads_client(
    credentials: MetaAdsCredentials,
    account_id: str,
    throttler: Throttler | None = None,
) -> MetaAdsApiClient:
    """Create a MetaAdsApiClient from credentials.

    Args:
        credentials: Meta Ads credentials
        account_id: Ad account ID ("act_XXXX" format)
        throttler: Optional rate-limit throttler

    Returns:
        MetaAdsApiClient instance
    """
    return MetaAdsApiClient(
        access_token=credentials.access_token,
        ad_account_id=account_id,
        throttler=throttler,
    )


# ---------------------------------------------------------------------------
# Meta Ads token refresh
# ---------------------------------------------------------------------------

_TOKEN_REFRESH_THRESHOLD_DAYS = 53
_META_GRAPH_TOKEN_URL = "https://graph.facebook.com/v21.0/oauth/access_token"
_refresh_lock = asyncio.Lock()


async def refresh_meta_token_if_needed(
    credentials: MetaAdsCredentials,
    path: Path | None = None,
) -> MetaAdsCredentials:
    """Check if Meta Ads token needs refresh and refresh if needed.

    Refreshes when:
    - app_id and app_secret are available
    - token_obtained_at is known
    - Token will expire within 7 days (53+ days old)

    Returns original credentials if refresh is not needed or not possible.
    """
    if not _should_refresh(credentials):
        return credentials

    async with _refresh_lock:
        # Re-check after acquiring lock (another coroutine may have refreshed)
        if not _should_refresh(credentials):
            return credentials

        try:
            new_token, new_obtained_at = await _call_refresh_api(credentials)
        except Exception:
            logger.warning("Failed to refresh Meta Ads token", exc_info=True)
            return credentials

        refreshed = replace(
            credentials,
            access_token=new_token,
            token_obtained_at=new_obtained_at,
        )

        resolved = path if path is not None else _resolve_default_path()
        try:
            _save_meta_token(resolved, new_token, new_obtained_at)
        except Exception:
            # The refreshed token works for THIS process (returned below) but is
            # not on disk, so every future process re-refreshes from the aging
            # stored token. If the underlying cause (read-only mount, bad perms,
            # corrupt credentials.json) persists past the token's ~60-day life,
            # Meta calls will start failing with an expired-token error that
            # looks unrelated. Surface an actionable warning rather than a bare
            # "failed to save".
            logger.warning(
                "Meta Ads token was refreshed but could NOT be persisted to %s "
                "— the new token is used for this session only. Check the file's "
                "permissions/JSON validity and re-run `mureo auth setup` if Meta "
                "tools later report an expired token.",
                resolved,
                exc_info=True,
            )

        return refreshed


def _should_refresh(credentials: MetaAdsCredentials) -> bool:
    """Return True if the token should be refreshed."""
    if not credentials.app_id or not credentials.app_secret:
        return False
    if not credentials.token_obtained_at:
        return False

    try:
        obtained = datetime.fromisoformat(credentials.token_obtained_at)
    except (ValueError, TypeError):
        logger.warning(
            "Invalid token_obtained_at format: %s",
            credentials.token_obtained_at,
        )
        return False

    age = datetime.now(tz=timezone.utc) - obtained.astimezone(timezone.utc)
    return age >= timedelta(days=_TOKEN_REFRESH_THRESHOLD_DAYS)


async def _call_refresh_api(
    credentials: MetaAdsCredentials,
) -> tuple[str, str]:
    """Call the Meta Graph API to refresh the token.

    Returns:
        Tuple of (new_access_token, new_obtained_at_iso).

    Raises:
        httpx.HTTPError: On network errors.
        ValueError: On unexpected API response.
    """
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": credentials.app_id,
        "client_secret": credentials.app_secret,
        "fb_exchange_token": credentials.access_token,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.get(_META_GRAPH_TOKEN_URL, params=params)

    if resp.status_code != 200:
        raise ValueError(
            f"Meta token refresh failed with status {resp.status_code}: " f"{resp.text}"
        )

    data = resp.json()
    new_token = data.get("access_token")
    if not new_token:
        raise ValueError("No access_token in refresh response")

    new_obtained_at = datetime.now(tz=timezone.utc).isoformat()
    return new_token, new_obtained_at


def _save_meta_token(
    path: Path,
    new_token: str,
    new_obtained_at: str,
) -> None:
    """Atomically update the meta_ads token in credentials.json.

    Reuses the hardened ``config_writer`` helpers rather than a local
    read-modify-write: ``_load_existing`` returns ``{}`` only when the file is
    absent and RAISES ``ConfigWriteError`` on malformed JSON — instead of the
    old ``data = {}`` reset that silently erased every other provider's
    credentials (google_ads etc.) on a slightly-corrupt file. On that raise the
    caller (:func:`refresh_meta_token_if_needed`) skips the save and warns,
    leaving the file intact. ``_atomic_write_json`` writes via tmp + fsync +
    ``os.replace`` at ``0o600`` so a crash mid-write is durable and safe.
    """
    # Lazy import mirrors ``auth_setup.save_credentials`` and avoids any
    # import-time coupling to the providers package.
    from mureo.providers.config_writer import _atomic_write_json, _load_existing

    data = _load_existing(path)

    meta_section = data.get("meta_ads", {})
    if not isinstance(meta_section, dict):
        meta_section = {}

    meta_section["access_token"] = new_token
    meta_section["token_obtained_at"] = new_obtained_at
    data["meta_ads"] = meta_section

    _atomic_write_json(data, path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_default_path() -> Path:
    """Resolve the default credentials.json path."""
    return Path.home() / ".mureo" / "credentials.json"


def _resolve_secret_store(path: Path | None) -> SecretStore:
    """Pick the SecretStore that ``load_*_credentials`` should consult.

    - ``path`` given → one-shot :class:`FilesystemSecretStore` bound to
      that path. Bypasses the process-wide RuntimeContext so tests that
      pass an explicit per-test file are isolated from any installed
      alternate backend.
    - ``path`` is ``None`` → the SecretStore from
      :func:`mureo.core.runtime_context.get_runtime_context` (the
      default file-backed store today, or whatever a registered
      ``mureo.runtime_context_factory`` entry-point returns).

    Imported lazily to keep ``mureo.auth`` decoupled from
    ``mureo.core.runtime_context``: if the resolver later wants to
    reference an ``mureo.auth`` type, a top-level import here would
    create a circular dependency.
    """
    if path is not None:
        return FilesystemSecretStore(path=path)
    from mureo.core.runtime_context import get_runtime_context

    return get_runtime_context().secret_store


def _load_google_ads_from_env() -> GoogleAdsCredentials | None:
    """Load Google Ads credentials from environment variables."""
    developer_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", "")
    login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID") or login_customer_id

    if not (developer_token and client_id and client_secret and refresh_token):
        return None

    return GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        login_customer_id=login_customer_id,
        customer_id=customer_id,
    )


def _load_meta_ads_from_env() -> MetaAdsCredentials | None:
    """Load Meta Ads credentials from environment variables."""
    access_token = os.environ.get("META_ADS_ACCESS_TOKEN", "")

    if not access_token:
        return None

    return MetaAdsCredentials(
        access_token=access_token,
        app_id=os.environ.get("META_ADS_APP_ID"),
        app_secret=os.environ.get("META_ADS_APP_SECRET"),
        token_obtained_at=os.environ.get("META_ADS_TOKEN_OBTAINED_AT"),
    )
