"""Update-availability check for ``mureo.web.version_check``.

``check_for_updates`` discovers the installed mureo / ``mureo-*``
distributions locally, then runs a SCOPED ``pip install --dry-run
--upgrade --no-deps --report -`` over just those packages and maps the
report's ``install`` list to the API envelope. The mapping tests patch
``_installed_mureo_versions`` and ``_run_pip_report``; the subprocess
fault-isolation tests patch ``subprocess.run``. Either way nothing here
depends on what is actually installed in the venv, nor reaches the network.
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any
from unittest.mock import patch

import pytest

from mureo.web import version_check
from mureo.web.version_check import (
    _reset_update_cache,
    check_for_updates,
    get_update_status,
    request_update_refresh,
    start_periodic_update_check,
    stop_periodic_update_check,
)


@pytest.fixture(autouse=True)
def _clean_update_cache() -> Any:
    """Each case starts and ends with a cold module-level cache."""

    _reset_update_cache()
    yield
    _reset_update_cache()


def _join_refresh(timeout: float = 5.0) -> None:
    """Block until the in-flight background refresh (if any) finishes."""

    thread = version_check._refresh_thread
    if thread is not None:
        thread.join(timeout)


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a ``CompletedProcess`` stand-in for ``subprocess.run``."""

    return subprocess.CompletedProcess(
        args=["pip"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _report(*entries: dict[str, str]) -> dict[str, Any]:
    """Build a ``pip install --report`` dict whose ``install`` list carries the
    given ``{name, version}`` metadata entries (``version`` = the latest pip
    would install)."""

    return {
        "version": "1",
        "install": [
            {"metadata": {"name": e["name"], "version": e["version"]}} for e in entries
        ],
    }


@pytest.mark.unit
class TestCheckForUpdates:
    """``check_for_updates`` maps pip's scoped report to the API envelope.

    The pure mapping is exercised by mocking ``_installed_mureo_versions``
    (the local metadata snapshot) and ``_run_pip_report`` (the scoped pip
    call). Subprocess-level fault isolation lives in ``TestRunPipReport``.
    """

    def test_surfaces_outdated_mureo_packages(self) -> None:
        """An outdated ``mureo-*`` package is reported with installed→latest."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo-agency": "0.1.0"},
            ),
            patch(
                "mureo.web.version_check._run_pip_report",
                return_value=_report({"name": "mureo-agency", "version": "0.2.0"}),
            ),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is True
        assert result["packages"] == [
            {"name": "mureo-agency", "installed": "0.1.0", "latest": "0.2.0"}
        ]

    def test_scopes_query_to_installed_mureo_packages(self) -> None:
        """The pip call is scoped to the installed mureo packages (sorted) —
        the whole point of the fix vs. ``pip list --outdated`` over the venv."""
        captured: dict[str, Any] = {}

        def _capture(packages: list[str]) -> dict[str, Any]:
            captured["packages"] = packages
            return _report()

        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo-agency": "0.1.0", "mureo": "0.10.0"},
            ),
            patch("mureo.web.version_check._run_pip_report", side_effect=_capture),
        ):
            check_for_updates()
        assert captured["packages"] == ["mureo", "mureo-agency"]

    def test_filters_out_non_mureo_packages(self) -> None:
        """Report entries that are not mureo / mureo-* are dropped."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo-logly-bridge": "0.3.0"},
            ),
            patch(
                "mureo.web.version_check._run_pip_report",
                return_value=_report(
                    {"name": "requests", "version": "2.31.0"},
                    {"name": "mureology", "version": "2.0.0"},  # prefix squatter
                    {"name": "mureo-logly-bridge", "version": "0.4.0"},
                ),
            ),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is True
        names = [pkg["name"] for pkg in result["packages"]]
        assert names == ["mureo-logly-bridge"]

    def test_mureo_itself_outdated_is_included(self) -> None:
        """The ``mureo`` core distribution is included when outdated."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo": "0.9.31"},
            ),
            patch(
                "mureo.web.version_check._run_pip_report",
                return_value=_report({"name": "mureo", "version": "0.9.32"}),
            ),
        ):
            result = check_for_updates()
        assert result["any_update"] is True
        assert result["packages"] == [
            {"name": "mureo", "installed": "0.9.31", "latest": "0.9.32"}
        ]

    def test_up_to_date_reports_no_update(self) -> None:
        """An empty ``install`` list → ``ok`` with ``any_update`` false."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo": "0.10.0"},
            ),
            patch("mureo.web.version_check._run_pip_report", return_value=_report()),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_no_mureo_installed_reports_no_update_without_pip(self) -> None:
        """No resolvable mureo distribution → ``ok`` empty, and pip is never run."""
        with (
            patch("mureo.web.version_check._installed_mureo_versions", return_value={}),
            patch("mureo.web.version_check._run_pip_report") as mock_report,
        ):
            result = check_for_updates()
        assert result == {"status": "ok", "any_update": False, "packages": []}
        mock_report.assert_not_called()

    def test_pip_failure_degrades_to_error(self) -> None:
        """When the scoped pip call fails (``None``), degrade to ``error``."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo": "0.10.0"},
            ),
            patch("mureo.web.version_check._run_pip_report", return_value=None),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_malformed_entry_is_skipped_not_fatal(self) -> None:
        """An ``install`` entry missing metadata is dropped; valid ones surface."""
        report = {
            "version": "1",
            "install": [
                {"metadata": {"name": "mureo-agency"}},  # no version
                {"foo": "bar"},  # no metadata at all
                {"metadata": {"name": "mureo-logly-bridge", "version": "0.4.0"}},
            ],
        }
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo-agency": "0.1.0", "mureo-logly-bridge": "0.3.0"},
            ),
            patch("mureo.web.version_check._run_pip_report", return_value=report),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        names = [pkg["name"] for pkg in result["packages"]]
        assert names == ["mureo-logly-bridge"]

    def test_constraint_pinned_downgrade_is_not_an_update(self) -> None:
        """``--upgrade`` can list a DOWNGRADE target when a pip constraint pins
        the package below what is installed; that is NOT an available update."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo": "0.10.0"},
            ),
            patch(
                "mureo.web.version_check._run_pip_report",
                return_value=_report({"name": "mureo", "version": "0.9.0"}),
            ),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_unparseable_index_version_is_dropped(self) -> None:
        """A non-PEP 440 ``latest`` is dropped, never shown as a dubious update."""
        with (
            patch(
                "mureo.web.version_check._installed_mureo_versions",
                return_value={"mureo-agency": "0.1.0"},
            ),
            patch(
                "mureo.web.version_check._run_pip_report",
                return_value=_report(
                    {"name": "mureo-agency", "version": "not-a-version"}
                ),
            ),
        ):
            result = check_for_updates()
        assert result["any_update"] is False
        assert result["packages"] == []


