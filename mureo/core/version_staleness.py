"""Detect when the running mureo MCP process is older than what is installed.

A long-running MCP server loads mureo into memory **once**, at process start.
If the operator then ``pip install -U mureo`` in the same environment but does
not fully restart the client, the process keeps serving the OLD code — and
there is no visible signal, so neither the operator nor the agent realises the
upgrade had no effect (the exact failure behind the missing ``last_synced_at``
report).

We capture the in-memory ``__version__`` at import (frozen for the process
lifetime) and compare it against the on-disk installed distribution metadata,
which an in-place upgrade refreshes. ``running < installed`` means "you
upgraded but this process is stale — restart". The server surfaces this by
appending a warning to tool output (push, not pull: the agent never has to ask
for a version), so a comparison baseline ("what is installed now") is built in.

This does NOT catch the separate case where the client launches mureo from a
wholly different environment that was never upgraded — that environment's
on-disk metadata is also old, so there is nothing to compare against here. For
that, re-running ``mureo setup`` re-points the launcher at the current
interpreter, and the PyPI update check (``mureo.web.version_check``) nudges
"a newer release exists".
"""

from __future__ import annotations

import logging

import mureo

logger = logging.getLogger(__name__)

# The version of the code actually loaded into THIS process's memory. Captured
# at import time; it does not change when files on disk are upgraded.
_RUNNING_VERSION = mureo.__version__


def installed_version() -> str | None:
    """Return the on-disk installed ``mureo`` distribution version, or ``None``.

    Read fresh from the distribution metadata on every call so an in-session
    ``pip install -U`` is observed. Never raises.
    """
    try:
        from importlib import metadata

        return metadata.version("mureo")
    except Exception:  # pragma: no cover - exotic metadata/layout failures
        logger.debug("could not read installed mureo version", exc_info=True)
        return None


def staleness_warning(
    *,
    running: str | None = None,
    installed: str | None = None,
) -> str | None:
    """Return a restart warning when the running process is older than what is
    installed on disk, else ``None``.

    Only ``running < installed`` is flagged. Equal, or ``running > installed``
    (a dev/editable checkout ahead of the published dist), returns ``None`` so
    a developer is never nagged. Args are injectable for testing; production
    callers pass neither.
    """
    running = running or _RUNNING_VERSION
    installed = installed if installed is not None else installed_version()
    if installed is None or installed == running:
        return None

    try:
        from packaging.version import InvalidVersion, Version

        try:
            if Version(installed) <= Version(running):
                return None
        except InvalidVersion:
            return None
    except Exception:  # pragma: no cover - packaging always present (dependency)
        return None

    return (
        f"⚠️ mureo MCP version mismatch: this server process is "
        f"running {running}, but {installed} is installed on disk. mureo was "
        f"upgraded, but this MCP process is still the OLD one, so every mureo "
        f"tool call here runs the old code. Fully quit and restart Claude "
        f"(quit the app completely — not just close the window — or "
        f"restart the CLI) so the {installed} server loads. Tell the operator "
        f"to do this before trusting further mureo results."
    )
