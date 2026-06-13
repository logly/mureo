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
from typing import Any
from unittest.mock import patch

import pytest

from mureo.web.version_check import check_for_updates


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
