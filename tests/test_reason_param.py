"""``reason`` is declared by every mutating tool's schema (#758, phase 2).

The parameter is injected into the SERVED tool list rather than written
into each of the ~120 mutating schemas by hand, so a tool added later
gets it for free and no registry module has to remember. This module
pins that the injection covers exactly the mutating surface, that it
leaves the registry's own ``Tool`` objects untouched, and that the
dispatcher strips ``reason`` before the handler ever sees it.
"""

from __future__ import annotations

import logging

import pytest
from mcp.types import Tool

from mureo.core.actor import ACTION_REASON_MAX_CHARS
from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.mcp._reason_param import (
    REASON_EXEMPT_BUILTINS,
    REASON_PROPERTY,
    STATE_WRITING_BUILTINS,
    inject_reason_params,
    split_call_reason,
    with_reason_property,
)

pytestmark = pytest.mark.unit

#: Built-in tools that declared a ``reason`` parameter of their OWN before
#: #758 existed: on these two it is the operator-facing "why was this
#: account not collected" note that is PERSISTED as content, not a
#: rationale for a change. They keep their own semantics — no injection,
#: no stripping — so they are excluded from the blanket assertions below.
_OWN_REASON_TOOLS = frozenset(
    {
        "mureo_state_platform_not_collected_set",
        "mureo_state_workspace_not_collected_set",
    }
)


def _builtin_registry_tools() -> list[Tool]:
    """Every built-in ``Tool`` straight from its registry module."""
    from mureo.mcp import (
        tools_analysis,
        tools_analytics_registry,
        tools_batch,
        tools_change_import,
        tools_creative_studio,
        tools_google_ads,
        tools_learning,
        tools_learning_preflight,
        tools_meta_ads,
        tools_mureo_context,
        tools_rollback,
        tools_search_console,
    )

    modules = (
        tools_google_ads,
        tools_meta_ads,
        tools_search_console,
        tools_rollback,
        tools_batch,
        tools_change_import,
        tools_analysis,
        tools_mureo_context,
        tools_analytics_registry,
        tools_learning,
        tools_learning_preflight,
        tools_creative_studio,
    )
    return [tool for module in modules for tool in module.TOOLS]


def _served_builtins() -> dict[str, Tool]:
    from mureo.mcp import server

    return {
        tool.name: tool
        for tool in server._ALL_TOOLS
        if tool.name not in server._PLUGIN_NAMES
    }


def _reason_schema(tool: Tool) -> dict | None:
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return None
    declared = properties.get("reason")
    return declared if isinstance(declared, dict) else None


class TestInjectedSurface:
    def test_every_mutating_builtin_declares_reason(self) -> None:
        missing = [
            name
            for name, tool in _served_builtins().items()
            if is_mutating_builtin_tool(name)
            and name not in _OWN_REASON_TOOLS
            and name not in REASON_EXEMPT_BUILTINS
            and _reason_schema(tool) is None
        ]
        assert missing == [], f"mutating tools without a reason parameter: {missing}"

    def test_the_injected_reason_is_bounded_by_the_shared_cap(self) -> None:
        wrong = [
            (name, _reason_schema(tool))
            for name, tool in _served_builtins().items()
            if is_mutating_builtin_tool(name)
            and name not in _OWN_REASON_TOOLS
            and name not in REASON_EXEMPT_BUILTINS
            and _reason_schema(tool) != REASON_PROPERTY
        ]
        assert wrong == [], f"reason declared with the wrong shape: {wrong}"
        assert REASON_PROPERTY["maxLength"] == ACTION_REASON_MAX_CHARS

    def test_no_read_only_builtin_gains_a_reason_parameter(self) -> None:
        from mureo.mcp import server

        offenders = [
            name
            for name, tool in _served_builtins().items()
            if not is_mutating_builtin_tool(name)
            and name not in STATE_WRITING_BUILTINS
            and _reason_schema(tool) is not None
        ]
        assert offenders == []
        assert not any(
            not is_mutating_builtin_tool(name) and name not in STATE_WRITING_BUILTINS
            for name in server._REASON_TOOLS
            if name not in server._PLUGIN_NAMES
        )

    def test_tools_with_their_own_reason_are_left_alone(self) -> None:
        from mureo.mcp import server

        for name in _OWN_REASON_TOOLS:
            assert name not in server._REASON_TOOLS
            declared = _reason_schema(_served_builtins()[name])
            assert declared is not None
            assert "maxLength" not in declared

    def test_additional_properties_false_survives_injection(self) -> None:
        open_schemas = [
            name
            for name, tool in _served_builtins().items()
            if tool.inputSchema.get("additionalProperties") is not False
        ]
        assert open_schemas == []

    def test_the_registry_objects_are_untouched(self) -> None:
        """Injection returns NEW tools; the module constants are shared
        state that tests, docs and the plugin ABI all read."""
        leaked = [
            tool.name
            for tool in _builtin_registry_tools()
            if tool.name not in _OWN_REASON_TOOLS and _reason_schema(tool) is not None
        ]
        assert leaked == []


