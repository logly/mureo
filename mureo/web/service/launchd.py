"""macOS LaunchAgent backend for ``mureo service`` (#241 Phase 2).

Registers the headless configure daemon as a *per-user* LaunchAgent so it
starts at login and is restarted if it dies — no reboot, no root. The
plist lives at ``~/Library/LaunchAgents/io.mureo.configure.plist`` and
runs ``<sys.executable> -m mureo configure --serve --port <port>``;
``launchctl bootstrap`` (modern) / ``launchctl load`` (fallback) makes it
take effect immediately, and ``launchctl bootout`` / ``unload`` stops it.

All ``subprocess`` calls use a fixed argv with ``shell=False`` and only
reference the user's own ``sys.executable`` and ``Path.home()`` — no
interpolation of untrusted data. Every failure path (missing
``launchctl``, nonzero exit, permission error) returns a structured
:class:`OpResult` / :class:`StatusResult` rather than raising.
"""

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
import time
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
from mureo.web.service._common import service_argv

logger = logging.getLogger(__name__)

#: launchd label / reverse-DNS identifier for the agent.
LABEL = "io.mureo.configure"


def _home(home: Path | None) -> Path:
    """Resolve the home root, honouring an injected ``home`` (tests)."""
    return home if home is not None else Path.home()


def plist_path(home: Path | None = None) -> Path:
    """Path to the LaunchAgent plist under ``~/Library/LaunchAgents``."""
    return _home(home) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _log_paths(home: Path) -> tuple[Path, Path]:
    """Return ``(stdout, stderr)`` log paths under ``~/.mureo``."""
    base = home / ".mureo"
    return base / "configure.log", base / "configure.err"


