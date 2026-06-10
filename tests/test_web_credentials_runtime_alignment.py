"""#194 — the configure-UI credentials path must follow the active
``RuntimeContext``.

Before the fix the web layer hardcoded ``host_paths.credentials_path``
(``~/.mureo/credentials.json``) for every credential write *and* its own
status read, while the MCP runtime reads via
``mureo.auth`` → ``get_runtime_context().secret_store``. A
``mureo.runtime_context_factory`` that relocates the ``SecretStore``
therefore produced a silent split-brain: the OAuth/setup wizard wrote
one place, the runtime read another.

The fix resolves the wizard's ``host_paths.credentials_path`` from the
active ``RuntimeContext`` when (and only when) a factory is registered
and its store is filesystem-backed, falling back to the host default
otherwise. Because every web write site and the status read share
``host_paths.credentials_path``, aligning that one value aligns the
whole web layer with the runtime.

These tests cover the core resolver helper and the wizard wiring.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
    runtime_credentials_path,
)
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Entry-point stubs (shape: ``.name`` + ``.load()``) — matches the
# resolver's usage and the pattern in tests/core/test_runtime_resolver.py.
# ---------------------------------------------------------------------------


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    """Stub ``mureo.core.runtime_context.entry_points`` for the
    runtime-context factory group."""

    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


class _MemorySecretStore:
    """Minimal non-filesystem ``SecretStore`` (no ``.path``)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def load(self, key: str) -> dict[str, Any]:
        return dict(self._data.get(key, {}))

    def save(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = dict(value)


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    """Each test starts and ends with a clean resolver cache so the
    process-wide singleton cannot bleed between tests."""
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------
# runtime_credentials_path helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runtime_credentials_path_default_when_no_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No factory registered → the supplied default is returned verbatim
    (single-backend installs and the test-injected home are unaffected;
    crucially the resolver must NOT fall through to the real-home
    default store path)."""
    _patch_entry_points(monkeypatch, [])
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == default


@pytest.mark.unit
def test_runtime_credentials_path_follows_factory_filesystem_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A registered factory whose store is a ``FilesystemSecretStore``
    relocates the path — the write side now matches the read side."""
    custom = tmp_path / "alt" / "creds.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("alt", lambda: default_runtime_context(credentials_path=custom))],
    )
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == custom


@pytest.mark.unit
def test_runtime_credentials_path_default_for_non_filesystem_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-filesystem store has no path to expose, so the path-based
    write functions keep the host default (the honest ceiling of a
    ``credentials_path: Path`` API)."""
    base = default_runtime_context()
    ctx = dataclasses.replace(base, secret_store=_MemorySecretStore())
    _patch_entry_points(monkeypatch, [_FakeEP("vault", lambda: ctx)])
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == default


# ---------------------------------------------------------------------------
# ConfigureWizard wiring
# ---------------------------------------------------------------------------


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "commands").mkdir()
    (home / ".mureo").mkdir()
    return home


@pytest.mark.unit
def test_wizard_credentials_path_defaults_to_host_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No factory → the wizard keeps the home-injected host default; it
    must not leak to the real ``~/.mureo/credentials.json``."""
    _patch_entry_points(monkeypatch, [])
    home = _make_home(tmp_path)
    wiz = ConfigureWizard(home=home)
    assert wiz.host_paths.credentials_path == home / ".mureo" / "credentials.json"


@pytest.mark.unit
def test_wizard_credentials_path_follows_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A registered FS-backed factory relocates the wizard's credentials
    path, so every web write site + the status read align with the MCP
    runtime (#194)."""
    custom = tmp_path / "alt" / "creds.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("alt", lambda: default_runtime_context(credentials_path=custom))],
    )
    home = _make_home(tmp_path)
    wiz = ConfigureWizard(home=home)
    assert wiz.host_paths.credentials_path == custom


@pytest.mark.unit
def test_wizard_set_host_preserves_factory_credentials_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Switching the host recomputes the path bundle but must re-apply
    the runtime-context override, not revert to the host default."""
    custom = tmp_path / "alt" / "creds.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("alt", lambda: default_runtime_context(credentials_path=custom))],
    )
    home = _make_home(tmp_path)
    wiz = ConfigureWizard(home=home)
    wiz.set_host("claude-desktop")
    assert wiz.host_paths.credentials_path == custom
