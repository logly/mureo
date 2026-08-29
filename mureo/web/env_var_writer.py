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
from typing import TYPE_CHECKING, Any

from mureo.core.atomic_json import atomic_write_json, load_existing_json
from mureo.fsutil import backup_file
from mureo.web._helpers import read_json_safe

if TYPE_CHECKING:
    from collections.abc import Iterable

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
    # Amazon Ads (official-MCP bridge). One name per field the bridge
    # declares in ``account_credential_fields`` / the loader reads in
    # ``mureo.auth._load_amazon_ads_from_env`` — the two must not drift.
    # Amazon renders a first-class credential card, so these names are
    # filtered out of the dashboard's generic env list (same treatment as
    # Creative Studio); they are listed here for the WRITE path and for the
    # status snapshot's ``env_vars`` row.
    "AMAZON_ADS_CLIENT_ID": EnvVarTarget("amazon_ads", "client_id"),
    "AMAZON_ADS_ACCESS_TOKEN": EnvVarTarget("amazon_ads", "access_token"),
    "AMAZON_ADS_REFRESH_TOKEN": EnvVarTarget("amazon_ads", "refresh_token"),
    "AMAZON_ADS_CLIENT_SECRET": EnvVarTarget("amazon_ads", "client_secret"),
    "AMAZON_ADS_REGION": EnvVarTarget("amazon_ads", "region"),
    "AMAZON_ADS_ACCOUNT_MODE": EnvVarTarget("amazon_ads", "account_mode"),
    "AMAZON_ADS_PROFILE_ID": EnvVarTarget("amazon_ads", "profile_id"),
    "AMAZON_ADS_ACCOUNT_ID": EnvVarTarget("amazon_ads", "account_id"),
    "AMAZON_ADS_MANAGER_ACCOUNT_ID": EnvVarTarget("amazon_ads", "manager_account_id"),
    # Creative Studio (image-generation providers)
    "OPENAI_API_KEY": EnvVarTarget("creative_studio", "openai_api_key"),
    "GEMINI_API_KEY": EnvVarTarget("creative_studio", "gemini_api_key"),
    "FAL_KEY": EnvVarTarget("creative_studio", "fal_key"),
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


# Section-aware field overrides for env var names SHARED across more than
# one credentials.json section. The base ``_ENV_VAR_TO_FIELD`` table is 1:1
# (one canonical target per name — the source of truth for the single-write
# and status surfaces), but ADC's ``GOOGLE_APPLICATION_CREDENTIALS`` is read
# by BOTH the ga4 and google_ads official MCPs, which each store a
# service-account path under their own section. This overlay lets the
# provider-env build path resolve the shared name against the SPECIFIC
# provider's section instead of always GA4 (the canonical binding).
_SECTION_FIELD_OVERRIDES: dict[tuple[str, str], str] = {
    ("GOOGLE_APPLICATION_CREDENTIALS", "google_ads"): "service_account_path",
}


def _resolve_field(env_name: str, section: str) -> str | None:
    """Resolve the credentials.json field for ``env_name`` within ``section``.

    Section-aware: a shared env name (see ``_SECTION_FIELD_OVERRIDES``) maps
    to the requested section's field; otherwise the canonical 1:1 binding is
    used, but only when its section matches. Returns ``None`` when
    ``env_name`` does not bind to ``section`` — defensive, so a name is never
    resolved against the wrong platform's section.
    """
    override = _SECTION_FIELD_OVERRIDES.get((env_name, section))
    if override is not None:
        return override
    target = _ENV_VAR_TO_FIELD.get(env_name)
    if target is not None and target.section == section:
        return target.field
    return None


