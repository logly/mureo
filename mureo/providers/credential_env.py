"""Credential env for an official MCP provider, and the native-disable gate.

Both install paths for a local-install official provider — the configure
UI's install route and ``mureo providers add`` — resolve the provider's env
from the credential store, inject it into the ``mcpServers[<id>]`` block, and
switch the overlapping mureo-native platform off only when that env lets the
official server authenticate. One resolver and one gate keep the two paths
from drifting apart (#945).

The env-var allow-list (env name -> ``credentials.json`` section and field)
lives here too, because the resolver reads it. This module depends on
``mureo.core`` and the other ``mureo.providers`` modules only;
``mureo.web.env_var_writer`` imports the table back for the dashboard's
single-field write path, so the dependency points web -> providers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mureo.core.secret_store import FilesystemSecretStore, default_credentials_path

# Read through the modules (not bound to names here) so monkeypatched
# settings writers are honoured at call time.
from mureo.providers import config_writer, mureo_env

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from mureo.providers.catalog import ProviderSpec


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
    # The field name is historical (the value used to be a service-account
    # key only); it holds the path of ANY ADC credential file — service-account
    # key, ``authorized_user`` file, or ``external_account`` configuration
    # (#937). Renaming it would churn existing credentials.json files.
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


# Section-aware field overrides for env var names SHARED across more than
# one credentials.json section. The base ``_ENV_VAR_TO_FIELD`` table is 1:1
# (one canonical target per name — the source of truth for the single-write
# and status surfaces), but ADC's ``GOOGLE_APPLICATION_CREDENTIALS`` is read
# by BOTH the ga4 and google_ads official MCPs, which each store a
# service-account path under their own section. This overlay lets the
# provider-env build path resolve the shared name against the SPECIFIC
# provider's section instead of always GA4 (the canonical binding).
# The overlay also carries an upstream-documented ALIAS of a canonical
# name: ``GOOGLE_CLOUD_PROJECT`` is what ``analytics-mcp``'s README
# recommends, so ``ga4-official`` emits it from the same stored
# ``ga4.project_id`` as ``GOOGLE_PROJECT_ID`` (#937). It is deliberately
# NOT in ``_ENV_VAR_TO_FIELD``: it is read-only output for the provider
# env block, never a dashboard row nor a write target.
_SECTION_FIELD_OVERRIDES: dict[tuple[str, str], str] = {
    ("GOOGLE_APPLICATION_CREDENTIALS", "google_ads"): "service_account_path",
    ("GOOGLE_CLOUD_PROJECT", "ga4"): "project_id",
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
    authenticates via ADC (+ optional legacy
    ``GOOGLE_ADS_DEVELOPER_TOKEN``, + optional
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
    # The credential store's own reader: a missing, unreadable or malformed
    # file and a non-object section all read as empty.
    section_data = FilesystemSecretStore(path).load(section)
    if not section_data:
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
    return default_credentials_path()


def credential_env_for(
    spec: ProviderSpec, credentials_path: Path | None
) -> dict[str, str]:
    """Resolve the credential env an official MCP needs from credentials.json.

    The upstream local-install MCPs (e.g. ``google-ads-mcp``) read their
    config ONLY from environment variables — never mureo's
    ``credentials.json`` — so a freshly registered provider is unusable
    unless this env is injected into its ``mcpServers[<id>]`` block.

    ``hosted_http`` providers are excluded: Meta's hosted Ads MCP
    authenticates via interactive browser OAuth on first connect (no
    env vars to pre-populate), and injecting stale meta_ads creds would
    be wrong. Returns ``{}`` (caller writes the bare catalog block) for
    hosted entries, providers with no overlapping platform, or when no
    matching credentials exist yet.

    The env is built from the provider's declared ``required_env`` +
    ``optional_env`` (not a blanket section dump), so only the names the
    upstream actually reads are injected — e.g. Google Ads' ADC env
    (``GOOGLE_APPLICATION_CREDENTIALS`` + optional MCC login id and legacy
    dev-token), never the Client-Library trio the upstream ignores (#102).
    """
    if spec.install_kind == "hosted_http":
        return {}
    section = spec.coexists_with_mureo_platform
    if not section:
        return {}
    return build_provider_env(
        (*spec.required_env, *spec.optional_env),
        section,
        credentials_path=credentials_path,
    )


# Required env names whose value is a path the upstream MCP opens at
# launch. A value that does not point at a readable regular file cannot
# authenticate, so it must not count as credentialed (no-strand, #102 /
# #761).
_FILE_PATH_ENV: frozenset[str] = frozenset({"GOOGLE_APPLICATION_CREDENTIALS"})


def _readable_file(value: str) -> bool:
    """True when ``value``, exactly as stored, is an absolute regular file.

    The value is injected verbatim into the upstream's env block and opened
    there by a process that does no shell expansion, so the check must use
    the same bytes: no ``expanduser`` (``~/sa.json`` would pass here and
    fail there) and no relative paths (resolved against the MCP host's cwd,
    not ours).
    """
    try:
        path = Path(value)
        return path.is_absolute() and path.is_file() and os.access(path, os.R_OK)
    except (OSError, ValueError):
        return False


def unresolved_required_env(spec: ProviderSpec, env: Mapping[str, str]) -> list[str]:
    """The ``required_env`` names that ``env`` does not resolve, in catalog order.

    A name is unresolved when it is absent from ``env`` or, for a
    path-valued name (``_FILE_PATH_ENV``), when its value is not a readable
    file: the upstream opens that file at launch, so a dangling path cannot
    authenticate either. The native-disable gate (:func:`is_credentialed`)
    and the operator-facing notes read this one list, so what blocks the
    disable is exactly what the note names.
    """
    return [
        name
        for name in spec.required_env
        if name not in env or (name in _FILE_PATH_ENV and not _readable_file(env[name]))
    ]


def is_credentialed(spec: ProviderSpec, env: Mapping[str, str]) -> bool:
    """True when EVERY ``required_env`` name resolved to a stored value.

    This is the #102 native-disable gate: mureo steps its native tools aside
    only when the official server can actually authenticate. ``env`` is
    built from the provider's ``required_env`` + ``optional_env``, so a
    required name is "credentialed" exactly when it is present in ``env``
    (see :func:`unresolved_required_env`, the one rule both share).
    A client-library-only Google Ads user (no
    ``GOOGLE_APPLICATION_CREDENTIALS``) is therefore correctly NOT
    credentialed — a ``bool(env)`` gate would treat them as credentialed
    and strand them (native off, official unable to auth).

    The ``bool(spec.required_env)`` guard keeps a provider with NO declared
    required env from being vacuously "credentialed" (``all(())`` is True):
    such a provider could never authenticate from env alone, so native must
    stay on even though nothing is unresolved. Unreachable today (the only
    empty-``required_env`` entry is the hosted Meta provider, which
    short-circuits before the gate) but it preserves the no-strand
    invariant if a future provider changes that.

    Presence alone is not enough for a path-valued name (``_FILE_PATH_ENV``,
    e.g. ``GOOGLE_APPLICATION_CREDENTIALS``): the upstream opens that file at
    launch, so a stored path that is missing, unreadable or a directory means
    an official server that cannot authenticate. Such a value therefore does
    NOT credential the provider — the install reports that credentials are
    still needed and mureo-native stays on instead of being switched off
    behind it (#761).
    """
    return bool(spec.required_env) and not unresolved_required_env(spec, env)


def register_with_credential_gate(
    spec: ProviderSpec, extra_env: Mapping[str, str]
) -> bool:
    """Register ``spec`` in the Claude Code MCP registry with ``extra_env``.

    Returns True when the provider is credentialed (every ``required_env``
    resolved) and the overlapping native platform was disabled in the same
    atomic write. Otherwise the provider is registered with whatever env
    resolved, any ``MUREO_DISABLE_<platform>`` a prior install left is
    cleared, and False is returned: a provider that cannot authenticate
    must not switch the native tools off.
    """
    # The upstream MCP reads its config ONLY from env vars (Google Ads via
    # ADC: GOOGLE_APPLICATION_CREDENTIALS; dev-token optional), so a
    # partially-credentialed registration cannot authenticate; disabling
    # native then would strand the user with zero working tools for that
    # platform (official dead AND native off, #102).
    platform = spec.coexists_with_mureo_platform
    credentialed = platform is not None and is_credentialed(spec, extra_env)
    if credentialed:
        mureo_env.add_provider_and_disable_in_mureo(spec, extra_env=extra_env)
        return True
    config_writer.add_provider_to_claude_settings(spec, extra_env=extra_env)
    if platform is not None:
        # Clear any MUREO_DISABLE_<platform> a prior credentialed install
        # left behind, so re-registering without full creds never leaves
        # native off AND official unauthenticated.
        mureo_env.unset_mureo_disable_env(platform)
    return False
