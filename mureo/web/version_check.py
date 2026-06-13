"""Update-availability check for the configure UI's "About mureo" tab (#239).

Surfaces whether a newer ``mureo`` or any installed ``mureo-*`` plugin is
available so the operator can upgrade with one click. The check shells out
to ``python -m pip list --outdated --format=json`` on ``sys.executable``
and FILTERS the result to mureo / ``mureo-*`` packages.

Why pip (not a direct PyPI query): running pip respects the operator's
configured package index, so private bridges (``mureo-logly-bridge``,
``mureo-agency`` — potentially on a private index, not public PyPI) are
checked correctly, and it shares the exact venv / index resolution that
``mureo upgrade --all`` uses. "Update available" and "the upgrade" are
then consistent by construction — no hand-rolled PEP 440 comparison, no
HTTP client of our own.

Fault isolation: any pip failure (non-zero exit, timeout, network down,
unparseable JSON, OS error) degrades to ``status="error"`` with
``any_update=False``. This function NEVER raises and NEVER produces a 500.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any, Final

from mureo.cli.upgrade_cmd import _canonicalise, _is_mureo_package

logger = logging.getLogger(__name__)

#: Hard ceiling on the pip subprocess so a hung index never blocks the
#: dashboard's background check.
_PIP_TIMEOUT_SECONDS: Final[int] = 60


def _error_result() -> dict[str, Any]:
    """The degraded envelope used for every failure mode."""

    return {"status": "error", "any_update": False, "packages": []}


def _run_pip_outdated() -> str | None:
    """Return pip's ``--outdated --format=json`` stdout, or ``None``.

    ``None`` signals any failure mode (non-zero exit, timeout, OS error)
    the caller must treat as "could not determine updates".
    """
    cmd = [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"]
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted exe
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_PIP_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        logger.exception("pip list --outdated failed to run")
        return None
    if proc.returncode != 0:
        logger.warning(
            "pip list --outdated exited %s: %s", proc.returncode, proc.stderr
        )
        return None
    return proc.stdout


def _row_to_package(row: Any) -> dict[str, str] | None:
    """Map one pip ``--outdated`` JSON row to ``{name, installed, latest}``.

    Returns ``None`` for a non-mureo package or a row missing the required
    keys (so one malformed entry never breaks the whole check).
    """
    if not isinstance(row, dict):
        return None
    name = row.get("name")
    installed = row.get("version")
    latest = row.get("latest_version")
    if not isinstance(name, str) or not name or not _is_mureo_package(name):
        return None
    if not isinstance(installed, str) or not isinstance(latest, str):
        return None
    if not installed or not latest:
        return None
    return {
        "name": _canonicalise(name),
        "installed": installed,
        "latest": latest,
    }


def check_for_updates() -> dict[str, Any]:
    """Return the ``GET /api/updates`` response payload.

    Shape::

        {
          "status": "ok" | "error",
          "any_update": bool,
          "packages": [{"name": str, "installed": str, "latest": str}, ...]
        }

    ``packages`` lists ONLY outdated mureo / ``mureo-*`` distributions
    (mureo itself included when outdated), sorted by canonical name.
    ``any_update`` is ``True`` iff at least one such package is listed.
    On any pip failure the envelope degrades to ``status="error"`` /
    ``any_update=False`` / empty ``packages`` — never an exception.
    """
    stdout = _run_pip_outdated()
    if stdout is None:
        return _error_result()
    try:
        rows = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("pip list --outdated produced unparseable JSON")
        return _error_result()
    if not isinstance(rows, list):
        logger.warning("pip list --outdated did not return a JSON array")
        return _error_result()

    packages = [pkg for pkg in (_row_to_package(row) for row in rows) if pkg]
    packages.sort(key=lambda pkg: pkg["name"])
    return {
        "status": "ok",
        "any_update": bool(packages),
        "packages": packages,
    }


__all__ = ["check_for_updates"]
