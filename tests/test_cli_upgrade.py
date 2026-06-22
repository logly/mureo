"""Tests for ``mureo upgrade`` — pipx venv-aware bulk upgrade command.

Implements the contract described in issue #177:

- ``mureo upgrade``           → upgrade ``mureo`` itself
- ``mureo upgrade <pkg>``     → upgrade a specific package in the same venv
- ``mureo upgrade --all``     → upgrade ``mureo`` + every installed ``mureo-*``
- ``mureo upgrade --dry-run`` → print the pip command without invoking it

The unit-of-isolation is ``mureo.cli.upgrade_cmd``:

* ``sys.executable`` is the source of truth for the target venv.
* ``importlib.metadata.distributions()`` is used to discover ``mureo-*``
  packages (PEP 503 canonicalised name match — exact ``mureo`` or
  ``mureo-<rest>``; prefix squatters such as ``mureology`` must be
  excluded).
* Package names are validated with a PEP 503 regex and pip is always
  invoked with a ``--`` sentinel so that operator-supplied input cannot
  be parsed as a pip option / VCS URL / PEP 508 marker.
* If ``python -m pip --version`` exits non-zero with ``No module named
  pip`` on stderr we bootstrap with ``ensurepip`` once and retry; any
  other failure is surfaced verbatim.
* pip's exit code is propagated as the CLI exit code.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class _FakeDist:
    """Stand-in for ``importlib.metadata.Distribution`` used by tests."""

    name: str

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}


def _runner() -> CliRunner:
    return CliRunner()


def _app() -> Any:
    from mureo.cli.main import app

    return app


@pytest.fixture
def fake_distributions(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch ``importlib.metadata.distributions`` used by upgrade_cmd."""

    state: dict[str, list[_FakeDist]] = {"dists": []}

    def _set(names: Iterable[str]) -> None:
        state["dists"] = [_FakeDist(name=n) for n in names]

    def _distributions() -> list[_FakeDist]:
        return state["dists"]

    monkeypatch.setattr("mureo.cli.upgrade_cmd.metadata.distributions", _distributions)
    return _set


@pytest.fixture
def fake_pip(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``subprocess.run`` inside upgrade_cmd.

    Default behaviour: ``pip --version`` is healthy, ``pip install`` exits 0.
    Tests override ``return_value`` or ``side_effect`` to drive scenarios.
    """

    def _default(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    mock = MagicMock(side_effect=_default)
    monkeypatch.setattr("mureo.cli.upgrade_cmd.subprocess.run", mock)
    return mock


# ---------------------------------------------------------------------------
# Default invocation — upgrade mureo itself
# ---------------------------------------------------------------------------


def test_upgrade_default_upgrades_mureo_self(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code == 0, result.stderr
    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert len(install_calls) == 1
    cmd = install_calls[0].args[0]
    assert cmd[:3] == [sys.executable, "-m", "pip"]
    assert "install" in cmd
    assert "--upgrade" in cmd
    # Sentinel guard must precede every target.
    assert "--" in cmd
    assert cmd[-1] == "mureo"


def test_pip_version_probe_captures_as_utf8(fake_pip: MagicMock) -> None:
    """The ``pip --version`` availability probe must decode output as UTF-8,
    not the locale codec (cp932 on a Japanese Windows) — otherwise capturing
    pip's output raises UnicodeDecodeError and ``mureo upgrade`` dies there."""
    _runner().invoke(_app(), ["upgrade"])

    version_calls = [c for c in fake_pip.call_args_list if c.args[0][-1] == "--version"]
    assert version_calls, "expected a `pip --version` probe"
    assert version_calls[0].kwargs["encoding"] == "utf-8"
    assert version_calls[0].kwargs["errors"] == "replace"


def test_every_pip_subprocess_forces_utf8_child_stdio(fake_pip: MagicMock) -> None:
    """Every pip / ensurepip subprocess must pass an ``env`` that forces the
    CHILD to encode its stdio as UTF-8 — on a Japanese Windows pip otherwise
    crashes encoding non-cp932 output (e.g. U+00B7) before we read it. Guards
    all of `_pip_is_available`, `_run_pip_install`, and `_bootstrap_pip`."""
    _runner().invoke(_app(), ["upgrade", "--all"])

    assert fake_pip.call_args_list, "expected at least one pip subprocess"
    for call in fake_pip.call_args_list:
        env = call.kwargs.get("env")
        assert env is not None, f"pip call missing env: {call.args[0]}"
        assert env["PYTHONIOENCODING"] == "utf-8:replace"
        assert env["PYTHONUTF8"] == "1"


# ---------------------------------------------------------------------------
# Explicit package + version pin
# ---------------------------------------------------------------------------


def test_upgrade_named_package_with_version(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade", "mureo-logly-bridge==1.2.3"])

    assert result.exit_code == 0, result.stderr
    install_cmd = [
        c.args[0] for c in fake_pip.call_args_list if "install" in c.args[0]
    ][0]
    assert install_cmd[-1] == "mureo-logly-bridge==1.2.3"
    assert install_cmd[install_cmd.index("--") + 1 :] == ["mureo-logly-bridge==1.2.3"]


# ---------------------------------------------------------------------------
# --all discovery
# ---------------------------------------------------------------------------


def test_upgrade_all_discovers_mureo_and_mureo_prefixed(
    fake_pip: MagicMock, fake_distributions: Any
) -> None:
    fake_distributions(
        [
            "mureo",
            "Mureo-Logly-Bridge",  # case + separator variants must normalise
            "mureo_lineyahoo_bridge",
            "mureology",  # squatter — must NOT be picked up
            "mureoextras",  # squatter — must NOT be picked up
            "unrelated-pkg",
        ]
    )

    result = _runner().invoke(_app(), ["upgrade", "--all"])

    assert result.exit_code == 0, result.stderr
    install_cmd = [
        c.args[0] for c in fake_pip.call_args_list if "install" in c.args[0]
    ][0]
    targets = install_cmd[install_cmd.index("--") + 1 :]
    assert set(targets) == {
        "mureo",
        "mureo-logly-bridge",
        "mureo-lineyahoo-bridge",
    }
    # mureo itself must always be present and ideally first for readability.
    assert "mureo" in targets


def test_upgrade_all_invokes_pip_once_for_atomic_resolution(
    fake_pip: MagicMock, fake_distributions: Any
) -> None:
    fake_distributions(["mureo", "mureo-a", "mureo-b", "mureo-c"])

    _runner().invoke(_app(), ["upgrade", "--all"])

    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert (
        len(install_calls) == 1
    ), "pip must be called once so resolver sees the full set"


# ---------------------------------------------------------------------------
# Argument injection guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "-r/etc/passwd",
        "--index-url=http://attacker/",
        "pkg @ git+https://attacker/x.git",
        "pkg; python_version<'3.0'",
        "pkg[extras]",
        "../mureo",
        "",
        "mureo plus space",
    ],
)
def test_upgrade_rejects_hostile_package_specs(
    fake_pip: MagicMock, hostile: str
) -> None:
    result = _runner().invoke(_app(), ["upgrade", hostile])

    assert result.exit_code != 0
    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert install_calls == [], "pip must not be invoked for hostile input"


