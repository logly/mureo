"""Integration tests for the ``host="codex"`` branches of setup_actions.

Codex has full host parity with the Claude hosts: basic setup (MCP / hook /
skills), official-provider install/remove into ``~/.codex/config.toml``
(TOML), the native↔official disable toggle, status detection, and bulk
clear. The provider install subprocess (``run_install``) is stubbed so these
tests never touch the network or a real pipx/npm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mureo.web import setup_actions as sa
from mureo.web.status_collector import collect_status

if TYPE_CHECKING:
    from pathlib import Path


class _OkInstall:
    returncode = 0


@pytest.fixture
def _stub_run_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mureo.providers.installer.run_install",
        lambda spec, dry_run=False: _OkInstall(),
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / ".mureo").mkdir()
    return tmp_path


def _config(home: Path) -> Path:
    return home / ".codex" / "config.toml"


@pytest.mark.unit
def test_basic_setup_writes_codex_files(home: Path) -> None:
    assert sa.install_mureo_mcp(home=home, host="codex").status == "ok"
    assert sa.install_mureo_mcp(home=home, host="codex").status == "noop"
    assert "[mcp_servers.mureo]" in _config(home).read_text()

    assert sa.install_auth_hook(home=home, host="codex").status == "ok"
    hooks = home / ".codex" / "hooks.json"
    assert hooks.exists() and "mureo-credential-guard" in hooks.read_text()

    res = sa.install_workflow_skills(home=home, host="codex")
    assert res.status == "ok"
    assert (home / ".codex" / "skills").exists()
    # Skills land under ~/.codex, NOT the shared ~/.claude.
    assert not (home / ".claude" / "skills").exists()


@pytest.mark.unit
def test_install_provider_codex_writes_tagged_block(
    home: Path, _stub_run_install: None
) -> None:
    res = sa.install_provider("google-ads-official", home=home, host="codex")
    assert res.status == "ok"
    text = _config(home).read_text()
    assert "[mcp_servers.google-ads-official]" in text
    assert "# >>> mureo-mcp:google-ads-official >>>" in text
    # Idempotent re-install.
    assert sa.install_provider(
        "google-ads-official", home=home, host="codex"
    ).status == ("noop")


@pytest.mark.unit
def test_install_hosted_provider_is_manual_required(home: Path) -> None:
    res = sa.install_provider("meta-ads-official", home=home, host="codex")
    assert res.status == "manual_required"
    # Nothing written for a hosted provider.
    assert (
        not _config(home).exists()
        or "meta-ads-official" not in _config(home).read_text()
    )


@pytest.mark.unit
def test_native_toggle_guard_and_apply(home: Path, _stub_run_install: None) -> None:
    # Guard: cannot prefer official before the provider is installed.
    assert (
        sa.set_native_preference("google_ads", True, home=home, host="codex").detail
        == "provider_not_installed"
    )
    sa.install_mureo_mcp(home=home, host="codex")
    sa.install_provider("google-ads-official", home=home, host="codex")
    # Now allowed → disable env set in the TOML mureo block.
    assert (
        sa.set_native_preference("google_ads", True, home=home, host="codex").status
        == "ok"
    )
    disable = collect_status("codex", home=home).as_dict()["mureo_disable"]
    assert disable["google_ads"] is True
    # Restore native — always allowed.
    assert (
        sa.set_native_preference("google_ads", False, home=home, host="codex").status
        == "ok"
    )
    disable = collect_status("codex", home=home).as_dict()["mureo_disable"]
    assert disable["google_ads"] is False


@pytest.mark.unit
def test_backfill_disables_provider_installed_before_mcp(
    home: Path, _stub_run_install: None
) -> None:
    # Provider registered FIRST (no mureo block yet) ...
    sa.install_provider("google-ads-official", home=home, host="codex")
    # ... then the mureo MCP — backfill must set the disable env.
    sa.install_mureo_mcp(home=home, host="codex")
    disable = collect_status("codex", home=home).as_dict()["mureo_disable"]
    assert disable["google_ads"] is True


@pytest.mark.unit
def test_status_detects_codex_installed_providers(
    home: Path, _stub_run_install: None
) -> None:
    sa.install_mureo_mcp(home=home, host="codex")
    sa.install_provider("google-ads-official", home=home, host="codex")
    installed = sa._installed_official_providers(home, host="codex")
    assert "google-ads-official" in installed


@pytest.mark.unit
def test_remove_provider_and_clear_all(home: Path, _stub_run_install: None) -> None:
    sa.install_mureo_mcp(home=home, host="codex")
    sa.install_auth_hook(home=home, host="codex")
    sa.install_provider("google-ads-official", home=home, host="codex")

    assert sa.remove_provider(
        "google-ads-official", home=home, host="codex"
    ).status == ("ok")
    assert sa.remove_provider(
        "google-ads-official", home=home, host="codex"
    ).status == ("noop")

    # Re-install then bulk clear removes the mureo block + hook + provider.
    sa.install_provider("google-ads-official", home=home, host="codex")
    env = sa.clear_all_setup(home=home, host="codex")
    assert env["mureo_mcp"]["status"] == "ok"
    assert env["auth_hook"]["status"] == "ok"
    assert "google-ads-official" in env["providers"]
    text = _config(home).read_text() if _config(home).exists() else ""
    assert "mcp_servers" not in text  # everything mureo-managed is gone


@pytest.mark.unit
def test_remove_mureo_mcp_and_auth_hook_codex(home: Path) -> None:
    sa.install_mureo_mcp(home=home, host="codex")
    sa.install_auth_hook(home=home, host="codex")
    assert sa.remove_mureo_mcp(home=home, host="codex").status == "ok"
    assert sa.remove_mureo_mcp(home=home, host="codex").status == "noop"
    assert sa.remove_auth_hook(home=home, host="codex").status == "ok"
    assert sa.remove_auth_hook(home=home, host="codex").status == "noop"


@pytest.mark.unit
def test_clear_all_removes_codex_skills_not_claude(home: Path) -> None:
    """Regression: clear_all must forward host=codex to the skills remover so
    it targets ~/.codex/skills, not the shared ~/.claude/skills."""
    sa.install_workflow_skills(home=home, host="codex")
    codex_skills = home / ".codex" / "skills"
    assert any(codex_skills.iterdir())  # something installed

    sa.clear_all_setup(home=home, host="codex")
    # The codex skill dirs the bundle owns are gone.
    from mureo.cli.setup_cmd import _get_data_path

    bundled = {p.name for p in _get_data_path("skills").iterdir() if p.is_dir()}
    remaining = (
        {p.name for p in codex_skills.iterdir()} if codex_skills.exists() else set()
    )
    assert not (bundled & remaining)
