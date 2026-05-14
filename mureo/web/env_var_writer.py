"""Write a single credential field via the configure UI's env-var form.

The dashboard exposes a small "Set environment variable" panel for
advanced users who want to inject a single missing token without
re-running the full OAuth flow. Each known env var name maps to a
``(section, field)`` tuple inside ``credentials.json`` and is routed
through the same atomic write as the rest of the credential surface.

Security boundary: the env var name comes from a closed allow-list;
the value never appears in a log line or a response body.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.web._helpers import atomic_write_json, read_json_safe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvVarTarget:
    """Where to write the env var inside ``credentials.json``."""

    section: str
    field: str


# Closed allow-list: env var name → (section, field) in credentials.json.
_ENV_VAR_TO_FIELD: dict[str, EnvVarTarget] = {
    # Google Ads
    "GOOGLE_ADS_DEVELOPER_TOKEN": EnvVarTarget("google_ads", "developer_token"),
    "GOOGLE_ADS_CLIENT_ID": EnvVarTarget("google_ads", "client_id"),
    "GOOGLE_ADS_CLIENT_SECRET": EnvVarTarget("google_ads", "client_secret"),
    "GOOGLE_ADS_REFRESH_TOKEN": EnvVarTarget("google_ads", "refresh_token"),
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": EnvVarTarget("google_ads", "login_customer_id"),
    "GOOGLE_ADS_CUSTOMER_ID": EnvVarTarget("google_ads", "customer_id"),
    # Meta Ads
    "META_ADS_ACCESS_TOKEN": EnvVarTarget("meta_ads", "access_token"),
    "META_ADS_APP_ID": EnvVarTarget("meta_ads", "app_id"),
    "META_ADS_APP_SECRET": EnvVarTarget("meta_ads", "app_secret"),
    "META_ADS_ACCOUNT_ID": EnvVarTarget("meta_ads", "account_id"),
    # GA4
    "GOOGLE_APPLICATION_CREDENTIALS": EnvVarTarget("ga4", "service_account_path"),
    "GOOGLE_PROJECT_ID": EnvVarTarget("ga4", "project_id"),
}


def allowed_env_var_names() -> tuple[str, ...]:
    """Return the closed allow-list for UI rendering / validation."""
    return tuple(sorted(_ENV_VAR_TO_FIELD.keys()))


def is_allowed_env_var(name: str) -> bool:
    """Tight allow-list membership check."""
    return name in _ENV_VAR_TO_FIELD


def _resolve_credentials_path(credentials_path: Path | None) -> Path:
    if credentials_path is not None:
        return credentials_path
    return Path.home() / ".mureo" / "credentials.json"


def write_credential_env_var(
    name: str,
    value: str,
    *,
    credentials_path: Path | None = None,
) -> None:
    """Persist one env var to ``credentials.json``.

    Raises ``ValueError`` if ``name`` is not on the allow-list or
    ``value`` is empty. The value is never logged.
    """
    if not is_allowed_env_var(name):
        raise ValueError(f"env var not allowed: {name!r}")
    if not value:
        raise ValueError("value must be non-empty")

    target = _ENV_VAR_TO_FIELD[name]
    path = _resolve_credentials_path(credentials_path)
    existing = read_json_safe(path)

    section_payload_raw = existing.get(target.section)
    section: dict[str, Any] = (
        dict(section_payload_raw) if isinstance(section_payload_raw, dict) else {}
    )
    section[target.field] = value
    merged: dict[str, Any] = dict(existing)
    merged[target.section] = section

    atomic_write_json(path, merged)
    # Log the field, not the value.
    logger.info("Wrote credential env var %s into %s", name, target.section)
