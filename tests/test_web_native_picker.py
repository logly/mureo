"""Tests for ``mureo.web.native_picker`` (OS-aware native picker).

The module exposes:

- ``PickResult`` — a ``@dataclass(frozen=True)`` envelope:
  ``status`` ("ok" | "cancelled" | "error"), ``path`` (str | None),
  ``detail`` (str | None), plus an ``as_dict()`` JSON projection.
- ``pick_directory(title) -> PickResult`` / ``pick_file(title, patterns)
  -> PickResult``.

OS-aware contract:

- **non-darwin** (Windows / Linux): spawns a short-lived
  ``sys.executable -c <const tkinter script>`` subprocess. argv is the
  FIXED list ``[sys.executable, "-c", _SCRIPT, mode, title, *patterns]``;
  the client ``title`` only appears as a trailing argv element, never
  shell-interpolated. stdout -> ``ok``; empty -> ``cancelled``;
  nonzero / FileNotFoundError / TimeoutExpired / tkinter-unavailable ->
  ``error``.
- **darwin** (macOS): shells out to ``osascript -e <CONST applescript>``
  (``choose folder`` / ``choose file``). The AppleScript body is a module
  constant with a baked-in prompt — the client ``title`` is IGNORED and
  never interpolated (zero AppleScript/shell injection). osascript exit
  ``-128`` / "User canceled" -> ``cancelled``; missing osascript
  (FileNotFoundError) / other nonzero -> ``error``.

``subprocess.run`` is fully mocked — NO real subprocess, NO real Tk
window, NO real osascript / Finder dialog is ever created.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.web import native_picker  # noqa: E402


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a fake ``CompletedProcess`` as ``subprocess.run`` returns."""
    return subprocess.CompletedProcess(
        args=["python", "-c", "<script>"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _d(result: Any) -> dict[str, Any]:
    return result.as_dict() if hasattr(result, "as_dict") else result


@pytest.fixture
def non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the non-darwin (tkinter subprocess) branch."""
    monkeypatch.setattr(native_picker.sys, "platform", "linux")


@pytest.fixture
def darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the darwin (osascript) branch."""
    monkeypatch.setattr(native_picker.sys, "platform", "darwin")


# ---------------------------------------------------------------------------
# PickResult — frozen result envelope (platform independent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPickResult:
    def test_is_frozen_dataclass(self) -> None:
        assert dataclasses.is_dataclass(native_picker.PickResult)
        params = native_picker.PickResult.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen is True

    def test_mutation_raises_frozen_instance_error(self) -> None:
        result = native_picker.PickResult(status="ok", path="/abs/x", detail=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = "error"  # type: ignore[misc]

    def test_as_dict_ok_shape(self) -> None:
        result = native_picker.PickResult(status="ok", path="/abs/dir", detail=None)
        assert _d(result)["status"] == "ok"
        assert _d(result)["path"] == "/abs/dir"

    def test_as_dict_cancelled_path_is_none(self) -> None:
        result = native_picker.PickResult(status="cancelled", path=None, detail=None)
        body = _d(result)
        assert body["status"] == "cancelled"
        assert body.get("path") is None


# ---------------------------------------------------------------------------
# Non-darwin (tkinter subprocess) — happy / cancelled / error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("non_darwin")
class TestPickDirectoryNonDarwin:
    def test_ok_returns_path_from_stdout(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="/Users/me/projects/demo\n"),
        ):
            result = native_picker.pick_directory(title="Pick a folder")
        assert result.status == "ok"
        assert result.path == "/Users/me/projects/demo"

    def test_empty_stdout_is_cancelled(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="\n"),
        ):
            result = native_picker.pick_directory(title="Pick a folder")
        assert result.status == "cancelled"
        assert result.path is None

    def test_blank_only_stdout_is_cancelled(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="   \n  "),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "cancelled"
        assert result.path is None

    def test_nonzero_returncode_is_error(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(returncode=1, stdout="", stderr="boom"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"

    def test_tkinter_unavailable_detail(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(
                returncode=1, stdout="", stderr="tkinter_unavailable"
            ),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"
        assert result.detail == "tkinter_unavailable"

    def test_file_not_found_is_error(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=FileNotFoundError("python missing"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"
        assert result.detail is not None

    def test_timeout_expired_is_error_with_detail(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="python", timeout=300),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"
        assert result.detail is not None

    def test_unexpected_exception_is_error_not_raised(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=RuntimeError("kaboom"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"


@pytest.mark.unit
@pytest.mark.usefixtures("non_darwin")
class TestPickFileNonDarwin:
    def test_ok_returns_path(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="/Users/me/data/bundle.xlsx\n"),
        ):
            result = native_picker.pick_file(
                title="Pick xlsx", patterns=("*.xlsx", "*.xlsm")
            )
        assert result.status == "ok"
        assert result.path == "/Users/me/data/bundle.xlsx"

    def test_cancel_returns_cancelled(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout=""),
        ):
            result = native_picker.pick_file(
                title="Pick xlsx", patterns=("*.xlsx", "*.xlsm")
            )
        assert result.status == "cancelled"
        assert result.path is None

    def test_patterns_passed_to_child_argv(self) -> None:
        """The xlsx/xlsm filter must reach the subprocess as argv data,
        never shell-interpolated."""
        mock_run = MagicMock(return_value=_completed(stdout="/a/b.xlsx"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_file(title="Pick xlsx", patterns=("*.xlsx", "*.xlsm"))
        argv = mock_run.call_args.args[0]
        flat = " ".join(str(a) for a in argv)
        assert "*.xlsx" in flat
        assert "*.xlsm" in flat


# ---------------------------------------------------------------------------
# Non-darwin subprocess argv / kwargs shape — injection-resistance
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("non_darwin")
class TestSubprocessInvocationShapeNonDarwin:
    def test_argv0_is_sys_executable(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        argv = mock_run.call_args.args[0]
        assert argv[0] == sys.executable

    def test_uses_dash_c_inline_script(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        argv = mock_run.call_args.args[0]
        assert "-c" in argv

    def test_script_argument_is_a_constant_string(self) -> None:
        """The ``-c`` payload must be identical regardless of the
        client-supplied title (no per-call interpolation)."""
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="alpha")
            native_picker.pick_directory(title="beta-DIFFERENT")
        first_argv = mock_run.call_args_list[0].args[0]
        second_argv = mock_run.call_args_list[1].args[0]
        first_script = first_argv[first_argv.index("-c") + 1]
        second_script = second_argv[second_argv.index("-c") + 1]
        assert first_script == second_script
        assert isinstance(first_script, str)

    def test_title_only_appears_as_argv_element_never_in_script(self) -> None:
        """A title carrying shell metacharacters must never be
        concatenated into the script string; it may only appear as a
        discrete trailing argv element."""
        evil = "; rm -rf / #$(whoami)`id`"
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title=evil)
        argv = mock_run.call_args.args[0]
        script = argv[argv.index("-c") + 1]
        assert evil not in script
        assert evil in argv

    def test_shell_is_false_or_absent(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("shell", False) is False

    def test_timeout_kwarg_is_passed(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        kwargs = mock_run.call_args.kwargs
        assert "timeout" in kwargs
        assert isinstance(kwargs["timeout"], (int, float))
        assert kwargs["timeout"] > 0

    def test_argv_is_a_list_not_a_string(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_file(title="t", patterns=("*.xlsx",))
        argv = mock_run.call_args.args[0]
        assert isinstance(argv, (list, tuple))
        assert not isinstance(argv, str)

    def test_stdout_is_captured(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        kwargs = mock_run.call_args.kwargs
        captured = kwargs.get("capture_output") is True or (
            kwargs.get("stdout") is subprocess.PIPE
        )
        assert captured


# ---------------------------------------------------------------------------
# darwin (osascript) — happy / cancel / error + injection-resistance
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("darwin")
class TestPickerMacOS:
    def test_directory_ok_returns_path(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="/Users/me/projects/demo\n"),
        ):
            result = native_picker.pick_directory(title="ignored")
        assert result.status == "ok"
        assert result.path == "/Users/me/projects/demo"

    def test_file_ok_returns_path(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout="/Users/me/data/bundle.xlsx\n"),
        ):
            result = native_picker.pick_file(
                title="ignored", patterns=("*.xlsx", "*.xlsm")
            )
        assert result.status == "ok"
        assert result.path == "/Users/me/data/bundle.xlsx"

    def test_empty_stdout_is_cancelled(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(stdout=""),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "cancelled"
        assert result.path is None

    def test_user_cancel_minus_128_is_cancelled_not_error(self) -> None:
        """osascript exits non-zero (-128) with "User canceled" on
        stderr when the user dismisses the Finder dialog."""
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(
                returncode=1,
                stdout="",
                stderr="execution error: User canceled. (-128)",
            ),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "cancelled"
        assert result.path is None

    def test_other_nonzero_is_error(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            return_value=_completed(
                returncode=1, stdout="", stderr="some other osa failure"
            ),
        ):
            result = native_picker.pick_file(title="t", patterns=("*.xlsx",))
        assert result.status == "error"

    def test_missing_osascript_is_error_not_raised(self) -> None:
        """osascript not on PATH -> FileNotFoundError -> graceful error
        envelope (UI falls back to manual entry); never raises."""
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=FileNotFoundError("osascript missing"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"
        assert result.detail is not None

    def test_timeout_is_error(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=300),
        ):
            result = native_picker.pick_file(title="t", patterns=("*.xlsx",))
        assert result.status == "error"

    def test_unexpected_exception_is_error_not_raised(self) -> None:
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=RuntimeError("kaboom"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"


@pytest.mark.unit
@pytest.mark.usefixtures("darwin")
class TestMacOSInvocationShapeAndInjection:
    def test_argv0_is_osascript(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        argv = mock_run.call_args.args[0]
        assert argv[0].endswith("osascript")
        assert "-e" in argv

    def test_shell_false_and_timeout_and_capture(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_file(title="t", patterns=("*.xlsx",))
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("shell", False) is False
        assert isinstance(kwargs.get("timeout"), (int, float))
        assert kwargs["timeout"] > 0
        assert kwargs.get("capture_output") is True

    def test_argv_is_a_list_not_a_string(self) -> None:
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        argv = mock_run.call_args.args[0]
        assert isinstance(argv, (list, tuple))
        assert not isinstance(argv, str)

    def test_applescript_body_is_constant_regardless_of_title(self) -> None:
        """The osascript ``-e`` payload must be byte-identical no matter
        what the client title is (zero per-call interpolation)."""
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="alpha")
            native_picker.pick_directory(title="beta-DIFFERENT")
        first = mock_run.call_args_list[0].args[0]
        second = mock_run.call_args_list[1].args[0]
        first_script = first[first.index("-e") + 1]
        second_script = second[second.index("-e") + 1]
        assert first_script == second_script
        assert isinstance(first_script, str)

    def test_hostile_title_never_reaches_applescript_or_argv(self) -> None:
        """A title crafted to break out of an AppleScript string and run
        a shell command must NOT appear anywhere in the osascript argv
        (the client title is ignored entirely on darwin)."""
        evil = '" & (do shell script "id") & "'
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title=evil)
            native_picker.pick_file(title=evil, patterns=("*.xlsx",))
        for call in mock_run.call_args_list:
            argv = call.args[0]
            joined = " ".join(str(a) for a in argv)
            assert evil not in joined
            assert "do shell script" not in joined

    def test_hostile_patterns_not_interpolated_into_applescript(self) -> None:
        """Client patterns are NOT passed into the AppleScript on darwin;
        the type list is the hardcoded xlsx/xlsm set."""
        evil_pat = '"} & (do shell script "id") & {"'
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_file(title="t", patterns=(evil_pat,))
        argv = mock_run.call_args.args[0]
        script = argv[argv.index("-e") + 1]
        assert evil_pat not in script
        assert "do shell script" not in script
        assert "xlsx" in script
        assert "xlsm" in script
