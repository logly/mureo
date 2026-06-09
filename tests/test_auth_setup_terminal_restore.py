"""Regression tests for #190 — TerminalMenu must not leak cbreak mode
into the surrounding shell session.

``simple_term_menu.TerminalMenu.show()`` flips the terminal into cbreak
(no ``ICANON``, no ``ECHO``, no ``ISIG``) and on a normal happy-path
exit it restores the original mode. On *any* non-normal exit path the
restore can silently fail and the terminal stays in cbreak — every
subsequent program in the same shell stops echoing keystrokes and
stops receiving SIGINT from Ctrl+C.

The fix is a small ``try/finally`` in mureo around every
``TerminalMenu.show()`` call that takes a snapshot of the terminal
attributes via ``termios.tcgetattr`` and restores them via
``termios.tcsetattr(fd, TCSADRAIN, ...)`` regardless of how
``show()`` exits. These tests pin that contract for both call sites
(``_select_account`` and ``setup_mcp_config``) and the non-TTY
degradation path.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ``termios`` is Unix-only and the entire restore mechanism this module
# exercises does not apply on Windows — mureo's production code on
# Windows takes the ``(ImportError, NotImplementedError)`` fallback
# path through ``simple_term_menu`` (its own ``termios`` import fails
# first), so there is nothing to restore and nothing to test.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="termios save/restore is Unix-only — Windows takes the no-menu fallback path",
)


_SENTINEL_OLD_ATTRS = ["iflag", "oflag", "cflag", "lflag", 0, 0, [b"\x00"] * 32]


def _patch_termios(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tty: bool = True,
) -> tuple[MagicMock, MagicMock]:
    """Install spy mocks for ``termios.tcgetattr`` / ``tcsetattr`` on the
    auth_setup module's view of ``termios``.

    Also patches ``_terminal_fd`` so the production code sees a real
    ``int`` fd (under pytest, ``sys.stdin.fileno()`` raises
    ``UnsupportedOperation`` because the harness replaces stdin with a
    pseudo-file — the helper would otherwise short-circuit before
    reaching ``tcgetattr``).

    Returns ``(tcgetattr_mock, tcsetattr_mock)`` so individual tests can
    assert call counts / args.

    When ``tty=False``, ``tcgetattr`` raises ``termios.error`` to
    simulate stdin being a pipe / closed / Windows — the production
    code must degrade to "do nothing" without crashing.
    """
    import termios

    import mureo.auth_setup as auth_setup_mod

    if tty:
        tcgetattr = MagicMock(return_value=list(_SENTINEL_OLD_ATTRS))
    else:
        tcgetattr = MagicMock(side_effect=termios.error("not a tty"))
    tcsetattr = MagicMock()

    monkeypatch.setattr(auth_setup_mod.termios, "tcgetattr", tcgetattr)
    monkeypatch.setattr(auth_setup_mod.termios, "tcsetattr", tcsetattr)
    monkeypatch.setattr(auth_setup_mod, "_terminal_fd", lambda: 0)
    return tcgetattr, tcsetattr


# ---------------------------------------------------------------------------
# _select_account
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_select_account_restores_terminal_on_normal_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful menu pick must still restore terminal attributes —
    we cannot rely on ``simple_term_menu`` doing it on the happy path.
    """
    from mureo.auth_setup import _select_account

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)
    accounts = [{"id": "111", "name": "A"}, {"id": "222", "name": "B"}]

    fake_menu = MagicMock()
    fake_menu.show.return_value = 1
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu) as menu_cls:
        result = _select_account(accounts)

    assert result == "222"
    menu_cls.assert_called_once()
    assert (
        tcgetattr.call_count == 1
    ), "must snapshot terminal attrs before TerminalMenu.show()"
    assert (
        tcsetattr.call_count == 1
    ), "must restore terminal attrs after TerminalMenu.show()"
    # tcsetattr is called with the snapshot from tcgetattr.
    args, _kwargs = tcsetattr.call_args
    assert args[2] == _SENTINEL_OLD_ATTRS


@pytest.mark.unit
def test_select_account_restores_terminal_on_cancelled_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TerminalMenu.show()`` returning ``None`` (operator pressed Esc /
    cancelled) is the most common non-happy-path. The terminal must
    still be restored — this is the primary failure mode reported in
    #190 (cancel a menu, run ``mureo configure``, Ctrl+C dead).
    """
    from mureo.auth_setup import _select_account

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)
    accounts = [{"id": "111", "name": "A"}]

    fake_menu = MagicMock()
    fake_menu.show.return_value = None  # cancelled
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        result = _select_account(accounts)

    assert result is None
    assert (
        tcsetattr.call_count == 1
    ), "restore must run even when the menu was cancelled"
    args, _kwargs = tcsetattr.call_args
    assert args[2] == _SENTINEL_OLD_ATTRS


@pytest.mark.unit
def test_select_account_restores_terminal_when_show_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception from ``TerminalMenu.show()`` (e.g. KeyboardInterrupt,
    internal cbreak failure) must still trigger the restore — that is
    the whole point of the ``try/finally`` introduced by #190.
    """
    from mureo.auth_setup import _select_account

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)
    accounts = [{"id": "111", "name": "A"}]

    fake_menu = MagicMock()
    fake_menu.show.side_effect = KeyboardInterrupt
    with (
        patch("simple_term_menu.TerminalMenu", return_value=fake_menu),
        pytest.raises(KeyboardInterrupt),
    ):
        _select_account(accounts)

    assert tcsetattr.call_count == 1, "restore must run before re-raising the exception"


