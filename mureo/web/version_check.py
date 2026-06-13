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

Non-blocking accessor: HTTP handlers must call :func:`get_update_status`,
NOT :func:`check_for_updates` directly. ``pip list --outdated`` reaches
the configured index and can take up to ``_PIP_TIMEOUT_SECONDS`` on a slow
or unreachable network. Running it inline on every request blocks the
request thread for that long — and the configure UI fetches ``/api/updates``
more than once per page load — so the slow check is run once in a daemon
thread and its result cached; the handler returns instantly.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from typing import Any, Final

from mureo.cli.upgrade_cmd import _canonicalise, _is_mureo_package

logger = logging.getLogger(__name__)

#: Hard ceiling on the pip subprocess so a hung index never blocks the
#: dashboard's background check.
_PIP_TIMEOUT_SECONDS: Final[int] = 60

#: How long a successful check stays fresh. The package index rarely moves
#: within a single configure session, so re-running the slow pip query on
#: every page load buys nothing.
_OK_TTL_SECONDS: Final[int] = 6 * 60 * 60

#: A failed check (timeout / offline) is retried far sooner than a success,
#: but not on every request — otherwise a slow index would spawn a fresh
#: 60s pip run for each ``/api/updates`` fetch.
_ERROR_TTL_SECONDS: Final[int] = 10 * 60

#: Returned on a cold cache while the first background check is still in
#: flight. The frontend treats any non-``ok`` status as "nothing to show".
_CHECKING_RESULT: Final[dict[str, Any]] = {
    "status": "checking",
    "any_update": False,
    "packages": [],
}


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
    except subprocess.TimeoutExpired:
        # Expected on a slow / unreachable index — not a bug. Log one line,
        # not a multi-line traceback that scares the operator on the console.
        logger.warning(
            "pip list --outdated timed out after %ss", _PIP_TIMEOUT_SECONDS
        )
        return None
    except OSError as exc:
        logger.warning("pip list --outdated could not run: %s", exc)
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


# --- Non-blocking cache layer ------------------------------------------------
#
# ``check_for_updates`` shells out to pip and can block for up to
# ``_PIP_TIMEOUT_SECONDS``. The HTTP handler must never pay that cost inline,
# so the slow check runs in a daemon thread and its envelope is cached. The
# server is threaded, hence the lock around the shared cache state.

_cache_lock = threading.Lock()
_cached_result: dict[str, Any] | None = None
_cached_at_monotonic: float = 0.0
_refresh_in_progress: bool = False
#: Last spawned worker — exposed only so tests (and a future graceful
#: shutdown) can join the background check deterministically.
_refresh_thread: threading.Thread | None = None


def _ttl_for(result: dict[str, Any]) -> int:
    """A success is cached far longer than a transient failure."""

    return _OK_TTL_SECONDS if result.get("status") == "ok" else _ERROR_TTL_SECONDS


def _refresh_updates() -> None:
    """Background worker: run the slow pip check and cache its result."""

    global _cached_result, _cached_at_monotonic, _refresh_in_progress
    try:
        result = check_for_updates()
    except Exception:  # noqa: BLE001 — a daemon thread must never die loudly;
        # check_for_updates is contracted not to raise, this is belt-and-braces.
        logger.warning("background update check failed unexpectedly", exc_info=True)
        result = _error_result()
    with _cache_lock:
        _cached_result = result
        _cached_at_monotonic = time.monotonic()
        _refresh_in_progress = False


def get_update_status() -> dict[str, Any]:
    """Non-blocking accessor for ``GET /api/updates``.

    Returns the cached envelope instantly so the request thread NEVER blocks
    on pip. On a cold or stale cache a single background refresh is started
    and the last-known result is returned — or the ``checking`` placeholder
    on a cold start. Shape matches :func:`check_for_updates`.
    """

    global _refresh_in_progress, _refresh_thread
    now = time.monotonic()
    with _cache_lock:
        cached = _cached_result
        fresh = cached is not None and (now - _cached_at_monotonic) < _ttl_for(cached)
        if fresh:
            return dict(cached)
        start_refresh = not _refresh_in_progress
        if start_refresh:
            _refresh_in_progress = True
    if start_refresh:
        worker = threading.Thread(
            target=_refresh_updates, name="mureo-update-check", daemon=True
        )
        try:
            worker.start()
        except RuntimeError:
            # Interpreter shutting down / out of threads. Clear the flag so a
            # later request can retry instead of being wedged forever.
            with _cache_lock:
                _refresh_in_progress = False
                _refresh_thread = None
            logger.warning("could not start background update check")
        else:
            with _cache_lock:
                _refresh_thread = worker
    # Return a copy: a caller that mutates the result must never corrupt the
    # shared cache (read by other request threads). Shallow is enough — the
    # payload is read-only output. ``packages`` stays shared by reference.
    return dict(cached) if cached is not None else dict(_CHECKING_RESULT)


def _reset_update_cache() -> None:
    """Test-only: clear cached state between cases (module globals persist)."""

    global _cached_result, _cached_at_monotonic, _refresh_in_progress
    global _refresh_thread
    with _cache_lock:
        _cached_result = None
        _cached_at_monotonic = 0.0
        _refresh_in_progress = False
        _refresh_thread = None


__all__ = ["check_for_updates", "get_update_status"]