def build_provider_env(
    env_names: Iterable[str],
    section: str,
    *,
    credentials_path: Path | None = None,
) -> dict[str, str]:
    """Build the ``env`` block an official MCP needs from credentials.json.

    Driven by the EXACT env var names a provider declares (its catalog
    ``required_env`` + ``optional_env``) rather than a blanket section dump,
    so it emits ONLY what the upstream reads — e.g. ``google-ads-mcp``
    authenticates via ADC and reads ``GOOGLE_ADS_DEVELOPER_TOKEN`` +
    ``GOOGLE_APPLICATION_CREDENTIALS`` (+ optional
    ``GOOGLE_ADS_LOGIN_CUSTOMER_ID``), never the Client-Library trio.

    For each name in ``env_names`` that binds to ``section`` (section-aware
    resolution — see :func:`_resolve_field`), read the field from
    ``credentials.json`` and emit ``{ENV_NAME: str(value)}`` for every
    PRESENT, NON-EMPTY value (ints coerced to ``str``). Names that do not
    bind to the section, empty/missing values, a missing section and a
    missing file all yield nothing.

    The official upstream MCPs read their config ONLY from environment
    variables — they cannot see mureo's ``credentials.json`` — so injecting
    this into the registered ``mcpServers[<id>].env`` block is what makes a
    freshly added official provider actually usable.
    """
    path = _resolve_credentials_path(credentials_path)
    existing = read_json_safe(path)
    section_data = existing.get(section)
    if not isinstance(section_data, dict):
        return {}

    env: dict[str, str] = {}
    for env_name in env_names:
        field = _resolve_field(env_name, section)
        if field is None:
            continue
        value = section_data.get(field)
        if value is None or value == "":
            continue
        env[env_name] = str(value)
    return env


def _resolve_credentials_path(credentials_path: Path | None) -> Path:
    if credentials_path is not None:
        return credentials_path
    return Path.home() / ".mureo" / "credentials.json"


def _clear_stale_refresh_clock(name: str, section_payload: dict[str, Any]) -> None:
    """Drop the Meta token's clock fields when it is written by hand (#578).

    This writer merges field-wise, which is right for most fields and wrong
    for a credential that another field describes. ``meta_ads`` keeps
    ``token_obtained_at`` to age the token: :func:`mureo.auth._should_refresh`
    compares it against ``_TOKEN_REFRESH_THRESHOLD_DAYS`` and, past that,
    every Meta tool call hands the token to Graph's ``fb_exchange_token``
    endpoint under the stored ``app_id``/``app_secret``.

    A hand-pasted token therefore inherited the *previous* token's stamp —
    already past the threshold, since that is why it was being replaced — so
    the refresh fired on the very next call. Either the exchange succeeded and
    overwrote a never-expiring system-user token with a ~60-day one, or the
    token belonged to a different app, Graph rejected it, and the failure was
    swallowed.

    Clearing the stamp makes ``_should_refresh`` short-circuit on its
    "no stamp" branch, which is what the dedicated paste card achieves by
    dropping ``app_id``/``app_secret`` outright. We keep those: an operator
    updating a token did not ask to lose the app secret, and the missing
    stamp alone is enough to stay off the clock. Any path that legitimately
    mints or refreshes a token re-stamps it.

    ``token_expires_at`` (#726) goes with it, for the same reason and one
    more. It describes the token being replaced, so leaving it would show a
    countdown — or an "expired" badge — for a credential that is gone. And
    since #726 the expiry is the FIRST clock ``_should_refresh`` consults,
    a stale one would re-arm on the expiry branch exactly the exchange this
    function exists to disarm. mureo cannot learn the new expiry here: this
    writer is a pure filesystem merge with no Graph call, which is the same
    reason the obtained-at stamp is cleared rather than set to now.

    ``token_type`` (#726) goes for the third time for the same reason: it is
    Graph's verdict on the token being replaced, and it decides which
    exchange the refresh path uses. Inherited by a hand-pasted token of a
    different kind, it would send a system-user-only parameter on a user
    token exchange — the very confusion the field was added to end.

    Only the token write clears the clock — writing ``META_ADS_ACCOUNT_ID``,
    say, leaves the token untouched, so its stamp, expiry and type still
    describe it.
    """
    if name == "META_ADS_ACCESS_TOKEN":
        section_payload.pop("token_obtained_at", None)
        section_payload.pop("token_expires_at", None)
        section_payload.pop("token_type", None)


