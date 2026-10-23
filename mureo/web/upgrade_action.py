"""Server-side one-click upgrade for the configure UI's About tab (#239).

``run_upgrade_all`` is the web counterpart of ``mureo upgrade --all``:
it discovers every installed ``mureo`` / ``mureo-*`` distribution in the
current venv (``sys.executable``) and runs ``pip install --upgrade``
against exactly that set. pip itself is upgraded first (#910); a failed
self-upgrade is logged and the package upgrade still runs.

Security contract: the target list is derived ONLY from
``discover_all_mureo_packages`` — never from the request body. The HTTP
handler passes no package list, so an attacker cannot smuggle an
arbitrary package (or a pip flag) onto the install command. The ``--``
sentinel further prevents any discovered name from being read as a flag.

Fault isolation mirrors :mod:`mureo.web.setup_actions`: any failure is
an :class:`~mureo.web.action_result.ActionResult` from
``ActionResult.failed`` (HTTP 500, #864), and pip's output goes to the
server log. This function NEVER raises.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Final

from mureo.installed_packages import discover_all_mureo_packages
from mureo.pip_env import (
    pip_install_cmd,
    pip_self_upgrade_cmd,
    pip_subprocess_env,
)
from mureo.web.action_result import ActionResult, returncode_detail

logger = logging.getLogger(__name__)

#: Generous ceiling — a full reinstall of mureo plus several plugins over
#: a slow index can take a while, but it must still be bounded.
_UPGRADE_TIMEOUT_SECONDS: Final[int] = 600

#: Ceiling for the pip self-upgrade that runs first (#910): one small wheel,
#: so a hang is cut off well before the package install's budget.
_SELF_UPGRADE_TIMEOUT_SECONDS: Final[int] = 120

#: Cap on the captured pip output echoed back in the JSON envelope (and
#: logged on a failure) so a verbose install log never bloats either. The
#: TAIL is kept (the error / "Successfully installed" summary is at the end).
_OUTPUT_CAP_CHARS: Final[int] = 4000

#: The ``error`` code of a pip run that could not start or exited non-zero.
_UPGRADE_FAILED: Final = "upgrade_failed"


def _tail(text: str) -> str:
    """Return the last :data:`_OUTPUT_CAP_CHARS` characters of ``text``."""

    return text[-_OUTPUT_CAP_CHARS:]


def _run_pip(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Run one pip command on this venv, capturing its output; never checks."""

    return subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted exe
        cmd,
        capture_output=True,
        text=True,
        # Force UTF-8 decoding of pip's output — otherwise text mode uses
        # the locale codec (cp932 on a Japanese Windows) and pip's install
        # log raises UnicodeDecodeError, which escapes the caller's except.
        encoding="utf-8",
        errors="replace",
        # Force the child (pip) to ENCODE its stdout as UTF-8 too, or a
        # Japanese Windows (cp932) crashes pip on a non-cp932 char in its
        # install log before our UTF-8 decoding runs. See pip_env.
        env=pip_subprocess_env(),
        check=False,
        timeout=timeout,
    )


def _pip_self_upgrade_output() -> str:
    """Upgrade pip itself; return its output. Never raises, never fails.

    A failure is logged as a warning and the package upgrade still runs
    with the installed pip — no worse off than before (#910).
    """

    try:
        proc = _run_pip(pip_self_upgrade_cmd(), _SELF_UPGRADE_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(
            "pip self-upgrade failed (%s); continuing with the installed pip",
            type(exc).__name__,
        )
        return ""
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        logger.warning(
            "pip self-upgrade failed (%s); continuing with the installed pip: %s",
            proc.returncode,
            _tail(output),
        )
    return output


def run_upgrade_all() -> dict[str, Any] | ActionResult:
    """Upgrade mureo + every installed ``mureo-*`` plugin in this venv.

    A success is ``{"status", "returncode", "packages", "output"}``: ``ok``
    after pip ran (``packages`` is the server-derived target list, ``output``
    the tail of pip's stdout/stderr), ``noop`` when no mureo distribution is
    discovered (pip never runs with no targets). pip upgrades itself first;
    that failure is only logged, and ``returncode`` is the install's. The
    running server still has the OLD code afterwards, so the UI prompts a
    restart. A failure is ``ActionResult.failed``: ``internal_error`` when
    discovery raised, ``upgrade_failed`` when pip could not run or exited
    non-zero — never an exception.
    """
    try:
        targets = discover_all_mureo_packages()
    except Exception as exc:  # noqa: BLE001 — discovery must never break the action
        logger.exception("run_upgrade_all package discovery failed")
        return ActionResult.failed("internal_error", type(exc).__name__)

    # Belt-and-braces, mirroring the CLI's _resolve_targets: mureo itself is
    # always upgraded even when discovery hides its dist metadata (editable
    # installs, a corrupted METADATA), but an empty discovery stays a noop.
    if targets and "mureo" not in targets:
        targets = ["mureo", *targets]

    if not targets:
        return {"status": "noop", "returncode": 0, "packages": [], "output": ""}

    self_output = _pip_self_upgrade_output()
    try:
        proc = _run_pip(pip_install_cmd(targets), _UPGRADE_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.exception("pip install --upgrade failed to run")
        return ActionResult.failed(_UPGRADE_FAILED, type(exc).__name__)

    combined = self_output + (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        logger.warning(
            "pip install --upgrade exited %s: %s", proc.returncode, _tail(combined)
        )
        return ActionResult.failed(
            _UPGRADE_FAILED, returncode_detail("upgrade", proc.returncode)
        )
    return {
        "status": "ok",
        "returncode": proc.returncode,
        "packages": targets,
        "output": _tail(combined),
    }


__all__ = ["run_upgrade_all"]