@pytest.mark.unit
def test_select_account_no_crash_when_stdin_is_not_a_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``termios.tcgetattr`` raises (pipe, closed stdin, Windows),
    the snapshot is skipped, restore is skipped, and the function
    still returns normally.
    """
    from mureo.auth_setup import _select_account

    tcgetattr, tcsetattr = _patch_termios(monkeypatch, tty=False)
    accounts = [{"id": "111", "name": "A"}]

    fake_menu = MagicMock()
    fake_menu.show.return_value = 0
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        result = _select_account(accounts)

    assert result == "111"
    assert tcgetattr.call_count == 1
    # No snapshot → no restore. The function must not raise from the
    # finally block in this state.
    assert tcsetattr.call_count == 0


# ---------------------------------------------------------------------------
# setup_mcp_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_setup_mcp_config_restores_terminal_on_normal_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setup_mcp_config()`` carries the second ``TerminalMenu`` site
    (placement scope choice). Same restore contract as
    ``_select_account``.
    """
    from mureo.auth_setup import setup_mcp_config

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)

    fake_menu = MagicMock()
    fake_menu.show.return_value = 2  # "Skip" — fastest happy-path exit
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        setup_mcp_config()

    assert tcgetattr.call_count == 1
    assert tcsetattr.call_count == 1
    args, _kwargs = tcsetattr.call_args
    assert args[2] == _SENTINEL_OLD_ATTRS


@pytest.mark.unit
def test_setup_mcp_config_restores_terminal_on_cancelled_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setup_mcp_config()`` second-call-site mirror of the cancelled
    case — the operator picking nothing must still trigger restore.
    """
    from mureo.auth_setup import setup_mcp_config

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)

    fake_menu = MagicMock()
    fake_menu.show.return_value = None  # cancelled
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        setup_mcp_config()

    assert (
        tcsetattr.call_count == 1
    ), "restore must run even when the operator cancelled the menu"


@pytest.mark.unit
def test_setup_mcp_config_no_crash_when_stdin_is_not_a_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setup_mcp_config()`` non-TTY mirror — snapshot fails, restore
    is skipped, function still completes normally."""
    from mureo.auth_setup import setup_mcp_config

    tcgetattr, tcsetattr = _patch_termios(monkeypatch, tty=False)

    fake_menu = MagicMock()
    fake_menu.show.return_value = 2  # "Skip"
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        setup_mcp_config()

    assert tcgetattr.call_count == 1
    assert tcsetattr.call_count == 0


@pytest.mark.unit
def test_setup_mcp_config_restores_terminal_when_show_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.auth_setup import setup_mcp_config

    tcgetattr, tcsetattr = _patch_termios(monkeypatch)

    fake_menu = MagicMock()
    fake_menu.show.side_effect = KeyboardInterrupt
    with (
        patch("simple_term_menu.TerminalMenu", return_value=fake_menu),
        pytest.raises(KeyboardInterrupt),
    ):
        setup_mcp_config()

    assert tcsetattr.call_count == 1, "restore must run before re-raising the exception"


# ---------------------------------------------------------------------------
# Order pin — snapshot before show(), restore after, regardless of exit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_select_account_call_order_is_get_then_show_then_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard against a future refactor that flips the order — the snapshot
    must precede ``show()`` and the restore must follow it (otherwise we
    capture a *broken* state and "restore" to it, which is worse than
    not running the fix at all).
    """
    import mureo.auth_setup as auth_setup_mod
    from mureo.auth_setup import _select_account

    events: list[str] = []

    def _spy_tcgetattr(_fd: int) -> list[Any]:
        events.append("tcgetattr")
        return list(_SENTINEL_OLD_ATTRS)

    def _spy_tcsetattr(*_args: Any, **_kwargs: Any) -> None:
        events.append("tcsetattr")

    monkeypatch.setattr(auth_setup_mod.termios, "tcgetattr", _spy_tcgetattr)
    monkeypatch.setattr(auth_setup_mod.termios, "tcsetattr", _spy_tcsetattr)
    monkeypatch.setattr(auth_setup_mod, "_terminal_fd", lambda: 0)

    fake_menu = MagicMock()

    def _spy_show() -> int:
        events.append("show")
        return 0

    fake_menu.show.side_effect = _spy_show
    with patch("simple_term_menu.TerminalMenu", return_value=fake_menu):
        _select_account([{"id": "111", "name": "A"}])

    assert events == ["tcgetattr", "show", "tcsetattr"]
