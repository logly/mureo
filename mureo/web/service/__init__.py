"""OS auto-start backends for ``mureo service`` (#241 Phase 2 — Part C).

The headless configure daemon (``mureo configure --serve``) is registered
as a *user-level* auto-start agent — never a system/root daemon, so there
is no privilege escalation:

* macOS  → a LaunchAgent plist + ``launchctl`` (:mod:`.launchd`);
* Linux  → a ``systemd --user`` unit + ``systemctl --user`` (:mod:`.systemd`);
* Windows → an on-logon Scheduled Task + ``schtasks`` (:mod:`.windows`).

Each backend exposes the same small contract — ``install()`` /
``uninstall()`` / ``status()`` — returning the structured results defined
here so the command layer (:mod:`mureo.cli.service_cmd`) stays
OS-agnostic. Every backend degrades gracefully: a missing loader binary,
a nonzero exit, or a permission error becomes an :class:`OpResult` with
``ok=False`` and a message, never a traceback.

The fixed daemon port (the default ``mureo configure`` port) is shared so
every backend, the status probe, and the printed URL agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from mureo.web.server import DEFAULT_CONFIGURE_PORT

#: Loopback-only host the daemon binds and the status probe targets.
SERVICE_BIND_HOST = "127.0.0.1"

#: Default port the auto-start daemon serves on (shared with configure).
SERVICE_PORT = DEFAULT_CONFIGURE_PORT


@dataclass(frozen=True)
class OpResult:
    """Outcome of an ``install`` / ``uninstall`` operation.

    ``ok`` drives the CLI exit code; ``message`` is a human-readable line
    (the success summary, or — on failure — the stderr tail / reason).
    """

    ok: bool
    message: str


@dataclass(frozen=True)
class StatusResult:
    """Snapshot of the auto-start service state.

    ``installed`` reflects whether the unit/plist/task is registered;
    ``running`` whether the daemon currently answers ``/api/ping``;
    ``url`` is the dashboard URL for display.
    """

    installed: bool
    running: bool
    url: str


def dashboard_url(host: str = SERVICE_BIND_HOST, port: int = SERVICE_PORT) -> str:
    """Return the loopback dashboard URL for ``host:port``."""
    return f"http://{host}:{port}/"


__all__ = [
    "SERVICE_BIND_HOST",
    "SERVICE_PORT",
    "OpResult",
    "StatusResult",
    "dashboard_url",
]
