"""Native OS file/dir picker for the localhost configure-UI.

Browsers cannot hand a server-side absolute path to the backend, but the
configure UI is a single-user localhost tool (server == user machine), so
the server process can pop a native OS dialog and return the chosen
absolute path.

OS-aware strategy
-----------------
* **macOS** (``sys.platform == "darwin"``): a Tk dialog launched from the
  server's child process does not GUI-activate, so the dialog never comes
  to the foreground (the Browse button appears dead). Instead we shell out
  to ``osascript`` (a macOS built-in) and use AppleScript's native
  ``choose folder`` / ``choose file`` Finder dialogs, which correctly come
  to the front. User cancel -> osascript exits ``-128`` with
  ``User canceled`` on stderr -> mapped to ``status="cancelled"``.
* **Windows / other** (``sys.platform != "darwin"``): the original
  short-lived ``sys.executable -c <const tkinter script>`` subprocess
  path, which works on Windows.

Either path degrades gracefully: a missing/erroring native tool
(``osascript`` absent, tkinter unavailable, timeout, nonzero exit) yields
a ``status="error"`` envelope so the server stays up and the UI falls
back to manual path entry; the picker NEVER raises.

Security
--------
The subprocess argv is always a FIXED list, ``shell=False``, with a
``timeout``.

* Non-darwin: ``[sys.executable, "-c", _SCRIPT, mode, title, *patterns]``.
  The client-supplied ``title``/``patterns`` reach the child ONLY as
  discrete trailing argv elements (read via ``sys.argv`` in the child)
  and are never shell-interpolated into ``_SCRIPT``.
* darwin: the AppleScript body is a module-level CONSTANT with a baked-in
  generic prompt. The client ``title`` is **ignored** and the file-type
  list is the hardcoded ``{"xlsx", "xlsm"}`` set — nothing client-supplied
  is ever concatenated/interpolated into the AppleScript, so a hostile
  title cannot execute AppleScript or shell.

The returned path is convenience only — callers still run it through the
existing ``_validate_target`` / ``_validate_xlsx_path`` validators
(defense in depth).
"""

from __future__ import annotations

import subprocess  # noqa: S404 - fixed argv, shell=False, see module docstring
import sys
from dataclasses import dataclass
from typing import Any

_TIMEOUT_SECONDS = 300

_TKINTER_UNAVAILABLE = "tkinter_unavailable"

# macOS AppleScript: user cancel maps to error number -128 ("User
# canceled."). We treat that as a cancel, not an error.
_OSASCRIPT = "osascript"
_MACOS_CANCEL_CODE = "-128"
_MACOS_CANCEL_TEXT = "User canceled"

# Baked-in generic prompts: NO client value is interpolated (zero AppleScript
# / shell injection surface). Hardcoded xlsx/xlsm type list for file mode.
_MACOS_DIR_SCRIPT = 'POSIX path of (choose folder with prompt "Select a folder")'
_MACOS_FILE_SCRIPT = (
    'POSIX path of (choose file with prompt "Select a file" '
    'of type {"xlsx", "xlsm"})'
)

# Module-level CONSTANT (non-darwin path). Read mode/title/patterns from
# sys.argv only; nothing is ever interpolated into this string.
_SCRIPT = r"""
import sys

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    sys.stderr.write("tkinter_unavailable")
    raise SystemExit(3)

mode = sys.argv[1] if len(sys.argv) > 1 else "dir"
title = sys.argv[2] if len(sys.argv) > 2 else ""
patterns = sys.argv[3:]

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

if mode == "file":
    if patterns:
        filetypes = [("Excel", " ".join(patterns)), ("All files", "*.*")]
    else:
        filetypes = [("All files", "*.*")]
    chosen = filedialog.askopenfilename(title=title, filetypes=filetypes)
else:
    chosen = filedialog.askdirectory(title=title)

root.destroy()
sys.stdout.write(chosen or "")
raise SystemExit(0)
"""


@dataclass(frozen=True)
class PickResult:
    """Frozen JSON-projectable result of a native picker invocation."""

    status: str
    path: str | None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"status": self.status}
        if self.path is not None:
            body["path"] = self.path
        if self.detail is not None:
            body["detail"] = self.detail
        return body


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _invoke(argv: list[str]) -> subprocess.CompletedProcess[str] | PickResult:
    """Run ``argv`` (fixed list, shell=False, timeout); on any spawn
    failure return a terminal error/cancel ``PickResult`` instead."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, shell=False
            argv,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            shell=False,
        )
    except FileNotFoundError:
        return PickResult(status="error", path=None, detail="interpreter_missing")
    except subprocess.TimeoutExpired:
        return PickResult(status="error", path=None, detail="timeout")
    except Exception as exc:  # noqa: BLE001
        return PickResult(status="error", path=None, detail=type(exc).__name__)


def _run(argv: list[str]) -> PickResult:
    """Non-darwin (tkinter) outcome mapping. Never raises."""
    outcome = _invoke(argv)
    if isinstance(outcome, PickResult):
        return outcome
    completed = outcome

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        detail = _TKINTER_UNAVAILABLE if _TKINTER_UNAVAILABLE in stderr else "failed"
        return PickResult(status="error", path=None, detail=detail)

    chosen = (completed.stdout or "").strip()
    if not chosen:
        return PickResult(status="cancelled", path=None, detail=None)
    return PickResult(status="ok", path=chosen, detail=None)


def _run_macos(applescript: str) -> PickResult:
    """darwin osascript outcome mapping. ``applescript`` is always a
    module CONSTANT (no client interpolation). Never raises."""
    outcome = _invoke([_OSASCRIPT, "-e", applescript])
    if isinstance(outcome, PickResult):
        return outcome
    completed = outcome

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        if _MACOS_CANCEL_CODE in stderr or _MACOS_CANCEL_TEXT in stderr:
            return PickResult(status="cancelled", path=None, detail=None)
        return PickResult(status="error", path=None, detail="failed")

    chosen = (completed.stdout or "").strip()
    if not chosen:
        return PickResult(status="cancelled", path=None, detail=None)
    return PickResult(status="ok", path=chosen, detail=None)


def pick_directory(title: str) -> PickResult:
    """Open a native folder picker; return the chosen absolute path."""
    if _is_macos():
        return _run_macos(_MACOS_DIR_SCRIPT)
    return _run([sys.executable, "-c", _SCRIPT, "dir", title])


def pick_file(title: str, patterns: tuple[str, ...]) -> PickResult:
    """Open a native file picker filtered by ``patterns`` (e.g. xlsx)."""
    if _is_macos():
        return _run_macos(_MACOS_FILE_SCRIPT)
    return _run([sys.executable, "-c", _SCRIPT, "file", title, *patterns])
