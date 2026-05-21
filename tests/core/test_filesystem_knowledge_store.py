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
    monkeypatch.setenv("HOME", str(tmp_path))
    store = FilesystemKnowledgeStore()
    expected = tmp_path / ".claude" / "skills" / "_mureo-pro-diagnosis" / "SKILL.md"
    assert store.operator_path == expected


@pytest.mark.unit
def test_scaffold_matches_skills_learn_template() -> None:
    """Regression guard: the seeded scaffold must stay byte-identical to
    the template embedded in ``skills/learn/SKILL.md``. If that template
    is edited without updating ``_OPERATOR_SCAFFOLD`` (or vice-versa)
    files written by /learn and files seeded by the default
    KnowledgeStore will silently diverge.

    The skill file embeds the scaffold inside a ```` ```markdown ```` fence
    nested in a numbered list, so every line carries a 3-space indent.
    Strip the common indent before comparing."""
    import re
    import textwrap

    from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD

    repo_root = Path(__file__).resolve().parents[2]
    skill_md = (repo_root / "skills" / "learn" / "SKILL.md").read_text(encoding="utf-8")

    match = re.search(
        r"```markdown\n(   ---\n.*?## Learned Insights\n)\s*```",
        skill_md,
        re.DOTALL,
    )
    assert match, (
        "could not locate the scaffold fence in skills/learn/SKILL.md; "
        "if the skill format changed, update both files together"
    )
    dedented = textwrap.dedent(match.group(1))
    assert dedented == _OPERATOR_SCAFFOLD
