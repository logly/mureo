"""RED tests for ``mureo.web.native_picker`` (does not exist yet).

The module is expected to expose:

- ``PickResult`` — a ``@dataclass(frozen=True)`` envelope:
  ``status`` ("ok" | "cancelled" | "error"), ``path`` (str | None),
  ``detail`` (str | None), plus an ``as_dict()`` JSON projection.
- ``pick_directory(title) -> PickResult`` — spawns a short-lived
  ``sys.executable -c <const tkinter script>`` subprocess running
  ``askdirectory()``; stdout (a single absolute path) -> ``ok``;
  empty stdout -> ``cancelled``; nonzero / FileNotFoundError /
  TimeoutExpired / tkinter-unavailable -> ``error``.
- ``pick_file(title, patterns) -> PickResult`` — same but
  ``askopenfilename()`` with Excel ``*.xlsx``/``*.xlsm`` filetypes.

Security core (planner HANDOFF L19, L31-L36):
- The subprocess argv is a FIXED list ``[sys.executable, "-c",
  CONST_SCRIPT, title]``. The client-supplied ``title`` appears ONLY
  as a trailing argv list element (read via ``sys.argv`` in the child),
  never shell-interpolated. ``shell`` is False (or absent). A
  ``timeout`` kwarg is always passed.

``subprocess.run`` is fully mocked — NO real subprocess, NO real Tk
window is ever created.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# NOTE: this import is expected to FAIL during the RED phase because
# ``mureo/web/native_picker.py`` does not exist yet. That ImportError
# (collection-time) is the intended RED signal for every test below.
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


# ---------------------------------------------------------------------------
# PickResult — frozen result envelope
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
        result = native_picker.PickResult(
            status="ok", path="/abs/dir", detail=None
        )
        assert _d(result)["status"] == "ok"
        assert _d(result)["path"] == "/abs/dir"

    def test_as_dict_cancelled_path_is_none(self) -> None:
        result = native_picker.PickResult(
            status="cancelled", path=None, detail=None
        )
        body = _d(result)
        assert body["status"] == "cancelled"
        assert body.get("path") is None


# ---------------------------------------------------------------------------
# pick_directory — happy / cancelled / error paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPickDirectory:
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
        """A child that fails to import tkinter signals
        ``tkinter_unavailable`` so the UI can fall back to manual entry
        (planner HANDOFF L21)."""
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
        """A picker failure must never propagate (server stays up,
        planner HANDOFF R1)."""
        with patch(
            "mureo.web.native_picker.subprocess.run",
            side_effect=RuntimeError("kaboom"),
        ):
            result = native_picker.pick_directory(title="t")
        assert result.status == "error"


# ---------------------------------------------------------------------------
# pick_file — Excel filetypes + path/cancel behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPickFile:
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
            native_picker.pick_file(
                title="Pick xlsx", patterns=("*.xlsx", "*.xlsm")
            )
        argv = mock_run.call_args.args[0]
        flat = " ".join(str(a) for a in argv)
        assert "*.xlsx" in flat
        assert "*.xlsm" in flat


# ---------------------------------------------------------------------------
# Subprocess argv / kwargs shape — injection-resistance (security core)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubprocessInvocationShape:
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
        discrete trailing argv element (planner HANDOFF L32, R4)."""
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
        """``shell=False`` requires a sequence argv; a bare string would
        be a single-program name and is a red flag for injection."""
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_file(title="t", patterns=("*.xlsx",))
        argv = mock_run.call_args.args[0]
        assert isinstance(argv, (list, tuple))
        assert not isinstance(argv, str)

    def test_stdout_is_captured(self) -> None:
        """The handler reads the chosen path from stdout, so capture
        must be requested (``capture_output=True`` or
        ``stdout=PIPE``)."""
        mock_run = MagicMock(return_value=_completed(stdout="/a"))
        with patch("mureo.web.native_picker.subprocess.run", mock_run):
            native_picker.pick_directory(title="t")
        kwargs = mock_run.call_args.kwargs
        captured = kwargs.get("capture_output") is True or (
            kwargs.get("stdout") is subprocess.PIPE
        )
        assert captured
