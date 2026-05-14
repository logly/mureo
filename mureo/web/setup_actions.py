"""High-level setup actions invoked by the configure-UI POST endpoints.

Each function wraps an existing CLI primitive and returns a structured
JSON-friendly result that the configure UI surfaces directly to the
browser. Failures degrade to ``status="error"`` envelopes rather than
propagating exceptions, so a click in the configure UI never produces
a 500 from a setup-time race.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.web.setup_state import (
    PART_HOOK,
    PART_MCP,
    PART_SKILLS,
    mark_part_installed,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


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


def install_mureo_mcp(home: Path | None = None) -> ActionResult:
    """Register the mureo MCP block in Claude settings."""
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


def install_auth_hook(home: Path | None = None) -> ActionResult:
    """Install the credential-guard PreToolUse hook."""
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


def install_workflow_skills(home: Path | None = None) -> ActionResult:
    """Copy workflow skills into ~/.claude/skills."""
    try:
        from mureo.cli.setup_cmd import install_skills

        count, dest = install_skills()
    except Exception as exc:  # noqa: BLE001
        logger.exception("install_workflow_skills failed")
        return ActionResult(status="error", detail=type(exc).__name__)

    mark_part_installed(PART_SKILLS, home=home)
    return ActionResult(status="ok", detail=f"installed {count} skills at {dest}")


def install_basic_setup(home: Path | None = None) -> dict[str, Any]:
    """Run all three basic-setup parts in order."""
    return {
        PART_MCP: install_mureo_mcp(home=home).as_dict(),
        PART_HOOK: install_auth_hook(home=home).as_dict(),
        PART_SKILLS: install_workflow_skills(home=home).as_dict(),
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
