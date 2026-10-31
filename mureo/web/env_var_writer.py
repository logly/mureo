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
from typing import TYPE_CHECKING, Any

from mureo.core.atomic_json import atomic_write_json, load_existing_json
from mureo.core.ga4_adc import (
    GA4_ADC_GOOGLE_FIELDS,
    GA4_PATH_FIELD,
    GA4_PROJECT_FIELD,
    GA4_SECTION,
    drop_managed_ga4_section,
    is_managed_ga4_section,
    refresh_managed_ga4_adc,
    unlink_managed_ga4_adc,
)
from mureo.fsutil import backup_file

# The allow-list table and the provider-env resolver live with the
# provider install code (``mureo.providers`` sits below ``mureo.web``);
# the names this module has always exported are re-exported from here.
from mureo.providers.credential_env import (
    _ENV_VAR_TO_FIELD,
    _resolve_credentials_path,
    _resolve_field,
)
from mureo.providers.credential_env import EnvVarTarget as EnvVarTarget
from mureo.providers.credential_env import (
    build_provider_env as build_provider_env,
)
from mureo.web._helpers import read_json_safe

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


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

    ``token_never_expires`` (#740) goes for the fourth time, and it is the
    one whose inheritance is silent rather than noisy: it is Graph's verdict
    that the token being replaced was permanent, and
    :func:`mureo.auth._should_refresh` returns ``False`` on it before every
    other clock. Left behind, a hand-entered 60-day token would be treated
    as permanent for its whole life and expire without a single warning.

    Only the token write clears the clock — writing ``META_ADS_ACCOUNT_ID``,
    say, leaves the token untouched, so its stamp, expiry and type still
    describe it.
    """
    if name == "META_ADS_ACCESS_TOKEN":
        section_payload.pop("token_obtained_at", None)
        section_payload.pop("token_expires_at", None)
        section_payload.pop("token_type", None)
        section_payload.pop("token_never_expires", None)


def write_credential_env_var(
    name: str,
    value: str,
    *,
    section: str | None = None,
    credentials_path: Path | None = None,
) -> None:
    """Persist one env var to ``credentials.json``.

    ``section`` disambiguates env names SHARED across sections (ADC's
    ``GOOGLE_APPLICATION_CREDENTIALS``): the value goes to that section's
    field via :func:`_resolve_field`, so the Google Ads wizard can write
    ``google_ads.service_account_path`` rather than the canonical GA4
    binding. Omitted, the canonical 1:1 target is used.

    Raises ``ValueError`` if ``name`` is not on the allow-list, ``value`` is
    empty, or ``name`` does not bind to ``section``; the value is never
    logged. Raises ``ConfigWriteError`` on a malformed existing file: treated
    as ``{}``, this read-modify-write would drop every other provider's
    credentials, so it fails closed (and keeps a ``.bak`` before writing).
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
    # Strict read: {} only when absent, raises on malformed JSON (see above).
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
    logger.info("Wrote credential env var %s into %s", name, target.section)
    _reconcile_ga4_adc(target, merged, path)


def _reconcile_ga4_adc(
    target: EnvVarTarget, merged: dict[str, Any], path: Path
) -> None:
    """Keep the GA4 file derived from the Google authorization in step with
    a single-field edit that already reached the store.

    A Google value edit re-writes the copy the official MCP reads, and so
    does a project id edit of a managed ``ga4`` section, whose value the
    file carries as ``quota_project_id``. Pointing GA4 at a file of the
    operator's own deletes the managed file, so no copy of the Google token
    lingers once nothing refers to it.
    """
    copied_value = (
        target.section == "google_ads" and target.field in GA4_ADC_GOOGLE_FIELDS
    ) or (target.section == GA4_SECTION and target.field == GA4_PROJECT_FIELD)
    if copied_value:
        refresh_managed_ga4_adc(merged, path)
    elif (
        target.section == GA4_SECTION
        and target.field == GA4_PATH_FIELD
        and not is_managed_ga4_section(merged[GA4_SECTION], path)
    ):
        unlink_managed_ga4_adc(path)


# Closed allow-list of removable mureo-native credential sections. Keyed
# to the dashboard's per-platform Remove buttons. Search Console is NOT
# listed: it has no own section — it reuses the google_ads Google OAuth
# (mureo.auth_setup._GOOGLE_SCOPES), so removing it == removing
# google_ads. The dashboard surfaces that relationship rather than a
# misleading standalone SC remove.
_REMOVABLE_SECTIONS: frozenset[str] = frozenset(
    {"google_ads", "meta_ads", "ga4", "creative_studio", "amazon_ads"}
)


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

    The GA4 credential file mureo derives from the Google authorization
    (:mod:`mureo.core.ga4_adc`) goes with either section. It is a copy of
    the ``google_ads`` refresh token, so removing ``google_ads`` also drops
    it and a ``ga4`` section pointing at it; an operator's own ``ga4`` file
    is left alone. The store is written first and the file deleted after,
    so a failed write never leaves the store pointing at a missing file.
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
    derived_ga4 = section in (GA4_SECTION, "google_ads")
    if derived_ga4:
        drop_managed_ga4_section(merged, path)
    backup_file(path)  # keep the prior good file before the overwrite
    atomic_write_json(merged, path)
    if derived_ga4:
        unlink_managed_ga4_adc(path)
    logger.info("Removed mureo credential section %s", section)
    return True
