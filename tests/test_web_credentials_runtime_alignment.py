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
# #196 — protocol-based resolution: a store advertises its own write path
# via ``credentials_write_path`` rather than being type-sniffed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runtime_credentials_path_honors_declared_write_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A filesystem-backed store that is NOT a ``FilesystemSecretStore``
    instance — e.g. a composite layering an override file over a shared
    base — advertises its real write target via ``credentials_write_path``.
    The resolver must return it instead of falling through to ``default``
    (which reintroduced the #194 split-brain for such backends)."""
    write_target = tmp_path / "base" / "shared-creds.json"

    class _LayeredSecretStore:
        """Reads merge override + base; writes land in ``base``."""

        credentials_write_path = write_target

        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            return None

        def delete(self, key: str) -> None:
            return None

    base = default_runtime_context()
    ctx = dataclasses.replace(base, secret_store=_LayeredSecretStore())
    _patch_entry_points(monkeypatch, [_FakeEP("layered", lambda: ctx)])
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == write_target


@pytest.mark.unit
def test_runtime_credentials_path_ignores_non_path_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``credentials_write_path`` that is not a ``Path`` (e.g. a bare
    string from a mis-typed store) must NOT be trusted — the resolver
    falls through rather than passing a non-Path to the path-based write
    functions."""

    class _BadDeclaration:
        credentials_write_path = "/etc/passwd"  # str, not Path

        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            return None

        def delete(self, key: str) -> None:
            return None

    base = default_runtime_context()
    ctx = dataclasses.replace(base, secret_store=_BadDeclaration())
    _patch_entry_points(monkeypatch, [_FakeEP("bad", lambda: ctx)])
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == default


@pytest.mark.unit
def test_runtime_credentials_path_declared_path_wins_over_isinstance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When a store BOTH is a ``FilesystemSecretStore`` AND declares a
    different ``credentials_write_path``, the declared capability wins
    (branch 1 precedes the concrete-type fallback)."""
    from mureo.core.secret_store import FilesystemSecretStore

    declared = tmp_path / "declared" / "creds.json"

    class _DeclaringFsStore(FilesystemSecretStore):
        credentials_write_path = declared

    base = default_runtime_context()
    store = _DeclaringFsStore(path=tmp_path / "concrete" / "creds.json")
    ctx = dataclasses.replace(base, secret_store=store)
    _patch_entry_points(monkeypatch, [_FakeEP("dual", lambda: ctx)])
    default = tmp_path / "home" / ".mureo" / "credentials.json"
    assert runtime_credentials_path(default) == declared


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
def test_wizard_ignores_factory_when_home_is_injected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SAFETY: an explicitly-injected ``home`` sandboxes the wizard. Even
    with a factory registered, the wizard MUST keep its injected-home
    default and never reach the process-global factory (whose paths live
    outside the sandbox — in dev/CI that is the operator's real
    ``~/.mureo/credentials.json``). Regression guard for the #195
    home-injection escape that let tests clobber real credentials."""
    custom = tmp_path / "alt" / "creds.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("alt", lambda: default_runtime_context(credentials_path=custom))],
    )
    home = _make_home(tmp_path)
    wiz = ConfigureWizard(home=home)
    assert wiz.host_paths.credentials_path == home / ".mureo" / "credentials.json"


@pytest.mark.unit
def test_wizard_set_host_keeps_injected_home_under_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Switching the host recomputes the path bundle but must stay
    sandboxed under the injected home, not leak to the factory path."""
    custom = tmp_path / "alt" / "creds.json"
    _patch_entry_points(
        monkeypatch,
        [_FakeEP("alt", lambda: default_runtime_context(credentials_path=custom))],
    )
    home = _make_home(tmp_path)
    wiz = ConfigureWizard(home=home)
    wiz.set_host("claude-desktop")
    assert wiz.host_paths.credentials_path == home / ".mureo" / "credentials.json"


@pytest.mark.unit
def test_wizard_applies_override_only_when_home_is_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Production path: with ``home=None`` the wizard applies the
    runtime-context override. ``runtime_credentials_path`` is patched to
    a tmp sentinel so the test never resolves the real factory or touches
    the operator's real ``~/.mureo`` (constructing the wizard only builds
    Path objects — no credential I/O)."""
    sentinel = tmp_path / "runtime" / "creds.json"
    monkeypatch.setattr(
        "mureo.web.server.runtime_credentials_path", lambda _default: sentinel
    )
    wiz = ConfigureWizard(home=None)
    assert wiz.host_paths.credentials_path == sentinel