class TestTheInjectedSetIsNotJustTheClassifier:
    """``is_mutating_builtin_tool`` answers a different question.

    It drives the STRATEGY.md reminder and the journal's ``mutating`` flag,
    where it means "this changed a live ad account". Three tools change
    STATE.json instead -- a change set, the conversion vocabulary, an
    imported history -- and are worth a rationale for the same reason, so
    the injected surface is the classifier PLUS those three, MINUS the one
    tool whose own entry already carries a rationale.
    """

    def test_the_state_writers_are_asked_for_a_reason(self) -> None:
        from mureo.mcp import server

        for name in STATE_WRITING_BUILTINS:
            assert not is_mutating_builtin_tool(name), (
                f"{name} is now classified as mutating; drop it from "
                "STATE_WRITING_BUILTINS rather than declaring it twice"
            )
            assert name in server._REASON_TOOLS
            assert _reason_schema(_served_builtins()[name]) == REASON_PROPERTY

    def test_the_action_log_writer_is_exempt(self) -> None:
        """It RECORDS a change; it is not the change. The rationale lives on
        the entry it writes, and a second one at call level would be a
        different sentence about the same event."""
        from mureo.mcp import server

        for name in REASON_EXEMPT_BUILTINS:
            assert name not in server._REASON_TOOLS
            assert _reason_schema(_served_builtins()[name]) is None

    def test_the_two_sets_do_not_overlap(self) -> None:
        assert not (STATE_WRITING_BUILTINS & REASON_EXEMPT_BUILTINS)