# ---------------------------------------------------------------------------
# --dry-run prints the command and does not invoke pip install
# ---------------------------------------------------------------------------


def test_upgrade_dry_run_does_not_invoke_pip_install(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade", "--dry-run"])

    assert result.exit_code == 0, result.stderr
    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert install_calls == []
    assert "pip" in result.stdout
    assert "install" in result.stdout
    assert "--upgrade" in result.stdout
    assert "mureo" in result.stdout


# ---------------------------------------------------------------------------
# ensurepip fallback — only when pip is missing
# ---------------------------------------------------------------------------


def test_upgrade_bootstraps_pip_when_missing(fake_pip: MagicMock) -> None:
    calls: list[list[str]] = []
    state = {"bootstrapped": False}

    def _side_effect(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[-2:] == ["pip", "--version"]:
            if state["bootstrapped"]:
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout="pip 24.0", stderr=""
                )
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="No module named pip\n"
            )
        if "ensurepip" in cmd:
            state["bootstrapped"] = True
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    fake_pip.side_effect = _side_effect

    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code == 0, result.stderr
    # ensurepip must be invoked exactly once before pip install proceeds.
    ensurepip_calls = [c for c in calls if "ensurepip" in c]
    assert len(ensurepip_calls) == 1
    assert ensurepip_calls[0][:3] == [sys.executable, "-m", "ensurepip"]
    # pip install must still run after the bootstrap, with the original target.
    install_cmds = [c for c in calls if "install" in c and "ensurepip" not in c]
    assert len(install_cmds) == 1
    assert install_cmds[0][-1] == "mureo"
    assert "--upgrade" in install_cmds[0]


