"""Server-side one-click upgrade for the configure UI's About tab (#239).

``run_upgrade_all`` is the web counterpart of ``mureo upgrade --all``:
it discovers every installed ``mureo`` / ``mureo-*`` distribution in the
current venv (``sys.executable``) and runs ``pip install --upgrade``
against exactly that set.

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
import sys
from typing import Any, Final

from mureo.installed_packages import discover_all_mureo_packages
from mureo.pip_env import pip_subprocess_env
from mureo.web.action_result import ActionResult, returncode_detail

logger = logging.getLogger(__name__)

#: Generous ceiling — a full reinstall of mureo plus several plugins over
#: a slow index can take a while, but it must still be bounded.
_UPGRADE_TIMEOUT_SECONDS: Final[int] = 600

#: Cap on the captured pip output echoed back in the JSON envelope (and
#: logged on a failure) so a verbose install log never bloats either. The
#: TAIL is kept (the error / "Successfully installed" summary is at the end).
_OUTPUT_CAP_CHARS: Final[int] = 4000

#: The ``error`` code of a pip run that could not start or exited non-zero.
_UPGRADE_FAILED: Final = "upgrade_failed"


def _tail(text: str) -> str:
    """Return the last :data:`_OUTPUT_CAP_CHARS` characters of ``text``."""

    return text[-_OUTPUT_CAP_CHARS:]


def run_upgrade_all() -> dict[str, Any] | ActionResult:
    """Upgrade mureo + every installed ``mureo-*`` plugin in this venv.

    A success is ``{"status", "returncode", "packages", "output"}``: ``ok``
    after pip ran (``packages`` is the server-derived target list, ``output``
    the tail of pip's stdout/stderr), ``noop`` when no mureo distribution is
    discovered (pip never runs with no targets). The running server is still
    on the OLD code afterwards, so the UI prompts a restart. A failure is
    ``ActionResult.failed``: ``internal_error`` when discovery raised,
    ``upgrade_failed`` when pip could not run or exited non-zero — never an
    exception.
    """
    try:
        targets = discover_all_mureo_packages()
    except Exception as exc:  # noqa: BLE001 — discovery must never break the action
        logger.exception("run_upgrade_all package discovery failed")
        return ActionResult.failed("internal_error", type(exc).__name__)

    # Belt-and-braces, mirroring the CLI's _resolve_targets: mureo itself
    # must always be upgraded even when its dist metadata is hidden from
    # discovery (editable installs without dist-info, a corrupted
    # METADATA). Only prepend when other mureo-* targets exist — an empty
    # discovery stays a genuine noop rather than forcing a bare upgrade.
    if targets and "mureo" not in targets:
        targets = ["mureo", *targets]

    if not targets:
        return {"status": "noop", "returncode": 0, "packages": [], "output": ""}

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--", *targets]
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted exe
            cmd,
            capture_output=True,
            text=True,
            # Force UTF-8 decoding of pip's output — otherwise text mode uses
            # the locale codec (cp932 on a Japanese Windows) and pip's install
            # log raises UnicodeDecodeError, which escapes the except below.
            encoding="utf-8",
            errors="replace",
            # Force the child (pip) to ENCODE its stdout as UTF-8 too, or a
            # Japanese Windows (cp932) crashes pip on a non-cp932 char in its
            # install log before our UTF-8 decoding runs. See pip_env.
            env=pip_subprocess_env(),
            check=False,
            timeout=_UPGRADE_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.exception("pip install --upgrade failed to run")
        return ActionResult.failed(_UPGRADE_FAILED, type(exc).__name__)

    combined = (proc.stdout or "") + (proc.stderr or "")
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