@pytest.mark.unit
class TestRunPipReport:
    """Subprocess-level fault isolation and command shape of the scoped query."""

    def test_success_returns_report_dict(self) -> None:
        report_json = json.dumps({"version": "1", "install": []})
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=report_json),
        ):
            assert version_check._run_pip_report(["mureo"]) == {
                "version": "1",
                "install": [],
            }

    def test_command_is_scoped_dry_run_for_given_packages(self) -> None:
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout='{"install": []}'),
        ) as mock_run:
            version_check._run_pip_report(["mureo", "mureo-agency"])
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[1:10] == [
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--upgrade",
            "--no-deps",
            "--quiet",
            "--report",
            "-",
        ]
        # Packages follow the ``--`` sentinel so a name can never be read as a flag.
        assert cmd[-3:] == ["--", "mureo", "mureo-agency"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 60
        # Decode pip output as UTF-8 explicitly — NOT the locale codec (cp932
        # on a Japanese Windows), which would raise UnicodeDecodeError and kill
        # the update check on Windows.
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        # …and force the CHILD (pip) to ENCODE its stdout as UTF-8 too, or pip
        # crashes on a non-cp932 char in its rich --report JSON before any
        # output reaches us. The env must carry the whole environment plus the
        # two UTF-8 switches.
        env = kwargs["env"]
        assert env["PYTHONIOENCODING"] == "utf-8:replace"
        assert env["PYTHONUTF8"] == "1"
        assert "PATH" in env  # a copy of os.environ, not a 2-key dict

    def test_nonzero_exit_returns_none(self) -> None:
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ):
            assert version_check._run_pip_report(["mureo"]) is None

    def test_timeout_returns_none(self) -> None:
        with patch(
            "mureo.web.version_check.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=60),
        ):
            assert version_check._run_pip_report(["mureo"]) is None

    def test_oserror_returns_none(self) -> None:
        with patch(
            "mureo.web.version_check.subprocess.run",
            side_effect=OSError("no such executable"),
        ):
            assert version_check._run_pip_report(["mureo"]) is None

    def test_unparseable_json_returns_none(self) -> None:
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout="not json at all"),
        ):
            assert version_check._run_pip_report(["mureo"]) is None

    def test_non_object_json_returns_none(self) -> None:
        """pip's report is a JSON object; a bare array is malformed."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout="[]"),
        ):
            assert version_check._run_pip_report(["mureo"]) is None


@pytest.mark.unit
class TestGetUpdateStatus:
    """The non-blocking cache layer the HTTP handler actually calls."""

    def test_cold_cache_returns_checking_without_blocking(self) -> None:
        """First call returns the ``checking`` placeholder immediately."""
        with patch(
            "mureo.web.version_check.check_for_updates",
            return_value={"status": "ok", "any_update": False, "packages": []},
        ):
            first = get_update_status()
            assert first["status"] == "checking"
            assert first["any_update"] is False
            assert first["packages"] == []
            _join_refresh()

    def test_background_result_is_cached_and_served(self) -> None:
        """Once the background check finishes, its result is returned."""
        payload = {
            "status": "ok",
            "any_update": True,
            "packages": [{"name": "mureo", "installed": "0.9.31", "latest": "0.9.32"}],
        }
        with patch(
            "mureo.web.version_check.check_for_updates", return_value=payload
        ) as mock_check:
            assert get_update_status()["status"] == "checking"
            _join_refresh()
            second = get_update_status()
        assert second == payload
        # Fresh cache → the slow check ran exactly once, not per request.
        mock_check.assert_called_once()

    def test_handler_never_runs_pip_inline(self) -> None:
        """The accessor must not call the blocking check on the caller's thread."""
        slow_calls: list[str] = []

        def _slow() -> dict[str, Any]:
            slow_calls.append("ran")
            return {"status": "ok", "any_update": False, "packages": []}

        with patch("mureo.web.version_check.check_for_updates", side_effect=_slow):
            result = get_update_status()
            # Returned before the background worker necessarily ran.
            assert result["status"] == "checking"
            _join_refresh()
        assert slow_calls == ["ran"]

    def test_error_result_is_cached_with_short_ttl(self) -> None:
        """A degraded check is cached (so it is not retried every request)."""
        with patch(
            "mureo.web.version_check.check_for_updates",
            return_value={"status": "error", "any_update": False, "packages": []},
        ) as mock_check:
            assert get_update_status()["status"] == "checking"
            _join_refresh()
            assert get_update_status()["status"] == "error"
            get_update_status()  # still within the error TTL
        mock_check.assert_called_once()

    def test_stale_cache_triggers_one_background_refresh(self) -> None:
        """An expired cache serves the stale result and refreshes once."""
        payload = {"status": "ok", "any_update": False, "packages": []}
        with patch(
            "mureo.web.version_check.check_for_updates", return_value=payload
        ) as mock_check:
            get_update_status()
            _join_refresh()
            assert get_update_status() == payload  # warm, fresh

            # Force the cache to look stale, then assert exactly one refresh.
            with version_check._cache_lock:
                version_check._cached_at_monotonic -= version_check._OK_TTL_SECONDS + 1
            served = get_update_status()
            assert served == payload  # last-known served while refreshing
            _join_refresh()
        assert mock_check.call_count == 2

    def test_concurrent_callers_spawn_one_worker(self) -> None:
        """Two simultaneous requests must trigger only one pip run (#244).

        This is the exact bug the cache exists to prevent: the configure UI
        fetches ``/api/updates`` more than once per page load, and the old
        synchronous handler spawned a 60s pip process for each.
        """
        import threading

        release = threading.Event()
        calls: list[str] = []

        def _blocked() -> dict[str, Any]:
            calls.append("ran")
            release.wait(5.0)  # hold the worker so the 2nd caller overlaps it
            return {"status": "ok", "any_update": False, "packages": []}

        with patch("mureo.web.version_check.check_for_updates", side_effect=_blocked):
            # 1st caller flips _refresh_in_progress (under the lock) before the
            # worker even starts, so the 2nd caller is gated regardless of timing.
            assert get_update_status()["status"] == "checking"
            assert get_update_status()["status"] == "checking"
            release.set()
            _join_refresh()
        assert calls == ["ran"]  # single-flight held: exactly one pip run

    def test_request_update_refresh_drops_cache_and_rechecks(self) -> None:
        """The "check now" button invalidates the cache and runs pip again."""
        payload = {"status": "ok", "any_update": False, "packages": []}
        with patch(
            "mureo.web.version_check.check_for_updates", return_value=payload
        ) as mock_check:
            get_update_status()  # warm
            _join_refresh()
            assert get_update_status() == payload  # fresh cache, no recheck
            # Force: drop the cache, return checking, trigger a fresh check.
            assert request_update_refresh()["status"] == "checking"
            _join_refresh()
            assert get_update_status() == payload
        # One warm + one forced recheck = two pip runs; the fresh-cache read in
        # between must NOT have re-run it.
        assert mock_check.call_count == 2