def test_upgrade_does_not_bootstrap_on_other_pip_errors(fake_pip: MagicMock) -> None:
    calls: list[list[str]] = []

    def _side_effect(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[-2:] == ["pip", "--version"]:
            return subprocess.CompletedProcess(
                cmd,
                returncode=1,
                stdout="",
                stderr="PermissionError: [Errno 13] Permission denied\n",
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    fake_pip.side_effect = _side_effect

    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code != 0
    ensurepip_calls = [c for c in calls if "ensurepip" in c]
    assert ensurepip_calls == []


# ---------------------------------------------------------------------------
# pip exit code propagation
# ---------------------------------------------------------------------------


def test_upgrade_propagates_pip_exit_code(fake_pip: MagicMock) -> None:
    def _side_effect(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        if "install" in cmd:
            return subprocess.CompletedProcess(
                cmd, returncode=42, stdout="", stderr="boom"
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    fake_pip.side_effect = _side_effect

    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code == 42


# ---------------------------------------------------------------------------
# Conflicting flags
# ---------------------------------------------------------------------------


def test_upgrade_rejects_all_with_explicit_packages(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade", "--all", "mureo-foo"])

    assert result.exit_code != 0
    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert install_calls == []


# ---------------------------------------------------------------------------
# Belt-and-braces: --all always includes mureo even if dist metadata hides it
# ---------------------------------------------------------------------------


def test_upgrade_all_always_includes_mureo_self(
    fake_pip: MagicMock, fake_distributions: Any
) -> None:
    # Simulate an editable / source checkout where mureo's own dist-info
    # is not visible to importlib.metadata.
    fake_distributions(["mureo-foo"])

    result = _runner().invoke(_app(), ["upgrade", "--all"])

    assert result.exit_code == 0, result.stderr
    install_cmd = [
        c.args[0] for c in fake_pip.call_args_list if "install" in c.args[0]
    ][0]
    targets = install_cmd[install_cmd.index("--") + 1 :]
    assert targets[0] == "mureo"
    assert "mureo-foo" in targets


def test_upgrade_all_dedups_case_and_separator_variants(
    fake_pip: MagicMock, fake_distributions: Any
) -> None:
    fake_distributions(["mureo-foo", "mureo_foo", "Mureo.Foo"])

    result = _runner().invoke(_app(), ["upgrade", "--all"])

    assert result.exit_code == 0, result.stderr
    install_cmd = [
        c.args[0] for c in fake_pip.call_args_list if "install" in c.args[0]
    ][0]
    targets = install_cmd[install_cmd.index("--") + 1 :]
    # mureo (belt-and-braces) + exactly one mureo-foo, no duplicates.
    assert targets.count("mureo-foo") == 1
    assert sorted(targets) == ["mureo", "mureo-foo"]


# ---------------------------------------------------------------------------
# Dry-run still validates hostile input
# ---------------------------------------------------------------------------


def test_upgrade_dry_run_still_rejects_hostile_input(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade", "--dry-run", "-r/etc/passwd"])

    assert result.exit_code != 0


def test_upgrade_rejects_double_equals(fake_pip: MagicMock) -> None:
    result = _runner().invoke(_app(), ["upgrade", "mureo==1.0==2.0"])

    assert result.exit_code != 0
    install_calls = [c for c in fake_pip.call_args_list if "install" in c.args[0]]
    assert install_calls == []


# ---------------------------------------------------------------------------
# sys.executable invariant: every captured cmd targets the running python
# ---------------------------------------------------------------------------


def test_upgrade_always_targets_sys_executable(fake_pip: MagicMock) -> None:
    _runner().invoke(_app(), ["upgrade"])

    for call in fake_pip.call_args_list:
        cmd = call.args[0]
        assert (
            cmd[0] == sys.executable
        ), f"command must start with sys.executable, got {cmd!r}"


# ---------------------------------------------------------------------------
# ensurepip succeeds but pip is still broken → clean error, no install attempt
# ---------------------------------------------------------------------------


def test_upgrade_aborts_if_pip_still_missing_after_bootstrap(
    fake_pip: MagicMock,
) -> None:
    calls: list[list[str]] = []

    def _side_effect(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[-2:] == ["pip", "--version"]:
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="No module named pip\n"
            )
        if "ensurepip" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    fake_pip.side_effect = _side_effect

    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code != 0
    install_calls = [c for c in calls if "install" in c and "ensurepip" not in c]
    assert (
        install_calls == []
    ), "must not attempt `pip install` if pip is still broken post-bootstrap"


def test_upgrade_propagates_ensurepip_failure(fake_pip: MagicMock) -> None:
    def _side_effect(
        cmd: list[str], *_: Any, **__: Any
    ) -> subprocess.CompletedProcess[str]:
        if cmd[-2:] == ["pip", "--version"]:
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="No module named pip\n"
            )
        if "ensurepip" in cmd:
            return subprocess.CompletedProcess(
                cmd, returncode=7, stdout="", stderr="boom"
            )
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    fake_pip.side_effect = _side_effect

    result = _runner().invoke(_app(), ["upgrade"])

    assert result.exit_code == 7
