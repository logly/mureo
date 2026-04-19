"""Tests for mureo.cli._tty — TTY detection and safe confirm helper.

Verifies that setup wizards don't hang when run as a subprocess (e.g.
from Claude Code's Bash tool) by detecting a missing TTY and taking
the caller-supplied default instead of calling ``typer.confirm``.
"""

from __future__ import annotations

import sys

import pytest

# Module under test does not exist yet — this drives RED.
from mureo.cli._tty import confirm_or_default, is_tty  # noqa: I001


class _FakeStream:
    """Minimal stream stand-in whose ``isatty()`` returns a fixed value.

    Used to patch both ``sys.stdin`` and ``sys.stdout`` — ``is_tty``
    now requires both ends to be terminals.
    """

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# Back-compat alias so existing test call sites still read naturally.
_FakeStdin = _FakeStream


def _set_tty(monkeypatch: pytest.MonkeyPatch, *, tty: bool) -> None:
    """Patch both stdin and stdout to the same TTY state."""
    monkeypatch.setattr(sys, "stdin", _FakeStream(tty=tty))
    monkeypatch.setattr(sys, "stdout", _FakeStream(tty=tty))


class TestIsTty:
    def test_returns_true_when_stdin_is_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_tty(monkeypatch, tty=True)
        assert is_tty() is True

    def test_returns_false_when_stdin_is_not_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_tty(monkeypatch, tty=False)
        assert is_tty() is False


class TestConfirmOrDefault:
    def test_no_tty_returns_default_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In non-TTY (subprocess / Claude Bash tool), take the default
        without any I/O — no typer.confirm, no input() call."""
        _set_tty(monkeypatch, tty=False)
        called = False

        def _sentinel(*_args: object, **_kwargs: object) -> bool:
            nonlocal called
            called = True
            return False

        monkeypatch.setattr("typer.confirm", _sentinel)
        assert confirm_or_default("Configure?", default=True) is True
        assert called is False, "typer.confirm must not be called in non-TTY"

    def test_no_tty_returns_default_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_tty(monkeypatch, tty=False)
        assert confirm_or_default("Configure?", default=False) is False

    def test_tty_delegates_to_typer_confirm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With a TTY present, the helper must let typer.confirm drive the
        actual prompt so existing CLI UX is unchanged."""
        _set_tty(monkeypatch, tty=True)
        captured: dict[str, object] = {}

        def _fake_confirm(prompt: str, default: bool = False) -> bool:
            captured["prompt"] = prompt
            captured["default"] = default
            return True

        monkeypatch.setattr("typer.confirm", _fake_confirm)
        result = confirm_or_default("Configure Google Ads?", default=True)

        assert result is True
        assert captured == {"prompt": "Configure Google Ads?", "default": True}

    def test_explicit_override_bypasses_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the caller already knows the value (e.g. from a CLI flag),
        passing override=... skips both TTY detection and typer.confirm."""
        _set_tty(monkeypatch, tty=True)
        called = False

        def _sentinel(*_args: object, **_kwargs: object) -> bool:
            nonlocal called
            called = True
            return True

        monkeypatch.setattr("typer.confirm", _sentinel)
        assert (
            confirm_or_default("Configure?", default=True, override=False) is False
        )
        assert called is False, "Explicit override must not call typer.confirm"

    def test_asymmetric_tty_counts_as_non_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stdin TTY but stdout piped (or vice versa) must be treated as
        non-interactive — prompting would either have no visible output
        or block on unreachable input."""
        monkeypatch.setattr(sys, "stdin", _FakeStream(tty=True))
        monkeypatch.setattr(sys, "stdout", _FakeStream(tty=False))
        assert is_tty() is False
        assert confirm_or_default("Configure?", default=True) is True

    def test_eof_from_confirm_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If stdin closes mid-prompt, fall back to default rather than
        aborting with a stack trace."""
        _set_tty(monkeypatch, tty=True)

        def _raise_eof(*_: object, **__: object) -> bool:
            raise EOFError

        monkeypatch.setattr("typer.confirm", _raise_eof)
        assert confirm_or_default("Configure?", default=True) is True
        assert confirm_or_default("Configure?", default=False) is False
