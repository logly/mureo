"""Keep the controlling TTY sane around long blocking waits (#227).

An interactive arrow-key menu (``simple_term_menu``) flips the terminal
into raw/cbreak mode (``ISIG`` / ``ICANON`` / ``ECHO`` cleared). If that
mode leaks — an unwrapped menu in a third-party backend, a prior CLI
step, or a suspend/resume during a menu — a later blocking wait such as
``mureo configure`` is stranded: with ``ISIG`` off, Ctrl+C never becomes
SIGINT, so the configure stop-signal never fires and the operator sees a
dead terminal with no echo (the #190 family, the uncovered path in #227).

``mureo configure`` is launched from a normal (cooked) shell, so the
robust fix is to defensively force cooked mode right before the wait —
re-enabling Ctrl+C and echo regardless of what was inherited. We do not
snapshot-and-restore the inherited state: restoring a *leaked raw* mode
on exit would simply re-strand the shell, and an interactive shell always
wants cooked mode back.

Every function is a no-op when stdin is not a TTY (pipe / redirect / CI /
Windows, where ``termios`` is absent), so they are always safe to call.
"""

from __future__ import annotations

import contextlib
import sys

try:
    import termios
except ImportError:  # pragma: no cover - Windows (Unix-only stdlib)
    termios = None  # type: ignore[assignment]


def terminal_fd() -> int | None:
    """Return stdin's file descriptor, or ``None`` when it has none.

    ``None`` under pytest (stdin replaced), a pipe/redirect, or a closed
    stream — the caller then skips the termios work.
    """
    try:
        return sys.stdin.fileno()
    except (OSError, ValueError, AttributeError):
        return None


def force_cooked_mode(fd: int | None) -> None:
    """Re-enable ``ISIG`` / ``ICANON`` / ``ECHO`` on ``fd`` (cooked mode).

    Makes Ctrl+C deliver SIGINT, line editing work, and typing echo again,
    whatever a prior step left the terminal in (#227). Only ORs the three
    local-mode bits in — it never clears anything, so a terminal already
    in cooked mode is unchanged. Best-effort: a non-TTY ``fd`` (or
    ``None``, or ``termios`` absent on Windows) is a silent no-op, and a
    ``tcsetattr`` failure is swallowed rather than crashing the caller.
    """
    if termios is None or fd is None:
        return
    with contextlib.suppress(termios.error, OSError, ValueError, AttributeError):
        attrs = termios.tcgetattr(fd)
        # ``attrs[3]`` is the local-mode flags (lflag). ``TCSADRAIN`` lets
        # pending output drain before the mode flip so no escape codes are
        # left mid-stream.
        attrs[3] |= termios.ISIG | termios.ICANON | termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)


__all__ = ["force_cooked_mode", "terminal_fd"]
