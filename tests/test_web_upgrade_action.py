"""Server-side one-click upgrade for ``mureo.web.upgrade_action``.

``run_upgrade_all`` derives its target list ONLY from
``discover_all_mureo_packages`` (server-derived — never from a request
body) and runs ``pip install --upgrade -- <targets>`` on
``sys.executable``, after upgrading pip itself (#910). Each scenario lists
the two ``subprocess.run`` results in order: the pip self-upgrade, then the
package install (the only call with the ``--`` sentinel). Every test patches ``subprocess.run`` and the
package-discovery helper, so nothing here installs anything, mutates the
venv, or reaches the network.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from mureo.web.action_result import ActionResult
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
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=targets,
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=0),
                    _completed(returncode=0, stdout="Successfully installed"),
                ],
            ),
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        assert result["returncode"] == 0
        assert result["packages"] == targets
        assert "Successfully installed" in result["output"]

    def test_nonzero_returncode_fails_and_logs_the_output(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-zero pip exit → ``upgrade_failed`` (HTTP 500, #864); pip's
        output goes to the server log, not the response."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=0),
                    _completed(returncode=1, stderr="Could not find a version"),
                ],
            ),
            caplog.at_level("WARNING", logger="mureo.web.upgrade_action"),
        ):
            result = run_upgrade_all()
        assert result == ActionResult.failed("upgrade_failed", "upgrade_returncode_1")
        assert "Could not find a version" in caplog.text

    def test_killed_pip_names_the_signal(self) -> None:
        """A negative return code (killed by a signal) stays a valid detail."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[_completed(returncode=0), _completed(returncode=-9)],
            ),
        ):
            result = run_upgrade_all()
        assert result == ActionResult.failed("upgrade_failed", "upgrade_signal_9")

    def test_targets_are_server_derived_only(self) -> None:
        """``run_upgrade_all`` takes no package list — discovery is the
        single source of truth (a request body can never reach pip)."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo", "mureo-logly-bridge"],
            ) as mock_discover,
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            result = run_upgrade_all()
        mock_discover.assert_called_once()
        install_cmds = [c.args[0] for c in mock_run.call_args_list if "--" in c.args[0]]
        assert len(install_cmds) == 1
        cmd = install_cmds[0]
        # The pip command's targets come straight from discovery, after the
        # ``--`` sentinel — nothing else can be injected.
        assert cmd[1:6] == ["-m", "pip", "install", "--upgrade", "--"]
        assert cmd[6:] == ["mureo", "mureo-logly-bridge"]
        assert result["packages"] == ["mureo", "mureo-logly-bridge"]
        # Decode pip output as UTF-8, not the locale codec (cp932 on a
        # Japanese Windows) — otherwise the upgrade raises UnicodeDecodeError.
        # Both pip runs (self-upgrade and package install) do this.
        for call in mock_run.call_args_list:
            assert call.kwargs["encoding"] == "utf-8"
            assert call.kwargs["errors"] == "replace"
            # …and force pip itself to ENCODE its stdout as UTF-8 (cp932
            # cannot encode every char pip emits, crashing the child first).
            env = call.kwargs["env"]
            assert env["PYTHONIOENCODING"] == "utf-8:replace"
            assert env["PYTHONUTF8"] == "1"

    def test_output_is_capped(self) -> None:
        """A huge pip output is truncated so the JSON envelope stays small."""
        huge = "x" * 10000
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=0, stdout=huge),
                    _completed(returncode=0, stdout=huge),
                ],
            ),
        ):
            result = run_upgrade_all()
        assert len(result["output"]) <= 4000

    def test_timeout_fails(self) -> None:
        """A pip timeout is ``upgrade_failed``, never a raise."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=0),
                    subprocess.TimeoutExpired(cmd="pip", timeout=600),
                ],
            ),
        ):
            result = run_upgrade_all()
        assert result == ActionResult.failed("upgrade_failed", "TimeoutExpired")

    def test_oserror_fails(self) -> None:
        """A missing interpreter / OS error is ``upgrade_failed``, never a raise."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[_completed(returncode=0), OSError("no such executable")],
            ),
        ):
            result = run_upgrade_all()
        assert result == ActionResult.failed("upgrade_failed", "OSError")

    def test_discovery_failure_is_an_internal_error(self) -> None:
        """If package discovery itself raises, the action fails, never raises."""
        with patch(
            "mureo.web.upgrade_action.discover_all_mureo_packages",
            side_effect=RuntimeError("metadata corrupt"),
        ):
            result = run_upgrade_all()
        assert result == ActionResult.failed("internal_error", "RuntimeError")

    def test_empty_target_list_is_noop_not_pip_call(self) -> None:
        """No mureo packages discovered → never invoke pip with no targets,
        and do not upgrade pip itself either (#910)."""
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
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
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo-agency"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            result = run_upgrade_all()
        assert result["packages"] == ["mureo", "mureo-agency"]
        install_cmds = [c.args[0] for c in mock_run.call_args_list if "--" in c.args[0]]
        assert install_cmds[0][6:] == ["mureo", "mureo-agency"]


_SELF_UPGRADE_CMD = [sys.executable, "-m", "pip", "install", "--upgrade", "pip"]


@pytest.mark.unit
class TestPipSelfUpgrade:
    """pip itself is upgraded before the packages (#910): pip < 26.2.2
    reads its own bundled certifi regardless of the OS trust store."""

    def test_self_upgrade_runs_before_package_install(self) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        assert [c.args[0] for c in mock_run.call_args_list] == [
            _SELF_UPGRADE_CMD,
            [sys.executable, "-m", "pip", "install", "--upgrade", "--", "mureo"],
        ]

    def test_failed_self_upgrade_still_installs_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[_completed(returncode=1), _completed(returncode=0)],
            ) as mock_run,
            caplog.at_level("WARNING", logger="mureo.web.upgrade_action"),
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        # returncode is the package install's, not the self-upgrade's.
        assert result["returncode"] == 0
        assert "--" in mock_run.call_args_list[1].args[0]
        assert "pip self-upgrade failed (1)" in caplog.text

    def test_self_upgrade_oserror_still_installs_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[OSError("no such executable"), _completed(returncode=0)],
            ) as mock_run,
            caplog.at_level("WARNING", logger="mureo.web.upgrade_action"),
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        assert result["returncode"] == 0
        assert "--" in mock_run.call_args_list[1].args[0]
        assert "pip self-upgrade failed (OSError)" in caplog.text

    def test_output_includes_the_self_upgrade_tail(self) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=0, stdout="Successfully installed pip"),
                    _completed(returncode=0, stdout="Successfully installed mureo"),
                ],
            ),
        ):
            result = run_upgrade_all()
        assert "Successfully installed pip" in result["output"]
        assert result["output"].endswith("Successfully installed mureo")

    def test_self_upgrade_timeout_still_installs_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    subprocess.TimeoutExpired(cmd="pip", timeout=120),
                    _completed(returncode=0),
                ],
            ) as mock_run,
            caplog.at_level("WARNING", logger="mureo.web.upgrade_action"),
        ):
            result = run_upgrade_all()
        assert result["status"] == "ok"
        assert result["returncode"] == 0
        assert "--" in mock_run.call_args_list[1].args[0]
        assert "pip self-upgrade failed (TimeoutExpired)" in caplog.text

    def test_self_upgrade_has_its_own_shorter_timeout(self) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                return_value=_completed(returncode=0),
            ) as mock_run,
        ):
            run_upgrade_all()
        self_call, install_call = mock_run.call_args_list
        assert self_call.kwargs["timeout"] == 120
        assert install_call.kwargs["timeout"] == 600

    def test_failed_self_upgrade_logs_its_output_tail(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(
                "mureo.web.upgrade_action.discover_all_mureo_packages",
                return_value=["mureo"],
            ),
            patch(
                "mureo.web.upgrade_action.subprocess.run",
                side_effect=[
                    _completed(returncode=1, stderr="SSL: CERTIFICATE_VERIFY_FAILED"),
                    _completed(returncode=0),
                ],
            ),
            caplog.at_level("WARNING", logger="mureo.web.upgrade_action"),
        ):
            run_upgrade_all()
        assert "SSL: CERTIFICATE_VERIFY_FAILED" in caplog.text
