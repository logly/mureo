"""Native OS file/dir picker for the localhost configure-UI.

Browsers cannot hand a server-side absolute path to the backend, but the
configure UI is a single-user localhost tool (server == user machine), so
the server process can pop a native OS dialog (tkinter) and return the
chosen absolute path.

The dialog runs in a short-lived child process (``sys.executable -c
<const script>``) so a broken/missing tkinter degrades gracefully instead
of taking down the server. The child prints the chosen absolute path to
stdout (empty when cancelled) and exits 0; an import failure prints the
``tkinter_unavailable`` sentinel to stderr and exits 3.

Security
--------
The subprocess argv is the FIXED list
``[sys.executable, "-c", _SCRIPT, mode, title, *patterns]``. The
client-supplied ``title``/``patterns`` reach the child ONLY as discrete
trailing argv elements (read via ``sys.argv`` in the child) and are never
shell-interpolated into ``_SCRIPT``. ``shell`` is always False and a
``timeout`` is always enforced. The returned path is convenience only —
callers still run it through the existing ``_validate_target`` /
``_validate_xlsx_path`` validators (defense in depth).
"""

from __future__ import annotations

import subprocess  # noqa: S404 - fixed argv, shell=False, see module docstring
import sys
from dataclasses import dataclass
from typing import Any

_TIMEOUT_SECONDS = 300

_TKINTER_UNAVAILABLE = "tkinter_unavailable"

# Module-level CONSTANT. Read mode/title/patterns from sys.argv only;
# nothing is ever interpolated into this string.
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


def _run(argv: list[str]) -> PickResult:
    """Invoke the picker child and map its outcome to a PickResult.

    Never raises: every failure mode (missing interpreter, timeout,
    tkinter-unavailable, nonzero exit, unexpected exception) degrades to
    a ``status="error"`` envelope so the server stays up.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
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

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        detail = _TKINTER_UNAVAILABLE if _TKINTER_UNAVAILABLE in stderr else "failed"
        return PickResult(status="error", path=None, detail=detail)

    chosen = (completed.stdout or "").strip()
    if not chosen:
        return PickResult(status="cancelled", path=None, detail=None)
    return PickResult(status="ok", path=chosen, detail=None)


def pick_directory(title: str) -> PickResult:
    """Open a native folder picker; return the chosen absolute path."""
    return _run([sys.executable, "-c", _SCRIPT, "dir", title])


def pick_file(title: str, patterns: tuple[str, ...]) -> PickResult:
    """Open a native file picker filtered by ``patterns`` (e.g. xlsx)."""
    return _run([sys.executable, "-c", _SCRIPT, "file", title, *patterns])
