"""Linux systemd --user backend for ``mureo service`` (#241 Phase 2).

Registers the headless configure daemon as a *per-user* systemd service
so it starts at login and restarts on failure — no root, no system unit.
The unit lives at ``~/.config/systemd/user/mureo-configure.service`` with
``ExecStart=<sys.executable> -m mureo configure --serve --port <port>``,
``Restart=always`` and ``WantedBy=default.target``; ``systemctl --user
enable --now`` makes it take effect immediately and ``disable --now``
stops it.

All ``subprocess`` calls use a fixed argv with ``shell=False`` and only
reference the user's own ``sys.executable`` / ``Path.home()``. Every
failure path (missing ``systemctl``, nonzero exit, permission error)
returns a structured result rather than raising.
"""

from __future__ import annotations

import contextlib
import logging
import subprocess
from pathlib import Path

from mureo.web.instance import probe_mureo_instance
from mureo.web.service import (
    SERVICE_BIND_HOST,
    SERVICE_ENVIRONMENT,
    SERVICE_PORT,
    OpResult,
    StatusResult,
    dashboard_url,
)
from mureo.web.service._common import service_command

logger = logging.getLogger(__name__)

#: systemd unit filename for the per-user service.
UNIT_NAME = "mureo-configure.service"


def _home(home: Path | None) -> Path:
    """Resolve the home root, honouring an injected ``home`` (tests)."""
    return home if home is not None else Path.home()


def unit_path(home: Path | None = None) -> Path:
    """Path to the unit under ``~/.config/systemd/user``."""
    return _home(home) / ".config" / "systemd" / "user" / UNIT_NAME


def build_unit(*, port: int = SERVICE_PORT) -> str:
    """Build the systemd unit body.

    ``Type=simple`` (the daemon never forks); ``Restart=always`` brings it
    back if it crashes; ``WantedBy=default.target`` enables it for the
    user's login session.
    """
    exec_start = service_command(port=port)
    return (
        "[Unit]\n"
        "Description=mureo configuration UI (headless daemon)\n"
        "After=default.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        # Managed-service marker so the daemon knows Restart=always will
        # relaunch it and may exit-to-restart after a self-upgrade.
        + "".join(
            f"Environment={key}={value}\n" for key, value in SERVICE_ENVIRONMENT.items()
        )
        + "Restart=always\n"
        "RestartSec=2\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` with a fixed list and ``shell=False`` (never a string)."""
    return subprocess.run(  # noqa: S603 — fixed argv, shell=False
        argv, capture_output=True, text=True, shell=False, check=False
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``systemctl --user <args...>``."""
    return _run(["systemctl", "--user", *args])


def install(*, home: Path | None = None, port: int = SERVICE_PORT) -> OpResult:
    """Write the unit, reload, and enable --now. Idempotent (overwrites)."""
    path = unit_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(build_unit(port=port), encoding="utf-8")
        # Auto-run unit: make owner-only explicit so no other local user can
        # rewrite the command that runs at our login (defense in depth; the
        # parent dir is already user-owned).
        path.chmod(0o600)
    except OSError as exc:
        return OpResult(ok=False, message=f"could not write unit: {exc}")
    try:
        reload_proc = _systemctl("daemon-reload")
        if reload_proc.returncode != 0:
            return OpResult(ok=False, message=(reload_proc.stderr or "").strip())
        enable_proc = _systemctl("enable", "--now", UNIT_NAME)
        if enable_proc.returncode != 0:
            return OpResult(ok=False, message=(enable_proc.stderr or "").strip())
    except FileNotFoundError:
        return OpResult(ok=False, message="systemctl not found on PATH")
    except OSError as exc:  # pragma: no cover - defensive
        return OpResult(ok=False, message=str(exc))
    return OpResult(ok=True, message="enabled")


def uninstall(*, home: Path | None = None) -> OpResult:
    """Disable --now and remove the unit. Clean no-op if not installed."""
    path = unit_path(home)
    if not path.exists():
        return OpResult(ok=True, message="not installed (nothing to remove)")
    # Best-effort stop+disable; an already-inactive unit returns nonzero
    # but the unit file must still be removed.
    try:
        _systemctl("disable", "--now", UNIT_NAME)
    except (FileNotFoundError, OSError):
        logger.debug("systemctl disable best-effort skip", exc_info=True)
    try:
        path.unlink()
    except OSError as exc:
        return OpResult(ok=False, message=f"could not remove unit: {exc}")
    # Best-effort post-remove reload; a missing/failing systemctl here must
    # not undo the (already-successful) removal.
    with contextlib.suppress(FileNotFoundError, OSError):
        _systemctl("daemon-reload")
    return OpResult(ok=True, message="removed")


def status(*, home: Path | None = None, port: int = SERVICE_PORT) -> StatusResult:
    """Report installed (unit exists) and running (``/api/ping``) state."""
    installed = unit_path(home).exists()
    running = probe_mureo_instance(SERVICE_BIND_HOST, port)
    return StatusResult(
        installed=installed, running=running, url=dashboard_url(port=port)
    )


__all__ = [
    "UNIT_NAME",
    "build_unit",
    "install",
    "status",
    "uninstall",
    "unit_path",
]
