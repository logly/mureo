"""Windows Task Scheduler backend for ``mureo service`` (#241 Phase 2).

Registers the headless configure daemon as an on-logon Scheduled Task
named ``MureoConfigure`` (per-user, no admin) via ``schtasks``. A
Scheduled Task is more robust than a Startup-folder shortcut: it survives
profile churn and restarts cleanly. ``schtasks /Create ... /SC ONLOGON
/F`` registers (``/F`` overwrites, so re-install is idempotent),
``schtasks /Run`` starts it now, and ``schtasks /Delete ... /F`` removes
it. Installed-ness is queried with ``schtasks /Query``.

All ``subprocess`` calls use a fixed argv with ``shell=False`` and only
reference the user's own ``sys.executable`` and an int port. Every failure
path (missing ``schtasks``, nonzero exit) returns a structured result
rather than raising.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from mureo.web.instance import probe_mureo_instance, read_state_file
from mureo.web.service import (
    SERVICE_BIND_HOST,
    SERVICE_PORT,
    OpResult,
    StatusResult,
    dashboard_url,
)
from mureo.web.service._common import service_command

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: Scheduled Task name registered with the per-user Task Scheduler.
TASK_NAME = "MureoConfigure"


def task_run_command(*, port: int = SERVICE_PORT) -> str:
    """Return the ``/TR`` command string: ``<py> -m mureo configure --serve``."""
    return service_command(port=port)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` with a fixed list and ``shell=False`` (never a string)."""
    return subprocess.run(  # noqa: S603 — fixed argv, shell=False
        argv, capture_output=True, text=True, shell=False, check=False
    )


def _task_exists() -> bool:
    """Return ``True`` iff ``schtasks /Query`` finds the task (exit 0)."""
    try:
        proc = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    except (FileNotFoundError, OSError):
        return False
    return proc.returncode == 0


def install(*, home: Path | None = None, port: int = SERVICE_PORT) -> OpResult:
    """Create the on-logon task and run it now. Idempotent (``/F``).

    ``home`` is accepted and ignored for signature parity with the
    file-writing backends (launchd/systemd) — Task Scheduler stores the
    task itself, so there is no unit file under a home dir to place.
    """
    create = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        task_run_command(port=port),
        "/SC",
        "ONLOGON",
        "/F",
    ]
    try:
        proc = _run(create)
        if proc.returncode != 0:
            return OpResult(
                ok=False, message=(proc.stderr or proc.stdout or "").strip()
            )
        # Start immediately so the user need not log out / in.
        _run(["schtasks", "/Run", "/TN", TASK_NAME])
    except FileNotFoundError:
        return OpResult(ok=False, message="schtasks not found on PATH")
    except OSError as exc:  # pragma: no cover - defensive
        return OpResult(ok=False, message=str(exc))
    return OpResult(ok=True, message="task created")


def uninstall(*, home: Path | None = None) -> OpResult:
    """Delete the task. Clean no-op when the task does not exist.

    Queries ``schtasks`` directly (rather than via the error-swallowing
    :func:`_task_exists`) so a missing ``schtasks`` binary surfaces as a
    structured error instead of being mistaken for "task absent".
    """
    try:
        query = _run(["schtasks", "/Query", "/TN", TASK_NAME])
        if query.returncode != 0:
            # Task not registered → clean no-op.
            return OpResult(ok=True, message="not installed (nothing to remove)")
        proc = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        if proc.returncode != 0:
            return OpResult(
                ok=False, message=(proc.stderr or proc.stdout or "").strip()
            )
    except FileNotFoundError:
        return OpResult(ok=False, message="schtasks not found on PATH")
    except OSError as exc:  # pragma: no cover - defensive
        return OpResult(ok=False, message=str(exc))
    return OpResult(ok=True, message="removed")


def restart(*, home: Path | None = None, port: int = SERVICE_PORT) -> OpResult:
    """Restart the on-logon task: end the running instance, then run it.

    Picks up new code / static assets without a re-install. Requires the
    task to exist — a clean "not installed" message points the user at
    ``mureo service install``. ``schtasks /End`` stops the current instance
    (a not-running task makes ``/End`` return nonzero, which is ignored so
    it never fails the restart) and ``/Run`` starts a fresh one.
    """
    try:
        query = _run(["schtasks", "/Query", "/TN", TASK_NAME])
        if query.returncode != 0:
            return OpResult(
                ok=False, message="not installed (run `mureo service install`)"
            )
        # Best-effort stop of any running instance before relaunching.
        _run(["schtasks", "/End", "/TN", TASK_NAME])
        proc = _run(["schtasks", "/Run", "/TN", TASK_NAME])
        if proc.returncode != 0:
            return OpResult(
                ok=False, message=(proc.stderr or proc.stdout or "").strip()
            )
    except FileNotFoundError:
        return OpResult(ok=False, message="schtasks not found on PATH")
    except OSError as exc:  # pragma: no cover - defensive
        return OpResult(ok=False, message=str(exc))
    return OpResult(ok=True, message="restarted")


def status(*, home: Path | None = None, port: int = SERVICE_PORT) -> StatusResult:
    """Report installed (task exists) and running (``/api/ping``) state.

    Prefer the actually-bound port/url from configure.json so an ephemeral-port
    fallback (SERVICE_PORT busy at launch) is not misreported as "not running".
    """
    from pathlib import Path as _Path

    installed = _task_exists()
    persisted = read_state_file(home if home is not None else _Path.home())
    if persisted is not None:
        effective_port = int(persisted["port"])
        url = str(persisted["url"])
    else:
        effective_port = port
        url = dashboard_url(port=port)
    running = probe_mureo_instance(SERVICE_BIND_HOST, effective_port)
    return StatusResult(installed=installed, running=running, url=url)


__all__ = [
    "TASK_NAME",
    "install",
    "restart",
    "status",
    "task_run_command",
    "uninstall",
]
