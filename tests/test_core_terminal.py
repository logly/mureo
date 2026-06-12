"""Unit tests for ``mureo.core.terminal`` (#227).

``force_cooked_mode`` re-enables ``ISIG`` / ``ICANON`` / ``ECHO`` on a
TTY so a blocking wait (``mureo configure``) can always be interrupted
with Ctrl+C even if a prior step leaked raw/cbreak mode. Exercised
against a real pseudo-terminal (``pty.openpty``) so the termios bit
manipulation is verified for real, not just mocked.

Unix-only: ``termios`` / ``pty`` are not available on Windows, where the
helpers are import-guarded no-ops — there is nothing to test.
"""

from __future__ import annotations

import os

import pytest

termios = pytest.importorskip("termios")
import pty  # noqa: E402 - after importorskip so Windows skips cleanly

from mureo.core.terminal import force_cooked_mode, terminal_fd  # noqa: E402


@pytest.mark.unit
def test_force_cooked_mode_reenables_isig_icanon_echo() -> None:
    """On a pty left in raw mode (the three bits cleared), the helper
    turns ISIG/ICANON/ECHO back on — restoring Ctrl+C, line editing, and
    echo (the #227 symptom signature)."""
    master, slave = pty.openpty()
    try:
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~(termios.ISIG | termios.ICANON | termios.ECHO)  # lflags
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        # Precondition: the bits really are off (this is "raw"-ish).
        assert not termios.tcgetattr(slave)[3] & termios.ISIG

        force_cooked_mode(slave)

        after = termios.tcgetattr(slave)[3]
        assert after & termios.ISIG, "Ctrl+C (SIGINT) must be re-enabled"
        assert after & termios.ICANON, "canonical line input must be re-enabled"
        assert after & termios.ECHO, "echo must be re-enabled"
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.unit
def test_force_cooked_mode_preserves_already_cooked_bits() -> None:
    """A terminal already in cooked mode is left with the three bits on
    (the helper only ORs them in — it never clears anything)."""
    master, slave = pty.openpty()
    try:
        force_cooked_mode(slave)
        after = termios.tcgetattr(slave)[3]
        assert after & termios.ISIG
        assert after & termios.ECHO
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.unit
def test_force_cooked_mode_none_is_noop() -> None:
    force_cooked_mode(None)  # must not raise


@pytest.mark.unit
def test_force_cooked_mode_non_tty_fd_is_noop() -> None:
    """A pipe fd is not a TTY — ``tcgetattr`` raises internally and the
    helper swallows it (best-effort), never propagating."""
    read_fd, write_fd = os.pipe()
    try:
        force_cooked_mode(read_fd)  # no raise
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.unit
def test_terminal_fd_returns_int_or_none() -> None:
    fd = terminal_fd()
    assert fd is None or isinstance(fd, int)
