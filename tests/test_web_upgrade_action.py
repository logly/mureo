"""Server-side one-click upgrade for ``mureo.web.upgrade_action``.

``run_upgrade_all`` derives its target list ONLY from
``_discover_all_mureo_packages`` (server-derived — never from a request
body) and runs ``pip install --upgrade -- <targets>`` on
``sys.executable``. Every test patches ``subprocess.run`` and the
package-discovery helper, so nothing here installs anything, mutates the
venv, or reaches the network.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from mureo.web.upgrade_action import run_upgrade_all


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a ``CompletedProcess`` stand-in for ``subprocess.run``."""

    return subprocess.CompletedProcess(
        args=["pip"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.mark.unit
class TestRunUpgradeAll:
    def test_success_returncode_zero_reports_ok(self) -> None:
        """A zero pip exit → ``ok`` with the server-derived target list."""
        targets = ["mureo", "mureo-agency"]
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=targets,
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0, stdout="Successfully installed"),
            ),
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        assert result["returncode"] == 0
        assert result["packages"] == targets
        assert "Successfully installed" in result["output"]

    def test_nonzero_returncode_reports_error_with_output(self) -> None:
        """A non-zero pip exit → ``error`` carrying the captured output."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(
                    returncode=1, stderr="Could not find a version"
                ),
            ),
        ):
            result = run_upgrade_all()
        assert result["status"] == "error"
        assert result["returncode"] == 1
        assert "Could not find a version" in result["output"]

    def test_targets_are_server_derived_only(self) -> None:
        """``run_upgrade_all`` takes no package list — discovery is the
        single source of truth (a request body can never reach pip)."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo", "mureo-logly-bridge"],
            ) as mock_discover,
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            result = run_upgrade_all()
        mock_discover.assert_called_once()
        cmd = mock_run.call_args.args[0]
        # The pip command's targets come straight from discovery, after the
        # ``--`` sentinel — nothing else can be injected.
        assert cmd[1:6] == ["-m", "pip", "install", "--upgrade", "--"]
        assert cmd[6:] == ["mureo", "mureo-logly-bridge"]
        assert result["packages"] == ["mureo", "mureo-logly-bridge"]
        # Decode pip output as UTF-8, not the locale codec (cp932 on a
        # Japanese Windows) — otherwise the upgrade raises UnicodeDecodeError.
        assert mock_run.call_args.kwargs["encoding"] == "utf-8"
        assert mock_run.call_args.kwargs["errors"] == "replace"
        # …and force pip itself to ENCODE its stdout as UTF-8 (cp932 cannot
        # encode every char pip emits, crashing the child before we decode).
        env = mock_run.call_args.kwargs["env"]
        assert env["PYTHONIOENCODING"] == "utf-8:replace"
        assert env["PYTHONUTF8"] == "1"

    def test_output_is_capped(self) -> None:
        """A huge pip output is truncated so the JSON envelope stays small."""
        huge = "x" * 10000
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0, stdout=huge),
            ),
        ):
            result = run_upgrade_all()
        assert len(result["output"]) <= 4000

    def test_timeout_degrades_to_error(self) -> None:
        """A pip timeout must degrade to an error envelope, never raise."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=600),
            ),
        ):
            result = run_upgrade_all()
        assert result["status"] == "error"
        assert result["packages"] == ["mureo"]

    def test_oserror_degrades_to_error(self) -> None:
        """A missing interpreter / OS error must degrade, never raise."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=OSError("no such executable"),
            ),
        ):
            result = run_upgrade_all()
        assert result["status"] == "error"

    def test_discovery_failure_degrades_to_error(self) -> None:
        """If package discovery itself raises, the action still degrades."""
        with patch(
            "mureo.web.upgrade_action._discover_all_mureo_packages",
            side_effect=RuntimeError("metadata corrupt"),
        ):
            result = run_upgrade_all()
        assert result["status"] == "error"
        assert result["packages"] == []

    def test_empty_target_list_is_noop_not_pip_call(self) -> None:
        """No mureo packages discovered → never invoke pip with no targets."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=[],
            ),
            patch("mureo.web.upgrade_action.subprocess.run") as mock_run,
        ):
            result = run_upgrade_all()
        mock_run.assert_not_called()
        assert result["status"] == "noop"
        assert result["packages"] == []

    def test_mureo_force_prepended_when_discovery_hides_it(self) -> None:
        """Belt-and-braces parity with the CLI: when discovery returns
        only plugins (mureo's own dist-info hidden, e.g. an editable
        install), ``mureo`` is still upgraded — prepended ahead of them."""
        with (
            patch(
                "mureo.web.upgrade_action._discover_all_mureo_packages",
                return_value=["mureo-agency"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            result = run_upgrade_all()
        assert result["packages"] == ["mureo", "mureo-agency"]
        assert mock_run.call_args.args[0][6:] == ["mureo", "mureo-agency"]