@pytest.mark.unit
class TestPeriodicUpdateCheck:
    """The always-on service's background poll that warms the cache (#244)."""

    _OK: Any = {"status": "ok", "any_update": False, "packages": []}

    def test_interval_resolves_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "120")
        assert version_check._resolve_poll_interval(None) == 120.0

    def test_explicit_interval_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "120")
        assert version_check._resolve_poll_interval(30) == 30.0

    def test_invalid_env_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "not-a-number")
        assert (
            version_check._resolve_poll_interval(None)
            == version_check._DEFAULT_POLL_INTERVAL_SECONDS
        )

    def test_unset_env_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", raising=False)
        assert (
            version_check._resolve_poll_interval(None)
            == version_check._DEFAULT_POLL_INTERVAL_SECONDS
        )

    def test_zero_interval_disables_polling(self) -> None:
        """``interval <= 0`` is the documented "off" switch."""
        assert start_periodic_update_check(interval_seconds=0) is False
        assert version_check._poll_thread is None

    def test_env_zero_disables_polling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MUREO_UPDATE_CHECK_INTERVAL_SECONDS", "0")
        assert start_periodic_update_check() is False
        assert version_check._poll_thread is None

    def test_start_warms_cache_immediately(self) -> None:
        """The poll runs once on start so the UI shows fresh data right away."""
        ran = threading.Event()
        payload = {
            "status": "ok",
            "any_update": True,
            "packages": [{"name": "mureo", "installed": "0.9.31", "latest": "0.9.32"}],
        }

        def _check() -> dict[str, Any]:
            ran.set()
            return payload

        with patch("mureo.web.version_check.check_for_updates", side_effect=_check):
            assert start_periodic_update_check(interval_seconds=3600) is True
            assert ran.wait(5.0)
            # stop() joins the worker, so the immediate refresh has stored its
            # result by the time it returns.
            stop_periodic_update_check()
            assert get_update_status() == payload

    def test_start_is_idempotent(self) -> None:
        """A second start while one runs is a no-op (single-instance reuse)."""
        with patch("mureo.web.version_check.check_for_updates", return_value=self._OK):
            assert start_periodic_update_check(interval_seconds=3600) is True
            assert start_periodic_update_check(interval_seconds=3600) is False
            stop_periodic_update_check()

    def test_stop_is_safe_when_not_running(self) -> None:
        stop_periodic_update_check()  # must not raise
        assert version_check._poll_thread is None

    def test_restart_after_stop_launches_fresh_poller(self) -> None:
        """start → stop → start must work (each launch gets its own event)."""
        with patch("mureo.web.version_check.check_for_updates", return_value=self._OK):
            assert start_periodic_update_check(interval_seconds=3600) is True
            stop_periodic_update_check()
            assert version_check._poll_thread is None
            # A clean stop must not wedge the next launch.
            assert start_periodic_update_check(interval_seconds=3600) is True
            stop_periodic_update_check()

    def test_refresh_if_idle_skips_when_a_refresh_is_in_flight(self) -> None:
        """The poll tick yields to an in-flight lazy refresh (no double run)."""
        calls: list[int] = []
        with version_check._cache_lock:
            version_check._refresh_in_progress = True
        try:
            with patch(
                "mureo.web.version_check.check_for_updates",
                side_effect=lambda: calls.append(1) or self._OK,
            ):
                version_check._refresh_if_idle()
            assert calls == []
        finally:
            with version_check._cache_lock:
                version_check._refresh_in_progress = False