def build_plist(home: Path | None = None, *, port: int = SERVICE_PORT) -> bytes:
    """Build the LaunchAgent plist body as XML bytes.

    ``RunAtLoad`` starts the daemon at login; ``KeepAlive`` restarts it if
    it exits; stdout/stderr are captured under ``~/.mureo`` for debugging.
    ``EnvironmentVariables`` stamps the managed-service marker so the daemon
    knows ``KeepAlive`` will relaunch it and may exit-to-restart after a
    self-upgrade.
    """
    resolved = _home(home)
    out_path, err_path = _log_paths(resolved)
    payload = {
        "Label": LABEL,
        "ProgramArguments": list(service_argv(port=port)),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": dict(SERVICE_ENVIRONMENT),
        "StandardOutPath": str(out_path),
        "StandardErrorPath": str(err_path),
    }
    return plistlib.dumps(payload)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` with a fixed list and ``shell=False`` (never a string)."""
    return subprocess.run(  # noqa: S603 — fixed argv, shell=False
        argv, capture_output=True, text=True, shell=False, check=False
    )


def _current_uid() -> int:
    """Return the POSIX uid, or ``0`` where ``os.getuid`` is absent.

    launchd only ever runs on macOS, but the backend is imported and
    unit-tested (with ``launchctl`` mocked) on every platform — including
    Windows, where ``os.getuid`` does not exist. Falling back to ``0``
    keeps the code importable/testable cross-platform; the value only
    feeds the ``gui/<uid>`` launchctl domain, which is never reached off
    macOS at runtime.
    """
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid is not None else 0


def _load(path: Path) -> OpResult:
    """Bootstrap the agent now via ``launchctl`` (modern then fallback)."""
    uid = _current_uid()
    bootstrap = ["launchctl", "bootstrap", f"gui/{uid}", str(path)]
    try:
        proc = _run(bootstrap)
        if proc.returncode == 0:
            return OpResult(ok=True, message="bootstrapped")
        # Fallback for older macOS that lacks ``bootstrap``.
        fallback = _run(["launchctl", "load", "-w", str(path)])
        if fallback.returncode == 0:
            return OpResult(ok=True, message="loaded")
        tail = (fallback.stderr or proc.stderr or "launchctl failed").strip()
        return OpResult(ok=False, message=tail)
    except FileNotFoundError:
        return OpResult(ok=False, message="launchctl not found on PATH")
    except OSError as exc:  # pragma: no cover - defensive
        return OpResult(ok=False, message=str(exc))


def _unload(path: Path) -> None:
    """Bootout the agent now (best-effort; ignore already-stopped)."""
    uid = _current_uid()
    try:
        proc = _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        if proc.returncode != 0:
            _run(["launchctl", "unload", "-w", str(path)])
    except (FileNotFoundError, OSError):
        logger.debug("launchctl unload best-effort skip", exc_info=True)


#: ``launchctl bootout`` is asynchronous: bootstrapping the new agent while the
#: previous one is still tearing down races and can leave NOTHING loaded (the
#: bootstrap returns 0 but the job never sticks). After bootstrap we confirm the
#: job is actually loaded and re-try a few times if not.
_BOOTSTRAP_RETRIES = 4
_BOOTSTRAP_RETRY_SECONDS = 0.75


def _is_loaded() -> bool:
    """``True`` if the agent is currently registered with launchd."""
    uid = _current_uid()
    return _run(["launchctl", "print", f"gui/{uid}/{LABEL}"]).returncode == 0


def install(*, home: Path | None = None, port: int = SERVICE_PORT) -> OpResult:
    """Write the plist and bootstrap it now. Idempotent (overwrites).

    On a RE-install the previous agent is booted out first. Because
    ``launchctl bootout`` is asynchronous, a single bootstrap can race the
    teardown and silently leave the service unloaded — so a bootstrap that
    "succeeds" but does not actually stick is dropped and re-tried a few
    times. A hard bootstrap error (missing launchctl, permission denied) is
    returned immediately — retrying would not help.
    """
    path = plist_path(home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build_plist(home, port=port))
        # Auto-run agent: make owner-only explicit so no other local user
        # can rewrite the command launchd runs at our login (defense in
        # depth; ~/Library/LaunchAgents is already user-owned).
        path.chmod(0o600)
    except OSError as exc:
        return OpResult(ok=False, message=f"could not write plist: {exc}")
    # Re-install cleanly: drop any previous load before bootstrapping.
    _unload(path)
    result = _load(path)
    for _ in range(_BOOTSTRAP_RETRIES):
        if not result.ok:
            return result  # a real bootstrap failure — retrying won't fix it
        if _is_loaded():
            return result  # bootstrapped AND stuck
        # "Succeeded" but did not stick (still racing the async bootout):
        # drop and re-bootstrap after a short pause.
        time.sleep(_BOOTSTRAP_RETRY_SECONDS)
        _unload(path)
        result = _load(path)
    # Out of retries — report failure rather than a false "ok" if the job
    # still is not loaded.
    if result.ok and _is_loaded():
        return result
    return OpResult(ok=False, message="service did not stay loaded after install")


def uninstall(*, home: Path | None = None) -> OpResult:
    """Stop the agent and remove the plist. Clean no-op if not installed."""
    path = plist_path(home)
    if not path.exists():
        return OpResult(ok=True, message="not installed (nothing to remove)")
    _unload(path)
    try:
        path.unlink()
    except OSError as exc:
        return OpResult(ok=False, message=f"could not remove plist: {exc}")
    return OpResult(ok=True, message="removed")


def status(*, home: Path | None = None, port: int = SERVICE_PORT) -> StatusResult:
    """Report installed (plist exists) and running (``/api/ping``) state."""
    installed = plist_path(home).exists()
    running = probe_mureo_instance(SERVICE_BIND_HOST, port)
    return StatusResult(
        installed=installed, running=running, url=dashboard_url(port=port)
    )


__all__ = [
    "LABEL",
    "build_plist",
    "install",
    "plist_path",
    "status",
    "uninstall",
]
