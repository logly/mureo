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


def get_env_var_target(name: str) -> EnvVarTarget | None:
    """Return the credentials.json ``(section, field)`` for ``name``.

    Returns ``None`` if ``name`` is not in the allow-list. Exposed as a
    read-only accessor so the status collector can resolve env-var
    names back to their stored location without touching the private
    mapping table.
    """
    return _ENV_VAR_TO_FIELD.get(name)


# Reverse of the closed allow-list: credentials.json section → list of
# (env var name, field). Built once at import. Used to materialise the
# ``env`` block an official upstream MCP needs (it reads ONLY env vars,
# never mureo's credentials.json).
_SECTION_TO_ENV_VARS: dict[str, tuple[tuple[str, str], ...]] = {}
for _name, _target in _ENV_VAR_TO_FIELD.items():
    _SECTION_TO_ENV_VARS.setdefault(_target.section, ())
    _SECTION_TO_ENV_VARS[_target.section] += ((_name, _target.field),)
del _name, _target


def build_credentials_env(
    section: str,
    *,
    credentials_path: Path | None = None,
) -> dict[str, str]:
    """Build the ``env`` block an official MCP needs from credentials.json.

    Reverse of :func:`write_credential_env_var`: for every entry in the
    closed allow-list whose target section is ``section``, read the
    field from ``credentials.json`` and emit ``{ENV_NAME: str(value)}``
    for every PRESENT, NON-EMPTY value (ints coerced to ``str``; only
    allow-listed fields are ever surfaced).

    The official upstream MCPs (e.g. ``google-ads-mcp``) read their
    config ONLY from environment variables — they cannot see mureo's
    ``credentials.json`` — so injecting this into the registered
    ``mcpServers[<id>].env`` block is what makes a freshly added official
    provider actually usable.

    Returns ``{}`` when the file or the section is absent (the caller
    then writes a bare block, exactly the pre-fix shape).
    """
    pairs = _SECTION_TO_ENV_VARS.get(section)
    if not pairs:
        return {}
    path = _resolve_credentials_path(credentials_path)
    existing = read_json_safe(path)
    section_data = existing.get(section)
    if not isinstance(section_data, dict):
        return {}

    env: dict[str, str] = {}
    for env_name, field in pairs:
        value = section_data.get(field)
        if value is None or value == "":
            continue
        env[env_name] = str(value)
    return env


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


# Closed allow-list of removable mureo-native credential sections. Keyed
# to the dashboard's per-platform Remove buttons. Search Console is NOT
# listed: it has no own section — it reuses the google_ads Google OAuth
# (mureo.auth_setup._GOOGLE_SCOPES), so removing it == removing
# google_ads. The dashboard surfaces that relationship rather than a
# misleading standalone SC remove.
_REMOVABLE_SECTIONS: frozenset[str] = frozenset({"google_ads", "meta_ads", "ga4"})


def removable_credential_sections() -> tuple[str, ...]:
    """Allow-listed mureo-native credential sections (UI/validation)."""
    return tuple(sorted(_REMOVABLE_SECTIONS))


def remove_credential_section(
    section: str,
    *,
    credentials_path: Path | None = None,
) -> bool:
    """Atomically pop one mureo-native platform section from credentials.json.

    Explicit per-platform user action from the dashboard — distinct
    from bulk clear, which deliberately never touches credentials.json.
    Idempotent: returns ``False`` (no rewrite) when the section is
    absent or the file does not exist; ``True`` when it was removed.
    Raises ``ValueError`` for a section outside the closed allow-list.
    """
    if section not in _REMOVABLE_SECTIONS:
        raise ValueError(f"credential section not allowed: {section!r}")

    path = _resolve_credentials_path(credentials_path)
    existing = read_json_safe(path)
    if section not in existing:
        return False

    merged: dict[str, Any] = dict(existing)
    merged.pop(section, None)
    atomic_write_json(path, merged)
    logger.info("Removed mureo credential section %s", section)
    return True
