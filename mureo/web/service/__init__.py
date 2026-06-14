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

import os
from dataclasses import dataclass

from mureo.web.server import DEFAULT_CONFIGURE_PORT

#: Loopback-only host the daemon binds and the status probe targets.
SERVICE_BIND_HOST = "127.0.0.1"

#: Default port the auto-start daemon serves on (shared with configure).
SERVICE_PORT = DEFAULT_CONFIGURE_PORT

#: Env var the install backends stamp into the launchd plist / systemd unit
#: so the RUNNING daemon knows it is supervised (launchd ``KeepAlive`` /
#: systemd ``Restart=always``). Only then may the server exit-to-restart
#: after a self-upgrade — a plain interactive ``mureo configure`` has no
#: supervisor, so exiting there would just kill the server (it keeps the
#: manual "restart" prompt instead). NOT set on Windows: Task Scheduler does
#: not relaunch a task that exits cleanly, so that path stays manual too.
MANAGED_SERVICE_ENV = "MUREO_MANAGED_SERVICE"

#: Environment the launchd / systemd backends inject into their unit so the
#: marker above is present in the daemon's process environment.
SERVICE_ENVIRONMENT: dict[str, str] = {MANAGED_SERVICE_ENV: "1"}


def is_managed_service() -> bool:
    """``True`` when this process runs under a mureo auto-start supervisor.

    Read from the process environment (the marker is stamped into the
    launchd plist / systemd unit by ``mureo service install``). The
    configure server consults this before exiting-to-restart on a
    self-upgrade: only safe when a supervisor will bring it back up.
    """
    return os.environ.get(MANAGED_SERVICE_ENV) == "1"


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
    "MANAGED_SERVICE_ENV",
    "SERVICE_BIND_HOST",
    "SERVICE_ENVIRONMENT",
    "SERVICE_PORT",
    "OpResult",
    "StatusResult",
    "dashboard_url",
    "is_managed_service",
]
