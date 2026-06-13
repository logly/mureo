"""Update-availability check for ``mureo.web.version_check``.

``check_for_updates`` shells out to ``python -m pip list --outdated
--format=json`` on ``sys.executable`` and FILTERS the result to mureo /
``mureo-*`` packages (reusing the scope helpers from
``mureo.cli.upgrade_cmd``). Every test patches ``subprocess.run`` at the
module's imported symbol, so nothing here depends on what is actually
installed in the venv running the suite, nor does anything reach the
network.
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


def _outdated_json(*rows: dict[str, Any]) -> str:
    """Serialise ``pip list --outdated --format=json`` rows."""

    return json.dumps(list(rows))


@pytest.mark.unit
class TestCheckForUpdates:
    def test_surfaces_outdated_mureo_packages(self) -> None:
        """An outdated ``mureo-*`` package is reported with installed→latest."""
        payload = _outdated_json(
            {
                "name": "mureo-agency",
                "version": "0.1.0",
                "latest_version": "0.2.0",
                "latest_filetype": "wheel",
            },
        )
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=payload),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is True
        assert result["packages"] == [
            {"name": "mureo-agency", "installed": "0.1.0", "latest": "0.2.0"}
        ]

    def test_filters_out_non_mureo_packages(self) -> None:
        """Outdated packages that are not mureo / mureo-* are dropped."""
        payload = _outdated_json(
            {
                "name": "requests",
                "version": "2.0.0",
                "latest_version": "2.31.0",
                "latest_filetype": "wheel",
            },
            {
                "name": "mureology",  # prefix squatter — must NOT match
                "version": "1.0.0",
                "latest_version": "2.0.0",
                "latest_filetype": "wheel",
            },
            {
                "name": "mureo-logly-bridge",
                "version": "0.3.0",
                "latest_version": "0.4.0",
                "latest_filetype": "wheel",
            },
        )
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=payload),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is True
        names = [pkg["name"] for pkg in result["packages"]]
        assert names == ["mureo-logly-bridge"]

    def test_mureo_itself_outdated_is_included(self) -> None:
        """The ``mureo`` core distribution is included when outdated."""
        payload = _outdated_json(
            {
                "name": "mureo",
                "version": "0.9.31",
                "latest_version": "0.9.32",
                "latest_filetype": "wheel",
            },
        )
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=payload),
        ):
            result = check_for_updates()
        assert result["any_update"] is True
        assert result["packages"] == [
            {"name": "mureo", "installed": "0.9.31", "latest": "0.9.32"}
        ]

    def test_up_to_date_reports_no_update(self) -> None:
        """An empty outdated list → ``ok`` with ``any_update`` false."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout="[]"),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_only_non_mureo_outdated_reports_no_update(self) -> None:
        """When every outdated row is non-mureo, ``any_update`` is false."""
        payload = _outdated_json(
            {
                "name": "pip",
                "version": "23.0",
                "latest_version": "24.0",
                "latest_filetype": "wheel",
            },
        )
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=payload),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_pip_nonzero_exit_degrades_to_error(self) -> None:
        """A non-zero pip exit → ``error`` envelope, no raise, no update."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(returncode=1, stderr="boom"),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_timeout_degrades_to_error(self) -> None:
        """A subprocess timeout must degrade, never propagate."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=60),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_unparseable_json_degrades_to_error(self) -> None:
        """Garbage on stdout must not crash JSON parsing."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout="not json at all"),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_subprocess_oserror_degrades_to_error(self) -> None:
        """A missing interpreter / OS error must degrade, never raise."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            side_effect=OSError("no such executable"),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_non_list_json_payload_degrades_to_error(self) -> None:
        """pip is documented to emit a JSON array; an object is malformed."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout='{"name": "mureo"}'),
        ):
            result = check_for_updates()
        assert result["status"] == "error"
        assert result["any_update"] is False
        assert result["packages"] == []

    def test_malformed_row_is_skipped_not_fatal(self) -> None:
        """A row missing required keys is dropped; valid rows still surface."""
        payload = json.dumps(
            [
                {"name": "mureo-agency"},  # no version / latest_version
                {
                    "name": "mureo-logly-bridge",
                    "version": "0.3.0",
                    "latest_version": "0.4.0",
                    "latest_filetype": "wheel",
                },
            ]
        )
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout=payload),
        ):
            result = check_for_updates()
        assert result["status"] == "ok"
        names = [pkg["name"] for pkg in result["packages"]]
        assert names == ["mureo-logly-bridge"]

    def test_uses_sys_executable_pip_list_outdated_json(self) -> None:
        """The command targets this venv's pip with the JSON outdated flags."""
        with patch(
            "mureo.web.version_check.subprocess.run",
            return_value=_completed(stdout="[]"),
        ) as mock_run:
            check_for_updates()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[1:] == ["-m", "pip", "list", "--outdated", "--format=json"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 60


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


@pytest.mark.unit
class TestPeriodicUpdateCheck:
    """The always-on service's background poll that warms the cache (#244)."""

    _OK: Any = {"status": "ok", "any_update": False, "packages": []}

    def test_interval_resolves_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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
        with patch(
            "mureo.web.version_check.check_for_updates", return_value=self._OK
        ):
            assert start_periodic_update_check(interval_seconds=3600) is True
            assert start_periodic_update_check(interval_seconds=3600) is False
            stop_periodic_update_check()

    def test_stop_is_safe_when_not_running(self) -> None:
        stop_periodic_update_check()  # must not raise
        assert version_check._poll_thread is None

    def test_restart_after_stop_launches_fresh_poller(self) -> None:
        """start → stop → start must work (each launch gets its own event)."""
        with patch(
            "mureo.web.version_check.check_for_updates", return_value=self._OK
        ):
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
