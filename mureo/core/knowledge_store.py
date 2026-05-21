"""``KnowledgeStore`` Protocol — two-tier pluggable ``/learn`` storage.

Abstracts the persistence used by the ``/learn`` skill and consumed by
diagnostic skills (``/daily-check``, ``/rescue``, ``/budget-rebalance``,
etc.). Today the operator tier lives at
``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md`` and there is no
workspace-scoped tier — single-workspace callers see only the operator
tier and the workspace methods are inert.

The two-tier shape exists so a future workspace-scoped tier can be
added without changing the Protocol or call sites. Default callers
that have no workspace tier observe ``read_workspace_knowledge() is
None`` and ``append_workspace_knowledge`` raises
``NotImplementedError`` (so misrouted writes fail loudly rather than
silently going nowhere).
"""

from __future__ import annotations

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
