"""Unit tests for :func:`mureo.pip_env.pip_subprocess_env`.

The helper exists so every pip / ensurepip subprocess forces the child
Python's stdio to UTF-8 — without it a Japanese Windows (cp932) crashes pip
on a non-cp932 character (e.g. U+00B7) in its rich-rendered output before any
of it reaches mureo. ``@pytest.mark.unit``.
"""

from __future__ import annotations

import sys

import pytest

from mureo.pip_env import pip_install_cmd, pip_self_upgrade_cmd, pip_subprocess_env


@pytest.mark.unit
def test_sets_utf8_io_switches() -> None:
    env = pip_subprocess_env()
    assert env["PYTHONIOENCODING"] == "utf-8:replace"
    assert env["PYTHONUTF8"] == "1"


@pytest.mark.unit
def test_preserves_existing_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The result is a COPY of os.environ plus the switches — pip still needs
    PATH / index config, so we must not hand it a 2-key dict."""
    monkeypatch.setenv("MUREO_TEST_SENTINEL", "kept")
    env = pip_subprocess_env()
    assert env["MUREO_TEST_SENTINEL"] == "kept"
    assert "PATH" in env


@pytest.mark.unit
def test_does_not_mutate_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutating the returned dict must not leak back into the process env."""
    import os

    monkeypatch.delenv("PYTHONUTF8", raising=False)
    env = pip_subprocess_env()
    env["PYTHONUTF8"] = "tampered"
    assert os.environ.get("PYTHONUTF8") != "tampered"


@pytest.mark.unit
def test_pip_self_upgrade_cmd_targets_this_venv() -> None:
    """#910: the pip that resolves an upgrade is upgraded first, in this venv."""
    assert pip_self_upgrade_cmd() == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
    ]


@pytest.mark.unit
def test_pip_install_cmd_puts_the_sentinel_before_targets() -> None:
    """The ``--`` sentinel precedes every target so none is read as a flag."""
    cmd = pip_install_cmd(["mureo", "mureo-foo==1.2.3"])
    assert cmd == [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--",
        "mureo",
        "mureo-foo==1.2.3",
    ]
    assert cmd[0] == sys.executable
    assert cmd.index("--") < cmd.index("mureo")
