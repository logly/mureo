"""Tests for the ``mureo_learning_insights_get`` MCP tool.

The tool is the read-side counterpart to the ``/learn`` skill's
``mureo learn add`` CLI: it returns the operator-tier knowledge base
(by default the contents of
``~/.claude/skills/_mureo-pro-diagnosis/SKILL.md``) so diagnostic
workflows like ``/daily-check``, ``/rescue``, and ``/budget-rebalance``
can consult accumulated practitioner know-how before drawing
conclusions.

These tests pin three things:

1. The tool is registered in ``mureo.mcp.tools_learning.TOOLS`` with
   the expected name and an empty ``inputSchema`` (no arguments).
2. The handler routes through the runtime context's KnowledgeStore
   (so an alternate backend registered via the
   ``mureo.runtime_context_factory`` entry-point group still works).
3. The handler returns a non-empty guidance string when no insights
   have been saved yet, instead of an empty / confusing payload.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _import_learning_tools() -> object:
    """Import :mod:`mureo.mcp.tools_learning` fresh per test.

    Mirrors the convention used by other ``test_mcp_tools_*`` files
    so module-level state (TOOLS list construction) is observed in a
    clean state.
    """
    import importlib

    import mureo.mcp.tools_learning

    return importlib.reload(mureo.mcp.tools_learning)


@pytest.mark.unit
class TestLearningInsightsToolDefinition:
    def test_tool_registered_with_correct_name(self) -> None:
        mod = _import_learning_tools()
        names = {t.name for t in mod.TOOLS}
        assert "mureo_learning_insights_get" in names

    def test_tool_has_empty_input_schema(self) -> None:
        """The tool takes no arguments — its job is to surface every
        insight in the operator-tier knowledge base. Callers must not
        be tempted to pass a filter / scope hint that we silently
        ignore."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        assert tool.inputSchema == {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def test_tool_description_references_learn_skill(self) -> None:
        """A reader inspecting the tool description should understand
        where the data comes from and why they should call it."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        assert "/learn" in tool.description
        assert "diagnostic" in tool.description.lower()


@pytest.mark.unit
class TestLearningInsightsHandler:
    @pytest.mark.asyncio
    async def test_handler_returns_insights_from_knowledge_store(self) -> None:
        """The handler must defer to the runtime context's
        KnowledgeStore — an alternate backend swapped in via the
        ``mureo.runtime_context_factory`` entry-point group should
        take effect transparently."""
        mod = _import_learning_tools()
        fake_store = MagicMock()
        fake_store.read_operator_knowledge.return_value = (
            "## Learned Insights\n\n### Use micro-conversions when CV is sparse\n"
        )
        fake_ctx = MagicMock(knowledge_store=fake_store)
        with patch(
            "mureo.mcp.tools_learning.get_runtime_context", return_value=fake_ctx
        ):
            result = await mod.handle_tool("mureo_learning_insights_get", {})

        fake_store.read_operator_knowledge.assert_called_once()
        assert len(result) == 1
        assert "Use micro-conversions when CV is sparse" in result[0].text

    @pytest.mark.asyncio
    async def test_handler_returns_guidance_when_no_insights_saved(self) -> None:
        """An empty knowledge base is the common first-time case, not
        an error. Return a guidance string so the agent understands
        nothing has been saved yet and the operator should be
        encouraged to run ``/learn``."""
        mod = _import_learning_tools()
        fake_store = MagicMock()
        fake_store.read_operator_knowledge.return_value = ""
        fake_ctx = MagicMock(knowledge_store=fake_store)
        with patch(
            "mureo.mcp.tools_learning.get_runtime_context", return_value=fake_ctx
        ):
            result = await mod.handle_tool("mureo_learning_insights_get", {})

        assert len(result) == 1
        assert "/learn" in result[0].text
        # Should explicitly note absence rather than returning a
        # blank string the agent might quote into its analysis.
        assert "no insights" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_handler_treats_scaffold_only_as_empty(self) -> None:
        """A freshly-created file with only the YAML frontmatter
        scaffold (no actual insights) should count as 'no insights
        saved yet' — otherwise the agent would treat the empty
        ``## Learned Insights`` header as authoritative content."""
        mod = _import_learning_tools()
        scaffold_only = """\
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
        fake_store = MagicMock()
        fake_store.read_operator_knowledge.return_value = scaffold_only
        fake_ctx = MagicMock(knowledge_store=fake_store)
        with patch(
            "mureo.mcp.tools_learning.get_runtime_context", return_value=fake_ctx
        ):
            result = await mod.handle_tool("mureo_learning_insights_get", {})

        # Treated as empty — guidance, not the raw scaffold.
        assert "no insights" in result[0].text.lower()

    def test_scaffold_only_check_matches_canonical_scaffold(self) -> None:
        """Pin the parity between
        :func:`mureo.mcp.tools_learning._is_scaffold_only` and the
        canonical scaffold constant in
        :mod:`mureo.core.knowledge_store`.

        Without this test, a future edit to ``_OPERATOR_SCAFFOLD``
        (renaming the heading, localising it, restructuring it)
        would silently break the empty-state detection and the
        agent would start seeing the raw YAML frontmatter dumped
        into its context.
        """
        from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD
        from mureo.mcp.tools_learning import _is_scaffold_only

        assert _is_scaffold_only(_OPERATOR_SCAFFOLD) is True
        # The same scaffold with one trailing insight is NOT
        # scaffold-only — guards against a regression where the
        # derived marker drifts and starts catching everything.
        insight = (
            "### Use micro-conversions when CV is sparse\n\n"
            "**Situation:** ...\n"
        )
        assert _is_scaffold_only(_OPERATOR_SCAFFOLD + insight) is False

    @pytest.mark.asyncio
    async def test_handler_unknown_tool_raises(self) -> None:
        """Same dispatch contract as every other ``tools_*`` module
        — unknown names raise ``ValueError`` so the server can return
        a clear MCP error."""
        mod = _import_learning_tools()
        with pytest.raises(ValueError, match="Unknown tool"):
            await mod.handle_tool("not_a_real_tool", {})


@pytest.mark.unit
class TestLearningInsightsServerWiring:
    """The tool surface is empty unless ``tools_learning`` is wired
    into the top-level server module — pin that wiring so a future
    refactor cannot accidentally drop it."""

    def test_server_module_includes_learning_tool(self) -> None:
        import importlib

        import mureo.mcp.server as server_mod

        importlib.reload(server_mod)
        names = {t.name for t in server_mod._ALL_TOOLS}
        assert "mureo_learning_insights_get" in names

    def test_server_reserves_learning_tool_name_against_plugins(self) -> None:
        """The plugin discovery layer must refuse a third-party tool
        that tries to shadow this name."""
        import importlib

        import mureo.mcp.server as server_mod

        importlib.reload(server_mod)
        assert "mureo_learning_insights_get" in server_mod._LEARNING_NAMES
