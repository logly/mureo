"""Wiring tests for plugin native-skill deployment (Issue #439).

Verifies the setup/upgrade call sites actually invoke the deployer, guard on
directory existence, and stay best-effort (a broken deploy never fails the
surrounding flow).
"""

from __future__ import annotations

from pathlib import Path

import mureo.cli.native_skills as native_skills
from mureo.cli.setup_cmd import _deploy_plugin_native_skills
from mureo.cli.upgrade_cmd import _refresh_native_skills


def test_deploy_helper_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    """A crash in the deployer must not propagate out of setup."""

    def _boom(dest: Path, **_kw: object) -> tuple[int, Path]:
        raise RuntimeError("plugin exploded")

    monkeypatch.setattr(native_skills, "install_native_skills", _boom)
    # Must not raise.
    _deploy_plugin_native_skills(tmp_path / "skills")


def test_refresh_only_targets_existing_dirs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    # Claude skills dir exists; Codex does not.
    (home / ".claude" / "skills").mkdir(parents=True)

    called_with: list[Path] = []

    def _record(dest: Path, **_kw: object) -> tuple[int, Path]:
        called_with.append(dest)
        return 0, dest

    monkeypatch.setattr(native_skills, "install_native_skills", _record)
    _refresh_native_skills()

    assert called_with == [home / ".claude" / "skills"]


def test_refresh_is_best_effort(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (home / ".codex" / "skills").mkdir(parents=True)

    def _boom(dest: Path, **_kw: object) -> tuple[int, Path]:
        raise RuntimeError("plugin exploded")

    monkeypatch.setattr(native_skills, "install_native_skills", _boom)
    # Must not raise even though the only existing target blows up.
    _refresh_native_skills()


def test_web_remove_workflow_skills_also_removes_native(
    tmp_path: Path, monkeypatch
) -> None:
    """clear-setup path must remove plugin native skills, not just the bundle."""
    from mureo.web import setup_actions

    dest = tmp_path / ".claude" / "skills"
    dest.mkdir(parents=True)

    called_with: list[Path] = []

    def _fake_remove_skills(target_dir: Path | None = None) -> tuple[int, Path]:
        return 0, dest

    def _fake_remove_native(dest_dir: Path, **_kw: object) -> tuple[int, Path]:
        called_with.append(dest_dir)
        return 2, dest_dir

    monkeypatch.setattr(setup_actions, "remove_skills", _fake_remove_skills)
    monkeypatch.setattr(native_skills, "remove_native_skills", _fake_remove_native)

    result = setup_actions.remove_workflow_skills()

    assert called_with == [dest]
    assert result.status == "ok"
    assert "plugin native skills" in result.detail
