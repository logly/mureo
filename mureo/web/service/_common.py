"""Shared argv construction for the auto-start backends (#241 Phase 2).

Every backend launches the same headless daemon command — the only
variation is the port — so the argv is built in one place. Anchoring on
``sys.executable -m mureo`` (rather than a bare ``mureo`` console script)
keeps the launch path independent of where ``pip`` placed the shim and of
``PATH``, which a login-time service may not fully inherit.

Only ``sys.executable`` and an integer port feed the argv, so there is no
interpolation of untrusted data; the list is consumed by ``subprocess``
with ``shell=False`` (POSIX) or rendered into a single-line command string
(launchd plist, systemd ``ExecStart``, ``schtasks /TR``).
"""

from __future__ import annotations

import os
import sys

from mureo.web.service import SERVICE_ENVIRONMENT


def service_argv(*, port: int) -> tuple[str, ...]:
    """Return the daemon launch argv: ``<py> -m mureo configure --serve``.

    Returned as a tuple so callers cannot mutate the shared shape; they
    materialise a ``list`` when an API (plist ``ProgramArguments``,
    ``subprocess.run``) requires one.
    """
    return (
        sys.executable,
        "-m",
        "mureo",
        "configure",
        "--serve",
        "--port",
        str(int(port)),
    )


def service_command(*, port: int) -> str:
    """Render :func:`service_argv` as a single-line command string.

    Used where a manager re-parses one command string rather than taking
    an argv list — systemd ``ExecStart`` and the Windows ``schtasks /TR``
    value. The executable is double-quoted because the default install
    path contains a space on Windows (``C:\\Program Files\\Python...``) and
    can on macOS/Linux too; without quoting the manager would split the
    path and the daemon would silently fail to launch at login. The
    remaining tokens are fixed literals + an int port, so they need no
    quoting, and nothing here is attacker-influenced.
    """
    executable, *rest = service_argv(port=port)
    return " ".join([f'"{executable}"', *rest])


def service_environment() -> dict[str, str]:
    """Environment the launchd / systemd unit injects into the daemon.

    The managed-service marker plus the ``PATH`` of the shell that runs
    ``mureo service install``: a login-time supervisor starts the daemon
    with its own minimal ``PATH``, which lacks ``/opt/homebrew/bin``,
    ``/usr/local/bin`` and ``~/.local/bin``, so provider installs that
    spawn ``pipx`` or ``npm`` would not find them. Recording the operator's
    ``PATH`` makes the daemon see the same tools the shell does. Only
    absolute entries are kept: an empty or relative entry would resolve
    against the daemon's working directory, not the shell's. ``PATH`` is
    omitted when no absolute entry remains.
    """
    env = dict(SERVICE_ENVIRONMENT)
    entries = os.environ.get("PATH", "").split(os.pathsep)
    path = os.pathsep.join(entry for entry in entries if os.path.isabs(entry))
    if path:
        env["PATH"] = path
    return env


__all__ = ["service_argv", "service_command", "service_environment"]
