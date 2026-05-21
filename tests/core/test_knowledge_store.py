"""Tests for ``mureo.core.knowledge_store`` — structural Protocol contract.

RED-phase tests for the new ``KnowledgeStore`` Protocol that abstracts
the two-tier ``/learn`` knowledge base — one tier shared across the
operator's workspaces (today: ``~/.claude/skills/_mureo-pro-diagnosis/``)
and one tier scoped to the current workspace (today: absent in the
default OSS configuration).

Default callers continue to read the operator tier from the existing
``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md`` location. This
Protocol exists so the tier-resolution mechanism is replaceable
(in-memory fakes, alternate locations, etc.).

This commit pins the Protocol shape only — concrete default
implementations land in a separate commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mureo.core.knowledge_store import KnowledgeStore


@dataclass
class _FakeKnowledgeStore:
    """Minimal in-memory implementation used to exercise the Protocol shape."""

    operator: str = ""
    workspace: str | None = None  # None means "no workspace tier configured"
    operator_appends: list[str] = field(default_factory=list)
    workspace_appends: list[str] = field(default_factory=list)

    def read_operator_knowledge(self) -> str:
        return self.operator

    def read_workspace_knowledge(self) -> str | None:
        return self.workspace

    def append_operator_knowledge(self, insight: str) -> None:
        self.operator_appends.append(insight)
        self.operator += insight

    def append_workspace_knowledge(self, insight: str) -> None:
        if self.workspace is None:
            raise NotImplementedError("no workspace tier configured")
        self.workspace_appends.append(insight)
        self.workspace += insight


@pytest.mark.unit
def test_protocol_is_runtime_checkable() -> None:
    assert isinstance(_FakeKnowledgeStore(), KnowledgeStore)


@pytest.mark.unit
def test_incomplete_implementation_is_rejected() -> None:
    class _MissingWorkspaceRead:
        def read_operator_knowledge(self) -> str:
            return ""

        def append_operator_knowledge(self, insight: str) -> None:
            pass

        def append_workspace_knowledge(self, insight: str) -> None:
            pass

    assert not isinstance(_MissingWorkspaceRead(), KnowledgeStore)


@pytest.mark.unit
def test_workspace_tier_may_be_absent() -> None:
    """``read_workspace_knowledge`` returns ``None`` when no workspace tier
    exists (default in single-workspace mode)."""
    store = _FakeKnowledgeStore()
    assert store.read_workspace_knowledge() is None


@pytest.mark.unit
def test_append_workspace_when_absent_raises() -> None:
    """When no workspace tier is configured, appends must fail loudly so
    misrouted writes are caught instead of silently going nowhere."""
    store = _FakeKnowledgeStore()
    with pytest.raises(NotImplementedError):
        store.append_workspace_knowledge("would be lost")


@pytest.mark.unit
def test_append_routes_to_correct_tier() -> None:
    store = _FakeKnowledgeStore(workspace="")  # opt in to workspace tier
    store.append_operator_knowledge("operator insight")
    store.append_workspace_knowledge("workspace insight")
    assert store.operator_appends == ["operator insight"]
    assert store.workspace_appends == ["workspace insight"]
    assert "operator insight" in store.read_operator_knowledge()
    assert store.read_workspace_knowledge() == "workspace insight"
