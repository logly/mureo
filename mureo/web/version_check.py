"""Update-availability check for the configure UI's "About mureo" tab (#239).

Surfaces whether a newer ``mureo`` or any installed ``mureo-*`` plugin is
available so the operator can upgrade with one click. The check enumerates
the installed mureo / ``mureo-*`` distributions locally, then shells out to
a SCOPED ``python -m pip install --dry-run --upgrade --no-deps --report -``
on ``sys.executable`` for just those packages and reads pip's JSON report.

Why scoped: ``pip list --outdated`` queries the index for EVERY installed
distribution, which on a heavy venv (e.g. the Google Ads SDK and its deps)
routinely exceeds the timeout and surfaces "could not check for updates".
Restricting the query to mureo + its plugins keeps it to a few seconds.

Why pip (not a direct PyPI query): running pip respects the operator's
configured package index, so private bridges (``mureo-logly-bridge``,
``mureo-agency`` — potentially on a private index, not public PyPI) are
checked correctly, and it shares the venv / index resolution that
``mureo upgrade`` uses. A package lands in the report's ``install`` list
when pip's resolver would change its version; we additionally require the
index version to be strictly newer than the installed one (a pinning
constraint can otherwise surface a downgrade), restoring parity with the
old ``pip list --outdated``. ``--no-deps`` scopes the query to the named
packages, so the check answers "is a newer mureo / plugin published?"
rather than fully simulating ``mureo upgrade --all``'s dependency
resolution — close enough for an availability badge, and far faster.

Fault isolation: any pip failure (non-zero exit, timeout, network down,
unparseable JSON, OS error) degrades to ``status="error"`` with
``any_update=False``. This function NEVER raises and NEVER produces a 500.

Non-blocking accessor: HTTP handlers must call :func:`get_update_status`,
NOT :func:`check_for_updates` directly. The scoped pip check still reaches
the configured index and can take up to ``_PIP_TIMEOUT_SECONDS`` on a slow
or unreachable network. Running it inline on every request blocks the
request thread for that long — and the configure UI fetches ``/api/updates``
more than once per page load — so the check is run once in a daemon
thread and its result cached; the handler returns instantly.
"""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
from importlib import metadata
from typing import Any, Final

from packaging.version import InvalidVersion, Version

from mureo.cli.upgrade_cmd import (
    _canonicalise,
    _discover_all_mureo_packages,
    _is_mureo_package,
)

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

#: Env override for the always-on service's background poll cadence, in
#: seconds. ``0`` or negative disables periodic polling; unset uses the
#: default. A wide cadence is fine — the index moves at most a few times a day.
_POLL_INTERVAL_ENV: Final[str] = "MUREO_UPDATE_CHECK_INTERVAL_SECONDS"

#: Default poll cadence: every 6h, aligned with ``_OK_TTL_SECONDS`` so the
#: cache is kept warm. At the exact tick/expiry boundary a UI hit may still
#: land on a momentarily-stale entry — the lazy refresh in ``get_update_status``
#: covers that window.
_DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 6 * 60 * 60


def _error_result() -> dict[str, Any]:
    """The degraded envelope used for every failure mode."""

    return {"status": "error", "any_update": False, "packages": []}


def _installed_mureo_versions() -> dict[str, str]:
    """``{canonical name: installed version}`` for installed mureo / ``mureo-*``
    distributions.

    Resolved locally from installed metadata (no network). Reused both to
    SCOPE the pip query below to just these packages and to fill the
    ``installed`` field of each reported package.
    """
    versions: dict[str, str] = {}
    for name in _discover_all_mureo_packages():
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return versions