class TestAToolWithNoPropertiesMap:
    def test_it_is_not_injected_and_produces_no_rationale(self) -> None:
        """No object ``properties`` map means no correct place to put the
        parameter -- inventing one would write a schema its author did not."""
        tool = Tool(name="odd_plugin_write", description="d", inputSchema={})
        injected, names = inject_reason_params([tool], lambda _n: True)
        assert injected == [tool]
        assert names == frozenset()
        assert split_call_reason("odd_plugin_write", {"reason": "r"}, names) == (
            None,
            {"reason": "r"},
        )

    def test_the_exemption_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Silent is how a mutating tool ends up with no rationale and
        nobody notices for a release."""
        tool = Tool(name="odd_plugin_write", description="d", inputSchema={})
        with caplog.at_level(logging.INFO, logger="mureo.mcp._reason_param"):
            inject_reason_params([tool], lambda _n: True)
        assert "odd_plugin_write" in caplog.text


class TestReasonPropertyIsShared:
    def test_the_definition_cannot_be_mutated(self) -> None:
        """One wording on every tool: a caller editing this in place would
        change the schema of all ~120 at once."""
        with pytest.raises(TypeError):
            REASON_PROPERTY["maxLength"] = 1  # type: ignore[index]

    def test_an_injected_tool_gets_its_own_copy(self) -> None:
        tool = Tool(
            name="t", description="d", inputSchema={"type": "object", "properties": {}}
        )
        injected = with_reason_property(tool)
        injected.inputSchema["properties"]["reason"]["maxLength"] = 1
        assert REASON_PROPERTY["maxLength"] == ACTION_REASON_MAX_CHARS


class TestWithReasonProperty:
    def _tool(self, schema: dict) -> Tool:
        return Tool(name="t", description="d", inputSchema=schema)

    def test_a_new_tool_is_returned_with_the_property_added(self) -> None:
        original = self._tool(
            {
                "type": "object",
                "properties": {"campaign_id": {"type": "string"}},
                "additionalProperties": False,
            }
        )
        injected = with_reason_property(original)
        assert injected is not original
        assert injected.inputSchema["properties"]["reason"] == REASON_PROPERTY
        assert injected.inputSchema["additionalProperties"] is False
        assert "reason" not in original.inputSchema["properties"]

    def test_the_original_nested_schema_is_not_shared(self) -> None:
        original = self._tool(
            {"type": "object", "properties": {"a": {"type": "object"}}}
        )
        injected = with_reason_property(original)
        injected.inputSchema["properties"]["a"]["type"] = "string"
        assert original.inputSchema["properties"]["a"]["type"] == "object"

    def test_a_tool_declaring_its_own_reason_is_returned_unchanged(self) -> None:
        own = {"type": "string", "description": "why the collection failed"}
        original = self._tool({"type": "object", "properties": {"reason": own}})
        assert with_reason_property(original) is original

    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "string"},
            {"type": "object"},
            {"type": "object", "properties": []},
        ],
    )
    def test_a_schema_with_no_properties_map_is_returned_unchanged(
        self, schema: dict
    ) -> None:
        original = self._tool(schema)
        assert with_reason_property(original) is original


class TestInjectReasonParams:
    def test_only_the_mutating_names_are_reported_as_injected(self) -> None:
        tools = [
            Tool(
                name=name,
                description="d",
                inputSchema={"type": "object", "properties": {}},
            )
            for name in ("read_one", "write_one", "write_two")
        ]
        injected, names = inject_reason_params(
            tools, lambda name: name.startswith("write")
        )
        assert names == frozenset({"write_one", "write_two"})
        assert [t.name for t in injected] == ["read_one", "write_one", "write_two"]
        assert injected[0] is tools[0]
        assert "reason" in injected[1].inputSchema["properties"]

    def test_a_mutating_tool_with_its_own_reason_is_not_reported(self) -> None:
        tools = [
            Tool(
                name="write_one",
                description="d",
                inputSchema={
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                },
            )
        ]
        injected, names = inject_reason_params(tools, lambda _name: True)
        assert names == frozenset()
        assert injected[0] is tools[0]


class TestSplitCallReason:
    def test_reason_is_popped_for_an_injected_tool(self) -> None:
        arguments = {"campaign_id": "c1", "reason": "  CPA is 3x target  "}
        reason, rest = split_call_reason(
            "meta_ads_campaigns_pause",
            arguments,
            frozenset({"meta_ads_campaigns_pause"}),
        )
        assert reason == "CPA is 3x target"
        assert rest == {"campaign_id": "c1"}
        assert arguments == {"campaign_id": "c1", "reason": "  CPA is 3x target  "}

    def test_a_tool_outside_the_injected_set_keeps_its_own_reason(self) -> None:
        arguments = {"reason": "the token expired"}
        reason, rest = split_call_reason(
            "mureo_state_workspace_not_collected_set", arguments, frozenset()
        )
        assert reason is None
        assert rest is arguments

    def test_a_blank_reason_reads_as_absent(self) -> None:
        reason, rest = split_call_reason("t", {"reason": "   "}, frozenset({"t"}))
        assert reason is None
        assert rest == {}

    def test_an_over_long_reason_is_refused_rather_than_truncated(self) -> None:
        arguments = {"reason": "x" * (ACTION_REASON_MAX_CHARS + 1)}
        with pytest.raises(ValueError, match="reason"):
            split_call_reason("t", arguments, frozenset({"t"}))
