"""Tests for ``MUREO_BYOD_DIR`` env-var override of ``byod_data_dir``.

The env var lets the install-desktop wrapper point each Claude
Desktop workspace at its own BYOD directory (``<workspace>/byod/``),
so demo and real-data setups can coexist without ``rm -rf
~/.mureo/byod/`` between them. The default (no env var set) keeps
the legacy ``~/.mureo/byod/`` location so existing CLI users see no
behaviour change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_default_is_home_dot_mureo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the env var, the legacy ``~/.mureo/byod/`` path stands.

    Existing users (CLI, Claude Code) must not see any behaviour
    change after this PR; only install-desktop callers opt in.
    """
    from mureo.byod.runtime import byod_data_dir

    fake_home = Path("/tmp/fake_home_for_byod_default")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("MUREO_BYOD_DIR", raising=False)

    assert byod_data_dir() == fake_home / ".mureo" / "byod"


def test_env_var_overrides_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``MUREO_BYOD_DIR=<path>`` redirects BYOD reads/writes."""
    from mureo.byod.runtime import byod_data_dir

    target = tmp_path / "workspace_byod"
    monkeypatch.setenv("MUREO_BYOD_DIR", str(target))

    assert byod_data_dir() == target


def test_env_var_expanduser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``~`` in the env var is expanded so users can point at
    ``~/mureo/byod/`` without resolving manually in their shell rc."""
    from mureo.byod.runtime import byod_data_dir

    # ``Path.expanduser`` reads the ``HOME`` env var, not ``Path.home()``,
    # so we must redirect both to keep the assertion stable.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("MUREO_BYOD_DIR", "~/custom_byod")

    assert byod_data_dir() == tmp_path / "custom_byod"


def test_empty_env_var_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty string in the env var must be treated as 'unset'.

    Otherwise a stray ``MUREO_BYOD_DIR=`` (e.g. from a malformed
    shell rc) silently writes BYOD into the cwd, which would surprise
    everyone.
    """
    from mureo.byod.runtime import byod_data_dir

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("MUREO_BYOD_DIR", "")

    assert byod_data_dir() == tmp_path / ".mureo" / "byod"


def test_manifest_path_follows_env_var(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Downstream helpers like ``manifest_path`` must compose on top of
    the env-aware ``byod_data_dir`` — verifying this prevents a
    regression where a future refactor reintroduces a hard-coded path."""
    from mureo.byod.runtime import byod_data_dir, manifest_path

    target = tmp_path / "ws_byod"
    monkeypatch.setenv("MUREO_BYOD_DIR", str(target))

    assert manifest_path() == byod_data_dir() / "manifest.json"
    assert manifest_path() == target / "manifest.json"
