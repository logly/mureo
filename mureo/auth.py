"""Credential loading module

Load Google Ads / Meta Ads credentials from ~/.mureo/credentials.json.
Falls back to environment variables if the file does not exist.

Platform SDKs are imported lazily, inside the ``create_*_client``
factories (#486). This module sits on the CLI startup path — ``mureo.cli.main``
imports ``mureo.cli.auth_cmd``, which imports this module — so a module-scope
``from google.ads.googleads.client import ...`` made *every* command pay for
the Google Ads SDK, including ``--help``, ``demo init`` and ``byod status``,
which never talk to Google. On Python 3.10 that SDK also prints two
``FutureWarning`` blocks from ``google.api_core`` at import time, so the very
first thing a new user saw after ``pip install mureo`` was four lines of
vendor warning noise. Credential *loading* needs no SDK; only client
*construction* does. Guarded by ``tests/test_cli_import_hygiene.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mureo.core.secret_store import FilesystemSecretStore, SecretStore
from mureo.fsutil import file_lock, lock_path_for

if TYPE_CHECKING:
    from mureo.google_ads import GoogleAdsApiClient
    from mureo.meta_ads import MetaAdsApiClient
    from mureo.search_console import SearchConsoleApiClient
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
    """Meta Ads credentials (immutable).

    ``access_token`` and ``app_secret`` are excluded from ``repr`` so an
    accidental ``repr()`` / log / traceback never prints them. This class now
    also carries hand-entered, never-expiring system-user tokens (#458),
    which raises the stakes on inadvertent disclosure.
    """

    access_token: str = field(repr=False)
    app_id: str | None = None
    app_secret: str | None = field(default=None, repr=False)
    token_obtained_at: str | None = None  # ISO 8601 timestamp
    account_id: str | None = None  # act_XXXX format


# Amazon Ads official-MCP bridge (#113 Phase 1). region picks the
# endpoint; account_mode picks Dynamic vs Fixed account context.
_AMAZON_REGIONS = frozenset({"na", "eu", "fe"})
_AMAZON_ACCOUNT_MODES = frozenset({"dynamic", "fixed"})


@dataclass(frozen=True)
class AmazonAdsCredentials:
    """Amazon Ads credentials for the official-MCP bridge (immutable).

    ``client_id`` + ``access_token`` are the minimum (Dynamic account
    context). ``refresh_token`` / ``client_secret`` enable LwA token
    refresh (Phase 2). The ``profile_id`` / ``account_id`` /
    ``manager_account_id`` triple is only used in Fixed account mode.
    """

    client_id: str
    access_token: str
    region: str = "na"  # na | eu | fe
    account_mode: str = "dynamic"  # dynamic | fixed
    refresh_token: str | None = None
    client_secret: str | None = None
    profile_id: str | None = None  # Amazon-Advertising-API-Scope (Fixed)
    account_id: str | None = None  # Amazon-Ads-AccountID (Fixed)
    manager_account_id: str | None = None  # Amazon-Ads-Manager-AccountID


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


def load_amazon_ads_credentials(
    path: Path | None = None,
) -> AmazonAdsCredentials | None:
    """Load Amazon Ads credentials with environment variable fallback.

    Priority:
        1. ``amazon_ads`` section from the resolved
           :class:`mureo.core.secret_store.SecretStore` (see
           :func:`load_google_ads_credentials` for the full resolution
           rules — same shape).
        2. Environment variables (``AMAZON_ADS_*``, #121).

    ``client_id`` is required, plus token material: EITHER a stored
    ``access_token`` OR the ``refresh_token`` + ``client_secret`` pair
    the bridge mints one from on first use (#121). An unknown ``region``
    / ``account_mode`` falls back to the safe defaults (``na`` /
    ``dynamic``) rather than failing the load.

    Returns:
        AmazonAdsCredentials, or None when neither source supplies a
        usable combination.
    """
    section = _resolve_secret_store(path).load("amazon_ads")
    credentials = _amazon_ads_from_mapping(section)
    if credentials is not None:
        return credentials

    # Environment variable fallback
    return _load_amazon_ads_from_env()


def _amazon_ads_from_mapping(section: dict[str, Any]) -> AmazonAdsCredentials | None:
    """Build credentials from a raw ``amazon_ads`` mapping, or ``None``.

    Shared by the file/secret-store path and the env-var path so the
    "what counts as usable" rule has exactly one definition.
    """
    client_id = section.get("client_id") or ""
    access_token = section.get("access_token") or ""
    refresh_token = section.get("refresh_token") or None
    client_secret = section.get("client_secret") or None
    if not client_id:
        return None
    if not (access_token or (refresh_token and client_secret)):
        return None

    return AmazonAdsCredentials(
        client_id=client_id,
        access_token=access_token,
        region=_amazon_region(section.get("region")),
        account_mode=_amazon_account_mode(section.get("account_mode")),
        refresh_token=refresh_token,
        client_secret=client_secret,
        profile_id=section.get("profile_id") or None,
        account_id=section.get("account_id") or None,
        manager_account_id=section.get("manager_account_id") or None,
    )


def _amazon_region(value: object) -> str:
    """Normalize a region to ``na`` / ``eu`` / ``fe`` (default ``na``)."""
    region = str(value if value is not None else "na").strip().lower()
    return region if region in _AMAZON_REGIONS else "na"


def _amazon_account_mode(value: object) -> str:
    """Normalize an account mode to ``dynamic`` / ``fixed`` (default
    ``dynamic``)."""
    mode = str(value if value is not None else "dynamic").strip().lower()
    return mode if mode in _AMAZON_ACCOUNT_MODES else "dynamic"


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
    # Lazy import (#486): keeps the Google Ads SDK — and the two
    # google.api_core FutureWarnings it prints on Python 3.10 — off the CLI
    # startup path for every command that never builds a Google client.
    from google.oauth2.credentials import Credentials

    from mureo.google_ads import GoogleAdsApiClient

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
    # Lazy import (#486) — see create_google_ads_client.
    from google.oauth2.credentials import Credentials

    from mureo.search_console import SearchConsoleApiClient

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
    # Lazy import (#486) — the Meta SDK is not a warning source, but keeping
    # all three factories symmetrical means no platform SDK loads at CLI
    # startup, and the import-hygiene guard stays a single simple assertion.
    from mureo.meta_ads import MetaAdsApiClient

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

    # POST (not GET) so the client_secret and the token itself travel in the
    # request body, never the URL. The Meta Graph ``/oauth/access_token``
    # endpoint accepts these token-grant parameters via POST as well as GET,
    # and httpx logs ``request.url`` at INFO — a GET would leak the secret and
    # ``fb_exchange_token`` into any INFO-level log. Mirrors the body-based
    # exchange in ``mureo.oauth_authcode``.
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        resp = await client.post(_META_GRAPH_TOKEN_URL, data=params)

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

    Reuses the hardened ``mureo.core.atomic_json`` helpers rather than a local
    read-modify-write: ``load_existing_json`` returns ``{}`` only when the file
    is absent and RAISES ``ConfigWriteError`` on malformed JSON — instead of the
    old ``data = {}`` reset that silently erased every other provider's
    credentials (google_ads etc.) on a slightly-corrupt file. On that raise the
    caller (:func:`refresh_meta_token_if_needed`) skips the save and warns,
    leaving the file intact. ``atomic_write_json`` writes via tmp + fsync +
    ``os.replace`` at ``0o600`` so a crash mid-write is durable and safe.

    The load -> mutate -> write cycle runs under a cross-process ``file_lock``
    so the background 53-day refresh and a concurrent CLI/web
    ``save_credentials`` cannot last-writer-wins away each other's sections
    (e.g. a wizard re-auth dropping the just-refreshed access_token, or this
    refresh dropping a freshly-saved google_ads block).
    """
    # Lazy import mirrors ``auth_setup.save_credentials`` and keeps the
    # module import graph flat.
    from mureo.core.atomic_json import atomic_write_json, load_existing_json

    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock_path_for(path)):
        data = load_existing_json(path)

        meta_section = data.get("meta_ads", {})
        if not isinstance(meta_section, dict):
            meta_section = {}

        meta_section["access_token"] = new_token
        meta_section["token_obtained_at"] = new_obtained_at
        data["meta_ads"] = meta_section

        atomic_write_json(data, path)


def save_amazon_access_token(
    access_token: str,
    refresh_token: str | None = None,
    path: Path | None = None,
) -> None:
    """Atomically persist a refreshed Amazon access token (#113 Phase 2A).

    Mirrors :func:`_save_meta_token` exactly, reusing the same hardened
    ``mureo.core.atomic_json`` helpers instead of a local read-modify-write:
    ``load_existing_json`` returns ``{}`` only when the file is absent and
    RAISES ``ConfigWriteError`` on malformed JSON, so a slightly-corrupt
    credentials.json is left untouched rather than reset to ``{}`` —
    which would silently erase every other provider's section
    (google_ads etc.). ``atomic_write_json`` writes via tmp + fsync +
    ``os.replace`` at ``0o600``, so a crash mid-write is durable and the
    file is never world-readable.

    The load -> mutate -> write cycle runs under the same cross-process
    ``credentials.json.lock`` every other credentials writer holds, so
    an LwA refresh and a concurrent CLI/web ``save_credentials`` cannot
    last-writer-wins away each other's sections.

    ``refresh_token`` is written only when given (LwA returns the same
    one, but write it through for robustness).

    Raises:
        ConfigWriteError: the existing credentials.json is malformed;
            nothing is written.
    """
    # Lazy import mirrors ``_save_meta_token`` and keeps the module import
    # graph flat.
    from mureo.core.atomic_json import atomic_write_json, load_existing_json

    resolved = path if path is not None else _resolve_default_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock_path_for(resolved)):
        data = load_existing_json(resolved)

        section = data.get("amazon_ads", {})
        if not isinstance(section, dict):
            section = {}
        section["access_token"] = access_token
        if refresh_token:
            section["refresh_token"] = refresh_token
        data["amazon_ads"] = section

        atomic_write_json(data, resolved)


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


def _load_amazon_ads_from_env() -> AmazonAdsCredentials | None:
    """Load Amazon Ads credentials from environment variables (#121).

    One env var per ``amazon_ads`` section key, so a container /
    CI deployment can configure the bridge without a credentials file.
    Usability is decided by :func:`_amazon_ads_from_mapping`, which is
    also what the file path uses — the two sources cannot drift.
    """
    section = {
        "client_id": os.environ.get("AMAZON_ADS_CLIENT_ID", ""),
        "access_token": os.environ.get("AMAZON_ADS_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get("AMAZON_ADS_REFRESH_TOKEN", ""),
        "client_secret": os.environ.get("AMAZON_ADS_CLIENT_SECRET", ""),
        "region": os.environ.get("AMAZON_ADS_REGION", ""),
        "account_mode": os.environ.get("AMAZON_ADS_ACCOUNT_MODE", ""),
        "profile_id": os.environ.get("AMAZON_ADS_PROFILE_ID", ""),
        "account_id": os.environ.get("AMAZON_ADS_ACCOUNT_ID", ""),
        "manager_account_id": os.environ.get("AMAZON_ADS_MANAGER_ACCOUNT_ID", ""),
    }
    return _amazon_ads_from_mapping(section)
