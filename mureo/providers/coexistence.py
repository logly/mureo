"""User-facing coexistence warning for official providers.

When a user installs an official MCP for a platform that mureo also serves
natively, we surface a warning that confirms (or recommends) disabling
mureo's own server for that platform.

Since the disable-mureo extension (2026-05-12, Founder Q1/Q2), the
``mureo providers add`` CLI auto-disables the matching mureo tool family
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
      auto-disable already happened (the CLI flipped the env var on
      ``mcpServers.mureo.env``) and explains how to re-enable. The text
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

    if mureo_block_present:
        return (
            f"Note: mureo's {label} tools have been auto-disabled "
            f'(mcpServers.mureo.env.{env_var}="1"). To re-enable, run '
            f"'mureo providers remove {spec.id}' to remove the official "
            f"server and clear the env entry, or edit "
            f"~/.claude/settings.json manually."
        )

    return (
        f"Note: mureo's native MCP is not registered in "
        f"~/.claude/settings.json — nothing to auto-disable for {label}. "
        f"If you later run 'mureo setup claude-code', re-run "
        f"'mureo providers add {spec.id}' to apply the auto-disable."
    )
