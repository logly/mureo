"""Credential loading module

Load Google Ads / Meta Ads credentials from ~/.mureo/credentials.json.
Falls back to environment variables if the file does not exist.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials

from mureo.google_ads import GoogleAdsApiClient
from mureo.meta_ads import MetaAdsApiClient

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoogleAdsCredentials:
    """Google Ads credentials (immutable)."""

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None


@dataclass(frozen=True)
class MetaAdsCredentials:
    """Meta Ads credentials (immutable)."""

    access_token: str
    app_id: str | None = None
    app_secret: str | None = None


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
        1. google_ads section in credentials.json
        2. Environment variables (GOOGLE_ADS_*)

    Returns:
        GoogleAdsCredentials or None if required fields are missing.
    """
    data = load_credentials(path)
    google_section = data.get("google_ads")

    if isinstance(google_section, dict):
        developer_token = google_section.get("developer_token", "")
        client_id = google_section.get("client_id", "")
        client_secret = google_section.get("client_secret", "")
        refresh_token = google_section.get("refresh_token", "")
        login_customer_id = google_section.get("login_customer_id")

        if developer_token and client_id and client_secret and refresh_token:
            return GoogleAdsCredentials(
                developer_token=developer_token,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                login_customer_id=login_customer_id,
            )

    # Environment variable fallback
    return _load_google_ads_from_env()


def load_meta_ads_credentials(
    path: Path | None = None,
) -> MetaAdsCredentials | None:
    """Load Meta Ads credentials with environment variable fallback.

    Priority:
        1. meta_ads section in credentials.json
        2. Environment variables (META_ADS_*)

    Returns:
        MetaAdsCredentials or None if required fields are missing.
    """
    data = load_credentials(path)
    meta_section = data.get("meta_ads")

    if isinstance(meta_section, dict):
        access_token = meta_section.get("access_token", "")
        if access_token:
            return MetaAdsCredentials(
                access_token=access_token,
                app_id=meta_section.get("app_id"),
                app_secret=meta_section.get("app_secret"),
            )

    # Environment variable fallback
    return _load_meta_ads_from_env()


# ---------------------------------------------------------------------------
# Client factory helpers
# ---------------------------------------------------------------------------


def create_google_ads_client(
    credentials: GoogleAdsCredentials,
    customer_id: str,
) -> GoogleAdsApiClient:
    """Create a GoogleAdsApiClient from credentials.

    Args:
        credentials: Google Ads credentials
        customer_id: Target Google Ads account (customer_id)

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
    )


def create_meta_ads_client(
    credentials: MetaAdsCredentials,
    account_id: str,
) -> MetaAdsApiClient:
    """Create a MetaAdsApiClient from credentials.

    Args:
        credentials: Meta Ads credentials
        account_id: Ad account ID ("act_XXXX" format)

    Returns:
        MetaAdsApiClient instance
    """
    return MetaAdsApiClient(
        access_token=credentials.access_token,
        ad_account_id=account_id,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_default_path() -> Path:
    """Resolve the default credentials.json path."""
    return Path.home() / ".mureo" / "credentials.json"


def _load_google_ads_from_env() -> GoogleAdsCredentials | None:
    """Load Google Ads credentials from environment variables."""
    developer_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", "")
    login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")

    if not (developer_token and client_id and client_secret and refresh_token):
        return None

    return GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        login_customer_id=login_customer_id,
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
    )