def _run_pip_report(packages: list[str]) -> dict[str, Any] | None:
    """Return pip's JSON install report for a scoped dry-run upgrade, or ``None``.

    Runs ``pip install --dry-run --upgrade --no-deps --report -`` for ONLY the
    given mureo packages. Scoping is what keeps this fast: ``pip list
    --outdated`` queries the index for EVERY installed distribution (60s+ in a
    heavy venv — the timeout operators hit), whereas this touches only mureo +
    its plugins (~3s). ``--upgrade`` lets pip's own resolver decide what is
    outdated — a package appears in the report's ``install`` list iff a newer
    version is available — so "update available" stays consistent with
    ``mureo upgrade`` and we never hand-roll a PEP 440 comparison.

    ``None`` signals any failure mode (non-zero exit, timeout, OS error,
    unparseable JSON) the caller must treat as "could not determine updates".
    """
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--upgrade",
        "--no-deps",
        "--quiet",
        "--report",
        "-",
        "--",
        *packages,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, trusted exe
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        # Should not happen now the query is scoped, but keep the guard. Log one
        # line, not a multi-line traceback that scares the operator on the console.
        logger.warning("pip update check timed out after %ss", _PIP_TIMEOUT_SECONDS)
        return None
    except OSError as exc:
        logger.warning("pip update check could not run: %s", exc)
        return None
    if proc.returncode != 0:
        logger.warning("pip update check exited %s: %s", proc.returncode, proc.stderr)
        return None
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("pip update check produced unparseable JSON")
        return None
    if not isinstance(report, dict):
        logger.warning("pip update check report was not a JSON object")
        return None
    return report


def _outdated_from_report(
    report: dict[str, Any], installed: dict[str, str]
) -> list[dict[str, str]]:
    """Map pip's report ``install`` list to outdated mureo packages.

    Each entry pip would install/upgrade becomes ``{name, installed, latest}``
    (canonical name; ``installed`` filled from the local metadata snapshot).
    A non-mureo, malformed, or not-locally-installed entry is dropped so one
    bad row never breaks the whole check.
    """
    install = report.get("install")
    if not isinstance(install, list):
        return []
    packages: list[dict[str, str]] = []
    for item in install:
        if not isinstance(item, dict):
            continue
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            continue
        name = meta.get("name")
        latest = meta.get("version")
        if not isinstance(name, str) or not name or not _is_mureo_package(name):
            continue
        if not isinstance(latest, str) or not latest:
            continue
        canonical = _canonicalise(name)
        installed_version = installed.get(canonical)
        if not installed_version:
            continue
        # ``--upgrade`` can also list a DOWNGRADE target when a pip constraint
        # pins the package below what is installed; only a strictly newer
        # version is an "update available" (parity with pip list --outdated).
        # An unparseable version is dropped rather than shown as a dubious update.
        try:
            if Version(latest) <= Version(installed_version):
                continue
        except InvalidVersion:
            continue
        packages.append(
            {"name": canonical, "installed": installed_version, "latest": latest}
        )
    packages.sort(key=lambda pkg: pkg["name"])
    return packages


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
    installed = _installed_mureo_versions()
    if not installed:
        # No mureo distribution is resolvable (highly unusual). Nothing to
        # check rather than an error — there is genuinely nothing to upgrade.
        return {"status": "ok", "any_update": False, "packages": []}
    report = _run_pip_report(sorted(installed))
    if report is None:
        return _error_result()
    packages = _outdated_from_report(report, installed)
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


def _refresh_if_idle() -> None:
    """Run the check inline now, unless one is already in flight.

    Used by the periodic poller: it owns a daemon thread to block in, so it
    refreshes on that thread rather than spawning another worker. Honours the
    same single-flight gate as the lazy path so the two never double-run.
    """

    global _refresh_in_progress
    with _cache_lock:
        if _refresh_in_progress:
            return
        _refresh_in_progress = True
    _refresh_updates()  # clears _refresh_in_progress when done


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
        # Inline ``cached is not None`` (rather than via a ``fresh`` flag) so the
        # type checker narrows ``cached`` to a dict in the return below.
        if cached is not None and (now - _cached_at_monotonic) < _ttl_for(cached):
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


# --- Periodic poll (always-on service) ---------------------------------------
#
# When `mureo configure` runs as a long-lived service (`--serve` / launchd /
# systemd), nothing opens the UI to trigger the lazy check. This poller warms
# the cache on a wide cadence so an operator who opens the dashboard later sees
# an up-to-date badge immediately, without the request ever touching pip.

# Each launch gets its OWN stop event, captured at start and passed into the
# loop, so a stop/start race can never make a new poller exit early or leave an
# old one running (a single module-level event would alias across generations).
_poll_lock = threading.Lock()
_poll_thread: threading.Thread | None = None
_poll_stop: threading.Event | None = None


