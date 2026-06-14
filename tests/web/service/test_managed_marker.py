"""The managed-service marker: env-gated supervised detection.

``mureo service install`` stamps ``MUREO_MANAGED_SERVICE=1`` into the launchd
plist / systemd unit so the running daemon knows a supervisor (launchd
``KeepAlive`` / systemd ``Restart=always``) will relaunch it, and may
exit-to-restart after a self-upgrade. Windows is deliberately excluded — Task
Scheduler does not relaunch a task that exits cleanly, so the marker is absent
there and the daemon keeps the manual "restart" prompt.
"""

from __future__ import annotations

import pytest

from mureo.web.service import MANAGED_SERVICE_ENV, is_managed_service, windows


@pytest.mark.unit
class TestIsManagedService:
    def test_true_when_exactly_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MANAGED_SERVICE_ENV, "1")
        assert is_managed_service() is True

    @pytest.mark.parametrize("value", ["0", "true", "yes", "", "TRUE", "1 "])
    def test_false_for_other_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """Strict ``== "1"`` — a false positive would exit a server that no
        supervisor brings back, so anything but the exact marker is False."""
        monkeypatch.setenv(MANAGED_SERVICE_ENV, value)
        assert is_managed_service() is False

    def test_false_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(MANAGED_SERVICE_ENV, raising=False)
        assert is_managed_service() is False


@pytest.mark.unit
class TestWindowsHasNoMarker:
    def test_task_command_omits_managed_marker(self) -> None:
        """Task Scheduler does not relaunch a clean exit, so the marker must
        NOT reach Windows — auto-restart would otherwise leave the server dead.
        """
        assert MANAGED_SERVICE_ENV not in windows.task_run_command(port=7613)
