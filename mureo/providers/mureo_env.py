"""Per-platform ``MUREO_DISABLE_*`` env-var writers for ``mcpServers.mureo``.

When an official provider for a platform mureo also serves natively (Google
Ads, Meta Ads, GA4) is installed via ``mureo providers add``, this module is
responsible for setting a corresponding ``MUREO_DISABLE_<PLATFORM>=1`` entry
on ``mcpServers.mureo.env`` so the mureo MCP server can auto-disable its own
tool family for that platform at startup.

Three public helpers:

- :func:`set_mureo_disable_env` — set the env var on an existing mureo block.
- :func:`unset_mureo_disable_env` — pop the env var.
- :func:`add_provider_and_disable_in_mureo` — combined single-atomic-write
  helper used by ``mureo providers add`` so the new provider block AND the
  auto-disable env var land in one ``os.replace`` call.

The catalog-controlled ``_PLATFORM_TO_ENV_VAR`` mapping is module-private and
deliberately omits ``"search_console"`` — Search Console has no official MCP
equivalent and mureo remains canonical for it. The ``CoexistsPlatform``
``Literal`` from :mod:`mureo.providers.catalog` enforces this at type-check
time; the lookup ``KeyError`` defends against dynamic callers that bypass
mypy strict.

Atomic-write machinery is *not* duplicated here — both helpers reuse the
private ``_load_existing`` and ``_atomic_write_json`` functions from
:mod:`mureo.providers.config_writer` so a single contract governs all writes
to ``~/.claude/settings.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.providers.config_writer import (
    AddResult,
    ConfigWriteError,
    _atomic_write_json,
    _build_desired_config,
    _default_settings_path,
    _load_existing,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from mureo.providers.catalog import CoexistsPlatform, ProviderSpec


# Module-private mapping. Search Console is intentionally NOT listed — there
# is no official MCP for it and mureo remains canonical. The Literal type on
# ``CoexistsPlatform`` forecloses adding a key here at type-check time; the
# runtime lookup ``KeyError`` is the secondary guard for dynamic callers.
_PLATFORM_TO_ENV_VAR: dict[str, str] = {
    "google_ads": "MUREO_DISABLE_GOOGLE_ADS",
    "meta_ads": "MUREO_DISABLE_META_ADS",
    "ga4": "MUREO_DISABLE_GA4",
}


@dataclass(frozen=True)
class SetEnvResult:
    """Outcome of a :func:`set_mureo_disable_env` call.

    Attributes:
        changed: ``True`` if the file was rewritten; ``False`` for a no-op
            (key already at the desired value, or no mureo block to update).
        mureo_block_present: ``True`` when ``mcpServers.mureo`` exists in
            the settings file, ``False`` otherwise. The CLI surfaces this
            so the coexistence message can degrade gracefully.
    """

    changed: bool
    mureo_block_present: bool


@dataclass(frozen=True)
class UnsetEnvResult:
    """Outcome of an :func:`unset_mureo_disable_env` call.

    Attributes:
        changed: ``True`` if the file was rewritten; ``False`` when the
            key was already absent or the mureo block does not exist.
    """

    changed: bool


def _env_var_for(platform: CoexistsPlatform) -> str:
    """Resolve the env var name for ``platform`` or raise ``KeyError``.

    The ``Literal`` on ``CoexistsPlatform`` keeps mypy strict honest at
    compile time; this runtime check defends against dynamic callers
    (e.g. CLI plumbing that loses the type) passing ``"search_console"``
    or anything else not in the mapping.
    """
    return _PLATFORM_TO_ENV_VAR[platform]


def set_mureo_disable_env(
    platform: CoexistsPlatform,
    *,
    settings_path: Path | None = None,
) -> SetEnvResult:
    """Set ``mcpServers.mureo.env[MUREO_DISABLE_<PLATFORM>]`` to ``"1"``.

    Behavior:

    - If ``settings.json`` does not exist OR has no ``mcpServers.mureo``
      entry: no-op. Returns ``SetEnvResult(changed=False,
      mureo_block_present=False)``. Never invents a mureo block — that is
      ``mureo setup …``'s job.
    - If ``mcpServers.mureo`` exists but has no ``env`` field: a fresh
      ``env`` dict is created with the single new key.
    - If ``mcpServers.mureo.env`` already contains the exact desired
      ``{<key>: "1"}`` pair: no-op. Returns ``changed=False``.
    - Otherwise: merges the key and atomically rewrites the file via
      :func:`mureo.providers.config_writer._atomic_write_json` (single
      ``os.replace`` call).

    Raises:
        KeyError: ``platform`` is not in ``_PLATFORM_TO_ENV_VAR`` (e.g.
            ``"search_console"``).
        ConfigWriteError: existing settings file is malformed JSON.
    """
    env_var = _env_var_for(platform)
    target = settings_path or _default_settings_path()

    if not target.exists():
        return SetEnvResult(changed=False, mureo_block_present=False)

    existing = _load_existing(target)
    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        return SetEnvResult(changed=False, mureo_block_present=False)

    mureo_block = mcp_servers.get("mureo")
    if not isinstance(mureo_block, dict):
        return SetEnvResult(changed=False, mureo_block_present=False)

    env_block = mureo_block.get("env")
    if isinstance(env_block, dict):
        if env_block.get(env_var) == "1":
            return SetEnvResult(changed=False, mureo_block_present=True)
        env_block[env_var] = "1"
    else:
        mureo_block["env"] = {env_var: "1"}

    mcp_servers["mureo"] = mureo_block
    existing["mcpServers"] = mcp_servers
    _atomic_write_json(existing, target)
    return SetEnvResult(changed=True, mureo_block_present=True)


def unset_mureo_disable_env(
    platform: CoexistsPlatform,
    *,
    settings_path: Path | None = None,
) -> UnsetEnvResult:
    """Pop ``mcpServers.mureo.env[MUREO_DISABLE_<PLATFORM>]``.

    Behavior:

    - If ``settings.json`` does not exist, or ``mcpServers.mureo`` is
      absent, or ``env`` is absent / the key is absent: no-op. Returns
      ``UnsetEnvResult(changed=False)`` and the file is NOT rewritten.
    - If the popped key was the only entry in ``env``: leaves
      ``env = {}`` (empty dict). Does NOT delete the ``env`` key itself
      — diff surface stays minimal and user-added env entries we never
      knew about are not accidentally removed.

    Raises:
        KeyError: ``platform`` is not in ``_PLATFORM_TO_ENV_VAR``.
        ConfigWriteError: existing settings file is malformed JSON.
    """
    env_var = _env_var_for(platform)
    target = settings_path or _default_settings_path()

    if not target.exists():
        return UnsetEnvResult(changed=False)

    existing = _load_existing(target)
    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        return UnsetEnvResult(changed=False)

    mureo_block = mcp_servers.get("mureo")
    if not isinstance(mureo_block, dict):
        return UnsetEnvResult(changed=False)

    env_block = mureo_block.get("env")
    if not isinstance(env_block, dict) or env_var not in env_block:
        return UnsetEnvResult(changed=False)

    del env_block[env_var]
    mureo_block["env"] = env_block
    mcp_servers["mureo"] = mureo_block
    existing["mcpServers"] = mcp_servers
    _atomic_write_json(existing, target)
    return UnsetEnvResult(changed=True)


def add_provider_and_disable_in_mureo(
    spec: ProviderSpec,
    *,
    settings_path: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> AddResult:
    """Combined single-atomic-write helper.

    Performs BOTH operations inside a single read/merge/write cycle so a
    crash between them cannot leave the file half-updated:

    1. Sets ``mcpServers[spec.id]`` to the provider block, with
       ``extra_env`` (credential env resolved from credentials.json)
       merged into its ``env`` so the official MCP is usable on first
       connect — without it the upstream server, which reads ONLY env
       vars, starts with zero credentials.
    2. If ``spec.coexists_with_mureo_platform`` is non-None AND a
       ``mcpServers.mureo`` block exists, also sets
       ``mcpServers.mureo.env[MUREO_DISABLE_<PLATFORM>] = "1"``.

    When ``mcpServers.mureo`` is absent the env-var step is silently
    skipped (the provider registration still happens). The CLI emits a
    user-facing note in that case via the coexistence helper.

    Returns:
        ``AddResult(changed=True)`` if anything was written; ``AddResult(
        changed=False)`` if both the provider entry AND the disable env
        var were already at their desired state (full idempotency).

    Raises:
        ConfigWriteError: existing settings file is malformed JSON or has
            a non-object ``mcpServers`` value.
    """
    target = settings_path or _default_settings_path()
    existing = _load_existing(target)

    mcp_servers_raw = existing.get("mcpServers")
    if mcp_servers_raw is None:
        mcp_servers: dict[str, Any] = {}
    elif isinstance(mcp_servers_raw, dict):
        mcp_servers = mcp_servers_raw
    else:
        raise ConfigWriteError(
            f"existing settings at {target} has a non-object 'mcpServers' "
            f"value (got {type(mcp_servers_raw).__name__}); refusing to "
            f"overwrite to protect user data."
        )

    # Shared builder: JSON round-trip + stdio ``type`` + ``extra_env``
    # merge, so the comparison key matches what would actually be written
    # to disk (mirrors `add_provider_to_claude_settings`).
    desired_config = _build_desired_config(spec, extra_env)
    provider_changed = mcp_servers.get(spec.id) != desired_config
    if provider_changed:
        mcp_servers[spec.id] = desired_config

    env_changed = _merge_disable_env(mcp_servers, spec)

    if not provider_changed and not env_changed:
        return AddResult(changed=False)

    existing["mcpServers"] = mcp_servers
    _atomic_write_json(existing, target)
    return AddResult(changed=True)


def _merge_disable_env(
    mcp_servers: dict[str, Any],
    spec: ProviderSpec,
) -> bool:
    """In-place merge the MUREO_DISABLE_* env var on the mureo block.

    Returns ``True`` if a mutation was applied to ``mcp_servers``,
    ``False`` otherwise (no overlap, no mureo block, or key already set).
    """
    platform = spec.coexists_with_mureo_platform
    if platform is None:
        return False

    mureo_block = mcp_servers.get("mureo")
    if not isinstance(mureo_block, dict):
        return False

    env_var = _env_var_for(platform)
    env_block = mureo_block.get("env")
    if isinstance(env_block, dict):
        if env_block.get(env_var) == "1":
            return False
        env_block[env_var] = "1"
    else:
        mureo_block["env"] = {env_var: "1"}
    mcp_servers["mureo"] = mureo_block
    return True
