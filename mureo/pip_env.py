"""UTF-8 environment for pip subprocess invocations (Windows cp932 safety).

Every pip / ensurepip subprocess mureo spawns must force its child stdio to
UTF-8. On Windows a child Python defaults its stdout/stderr encoding to the
active console code page — cp932 on a Japanese Windows. pip's rich-rendered
``--report -`` JSON and install logs can contain characters outside cp932
(e.g. ``U+00B7`` MIDDLE DOT), so the child raises ``UnicodeEncodeError`` and
exits *before* emitting any output. Decoding our side as UTF-8 (done at each
call site) is necessary but not sufficient — the child must also ENCODE as
UTF-8. ``PYTHONIOENCODING`` + ``PYTHONUTF8`` force that regardless of the code
page, and are a no-op on macOS/Linux (already UTF-8).

Scope: this is for the pip / ensurepip subprocesses only. The pipx / npm
installer in ``mureo.providers.installer`` deliberately runs WITHOUT a custom
``env`` (its docstring explains the anti-tampering reason, and it emits no rich
``--report`` JSON), so it must NOT adopt this helper.
"""

from __future__ import annotations

import os


def pip_subprocess_env() -> dict[str, str]:
    """Return a copy of ``os.environ`` with child stdio forced to UTF-8.

    See the module docstring for why both variables are set: cp932 cannot
    encode every character pip emits, so the child Python must be told to use
    UTF-8 for its standard streams or it crashes on a Japanese Windows. The
    ``:replace`` error handler is belt-and-suspenders — the encoding goal is
    "the child never dies emitting output", so an unrepresentable byte degrades
    to U+FFFD rather than raising (mirroring the ``errors="replace"`` we already
    decode with on the parent side).
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"
    return env


__all__ = ["pip_subprocess_env"]
