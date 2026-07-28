"""Tests for ``mureo learn add`` / ``mureo learn tiers`` — the CLI
bridge that routes ``/learn`` skill writes through the KnowledgeStore
Protocol, plus the read-only tier-detection command the skill calls
before choosing a scope.

The contract:
- ``--scope operator`` (default) calls
  ``KnowledgeStore.append_operator_knowledge``.
- ``--scope workspace`` calls
  ``KnowledgeStore.append_workspace_knowledge``; when the resolved
  store has no workspace tier, the command exits non-zero with a
  helpful message instead of silently dropping the insight.
- ``mureo learn tiers`` reports which tiers the resolved store exposes
  in a shape an LLM can parse off stdout, exits 0 either way, and
  creates nothing on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

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


def _inject_store(monkeypatch: pytest.MonkeyPatch, knowledge_store: object) -> None:
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
class TestLearnTiers:
    """``mureo learn tiers`` is how the ``/learn`` skill discovers
    whether a workspace tier exists before asking the user where to
    save. It must be read-only and machine-parseable."""

    def test_reports_both_tiers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _RecordingKnowledgeStore(has_workspace_tier=True)
        _inject_store(monkeypatch, store)
        from mureo.cli.main import app

        result = runner.invoke(app, ["learn", "tiers"])
        assert result.exit_code == 0, result.output
        lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()]
        assert "operator: configured" in lines
        assert "workspace: configured" in lines

    def test_reports_workspace_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _RecordingKnowledgeStore(has_workspace_tier=False)
        _inject_store(monkeypatch, store)
        from mureo.cli.main import app

        result = runner.invoke(app, ["learn", "tiers"])
        assert result.exit_code == 0, result.output
        lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()]
        assert "operator: configured" in lines
        assert "workspace: absent" in lines

    def test_does_not_write_to_either_tier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _RecordingKnowledgeStore(has_workspace_tier=True)
        _inject_store(monkeypatch, store)
        from mureo.cli.main import app

        runner.invoke(app, ["learn", "tiers"])
        assert store.operator_appends == []
        assert store.workspace_appends == []

    def test_does_not_create_the_workspace_file_on_disk(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Detection must not touch disk beyond reads: a configured but
        not-yet-written workspace file stays absent, and the tier still
        reports as configured."""
        from mureo.core.knowledge_store import FilesystemKnowledgeStore

        operator_path = tmp_path / "operator" / "SKILL.md"
        workspace_path = tmp_path / "workspace" / "SKILL.md"
        _inject_store(
            monkeypatch,
            FilesystemKnowledgeStore(
                operator_path=operator_path, workspace_path=workspace_path
            ),
        )
        from mureo.cli.main import app

        result = runner.invoke(app, ["learn", "tiers"])
        assert result.exit_code == 0, result.output
        assert "workspace: configured" in result.output
        assert not workspace_path.exists()
        assert not workspace_path.parent.exists()
        assert not operator_path.exists()

    def test_raising_workspace_read_exits_non_zero_with_a_clean_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Detection is inconclusive, not "absent" — reporting ``absent``
        would push the skill into the silent legacy flow and quietly
        misroute a workspace-scoped insight. Fail loudly, but with a
        readable line rather than a traceback the skill would paste
        into the conversation."""

        class _ExplodingStore(_RecordingKnowledgeStore):
            def read_workspace_knowledge(self) -> str | None:
                raise RuntimeError("workspace backend unreachable")

        _inject_store(monkeypatch, _ExplodingStore())
        from mureo.cli.main import app

        result = runner.invoke(app, ["learn", "tiers"])
        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert "workspace" in result.output.lower()
        # Must not claim a definite answer either way.
        assert "workspace: absent" not in result.output
        assert "workspace: configured" not in result.output

    def test_filesystem_default_without_workspace_reports_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.core.knowledge_store import FilesystemKnowledgeStore

        _inject_store(
            monkeypatch,
            FilesystemKnowledgeStore(operator_path=tmp_path / "operator" / "SKILL.md"),
        )
        from mureo.cli.main import app

        result = runner.invoke(app, ["learn", "tiers"])
        assert result.exit_code == 0, result.output
        assert "workspace: absent" in result.output


@pytest.mark.unit
def test_learn_app_registered_under_main() -> None:
    """`mureo learn` is discoverable from the top-level CLI app."""
    from mureo.cli.main import app

    group_names = [
        g.typer_instance.info.name for g in app.registered_groups if g.typer_instance
    ]
    assert "learn" in group_names
