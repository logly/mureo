"""``KnowledgeStore`` Protocol and default in-process implementation.

The Protocol abstracts the persistence used by the ``/learn`` skill and
consumed by diagnostic skills (``/daily-check``, ``/rescue``,
``/budget-rebalance``, etc.). It splits storage into two tiers — one
shared across all of the operator's workspaces, and one optional tier
scoped to the current workspace — so a future workspace-scoped tier
can be added without changing the Protocol or call sites.

``FilesystemKnowledgeStore`` is the default implementation. The
operator tier defaults to today's
``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md`` location and seeds
the file with the same frontmatter scaffold the ``/learn`` skill uses
today. The workspace tier is absent by default — callers see
``read_workspace_knowledge() is None`` and
``append_workspace_knowledge`` raises ``NotImplementedError`` — so
misrouted writes fail loudly rather than silently going nowhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class KnowledgeStore(Protocol):
    """Two-tier persistence for ``/learn`` insights.

    Tiers:
    - **Operator tier**: shared across every workspace this operator
      opens. Holds general practitioner know-how.
    - **Workspace tier**: scoped to the current workspace. May be
      absent — in which case ``read_workspace_knowledge`` returns
      ``None`` and ``append_workspace_knowledge`` raises
      ``NotImplementedError``.

    Contract:
    - ``read_operator_knowledge`` always returns a string (possibly
      empty); it must not raise on a missing file.
    - ``read_workspace_knowledge`` returns ``None`` when no workspace
      tier is configured; otherwise returns the tier's text (possibly
      empty).
    - Append operations must be additive — never overwrite the file.
    - When no workspace tier is configured, ``append_workspace_knowledge``
      raises ``NotImplementedError``. Callers that want graceful
      fallback should check ``read_workspace_knowledge() is None`` first
      and route the insight to the operator tier instead.
    """

    def read_operator_knowledge(self) -> str: ...

    def read_workspace_knowledge(self) -> str | None: ...

    def append_operator_knowledge(self, insight: str) -> None: ...

    def append_workspace_knowledge(self, insight: str) -> None: ...


# ---------------------------------------------------------------------------
# Default implementation — Markdown files under ``~/.claude/skills/``
# ---------------------------------------------------------------------------


# Frontmatter scaffold mirrors the one emitted by ``skills/learn/SKILL.md``
# so consumers (diagnostic workflows) see the same file shape they have
# always seen. Keep this byte-identical to the skill's template until the
# follow-up commit refactors the skill itself to consume the store.
_OPERATOR_SCAFFOLD = """\
---
name: _mureo-pro-diagnosis
description: "Professional marketing diagnostic frameworks: expert-level campaign analysis that grows with your experience."
metadata:
  version: 0.1.0
---

# Pro Diagnosis — Account Knowledge Base

Insights learned from operating this account, applied by every mureo
diagnostic workflow.

## Learned Insights
"""


class FilesystemKnowledgeStore:
    """Persist ``/learn`` insights to Markdown files on disk.

    Operator-tier default path:
    ``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``. Workspace tier
    is absent unless ``workspace_path`` is supplied at construction.
    """

    def __init__(
        self,
        operator_path: Path | None = None,
        workspace_path: Path | None = None,
    ) -> None:
        if operator_path is not None:
            self.operator_path = operator_path
        else:
            self.operator_path = (
                Path.home()
                / ".claude"
                / "skills"
                / "_mureo-pro-diagnosis"
                / "SKILL.md"
            )
        self.workspace_path = workspace_path

    def read_operator_knowledge(self) -> str:
        if not self.operator_path.exists():
            return ""
        return self.operator_path.read_text(encoding="utf-8")

    def read_workspace_knowledge(self) -> str | None:
        if self.workspace_path is None:
            return None
        if not self.workspace_path.exists():
            return ""
        return self.workspace_path.read_text(encoding="utf-8")

    def append_operator_knowledge(self, insight: str) -> None:
        self.operator_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.operator_path.exists():
            self.operator_path.write_text(
                _OPERATOR_SCAFFOLD + insight, encoding="utf-8"
            )
            return
        with self.operator_path.open("a", encoding="utf-8") as f:
            f.write(insight)

    def append_workspace_knowledge(self, insight: str) -> None:
        if self.workspace_path is None:
            raise NotImplementedError(
                "no workspace tier configured for this KnowledgeStore"
            )
        self.workspace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.workspace_path.open("a", encoding="utf-8") as f:
            f.write(insight)
