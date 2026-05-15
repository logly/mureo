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
from typing import Any

from mureo.cli.settings_remove import (
    remove_credential_guard,
    remove_mcp_config,
)
from mureo.cli.setup_cmd import remove_skills
from mureo.web.desktop_mcp import (
    install_desktop_mcp_block,
    remove_desktop_mcp_block,
    resolve_desktop_config_path,
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

    status: str  # "ok" | "noop" | "error"
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


def install_mureo_mcp(home: Path | None = None, host: str = _HOST_CODE) -> ActionResult:
    """Register the mureo MCP block in the host's config.

    ``host="claude-code"`` (default) is byte-for-byte the prior
    behaviour. ``host="claude-desktop"`` writes only the
    ``mcpServers.mureo`` block to ``claude_desktop_config.json``.
    """
    if host == _HOST_DESKTOP:
        return _install_desktop_mcp(home)

    try:
        from mureo.auth_setup import install_mcp_config

        result = install_mcp_config(scope="global")
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_mureo_mcp failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    mark_part_installed(PART_MCP, home=home)
    if result is None:
        return ActionResult(status="noop", detail="already_configured")
    return ActionResult(status="ok", detail=str(result))


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


def install_provider(provider_id: str) -> ActionResult:
    """Install one official MCP provider by catalog id."""
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

    try:
        if spec.coexists_with_mureo_platform is None:
            add_provider_to_claude_settings(spec)
        else:
            add_provider_and_disable_in_mureo(spec)
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_provider settings write failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    return ActionResult(status="ok", detail=spec.id)


def remove_provider(provider_id: str) -> ActionResult:
    """Drop a provider entry from ~/.claude/settings.json."""
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


def _installed_official_providers(home: Path | None) -> list[str]:
    """Return the subset of ``_OFFICIAL_PROVIDER_IDS`` present in settings.

    Reads ``settings.json`` directly because ``clear_all_setup`` needs to
    know which providers were installed without depending on the
    ``setup_state.json`` flags (those only track the basic-setup parts).
    A missing or malformed settings file is treated as "no installed
    providers" — the bulk action degrades gracefully.
    """
    base = home or Path.home()
    settings_path = base / ".claude" / "settings.json"
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
    for provider_id in _installed_official_providers(home):
        providers_envelope[provider_id] = _safe_step(remove_provider, provider_id)
    envelope["providers"] = providers_envelope

    return envelope
