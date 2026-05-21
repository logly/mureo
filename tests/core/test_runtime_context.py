"""Tests for ``mureo.core.runtime_context`` — frozen dataclass aggregating
the four core extension Protocols plus a workspace identifier.

RED-phase tests pin the dataclass shape, immutability, and the
non-empty ``workspace_id`` validator. Default construction (the factory
that returns a sensible context for single-workspace callers) lands in
a separate commit.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Any

import pytest

from mureo.context.models import ActionLogEntry, StateDocument, StrategyEntry
from mureo.core.runtime_context import RuntimeContext

# ---------------------------------------------------------------------------
# Minimal in-process fakes — kept here (not shared) so this test stays
# self-contained and the contract is visible at a glance.
# ---------------------------------------------------------------------------


@dataclass
class _S:
    def load(self, key: str) -> dict[str, Any]:
        return {}

    def save(self, key: str, value: dict[str, Any]) -> None: ...
    def delete(self, key: str) -> None: ...


@dataclass
class _St:
    def read_state(self) -> StateDocument:
        return StateDocument()

    def write_state(self, doc: StateDocument) -> None: ...
    def read_strategy(self) -> list[StrategyEntry]:
        return []

    def write_strategy(self, entries: list[StrategyEntry]) -> None: ...
    def append_action_log(self, entry: ActionLogEntry) -> None: ...


@dataclass
class _K:
    def read_operator_knowledge(self) -> str:
        return ""

    def read_workspace_knowledge(self) -> str | None:
        return None

    def append_operator_knowledge(self, insight: str) -> None: ...
    def append_workspace_knowledge(self, insight: str) -> None: ...


@dataclass
class _T:
    async def acquire(self, key: str) -> None: ...


def _ctx(workspace_id: str = "default") -> RuntimeContext:
    return RuntimeContext(
        secret_store=_S(),
        state_store=_St(),
        knowledge_store=_K(),
        throttle_store=_T(),
        workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_construct_with_all_protocols() -> None:
    ctx = _ctx()
    assert ctx.workspace_id == "default"


@pytest.mark.unit
def test_all_fields_round_trip_by_identity() -> None:
    """The dataclass must store the passed stores by identity — no eager
    wrapping or copying. Catches a future bug where someone introduces
    validation that swaps the referenced object."""
    s, st, k, t = _S(), _St(), _K(), _T()
    ctx = RuntimeContext(
        secret_store=s,
        state_store=st,
        knowledge_store=k,
        throttle_store=t,
        workspace_id="default",
    )
    assert ctx.secret_store is s
    assert ctx.state_store is st
    assert ctx.knowledge_store is k
    assert ctx.throttle_store is t


@pytest.mark.unit
def test_is_frozen() -> None:
    ctx = _ctx()
    with pytest.raises(FrozenInstanceError):
        ctx.workspace_id = "other"  # type: ignore[misc]


@pytest.mark.unit
def test_workspace_id_required() -> None:
    """``workspace_id`` is mandatory — no implicit default — so callers must
    be explicit about whether they are in single-workspace ('default') or
    another mode. The canonical sentinel for single-workspace is the
    literal ``"default"``."""
    with pytest.raises(TypeError):
        RuntimeContext(  # type: ignore[call-arg]
            secret_store=_S(),
            state_store=_St(),
            knowledge_store=_K(),
            throttle_store=_T(),
        )


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", " ", "\t", "\n"])
def test_workspace_id_rejects_empty_or_whitespace(bad: str) -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        _ctx(workspace_id=bad)


# ---------------------------------------------------------------------------
# default_runtime_context() — wires the four file-backed default stores
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_factory_wires_all_four_filesystem_defaults(tmp_path: Path) -> None:
    from mureo.core.knowledge_store import FilesystemKnowledgeStore
    from mureo.core.runtime_context import default_runtime_context
    from mureo.core.secret_store import FilesystemSecretStore
    from mureo.core.state_store import FilesystemStateStore
    from mureo.core.throttle_store import ProcessLocalThrottleStore

    ctx = default_runtime_context(
        workspace=tmp_path,
        credentials_path=tmp_path / "creds.json",
        operator_knowledge_path=tmp_path / "op.md",
    )
    assert isinstance(ctx.secret_store, FilesystemSecretStore)
    assert isinstance(ctx.state_store, FilesystemStateStore)
    assert isinstance(ctx.knowledge_store, FilesystemKnowledgeStore)
    assert isinstance(ctx.throttle_store, ProcessLocalThrottleStore)


@pytest.mark.unit
def test_default_factory_workspace_id_is_default_sentinel(tmp_path: Path) -> None:
    """The canonical sentinel for single-workspace callers is the literal
    ``"default"`` — pinned here so it does not drift."""
    from mureo.core.runtime_context import default_runtime_context

    ctx = default_runtime_context(workspace=tmp_path)
    assert ctx.workspace_id == "default"


@pytest.mark.unit
def test_default_factory_no_args_uses_legacy_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Called without overrides, the factory must reproduce today's
    file locations: ``~/.mureo/credentials.json``, CWD-relative STATE.json
    / STRATEGY.md, ``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``.

    Patches ``Path.home`` directly so the test is Windows-safe — the
    ``HOME`` env var is consulted on POSIX but Windows looks at
    ``USERPROFILE`` first, which would make a ``setenv("HOME", ...)``
    approach silently fall through to the real home directory on the
    Windows CI lane added in #122."""
    from mureo.core.runtime_context import default_runtime_context

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(tmp_path)

    ctx = default_runtime_context()
    assert ctx.secret_store.path == tmp_path / ".mureo" / "credentials.json"  # type: ignore[attr-defined]
    assert ctx.state_store.state_path == tmp_path / "STATE.json"  # type: ignore[attr-defined]
    assert ctx.state_store.strategy_path == tmp_path / "STRATEGY.md"  # type: ignore[attr-defined]
    assert (
        ctx.knowledge_store.operator_path  # type: ignore[attr-defined]
        == tmp_path / ".claude" / "skills" / "_mureo-pro-diagnosis" / "SKILL.md"
    )
    assert ctx.knowledge_store.workspace_path is None  # type: ignore[attr-defined]


@pytest.mark.unit
def test_default_factory_accepts_workspace_knowledge_override(tmp_path: Path) -> None:
    from mureo.core.runtime_context import default_runtime_context

    ws_md = tmp_path / "ws.md"
    ctx = default_runtime_context(
        workspace=tmp_path,
        workspace_knowledge_path=ws_md,
    )
    assert ctx.knowledge_store.workspace_path == ws_md  # type: ignore[attr-defined]


@pytest.mark.unit
def test_default_factory_accepts_throttle_config_override(tmp_path: Path) -> None:
    from mureo.core.runtime_context import default_runtime_context
    from mureo.throttle import ThrottleConfig

    config = ThrottleConfig(rate=42.0, burst=7)
    ctx = default_runtime_context(workspace=tmp_path, throttle_config=config)
    assert ctx.throttle_store.default_config is config  # type: ignore[attr-defined]
