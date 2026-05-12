"""Unit tests for ``mureo.providers.installer``.

Covers ``run_install`` (list-form argv, no shell=True, dry-run skip,
returncode propagation, allow-list enforcement) and ``InstallResult``
immutability. See planner HANDOFF ``feat-providers-cli-phase1.md``.

External calls are mocked at ``mureo.providers.installer.subprocess.run``.
"""

from __future__ import annotations

import dataclasses
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _make_spec(
    *,
    spec_id: str = "google-ads-official",
    install_kind: str = "pipx",
    install_argv: tuple[str, ...] | None = None,
) -> Any:
    """Build a real ``ProviderSpec`` instance for installer tests.

    Keeping this helper inside each test (via import-on-call) ensures the
    test still raises ``ImportError`` cleanly in the RED phase rather than
    erroring at collection time.
    """
    from mureo.providers.catalog import ProviderSpec

    if install_argv is None:
        install_argv = ("pipx", "run", "google-ads-mcp")

    return ProviderSpec(
        id=spec_id,
        display_name=spec_id,
        install_kind=install_kind,  # type: ignore[arg-type]
        install_argv=install_argv,
        mcp_server_config={"command": "echo", "args": []},
        required_env=(),
        notes="",
        coexists_with_mureo_platform=None,
    )


@pytest.mark.unit
def test_run_install_passes_argv_list_form() -> None:
    """``subprocess.run`` is invoked with exact list-form argv."""
    from mureo.providers.installer import run_install

    argv: tuple[str, ...] = (
        "pipx",
        "run",
        "--spec",
        "git+https://example.com/x",
        "google-ads-mcp",
    )
    spec = _make_spec(install_argv=argv)

    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout="", stderr=""
        )
        run_install(spec)

    assert mock_run.call_count == 1
    call_args, call_kwargs = mock_run.call_args
    # First positional is the argv list; or it may have been passed as
    # the first kwarg. Either way the value must equal ``argv``.
    passed_argv = call_args[0] if call_args else call_kwargs.get("args")
    assert passed_argv == list(argv)


@pytest.mark.unit
def test_run_install_never_uses_shell_true() -> None:
    """Regression guard: ``shell`` kwarg must be absent or ``False``."""
    from mureo.providers.installer import run_install

    spec = _make_spec()
    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=spec.install_argv, returncode=0, stdout="", stderr=""
        )
        run_install(spec)

    _, kwargs = mock_run.call_args
    assert kwargs.get("shell", False) is False


@pytest.mark.unit
def test_run_install_dry_run_skips_subprocess() -> None:
    """``dry_run=True`` returns an ``InstallResult`` without invoking subprocess."""
    from mureo.providers.installer import run_install

    spec = _make_spec(install_argv=("pipx", "run", "google-ads-mcp"))

    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        result = run_install(spec, dry_run=True)

    mock_run.assert_not_called()
    assert result.argv == list(spec.install_argv)


@pytest.mark.unit
def test_run_install_returns_returncode_stdout_stderr() -> None:
    """Subprocess outputs propagate into the ``InstallResult``."""
    from mureo.providers.installer import run_install

    spec = _make_spec()
    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=spec.install_argv, returncode=0, stdout="ok", stderr=""
        )
        result = run_install(spec)

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert result.stderr == ""


@pytest.mark.unit
def test_run_install_propagates_nonzero_returncode() -> None:
    """Non-zero returncode does not raise; CLI layer decides what to do."""
    from mureo.providers.installer import run_install

    spec = _make_spec()
    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=spec.install_argv,
            returncode=1,
            stdout="",
            stderr="boom",
        )
        result = run_install(spec)

    assert result.returncode == 1
    assert result.stderr == "boom"


@pytest.mark.unit
def test_run_install_rejects_disallowed_executable() -> None:
    """A non-allow-listed executable raises ``ValueError`` before subprocess."""
    from mureo.providers.installer import run_install

    spec = _make_spec(install_argv=("curl", "https://evil.example.com"))

    with (
        patch("mureo.providers.installer.subprocess.run") as mock_run,
        pytest.raises(ValueError),
    ):
        run_install(spec)
    mock_run.assert_not_called()


@pytest.mark.unit
def test_install_result_is_frozen() -> None:
    """``InstallResult`` is a frozen dataclass; mutation raises."""
    from mureo.providers.installer import InstallResult

    result = InstallResult(
        returncode=0, stdout="ok", stderr="", argv=["pipx", "run", "x"]
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.returncode = 1  # type: ignore[misc]


@pytest.mark.unit
def test_run_install_does_not_pass_env_kwarg() -> None:
    """Subprocess inherits parent env (no ``env=`` kwarg, no credential leak)."""
    from mureo.providers.installer import run_install

    spec = _make_spec()
    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=spec.install_argv, returncode=0, stdout="", stderr=""
        )
        run_install(spec)

    _, kwargs = mock_run.call_args
    assert "env" not in kwargs, (
        "subprocess.run was called with env=..., risking credential leakage "
        "if call args are ever logged. Inherit parent env instead."
    )


@pytest.mark.unit
def test_run_install_hosted_http_returns_success_no_subprocess() -> None:
    """``hosted_http`` specs skip subprocess entirely with a success result.

    Hosted endpoints (e.g. Meta's official MCP at ``mcp.facebook.com/ads``)
    have no local install step. ``run_install`` must short-circuit before
    touching ``subprocess.run`` *and* before the allow-list check (which
    would otherwise reject the empty ``install_argv``).
    """
    from mureo.providers.installer import run_install

    spec = _make_spec(install_kind="hosted_http", install_argv=())

    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        result = run_install(spec)

    mock_run.assert_not_called()
    assert result.returncode == 0
    assert result.argv == []
    # The synthetic stdout marks it as a hosted no-op so callers /
    # operators can tell the success was not a subprocess success.
    assert "hosted" in result.stdout.lower() or "no local" in result.stdout.lower()


@pytest.mark.unit
def test_run_install_hosted_http_dry_run_also_skips_subprocess() -> None:
    """Hosted short-circuit applies regardless of ``dry_run`` value.

    Both real and dry-run invocations against a hosted entry return the
    same synthetic success — there is no work to dry-run-preview because
    no install step exists in the first place.
    """
    from mureo.providers.installer import run_install

    spec = _make_spec(install_kind="hosted_http", install_argv=())

    with patch("mureo.providers.installer.subprocess.run") as mock_run:
        result_real = run_install(spec, dry_run=False)
        result_dry = run_install(spec, dry_run=True)

    mock_run.assert_not_called()
    assert result_real.returncode == 0
    assert result_dry.returncode == 0
    assert result_real.argv == []
    assert result_dry.argv == []


# Silence the unused-import warning when MagicMock is referenced for clarity.
_ = MagicMock
