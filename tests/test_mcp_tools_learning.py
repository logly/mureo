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
4. The handler reads BOTH KnowledgeStore tiers: the legacy
   operator-only payload is returned byte-identically when no
   workspace tier is configured, and a two-section payload (with the
   workspace-wins precedence note) when the workspace tier has
   content.
"""

from __future__ import annotations

import logging
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
        ignore. ``additionalProperties: false`` now enforces that: an
        unknown key is rejected at validation instead of dropped."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        assert tool.inputSchema == {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

    def test_tool_description_references_learn_skill(self) -> None:
        """A reader inspecting the tool description should understand
        where the data comes from and why they should call it."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        assert "/learn" in tool.description
        assert "diagnostic" in tool.description.lower()

    def test_tool_description_documents_both_tiers_and_precedence(self) -> None:
        """The agent decides how to weigh conflicting insights from the
        description alone — it must say both tiers are returned and
        which one wins."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        lowered = tool.description.lower()
        assert "operator" in lowered
        assert "workspace" in lowered
        assert "precede" in lowered or "precedence" in lowered

    def test_tool_still_takes_no_arguments_after_two_tier_read(self) -> None:
        """Reading both tiers must not introduce a scope argument —
        mureo-pro and every bundled skill call this tool with ``{}``."""
        mod = _import_learning_tools()
        tool = next(t for t in mod.TOOLS if t.name == "mureo_learning_insights_get")
        assert tool.inputSchema["properties"] == {}
        assert tool.inputSchema["required"] == []


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
        fake_store.read_workspace_knowledge.return_value = None
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
        fake_store.read_workspace_knowledge.return_value = None
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
        fake_store.read_workspace_knowledge.return_value = None
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
            "### Use micro-conversions when CV is sparse\n\n" "**Situation:** ...\n"
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


_OPERATOR_TEXT = (
    "## Learned Insights\n\n### Cap ad groups at 3 when the daily budget is small\n"
)
_WORKSPACE_TEXT = "## Learned Insights\n\n### This account's CV fires 2 days late\n"


def _fake_store(operator: str, workspace: str | None) -> MagicMock:
    """Build a KnowledgeStore double whose BOTH readers are pinned.

    Leaving ``read_workspace_knowledge`` unconfigured on a bare
    ``MagicMock`` would return a truthy ``Mock``, which is neither the
    ``str`` nor the ``None`` the Protocol allows — the tests would then
    exercise a state no real backend can produce.
    """
    store = MagicMock()
    store.read_operator_knowledge.return_value = operator
    store.read_workspace_knowledge.return_value = workspace
    return store


async def _run_handler(mod: object, store: MagicMock) -> str:
    fake_ctx = MagicMock(knowledge_store=store)
    with patch("mureo.mcp.tools_learning.get_runtime_context", return_value=fake_ctx):
        result = await mod.handle_tool("mureo_learning_insights_get", {})
    assert len(result) == 1
    return str(result[0].text)


@pytest.mark.unit
class TestTwoTierRead:
    """The handler surfaces the workspace tier alongside the operator
    tier. Every path where the workspace tier contributes nothing must
    stay byte-identical to the pre-two-tier behaviour, because every
    bundled diagnostic skill (and mureo-pro) already consumes it."""

    @pytest.mark.asyncio
    async def test_workspace_absent_returns_legacy_operator_payload(self) -> None:
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_TEXT, None))
        assert text == _OPERATOR_TEXT

    @pytest.mark.asyncio
    async def test_workspace_absent_and_operator_empty_returns_legacy_guidance(
        self,
    ) -> None:
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store("", None))
        assert text == mod._NO_INSIGHTS_MESSAGE

    @pytest.mark.asyncio
    async def test_workspace_absent_and_scaffold_only_returns_legacy_guidance(
        self,
    ) -> None:
        from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD

        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_SCAFFOLD, None))
        assert text == mod._NO_INSIGHTS_MESSAGE

    @pytest.mark.asyncio
    async def test_empty_workspace_text_is_treated_as_absent(self) -> None:
        """A configured-but-never-written workspace tier reads as ``""``
        (or whitespace). It must contribute nothing rather than emit an
        empty section the agent would quote."""
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_TEXT, "   \n\n  "))
        assert text == _OPERATOR_TEXT

    @pytest.mark.asyncio
    async def test_non_string_workspace_return_is_treated_as_absent(self) -> None:
        """``KnowledgeStore`` is a third-party-implementable Protocol —
        a backend returning something other than ``str | None`` must
        degrade to the legacy payload, not crash the diagnostic
        workflow."""
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_TEXT, object()))
        assert text == _OPERATOR_TEXT

    @pytest.mark.asyncio
    async def test_raising_workspace_read_is_treated_as_absent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A workspace tier that *raises* must degrade exactly like one
        that is absent. A remote- or DB-backed third-party store can
        fail transiently; a broken workspace tier must never take down
        the whole tool, because the operator tier — which read fine —
        is what 7 diagnostic workflows depend on."""
        mod = _import_learning_tools()
        store = _fake_store(_OPERATOR_TEXT, None)
        store.read_workspace_knowledge.side_effect = RuntimeError(
            "workspace backend unreachable"
        )

        with caplog.at_level(logging.WARNING, logger="mureo.mcp.tools_learning"):
            text = await _run_handler(mod, store)

        assert text == _OPERATOR_TEXT
        assert any(
            "workspace" in rec.message.lower() and rec.levelno >= logging.WARNING
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_raising_workspace_read_still_reports_no_insights_when_empty(
        self,
    ) -> None:
        """Degrading to legacy means the *whole* legacy contract, including
        the empty-knowledge-base sentinel."""
        mod = _import_learning_tools()
        store = _fake_store("", None)
        store.read_workspace_knowledge.side_effect = OSError("disk gone")

        text = await _run_handler(mod, store)
        assert text == mod._NO_INSIGHTS_MESSAGE

    @pytest.mark.asyncio
    async def test_both_tiers_populated_composes_two_labelled_sections(self) -> None:
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_TEXT, _WORKSPACE_TEXT))

        assert "Cap ad groups at 3 when the daily budget is small" in text
        assert "This account's CV fires 2 days late" in text
        assert mod._OPERATOR_SECTION_HEADING in text
        assert mod._WORKSPACE_SECTION_HEADING in text
        # Operator section first, workspace section second.
        assert text.index(mod._OPERATOR_SECTION_HEADING) < text.index(
            mod._WORKSPACE_SECTION_HEADING
        )

    @pytest.mark.asyncio
    async def test_both_tiers_populated_states_workspace_precedence(self) -> None:
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_TEXT, _WORKSPACE_TEXT))
        lowered = text.lower()
        assert "precede" in lowered or "precedence" in lowered
        assert "conflict" in lowered

    @pytest.mark.asyncio
    async def test_workspace_content_with_empty_operator_still_shows_workspace(
        self,
    ) -> None:
        """The workspace tier alone is real content — returning the
        'nothing saved yet' sentinel here would hide it."""
        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store("", _WORKSPACE_TEXT))

        assert mod._NO_INSIGHTS_MESSAGE not in text
        assert "This account's CV fires 2 days late" in text
        assert mod._WORKSPACE_SECTION_HEADING in text
        assert "no operator-tier insights" in text.lower()

    @pytest.mark.asyncio
    async def test_workspace_content_with_scaffold_only_operator(self) -> None:
        from mureo.core.knowledge_store import _OPERATOR_SCAFFOLD

        mod = _import_learning_tools()
        text = await _run_handler(mod, _fake_store(_OPERATOR_SCAFFOLD, _WORKSPACE_TEXT))

        assert mod._NO_INSIGHTS_MESSAGE not in text
        assert "This account's CV fires 2 days late" in text
        assert "no operator-tier insights" in text.lower()

    @pytest.mark.asyncio
    async def test_both_tiers_are_read_exactly_once(self) -> None:
        mod = _import_learning_tools()
        store = _fake_store(_OPERATOR_TEXT, _WORKSPACE_TEXT)
        await _run_handler(mod, store)
        store.read_operator_knowledge.assert_called_once()
        store.read_workspace_knowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_never_appends_to_either_tier(self) -> None:
        """The read tool must stay read-only."""
        mod = _import_learning_tools()
        store = _fake_store(_OPERATOR_TEXT, _WORKSPACE_TEXT)
        await _run_handler(mod, store)
        store.append_operator_knowledge.assert_not_called()
        store.append_workspace_knowledge.assert_not_called()


@pytest.mark.unit
class TestMureoProCompatibility:
    """mureo-pro pins ``tools_learning.get_runtime_context`` as a
    module-level name and monkeypatches it. Renaming, aliasing, or
    caching the store at import time would break their shim."""

    def test_get_runtime_context_is_a_module_level_name(self) -> None:
        mod = _import_learning_tools()
        assert hasattr(mod, "get_runtime_context")

    @pytest.mark.asyncio
    async def test_store_is_resolved_at_call_time(self) -> None:
        """Two calls with two different patched contexts must see two
        different stores — i.e. no module-level caching."""
        mod = _import_learning_tools()
        first = await _run_handler(mod, _fake_store("first tier text\n", None))
        second = await _run_handler(mod, _fake_store("second tier text\n", None))
        assert first == "first tier text\n"
        assert second == "second tier text\n"


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
