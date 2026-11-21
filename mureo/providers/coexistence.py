"""User-facing coexistence warning for official providers.

When a user installs an official MCP for a platform that has a
``MUREO_DISABLE_<PLATFORM>`` flag, we surface a note that confirms (or
recommends) setting that flag. For a platform whose native tool family the
MCP server registers, the flag disables those tools; for a platform without
one (see :func:`has_native_tools`) the note states only the env entry.

The ``mureo providers add`` CLI auto-disables the matching mureo tool family
via ``mcpServers.mureo.env.MUREO_DISABLE_<PLATFORM>=1``. The warning text
varies depending on whether the user has a ``mcpServers.mureo`` block to
auto-disable:

- ``mureo_block_present=True`` (default — the common case): the message
  confirms the auto-disable already happened, names the env var, and
  describes how to undo it.
- ``mureo_block_present=False``: the message degrades — points the user
  at ``mureo setup claude-code`` so they can install the native MCP, then
  re-run ``mureo providers add`` if they want the auto-disable applied.

Kept as a pure helper so the wording is unit-testable without standing up
the CLI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.providers.catalog import ProviderSpec

_PLATFORM_LABELS: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "ga4": "GA4",
}

_PLATFORM_TO_ENV_VAR: dict[str, str] = {
    "google_ads": "MUREO_DISABLE_GOOGLE_ADS",
    "meta_ads": "MUREO_DISABLE_META_ADS",
    "ga4": "MUREO_DISABLE_GA4",
}

# The platforms whose native tool family the MCP server registers. A platform
# outside this set can still own a ``MUREO_DISABLE_<PLATFORM>`` flag (GA4
# does), which then gates nothing.
_PLATFORMS_WITH_NATIVE_TOOLS: frozenset[str] = frozenset({"google_ads", "meta_ads"})


def has_native_tools(platform: str) -> bool:
    """Return whether the MCP server registers native tools for ``platform``.

    The notes in this module and in :mod:`mureo.cli.providers_cmd` use it to
    avoid describing tools that do not exist.
    """
    return platform in _PLATFORMS_WITH_NATIVE_TOOLS


def _block_present_note(spec_id: str, label: str, env_var: str, *, native: bool) -> str:
    """Return the note for a ``mcpServers.mureo`` block that got ``env_var``."""
    if native:
        return (
            f"Note: mureo's {label} tools have been auto-disabled "
            f'(mcpServers.mureo.env.{env_var}="1"). To re-enable, run '
            f"'mureo providers remove {spec_id}' to remove the official "
            f"server and clear the env entry, or edit "
            f"~/.claude.json manually."
        )
    return (
        f'Note: mcpServers.mureo.env.{env_var}="1" has been set. '
        f"mureo registers no native {label} tools, so no mureo tool changes. "
        f"To undo, run 'mureo providers remove {spec_id}' to remove the "
        f"official server and clear the env entry, or edit "
        f"~/.claude.json manually."
    )


def coexistence_warning(
    spec: ProviderSpec,
    *,
    mureo_block_present: bool = True,
) -> str | None:
    """Return a coexistence warning for ``spec`` or ``None``.

    Returns ``None`` when ``spec.coexists_with_mureo_platform`` is ``None``
    (no overlap with a mureo-native platform).

    When the overlap exists:

    - If ``mureo_block_present=True`` (default), the message confirms the
      CLI set the env var on ``mcpServers.mureo.env`` and explains how to
      undo it. For a platform with native tools it says they were
      auto-disabled; for one without, that no mureo tool changes. The text
      mentions ``"manually"`` so legacy callers grepping for the Phase 1
      "manual remediation" hint still match.
    - If ``mureo_block_present=False``, the message degrades to point the
      user at ``mureo setup claude-code`` (no native block to auto-
      disable yet) and explains how to apply the auto-disable later.

    The function is pure — no I/O. The CLI is responsible for passing the
    correct ``mureo_block_present`` value (typically from the result of
    :func:`mureo.providers.mureo_env.set_mureo_disable_env`).
    """
    platform = spec.coexists_with_mureo_platform
    if platform is None:
        return None

    label = _PLATFORM_LABELS.get(platform, platform)
    env_var = _PLATFORM_TO_ENV_VAR.get(platform, f"MUREO_DISABLE_{platform.upper()}")

    # Claude Code reads user-scope MCP servers (and their env) from
    # ~/.claude.json — NOT ~/.claude/settings.json (that file is hooks/
    # permissions/env only). config_writer writes the auto-disable there, so
    # the remediation message must name the same file.
    if mureo_block_present:
        return _block_present_note(
            spec.id, label, env_var, native=has_native_tools(platform)
        )

    return (
        f"Note: mureo's native MCP is not registered in "
        f"~/.claude.json — nothing to auto-disable for {label}. "
        f"If you later run 'mureo setup claude-code', re-run "
        f"'mureo providers add {spec.id}' to apply the auto-disable."
    )
