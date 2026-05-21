"""Tests for ``mureo.core.knowledge_store.FilesystemKnowledgeStore`` —
the default in-process implementation that persists ``/learn`` insights
to Markdown files on disk.

Default operator-tier path mirrors today's
``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``. Default workspace
tier is absent (``read_workspace_knowledge`` returns ``None`` and
``append_workspace_knowledge`` raises). Both paths are injectable for
tests and for alternate setups.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mureo.core.knowledge_store import FilesystemKnowledgeStore, KnowledgeStore


@pytest.mark.unit
def test_satisfies_protocol(tmp_path: Path) -> None:
    store = FilesystemKnowledgeStore(operator_path=tmp_path / "op.md")
    assert isinstance(store, KnowledgeStore)


@pytest.mark.unit
def test_read_operator_missing_returns_empty_string(tmp_path: Path) -> None:
    store = FilesystemKnowledgeStore(operator_path=tmp_path / "op.md")
    assert store.read_operator_knowledge() == ""


@pytest.mark.unit
def test_append_operator_creates_file_with_scaffold(tmp_path: Path) -> None:
    """First write must seed the file with the same frontmatter scaffold
    that today's ``/learn`` skill (`skills/learn/SKILL.md`) uses, so the
    operator-tier consumers see no behavioural change."""
    path = tmp_path / "op.md"
    store = FilesystemKnowledgeStore(operator_path=path)
    store.append_operator_knowledge("first insight\n")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: _mureo-pro-diagnosis" in text
    assert "## Learned Insights" in text
    assert "first insight" in text


@pytest.mark.unit
def test_append_operator_is_additive(tmp_path: Path) -> None:
    store = FilesystemKnowledgeStore(operator_path=tmp_path / "op.md")
    store.append_operator_knowledge("first insight\n")
    store.append_operator_knowledge("second insight\n")
    text = store.read_operator_knowledge()
    assert "first insight" in text
    assert "second insight" in text
    assert text.index("first") < text.index("second")


@pytest.mark.unit
def test_workspace_tier_absent_by_default(tmp_path: Path) -> None:
    store = FilesystemKnowledgeStore(operator_path=tmp_path / "op.md")
    assert store.read_workspace_knowledge() is None


@pytest.mark.unit
def test_append_workspace_without_tier_raises(tmp_path: Path) -> None:
    store = FilesystemKnowledgeStore(operator_path=tmp_path / "op.md")
    with pytest.raises(NotImplementedError):
        store.append_workspace_knowledge("would be lost")


@pytest.mark.unit
def test_workspace_tier_round_trip_when_configured(tmp_path: Path) -> None:
    op = tmp_path / "op.md"
    ws = tmp_path / "ws.md"
    store = FilesystemKnowledgeStore(operator_path=op, workspace_path=ws)
    assert store.read_workspace_knowledge() == ""  # configured but empty
    store.append_workspace_knowledge("ws insight\n")
    assert "ws insight" in (store.read_workspace_knowledge() or "")


@pytest.mark.unit
def test_default_operator_path_under_claude_skills(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Patches ``Path.home`` directly so the test is Windows-safe — see
    ``test_runtime_context.test_default_factory_no_args_uses_legacy_paths``
    for the rationale."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    store = FilesystemKnowledgeStore()
    expected = tmp_path / ".claude" / "skills" / "_mureo-pro-diagnosis" / "SKILL.md"
    assert store.operator_path == expected


@pytest.mark.unit
def test_scaffold_has_expected_frontmatter_and_section() -> None:
    """The seeded scaffold must contain the YAML frontmatter and the
    ``## Learned Insights`` section that downstream diagnostic skills
    rely on.

    The /learn skill no longer ships its own copy of this scaffold (it
    now invokes ``mureo learn add`` which uses :class:`KnowledgeStore`
    instead of writing the file directly), so the previous
    drift-vs-skill regression test is replaced by a shape check on the
    constant itself."""
    from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD

    assert _OPERATOR_SCAFFOLD.startswith("---\n")
    assert "name: _mureo-pro-diagnosis" in _OPERATOR_SCAFFOLD
    assert "## Learned Insights" in _OPERATOR_SCAFFOLD
    # The scaffold MUST end with a newline so the first appended
    # insight does not land on the same line as "## Learned Insights".
    assert _OPERATOR_SCAFFOLD.endswith("\n")