def write_credential_env_var(
    name: str,
    value: str,
    *,
    section: str | None = None,
    credentials_path: Path | None = None,
) -> None:
    """Persist one env var to ``credentials.json``.

    ``section`` disambiguates env names SHARED across more than one section
    (today only ADC's ``GOOGLE_APPLICATION_CREDENTIALS``): when given, the
    value is written to that section's field via the section-aware resolver
    (:func:`_resolve_field`), so the Google Ads wizard can persist a
    service-account path into ``google_ads.service_account_path`` rather than
    the canonical GA4 binding. When ``section`` is omitted the canonical 1:1
    target is used (unchanged behaviour).

    Raises ``ValueError`` if ``name`` is not on the allow-list, ``value`` is
    empty, or ``name`` does not bind to ``section``. The value is never
    logged.

    Raises ``ConfigWriteError`` if ``credentials.json`` already exists but is
    malformed JSON: this is a read-modify-write, and silently treating a
    corrupt file as ``{}`` (the old ``read_json_safe`` behaviour) would drop
    every other provider's saved credentials on the next single-field write.
    We fail closed and keep a ``.bak`` of the prior file before overwriting.
    """
    if not is_allowed_env_var(name):
        raise ValueError(f"env var not allowed: {name!r}")
    if not value:
        raise ValueError("value must be non-empty")

    if section is None:
        target = _ENV_VAR_TO_FIELD[name]
    else:
        field = _resolve_field(name, section)
        if field is None:
            raise ValueError(f"env var {name!r} not valid for section {section!r}")
        target = EnvVarTarget(section, field)
    path = _resolve_credentials_path(credentials_path)
    # Strict read: {} only when the file is absent; raises ConfigWriteError on
    # malformed JSON so a corrupt file is never clobbered into a one-section
    # dict that erases other providers.
    existing = load_existing_json(path)

    section_payload_raw = existing.get(target.section)
    section_payload: dict[str, Any] = (
        dict(section_payload_raw) if isinstance(section_payload_raw, dict) else {}
    )
    section_payload[target.field] = value
    _clear_stale_refresh_clock(name, section_payload)
    merged: dict[str, Any] = dict(existing)
    merged[target.section] = section_payload

    backup_file(path)  # keep the prior good file before the overwrite
    atomic_write_json(merged, path)
    # Log the field, not the value.
    logger.info("Wrote credential env var %s into %s", name, target.section)


# Closed allow-list of removable mureo-native credential sections. Keyed
# to the dashboard's per-platform Remove buttons. Search Console is NOT
# listed: it has no own section — it reuses the google_ads Google OAuth
# (mureo.auth_setup._GOOGLE_SCOPES), so removing it == removing
# google_ads. The dashboard surfaces that relationship rather than a
# misleading standalone SC remove.
_REMOVABLE_SECTIONS: frozenset[str] = frozenset(
    {"google_ads", "meta_ads", "ga4", "creative_studio", "amazon_ads"}
)


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
    # Lenient read is safe HERE (unlike the single-field write above): on a
    # malformed file ``read_json_safe`` yields ``{}``, the section reads as
    # "absent", and we no-op (return False) WITHOUT writing — so a corrupt
    # file is never clobbered. The cost is that removal silently reports
    # "nothing to remove" instead of surfacing the corruption; acceptable for
    # an idempotent delete, and out of scope for the #276 data-loss fix.
    existing = read_json_safe(path)
    if section not in existing:
        return False

    merged: dict[str, Any] = dict(existing)
    merged.pop(section, None)
    backup_file(path)  # keep the prior good file before the overwrite
    atomic_write_json(merged, path)
    logger.info("Removed mureo credential section %s", section)
    return True