def _resolve_poll_interval(explicit: float | None) -> float:
    """Interval in seconds: explicit arg → env → default.

    A non-finite env value (``nan`` / ``inf``) is treated as invalid so it can
    never produce a degenerate ``Event.wait()`` timeout.
    """

    if explicit is not None:
        return explicit
    raw = os.environ.get(_POLL_INTERVAL_ENV)
    if raw is None or not raw.strip():
        return _DEFAULT_POLL_INTERVAL_SECONDS
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r; using default %ss",
            _POLL_INTERVAL_ENV,
            raw,
            _DEFAULT_POLL_INTERVAL_SECONDS,
        )
        return _DEFAULT_POLL_INTERVAL_SECONDS
    return value


def _poll_loop(interval: float, stop_event: threading.Event) -> None:
    """Warm the cache now, then once per ``interval`` until ``stop_event``."""

    while True:
        _refresh_if_idle()
        if stop_event.wait(interval):
            return


def start_periodic_update_check(interval_seconds: float | None = None) -> bool:
    """Start the always-on service's background update poll (#244).

    Idempotent — safe to call once per service launch. Returns ``True`` when a
    poller thread was started, ``False`` when polling is disabled
    (``interval <= 0``) or one is already running. Interval resolves from
    ``interval_seconds`` → ``$MUREO_UPDATE_CHECK_INTERVAL_SECONDS`` →
    ``_DEFAULT_POLL_INTERVAL_SECONDS``.
    """

    global _poll_thread, _poll_stop
    interval = _resolve_poll_interval(interval_seconds)
    if interval <= 0:
        logger.info("periodic update check disabled (interval=%s)", interval)
        return False
    with _poll_lock:
        if _poll_thread is not None and _poll_thread.is_alive():
            return False
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_poll_loop,
            args=(interval, stop_event),
            name="mureo-update-poll",
            daemon=True,
        )
        _poll_thread = worker
        _poll_stop = stop_event
    try:
        worker.start()
    except RuntimeError:
        with _poll_lock:
            _poll_thread = None
            _poll_stop = None
        logger.warning("could not start periodic update check")
        return False
    logger.debug("periodic update check started (every %ss)", interval)
    return True


def stop_periodic_update_check() -> None:
    """Stop the background poll (service shutdown). No-op if not running.

    The join is best-effort (the worker may be mid-pip, up to the pip timeout):
    ``daemon=True`` is what actually guarantees no shutdown block, so a slow
    worker is reaped at interpreter exit rather than blocking the caller.
    """

    global _poll_thread, _poll_stop
    with _poll_lock:
        worker = _poll_thread
        stop_event = _poll_stop
        _poll_thread = None
        _poll_stop = None
    if stop_event is not None:
        stop_event.set()
    if worker is not None:
        worker.join(timeout=2.0)


def request_update_refresh() -> dict[str, Any]:
    """Invalidate the cache and kick off a fresh check; return immediately.

    Backs the About tab's "check for updates" button (#246). Drops the cached
    envelope so the next :func:`get_update_status` treats the cache as cold —
    starting a background refresh and returning the ``checking`` placeholder.
    Never blocks on pip; the client polls ``GET /api/updates`` until the status
    settles.

    Best-effort freshness: if a refresh is already in flight when this is
    called, the single-flight gate reuses that run rather than forcing a brand
    new one — the operator still gets a current result, just not a guaranteed
    brand-new pip invocation.
    """

    global _cached_result, _cached_at_monotonic
    with _cache_lock:
        _cached_result = None
        _cached_at_monotonic = 0.0
    return get_update_status()


def _reset_update_cache() -> None:
    """Test-only: stop polling and clear cached state between cases."""

    global _cached_result, _cached_at_monotonic, _refresh_in_progress
    global _refresh_thread
    stop_periodic_update_check()
    with _cache_lock:
        _cached_result = None
        _cached_at_monotonic = 0.0
        _refresh_in_progress = False
        _refresh_thread = None


__all__ = [
    "check_for_updates",
    "get_update_status",
    "request_update_refresh",
    "start_periodic_update_check",
    "stop_periodic_update_check",
]
