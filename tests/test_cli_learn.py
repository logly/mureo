"""Tests for ``mureo learn add`` — the CLI bridge that routes
``/learn`` skill writes through the KnowledgeStore Protocol.

The contract:
- ``--scope operator`` (default) calls
  ``KnowledgeStore.append_operator_knowledge``.
- ``--scope workspace`` calls
  ``KnowledgeStore.append_workspace_knowledge``; when the resolved
  store has no workspace tier, the command exits non-zero with a
  helpful message instead of silently dropping the insight.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from typer.testing import CliRunner

from mureo.core.runtime_context import (
    RuntimeContext,
    default_runtime_context,
    reset_runtime_context,
)

runner = CliRunner()


@dataclass
class _RecordingKnowledgeStore:
    operator_appends: list[str] = field(default_factory=list)
    workspace_appends: list[str] = field(default_factory=list)
    has_workspace_tier: bool = False

    def read_operator_knowledge(self) -> str:  # pragma: no cover
        return ""

    def read_workspace_knowledge(self) -> str | None:  # pragma: no cover
        return "" if self.has_workspace_tier else None

    def append_operator_knowledge(self, insight: str) -> None:
        self.operator_appends.append(insight)

    def append_workspace_knowledge(self, insight: str) -> None:
        if not self.has_workspace_tier:
            raise NotImplementedError("no workspace tier configured")
        self.workspace_appends.append(insight)


def _inject_store(
    monkeypatch: pytest.MonkeyPatch, knowledge_store: _RecordingKnowledgeStore
) -> None:
    base = default_runtime_context()
    ctx = RuntimeContext(
        secret_store=base.secret_store,
        state_store=base.state_store,
        knowledge_store=knowledge_store,
        throttle_store=base.throttle_store,
        workspace_id="injected",
    )
    monkeypatch.setattr("mureo.core.runtime_context._cached_context", ctx)


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.mark.unit
def test_add_with_default_scope_writes_to_operator_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RecordingKnowledgeStore()
    _inject_store(monkeypatch, store)
    from mureo.cli.main import app

    result = runner.invoke(app, ["learn", "add", "first insight\n"])
    assert result.exit_code == 0, result.output
    assert store.operator_appends == ["first insight\n"]
    assert store.workspace_appends == []
    assert "operator" in result.output.lower()


@pytest.mark.unit
def test_add_with_operator_scope_writes_to_operator_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RecordingKnowledgeStore()
    _inject_store(monkeypatch, store)
    from mureo.cli.main import app

    result = runner.invoke(
        app, ["learn", "add", "operator insight\n", "--scope", "operator"]
    )
    assert result.exit_code == 0, result.output
    assert store.operator_appends == ["operator insight\n"]
    assert store.workspace_appends == []


@pytest.mark.unit
def test_add_with_workspace_scope_writes_to_workspace_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RecordingKnowledgeStore(has_workspace_tier=True)
    _inject_store(monkeypatch, store)
    from mureo.cli.main import app

    result = runner.invoke(
        app, ["learn", "add", "workspace insight\n", "--scope", "workspace"]
    )
    assert result.exit_code == 0, result.output
    assert store.workspace_appends == ["workspace insight\n"]
    assert store.operator_appends == []
    assert "workspace" in result.output.lower()


@pytest.mark.unit
def test_workspace_scope_without_tier_exits_with_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolved store has no workspace tier, the command must
    fail clearly so the skill (or operator) does not silently lose the
    insight. The error mentions ``--scope operator`` as the recovery."""
    store = _RecordingKnowledgeStore(has_workspace_tier=False)
    _inject_store(monkeypatch, store)
    from mureo.cli.main import app

    result = runner.invoke(
        app, ["learn", "add", "lost insight\n", "--scope", "workspace"]
    )
    assert result.exit_code != 0
    assert store.workspace_appends == []
    assert "--scope operator" in result.output


@pytest.mark.unit
def test_learn_app_registered_under_main() -> None:
    """`mureo learn` is discoverable from the top-level CLI app."""
    from mureo.cli.main import app

    group_names = [
        g.typer_instance.info.name for g in app.registered_groups if g.typer_instance
    ]
    assert "learn" in group_names
