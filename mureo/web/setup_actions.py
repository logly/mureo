"""High-level setup actions invoked by the configure-UI POST endpoints.

Each function wraps an existing CLI primitive and returns a structured
JSON-friendly result that the configure UI surfaces directly to the
browser. Failures degrade to ``status="error"`` envelopes rather than
propagating exceptions, so a click in the configure UI never produces
a 500 from a setup-time race.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.providers.catalog import ProviderSpec

from mureo.cli.settings_remove import (
    remove_credential_guard,
    remove_mcp_config,
)
from mureo.cli.setup_cmd import remove_skills
from mureo.web.desktop_mcp import (
    install_desktop_mcp_block,
    install_desktop_server_block,
    remove_desktop_mcp_block,
    remove_desktop_server_block,
    resolve_desktop_config_path,
    set_mureo_disable_env_desktop,
    unset_mureo_disable_env_desktop,
)
from mureo.web.legacy_commands import remove_legacy_commands
from mureo.web.setup_state import (
    PART_HOOK,
    PART_MCP,
    PART_SKILLS,
    clear_part,
    mark_part_installed,
)

logger = logging.getLogger(__name__)

# Host identifiers (mirrors ``host_paths.SUPPORTED_HOSTS``). ``host``
# defaults to ``_HOST_CODE`` on every wrapper so existing callers and
# tests keep the exact pre-change Claude Code behaviour.
_HOST_CODE = "claude-code"
_HOST_DESKTOP = "claude-desktop"

# Official MCP provider IDs that ``clear_all_setup`` will try to remove if
# they are present in ``settings.json``. Listed explicitly (rather than
# inferred from the on-disk keys) so an unrelated user-managed entry is
# never accidentally routed through ``remove_provider``.
_OFFICIAL_PROVIDER_IDS: tuple[str, ...] = (
    "google-ads-official",
    "meta-ads-official",
    "ga4-official",
)


@dataclass(frozen=True)
class ActionResult:
    """JSON-friendly result of one setup action."""

    # "ok"|"noop"|"error"|"manual_required" (+ "auth_required" reserved,
    # not currently produced — hosted Meta now returns manual_required).
    status: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail is not None:
            out["detail"] = self.detail
        return out


def _install_desktop_mcp(home: Path | None) -> ActionResult:
    """Register the mureo MCP block in the Claude Desktop config."""
    try:
        config_path = resolve_desktop_config_path(home)
        # Mirror the proven Claude Code ``_MCP_SERVER_CONFIG`` shape:
        # bare executable + split args. ``sys.executable`` is the
        # absolute interpreter so Desktop spawns the right Python.
        wrote = install_desktop_mcp_block(
            config_path, sys.executable, ["-m", "mureo.mcp"]
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_mureo_mcp (desktop) failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    mark_part_installed(PART_MCP, home=home)
    if not wrote:
        return ActionResult(status="noop", detail="already_configured")
    return ActionResult(status="ok", detail=str(config_path))


def backfill_disable_for_installed_providers(
    host: str, home: Path | None = None
) -> None:
    """Set ``MUREO_DISABLE_<PLATFORM>`` for official providers already
    registered when the mureo MCP is (re)configured.

    Closes the order-dependency hole: ``mureo providers add`` only
    auto-sets the disable env when a ``mcpServers.mureo`` block already
    exists. A user who added the official provider FIRST and configured
    the mureo MCP LATER otherwise ended up with native + official both
    active and no deterministic precedence. This runs after the mureo
    block is written and backfills the disable env for each overlapping
    provider that is actually in effect.

    Scope:
    - pipx/npm providers (google-ads-official, ga4-official):
      file-registry presence in the host's MCP config is the signal —
      a pure, network-free read.
    - hosted_http (Meta) is intentionally NOT backfilled here: detecting
      it would need a network ``claude mcp list`` probe, which must not
      run on the basic-setup path. Meta native↔official is handled by
      the explicit ``mureo providers confirm`` / dashboard native-toggle
      (both gate on the verified connector — no-strand preserved).

    Best-effort and idempotent: never raises (a failure must not break
    basic setup) and never invents a mureo block (the per-host setter
    no-ops when absent). Search Console has no catalog provider and is
    never disabled.
    """
    try:
        from mureo.providers.catalog import get_catalog
        from mureo.providers.config_writer import is_provider_installed
        from mureo.web.host_paths import get_host_paths

        registry = get_host_paths(host, home).mcp_registry_path
        for spec in get_catalog():
            platform = spec.coexists_with_mureo_platform
            if not platform:
                continue
            # hosted_http (Meta) is deliberately NOT backfilled here:
            # detecting it needs a network `claude mcp list` probe, which
            # must not run on the basic-setup path (kept out of every
            # frequently-run/sync surface — same rationale as the
            # separate hosted-status endpoint). Meta native↔official is
            # handled by the explicit `providers confirm` / the dashboard
            # native-toggle, which gate on the verified connector.
            if spec.install_kind == "hosted_http":
                continue
            if is_provider_installed(spec.id, settings_path=registry):
                _disable_native_for(host, platform, home, registry)
    except Exception:  # noqa: BLE001 — backfill must never break setup
        logger.exception("backfill disable-env after mureo MCP install failed")


def _apply_disable_env(
    host: str, platform: str, home: Path | None, registry: Path
) -> tuple[bool, bool]:
    """Single host-aware ``MUREO_DISABLE_<platform>`` setter.

    Returns ``(changed, mureo_block_present)``. Idempotent; never
    invents a ``mcpServers.mureo`` block. The env-var name and the
    host dispatch live ONLY here (the Code path's canonical source of
    truth is ``mureo_env._PLATFORM_TO_ENV_VAR``; the Desktop branch
    derives the same name by uppercase — holds for every catalog
    platform google_ads/meta_ads/ga4, revisit if a future platform
    isn't a simple uppercase mapping). Desktop has no
    ``mureo_block_present`` signal, so it reports ``True`` (callers
    that gate on it only do so for Code, preserving prior behaviour).
    """
    if host == _HOST_DESKTOP:
        env_var = "MUREO_DISABLE_" + platform.upper()
        changed = set_mureo_disable_env_desktop(
            resolve_desktop_config_path(home), env_var
        )
        return changed, True
    from mureo.providers.mureo_env import set_mureo_disable_env

    res = set_mureo_disable_env(platform, settings_path=registry)  # type: ignore[arg-type]
    return res.changed, res.mureo_block_present


def _disable_native_for(
    host: str, platform: str, home: Path | None, registry: Path
) -> None:
    """Best-effort backfill setter (result ignored — see
    ``backfill_disable_for_installed_providers``)."""
    _apply_disable_env(host, platform, home, registry)


_TOGGLE_PLATFORMS: tuple[str, ...] = ("google_ads", "meta_ads", "ga4")


def set_native_preference(
    platform: str,
    prefer_official: bool,
    home: Path | None = None,
    host: str = _HOST_CODE,
) -> ActionResult:
    """User-driven per-platform switch between mureo-native and official.

    ``prefer_official=True`` sets ``MUREO_DISABLE_<PLATFORM>=1`` (native
    steps aside, official is the single source) — allowed ONLY when the
    official path is actually in effect (pipx/npm provider registered,
    or Meta's account-level connector verified Connected), so the user
    can't strand themselves. ``prefer_official=False`` removes the flag
    (restore native) — always allowed (the un-strand path).

    Statuses: ``ok`` (changed), ``noop`` (already in desired state),
    ``error`` with detail ``invalid_platform`` /
    ``provider_not_installed`` / ``connector_not_connected`` /
    ``no_mureo_block``.
    """
    if platform not in _TOGGLE_PLATFORMS:
        return ActionResult(status="error", detail="invalid_platform")

    try:
        from mureo.web.host_paths import get_host_paths

        registry = get_host_paths(host, home).mcp_registry_path
    except Exception as exc:  # noqa: BLE001
        logger.exception("set_native_preference path resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not prefer_official:
        return _restore_native(host, platform, home, registry)

    # prefer_official: guard — the official path must really be usable.
    try:
        from mureo.providers.catalog import get_catalog
        from mureo.providers.config_writer import (
            is_hosted_provider_connected,
            is_provider_installed,
        )

        spec = next(
            (s for s in get_catalog() if s.coexists_with_mureo_platform == platform),
            None,
        )
        if spec is None:
            return ActionResult(status="error", detail="invalid_platform")
        if spec.install_kind == "hosted_http":
            if not is_hosted_provider_connected(spec):
                return ActionResult(status="error", detail="connector_not_connected")
        elif not is_provider_installed(spec.id, settings_path=registry):
            return ActionResult(status="error", detail="provider_not_installed")
    except Exception as exc:  # noqa: BLE001
        logger.exception("set_native_preference guard failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    return _prefer_official(host, platform, home, registry)


def _prefer_official(
    host: str, platform: str, home: Path | None, registry: Path
) -> ActionResult:
    """Set MUREO_DISABLE_<platform> (guard already passed)."""
    try:
        changed, mureo_block_present = _apply_disable_env(
            host, platform, home, registry
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("set_native_preference set failed")
        return ActionResult(status="error", detail=type(exc).__name__)
    if not mureo_block_present:
        return ActionResult(status="error", detail="no_mureo_block")
    return ActionResult(status="ok" if changed else "noop", detail=platform)


def _restore_native(
    host: str, platform: str, home: Path | None, registry: Path
) -> ActionResult:
    """Remove MUREO_DISABLE_<platform> (always allowed)."""
    try:
        if host == _HOST_DESKTOP:
            env_var = "MUREO_DISABLE_" + platform.upper()
            changed = unset_mureo_disable_env_desktop(
                resolve_desktop_config_path(home), env_var
            )
        else:
            from mureo.providers.mureo_env import unset_mureo_disable_env

            changed = unset_mureo_disable_env(
                platform,  # type: ignore[arg-type]
                settings_path=registry,
            ).changed
        return ActionResult(status="ok" if changed else "noop", detail=platform)
    except Exception as exc:  # noqa: BLE001
        logger.exception("set_native_preference unset failed")
        return ActionResult(status="error", detail=type(exc).__name__)


def install_mureo_mcp(home: Path | None = None, host: str = _HOST_CODE) -> ActionResult:
    """Register the mureo MCP block in the host's config.

    ``host="claude-code"`` (default) is byte-for-byte the prior
    behaviour. ``host="claude-desktop"`` writes only the
    ``mcpServers.mureo`` block to ``claude_desktop_config.json``. After
    a successful (re)write the disable env is backfilled for any
    official provider that was registered BEFORE the mureo MCP — closing
    the order-dependency precedence hole.
    """
    if host == _HOST_DESKTOP:
        result = _install_desktop_mcp(home)
    else:
        try:
            from mureo.auth_setup import install_mcp_config

            res = install_mcp_config(scope="global")
        except Exception as exc:  # noqa: BLE001
            logger.exception("install_mureo_mcp failed")
            return ActionResult(status="error", detail=type(exc).__name__)

        mark_part_installed(PART_MCP, home=home)
        result = (
            ActionResult(status="noop", detail="already_configured")
            if res is None
            else ActionResult(status="ok", detail=str(res))
        )

    if result.status != "error":
        backfill_disable_for_installed_providers(host, home)
    return result


def install_auth_hook(home: Path | None = None, host: str = _HOST_CODE) -> ActionResult:
    """Install the credential-guard PreToolUse hook.

    Claude Desktop has no ``hooks.PreToolUse`` surface, so the Desktop
    branch is a graceful no-op that writes nothing and does NOT mark
    ``PART_HOOK`` installed (planner HANDOFF Q2).
    """
    if host == _HOST_DESKTOP:
        return ActionResult(status="noop", detail="unsupported_on_desktop")

    try:
        from mureo.auth_setup import install_credential_guard

        result = install_credential_guard()
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_auth_hook failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    mark_part_installed(PART_HOOK, home=home)
    if result is None:
        return ActionResult(status="noop", detail="already_installed")
    return ActionResult(status="ok", detail=str(result))


def install_workflow_skills(
    home: Path | None = None, host: str = _HOST_CODE
) -> ActionResult:
    """Copy workflow skills into ~/.claude/skills.

    Host-agnostic by design (planner HANDOFF Q3): both Claude Code and
    Claude Desktop share ``~/.claude/skills`` and there is no Desktop
    plugin bundle in the repo. The ``host`` param is accepted for
    signature symmetry only and intentionally does not branch.
    """
    del host  # host-agnostic; accepted for signature symmetry only
    try:
        from mureo.cli.setup_cmd import install_skills

        count, dest = install_skills()
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_workflow_skills failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    mark_part_installed(PART_SKILLS, home=home)
    return ActionResult(status="ok", detail=f"installed {count} skills at {dest}")


def install_basic_setup(
    home: Path | None = None, host: str = _HOST_CODE
) -> dict[str, Any]:
    """Run all three basic-setup parts in order, forwarding ``host``."""
    return {
        PART_MCP: install_mureo_mcp(home=home, host=host).as_dict(),
        PART_HOOK: install_auth_hook(home=home, host=host).as_dict(),
        PART_SKILLS: install_workflow_skills(home=home, host=host).as_dict(),
    }


def _credential_env_for(
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
    be wrong. Returns ``{}`` (caller writes the pre-fix bare block) for
    hosted entries, providers with no overlapping platform, or when no
    matching credentials exist yet.
    """
    if spec.install_kind == "hosted_http":
        return {}
    section = spec.coexists_with_mureo_platform
    if not section:
        return {}
    from mureo.web.env_var_writer import build_credentials_env

    return build_credentials_env(section, credentials_path=credentials_path)


def _install_provider_code(
    provider_id: str, credentials_path: Path | None = None
) -> ActionResult:
    """Claude Code path — register the provider WITH its credential env.

    Behaviour is unchanged for the registration mechanics; the only
    addition is the ``extra_env`` (resolved from credentials.json) so the
    official MCP can actually authenticate on first connect instead of
    registering into an unusable, credential-less state.
    """
    try:
        from mureo.providers.catalog import get_provider
        from mureo.providers.config_writer import (
            add_provider_to_claude_settings,
        )
        from mureo.providers.installer import run_install
        from mureo.providers.mureo_env import (
            add_provider_and_disable_in_mureo,
        )

        spec = get_provider(provider_id)
    except KeyError:
        return ActionResult(status="error", detail="unknown_provider")
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider import/resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if spec.install_kind == "hosted_http":
        # Claude Code: Meta's hosted MCP CANNOT be OAuth-authenticated as
        # a user-scope server — it has no RFC 7591 Dynamic Client
        # Registration, so `/mcp` → Authenticate fails with
        # "redirect_uris are not registered for this client". Registering
        # the {"type":"http","url":...} block would only create an
        # unauthenticatable server. The only Claude Code path that works
        # today is a Claude.ai account connector (Anthropic brokers the
        # OAuth there). So mureo does NOT register it locally; it returns
        # ``manual_required`` and the UI surfaces the claude.ai connector
        # steps (connector.code.* — identical result shape to the
        # Desktop hosted_http path).
        #
        # No native auto-disable: nothing was registered and the
        # connector is not yet verified. mureo-native Meta steps aside
        # only once the connector is confirmed Connected, via
        # `providers confirm` / the dashboard native-toggle (no-strand).
        return ActionResult(status="manual_required", detail=spec.id)

    try:
        result = run_install(spec, dry_run=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider subprocess failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if result.returncode != 0:
        return ActionResult(
            status="error",
            detail=f"install_returncode_{result.returncode}",
        )

    extra_env = _credential_env_for(spec, credentials_path)
    try:
        if spec.coexists_with_mureo_platform is None:
            add_provider_to_claude_settings(spec, extra_env=extra_env)
        else:
            add_provider_and_disable_in_mureo(spec, extra_env=extra_env)
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider settings write failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    return ActionResult(status="ok", detail=spec.id)


def _desktop_block_for(spec: ProviderSpec) -> Mapping[str, Any]:
    """Return the stdio block Claude Desktop accepts for a local-install spec.

    ``claude_desktop_config.json`` only accepts stdio servers
    (``command``/``args``). pipx/npm catalog blocks are already that
    shape and are returned verbatim, exactly preserving the pre-change
    Desktop behaviour for local-install providers.

    ``hosted_http`` providers never reach this function: a remote MCP
    cannot be wired into Claude Desktop via the config file at all.
    Claude Desktop's config rejects the Claude Code native
    ``{"type":"http","url":...}`` shape, and the ``mcp-remote`` stdio
    bridge fails against servers without OAuth Dynamic Client
    Registration (e.g. Meta's hosted Ads MCP returns
    ``InvalidClientMetadataError: Dynamic registration is not
    available``). The only working path is the user adding it manually
    via Claude Desktop → Settings → Connectors → Add custom connector,
    so ``_install_provider_desktop`` short-circuits hosted_http with a
    ``manual_required`` result before ever calling this.
    """
    return spec.mcp_server_config


def _install_provider_desktop(
    provider_id: str,
    home: Path | None,
    credentials_path: Path | None = None,
) -> ActionResult:
    """Desktop path — install one official provider.

    pipx/npm: the local ``run_install`` subprocess STILL runs (the
    install is host-agnostic); on non-zero returncode NO config is
    written; otherwise the catalog ``mcp_server_config`` block is
    written to ``claude_desktop_config.json``.

    hosted_http: a remote MCP cannot be wired into Claude Desktop via
    the config file (Desktop rejects the native http shape; mcp-remote
    fails on Meta's no-DCR OAuth), so the Meta block is NOT written and
    the result is ``manual_required`` (the UI shows Connectors steps).
    mureo-native Meta is intentionally NOT auto-disabled: the official
    path only works once the user has manually added the connector, and
    disabling native before that strands the user with zero Meta
    capability (observed regression — see the Code/CLI hosted_http
    handling for the same rationale). Consistent across Code, CLI and
    Desktop.

    ``credentials.json`` is never touched.
    """
    try:
        from mureo.providers.catalog import get_provider
        from mureo.providers.installer import run_install

        spec = get_provider(provider_id)
    except KeyError:
        return ActionResult(status="error", detail="unknown_provider")
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider (desktop) import/resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if spec.install_kind == "hosted_http":
        # A remote MCP cannot be wired into Claude Desktop via the
        # config file: Desktop rejects the native {"type":"http",...}
        # shape, and the mcp-remote bridge fails on servers without
        # OAuth Dynamic Client Registration (Meta's hosted Ads MCP:
        # "InvalidClientMetadataError: Dynamic registration is not
        # available"). The only working path is the user adding it via
        # Claude's Connectors, so the Meta MCP block is NOT written here.
        #
        # We also do NOT disable mureo-native Meta: the official path is
        # not usable until the user completes the manual Connectors
        # setup, and auto-disabling native before that leaves the user
        # with no Meta capability at all (the reported regression).
        # Native stays until the user confirms the connector works —
        # identical to the Code/CLI hosted_http behaviour.
        return ActionResult(status="manual_required", detail=spec.id)

    if spec.install_argv:
        try:
            result = run_install(spec, dry_run=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("install_provider (desktop) subprocess failed")
            return ActionResult(status="error", detail=type(exc).__name__)
        if result.returncode != 0:
            return ActionResult(
                status="error",
                detail=f"install_returncode_{result.returncode}",
            )

    block: dict[str, Any] = dict(_desktop_block_for(spec))
    extra_env = _credential_env_for(spec, credentials_path)
    if extra_env:
        block = {**block, "env": {**block.get("env", {}), **extra_env}}
    try:
        config_path = resolve_desktop_config_path(home)
        wrote = install_desktop_server_block(config_path, spec.id, block)
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider (desktop) config write failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not wrote:
        return ActionResult(status="noop", detail="already_configured")
    return ActionResult(status="ok", detail=spec.id)


def install_provider(
    provider_id: str,
    home: Path | None = None,
    host: str = _HOST_CODE,
    *,
    credentials_path: Path | None = None,
) -> ActionResult:
    """Install one official MCP provider by catalog id.

    ``host="claude-code"`` (default) registers into ``~/.claude.json``;
    ``host="claude-desktop"`` writes the provider block into
    ``claude_desktop_config.json``. In BOTH cases the credential env the
    upstream MCP needs is resolved from ``credentials_path`` (defaults to
    ``~/.mureo/credentials.json``) and injected into the registered
    block — without it the official server registers but cannot
    authenticate.
    """
    if host == _HOST_DESKTOP:
        return _install_provider_desktop(provider_id, home, credentials_path)
    return _install_provider_code(provider_id, credentials_path)


def _remove_provider_desktop(provider_id: str, home: Path | None) -> ActionResult:
    """Desktop path — pop only ``mcpServers[provider_id]``.

    Idempotent (``noop not_registered``) when the entry is absent or the
    config file is missing. ``credentials.json`` is never touched.
    """
    try:
        from mureo.providers.catalog import get_provider

        spec = get_provider(provider_id)
    except KeyError:
        return ActionResult(status="error", detail="unknown_provider")
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_provider (desktop) import/resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if spec.install_kind == "hosted_http":
        # The hosted MCP block was never written on Desktop (manual
        # Connectors). The meaningful inverse of install here is
        # re-enabling mureo's own tool family for the platform by
        # unsetting MUREO_DISABLE_<PLATFORM> on mcpServers.mureo.env.
        platform = spec.coexists_with_mureo_platform
        if not platform:
            return ActionResult(status="noop", detail="not_registered")
        env_var = "MUREO_DISABLE_" + platform.upper()
        try:
            config_path = resolve_desktop_config_path(home)
            changed = unset_mureo_disable_env_desktop(config_path, env_var)
        except Exception as exc:  # noqa: BLE001
            logger.exception("remove_provider (desktop) unset-env failed")
            return ActionResult(status="error", detail=type(exc).__name__)
        if not changed:
            return ActionResult(status="noop", detail="not_registered")
        return ActionResult(status="ok", detail=provider_id)

    try:
        config_path = resolve_desktop_config_path(home)
        removed = remove_desktop_server_block(config_path, provider_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_provider (desktop) failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not removed:
        return ActionResult(status="noop", detail="not_registered")
    return ActionResult(status="ok", detail=provider_id)


def remove_provider(
    provider_id: str, home: Path | None = None, host: str = _HOST_CODE
) -> ActionResult:
    """Unregister a provider from the host.

    ``host="claude-code"`` (default) unregisters it from user scope via
    the ``claude`` CLI (``~/.claude.json``), NOT ``settings.json``.
    ``host="claude-desktop"`` pops only ``mcpServers[provider_id]`` from
    ``claude_desktop_config.json``.
    """
    if host == _HOST_DESKTOP:
        return _remove_provider_desktop(provider_id, home)

    try:
        from mureo.providers.catalog import get_provider
        from mureo.providers.config_writer import (
            remove_provider_from_claude_settings,
        )

        get_provider(provider_id)
    except KeyError:
        return ActionResult(status="error", detail="unknown_provider")
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_provider import/resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    try:
        result = remove_provider_from_claude_settings(provider_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_provider failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not result.changed:
        return ActionResult(status="noop", detail="not_registered")
    return ActionResult(status="ok", detail=provider_id)


def confirm_hosted_provider(
    provider_id: str, home: Path | None = None, host: str = _HOST_CODE
) -> ActionResult:
    """Disable mureo-native tools ONCE the official hosted connector works.

    A ``hosted_http`` provider (Meta) can only be wired via Claude's
    account-level Connectors, authorised by a one-time browser OAuth that
    mureo cannot perform. Native is never auto-disabled before that (it
    would strand the user). This is the explicit, safe follow-up.

    Claude Code: verify the connector is Connected via
    ``is_hosted_provider_connected`` (parses ``claude mcp list``), and
    only then set ``MUREO_DISABLE_<PLATFORM>=1`` on ``mcpServers.mureo``.
    Statuses: ``ok`` (just disabled), ``noop`` (already disabled),
    ``not_connected`` (finish the browser setup first), ``manual``
    (Desktop — mureo can't auto-detect, the user verifies there),
    ``error`` (``unknown_provider`` / ``not_hosted`` / ``no_mureo_block``).
    """
    try:
        from mureo.providers.catalog import get_provider

        spec = get_provider(provider_id)
    except KeyError:
        return ActionResult(status="error", detail="unknown_provider")
    except Exception as exc:  # noqa: BLE001
        logger.exception("confirm_hosted_provider import/resolve failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if spec.install_kind != "hosted_http":
        return ActionResult(status="error", detail="not_hosted")

    platform = spec.coexists_with_mureo_platform
    if platform is None:
        return ActionResult(status="noop", detail="nothing_to_switch")

    if host == _HOST_DESKTOP:
        # No reliable programmatic signal for the account connector on
        # Desktop (no `claude mcp list`); the user verifies in Claude
        # Desktop. Never auto-disable native here (no stranding).
        return ActionResult(status="manual", detail=spec.id)

    try:
        from mureo.providers.config_writer import is_hosted_provider_connected
        from mureo.providers.mureo_env import set_mureo_disable_env

        if not is_hosted_provider_connected(spec):
            return ActionResult(status="not_connected", detail=spec.id)
        env_result = set_mureo_disable_env(platform)
    except Exception as exc:  # noqa: BLE001
        logger.exception("confirm_hosted_provider failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if env_result.changed:
        return ActionResult(status="ok", detail=spec.id)
    if env_result.mureo_block_present:
        return ActionResult(status="noop", detail="already_disabled")
    return ActionResult(status="error", detail="no_mureo_block")


def hosted_provider_status(host: str = _HOST_CODE) -> dict[str, bool]:
    """Connected-state for every ``hosted_http`` catalog provider.

    mureo never registers a hosted provider in the config file (it can't
    — Meta has no OAuth DCR), so the file-parse status always reports it
    absent. This probes ``claude mcp list`` (timeout-bounded, never
    raises) so the dashboard can show ``✓`` once the user has finished
    the account-level Connector browser setup. Returns ``{id: bool}``.

    Deliberately a SEPARATE endpoint, NOT folded into ``collect_status``:
    the subprocess/network probe must not slow every ``/api/status`` poll
    nor leak a real ``claude`` subprocess into the broad status test
    surface. ``host`` is accepted for symmetry; detection is via the
    Claude Code ``claude`` CLI (absent on Desktop ⇒ all ``False``, which
    correctly drives the "use Connectors" UI there).
    """
    del host  # detection is CLI-based; absent ⇒ False (correct for Desktop)
    try:
        from mureo.providers.catalog import get_catalog
        from mureo.providers.config_writer import is_hosted_provider_connected

        return {
            spec.id: is_hosted_provider_connected(spec)
            for spec in get_catalog()
            if spec.install_kind == "hosted_http"
        }
    except Exception:  # noqa: BLE001 — status probe must never raise
        logger.exception("hosted_provider_status failed")
        return {}


# ---------------------------------------------------------------------------
# Remove wrappers — symmetric counterparts of the install_* wrappers above.
# ---------------------------------------------------------------------------


def _remove_desktop_mcp(home: Path | None) -> ActionResult:
    """Pop the mureo MCP block from the Claude Desktop config."""
    try:
        config_path = resolve_desktop_config_path(home)
        removed = remove_desktop_mcp_block(config_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_mureo_mcp (desktop) failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not removed:
        return ActionResult(status="noop", detail="not_installed")
    clear_part(PART_MCP, home=home)
    return ActionResult(status="ok")


def remove_mureo_mcp(home: Path | None = None, host: str = _HOST_CODE) -> ActionResult:
    """Pop the mureo MCP block from the host's config.

    ``host="claude-code"`` (default) is unchanged;
    ``host="claude-desktop"`` removes only ``mcpServers.mureo`` from
    ``claude_desktop_config.json``.
    """
    if host == _HOST_DESKTOP:
        return _remove_desktop_mcp(home)

    try:
        result = remove_mcp_config()
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_mureo_mcp failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not result.changed:
        return ActionResult(status="noop", detail="not_installed")
    clear_part(PART_MCP, home=home)
    return ActionResult(status="ok")


def remove_auth_hook(home: Path | None = None, host: str = _HOST_CODE) -> ActionResult:
    """Drop the credential-guard PreToolUse hook from the host config.

    Mirror of ``install_auth_hook``: the Desktop branch is a no-op
    (Desktop has no hook surface) that touches no file and does NOT
    clear ``PART_HOOK`` state (planner HANDOFF Q2).
    """
    if host == _HOST_DESKTOP:
        return ActionResult(status="noop", detail="unsupported_on_desktop")

    try:
        result = remove_credential_guard()
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_auth_hook failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    if not result.changed:
        return ActionResult(status="noop", detail="not_installed")
    clear_part(PART_HOOK, home=home)
    return ActionResult(status="ok")


def remove_workflow_skills(
    home: Path | None = None, host: str = _HOST_CODE
) -> ActionResult:
    """Delete bundle-listed workflow skills from ``~/.claude/skills``.

    Host-agnostic (planner HANDOFF Q3): skills live in the shared
    ``~/.claude/skills`` for both hosts. ``host`` is accepted for
    signature symmetry only and intentionally does not branch.
    """
    del host  # host-agnostic; accepted for signature symmetry only
    try:
        count, dest = remove_skills()
    except Exception as exc:  # noqa: BLE001
        logger.exception("remove_workflow_skills failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    # Clear the state flag on both success AND noop so the dashboard
    # tri-state stays consistent (planner HANDOFF L137 — flag must reflect
    # actual on-disk state).
    clear_part(PART_SKILLS, home=home)
    if count == 0:
        return ActionResult(status="noop", detail=f"no skills found at {dest}")
    return ActionResult(status="ok", detail=f"removed {count} skills from {dest}")


def _installed_official_providers(
    home: Path | None, host: str = _HOST_CODE
) -> list[str]:
    """Return the subset of ``_OFFICIAL_PROVIDER_IDS`` actually registered.

    ``clear_all_setup`` needs to know which providers were installed
    without depending on ``setup_state.json`` flags (those only track
    basic-setup parts).

    For ``host="claude-code"`` registration lives in ``~/.claude.json``
    (managed by ``claude mcp``) — NOT ``~/.claude/settings.json`` — so we
    probe via ``config_writer.is_provider_installed`` (``claude mcp get``
    with a ``~/.claude.json`` fallback), the SAME source the
    install/remove path writes to. Reading settings.json here is exactly
    what left bulk-clear unable to find (and therefore unable to remove)
    an official provider. For ``host="claude-desktop"`` entries live in
    ``claude_desktop_config.json`` so that file is read directly. A
    missing/malformed file degrades gracefully to "none".
    """
    if host != _HOST_DESKTOP:
        from mureo.providers.config_writer import is_provider_installed

        return [pid for pid in _OFFICIAL_PROVIDER_IDS if is_provider_installed(pid)]

    settings_path = resolve_desktop_config_path(home)
    if not settings_path.exists():
        return []
    try:
        text = settings_path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, json.JSONDecodeError):
        logger.warning("could not enumerate installed providers from %s", settings_path)
        return []
    mcp_servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    if not isinstance(mcp_servers, dict):
        return []
    return [pid for pid in _OFFICIAL_PROVIDER_IDS if pid in mcp_servers]


def _safe_step(fn: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run ``fn`` and capture its outcome as an ``ActionResult.as_dict()``.

    Wraps the call so an uncaught exception is reported in the envelope
    without aborting the surrounding ``clear_all_setup`` chain.
    """
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("clear_all_setup step %s failed", getattr(fn, "__name__", fn))
        return ActionResult(status="error", detail=type(exc).__name__).as_dict()
    if isinstance(result, ActionResult):
        return result.as_dict()
    return {"status": "ok", "detail": str(result)}


def clear_all_setup(home: Path | None = None, host: str = _HOST_CODE) -> dict[str, Any]:
    """Run every uninstall step regardless of prior failures.

    Envelope keys: ``mureo_mcp``, ``auth_hook``, ``skills``,
    ``legacy_commands``, ``providers``. ``host`` is forwarded to the
    mcp + hook removers so Desktop uninstall is symmetric. Per CTO
    decision #3, this function MUST NOT touch
    ``~/.mureo/credentials.json`` (credential removal is a separate
    user decision).
    """
    envelope: dict[str, Any] = {}
    envelope["mureo_mcp"] = _safe_step(remove_mureo_mcp, home=home, host=host)
    envelope["auth_hook"] = _safe_step(remove_auth_hook, home=home, host=host)
    envelope["skills"] = _safe_step(remove_workflow_skills, home=home)

    commands_dir = (home or Path.home()) / ".claude" / "commands"
    try:
        legacy_removed = remove_legacy_commands(commands_dir)
    except Exception as exc:  # noqa: BLE001
        logger.exception("clear_all_setup legacy_commands step failed")
        envelope["legacy_commands"] = {
            "status": "error",
            "detail": type(exc).__name__,
        }
    else:
        envelope["legacy_commands"] = legacy_removed

    providers_envelope: dict[str, Any] = {}
    for provider_id in _installed_official_providers(home, host):
        providers_envelope[provider_id] = _safe_step(
            remove_provider, provider_id, home=home, host=host
        )
    envelope["providers"] = providers_envelope

    return envelope
