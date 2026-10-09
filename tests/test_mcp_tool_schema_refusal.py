"""A schema that cannot check a call must refuse it, not wave it through.

``inputSchema`` is what makes a declared ``minimum: 1`` on a budget or a bid
real (#277), so the direction of a schema fault matters more than its message.
Before #807, a schema that failed to compile with anything but ``SchemaError``
stopped the server from starting, and one that failed when applied (a ``$ref``
into nothing) failed the call. Deferring compilation to the first call must not
turn either of those into "the handler runs with bounds nobody checked":

* :class:`TestTheHandlerNeverRuns` — through the real dispatcher, a refused call
  never reaches the tool's handler; a ``SchemaError`` schema, as before #807,
  is served unvalidated.
* :class:`TestApplyTimeRefusal` — the refusal itself: its type, its cause, and
  how it is reported (both channels for a plugin, once in full, then quietly).
* :class:`TestReportsAreAscii` — a report survives an ASCII-only console.
"""

from __future__ import annotations

import io
import logging
import warnings
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mureo.mcp import _tool_validation
from mureo.mcp._tool_validation import LazyToolValidators, ToolSchemaUnusableError
from mureo.plugin_warnings import PluginToolWarning

_LOGGER_NAME = _tool_validation.logger.name

#: Passes ``check_schema``; resolving the ``$ref`` is deferred to the first
#: validation, which then raises. The bound it hides is a spend-shaped minimum.
_UNRESOLVABLE = {
    "type": "object",
    "properties": {"daily_budget": {"$ref": "#/nowhere", "minimum": 1}},
    "required": ["daily_budget"],
}
_BELOW_THE_MINIMUM = {"daily_budget": 0}


def _tool(name: str, schema: object) -> SimpleNamespace:
    """A stand-in for ``mcp.types.Tool`` that accepts a deliberately bad schema."""
    return SimpleNamespace(name=name, inputSchema=schema)


def _own_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """This module's records only: ``caplog`` sits on the root logger."""
    return [record for record in caplog.records if record.name == _LOGGER_NAME]


def _recursion_error(schema: object) -> None:
    raise RecursionError("maximum recursion depth exceeded")


def _routed_tool() -> str:
    """A built-in tool the dispatcher routes to a handler we can replace."""
    from mureo.mcp import server

    return sorted(server._ANALYSIS_NAMES)[0]


async def _dispatch(
    validators: LazyToolValidators, name: str, handler: AsyncMock
) -> None:
    """Call ``name`` through the real dispatcher, with ``handler`` behind it."""
    from mureo.mcp import server

    with (
        patch.object(server, "_TOOL_VALIDATORS", validators),
        patch.object(server, "handle_analysis_tool", handler),
    ):
        await server.handle_call_tool(name, dict(_BELOW_THE_MINIMUM))


@pytest.mark.unit
class TestTheHandlerNeverRuns:
    """Measured at the handler, not at the function that raises."""

    async def test_an_unappliable_schema_never_reaches_the_handler(self) -> None:
        name = _routed_tool()
        validators = LazyToolValidators([_tool(name, _UNRESOLVABLE)])
        handler = AsyncMock(return_value=[])

        with pytest.raises(ToolSchemaUnusableError, match=name):
            await _dispatch(validators, name, handler)

        handler.assert_not_awaited()

    async def test_a_schema_that_will_not_compile_never_reaches_the_handler(
        self,
    ) -> None:
        """A non-``SchemaError`` compile failure used to stop the server.

        Compiling is lazy now, so the server is already up when it happens; the
        equivalent is that this one tool cannot be called.
        """
        name = _routed_tool()
        validators = LazyToolValidators([_tool(name, {"type": "object"})])
        handler = AsyncMock(return_value=[])

        with (
            patch.object(Draft202012Validator, "check_schema", _recursion_error),
            pytest.raises(ToolSchemaUnusableError, match="RecursionError"),
        ):
            await _dispatch(validators, name, handler)

        handler.assert_not_awaited()

    async def test_a_refusal_is_repeated_on_every_call(self) -> None:
        name = _routed_tool()
        validators = LazyToolValidators([_tool(name, {"type": "object"})])
        handler = AsyncMock(return_value=[])

        with patch.object(Draft202012Validator, "check_schema", _recursion_error):
            for _ in range(3):
                with pytest.raises(ToolSchemaUnusableError):
                    await _dispatch(validators, name, handler)

        handler.assert_not_awaited()

    async def test_a_schema_error_is_still_served_unvalidated(self) -> None:
        """The one case that stays open, exactly as before #807.

        Not a valid JSON Schema at all: mureo's own schemas cannot ship like
        that (tests/test_mcp_strict_input_schemas.py), and for a plugin's the
        documented consequence is a lost guardrail, reported, not a lost tool.
        """
        name = _routed_tool()
        validators = LazyToolValidators([_tool(name, {"type": 1})])
        handler = AsyncMock(return_value=[])

        await _dispatch(validators, name, handler)

        handler.assert_awaited_once()


@pytest.mark.unit
class TestApplyTimeRefusal:
    """What the refusal is, and how it is reported."""

    def test_the_refusal_names_the_tool_and_chains_the_cause(self) -> None:
        Draft202012Validator.check_schema(_UNRESOLVABLE)  # compiling is happy
        validators = LazyToolValidators([_tool("reffy", _UNRESOLVABLE)])

        with pytest.raises(ToolSchemaUnusableError) as raised:
            validators.validate_tool_input("reffy", dict(_BELOW_THE_MINIMUM))

        assert "reffy" in str(raised.value)
        assert "could not be applied" in str(raised.value)
        # Not a caller error, and not a third-party type leaking out.
        assert not isinstance(raised.value, ValueError)
        assert type(raised.value).__module__ == _tool_validation.__name__
        assert raised.value.__cause__ is not None

    def test_a_schema_error_is_not_a_refusal(self) -> None:
        validators = LazyToolValidators([_tool("bad", {"type": 1})])

        validators.validate_tool_input("bad", {"anything": "goes"})

    def test_a_plugins_apply_failure_reaches_both_channels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        validators = LazyToolValidators(
            [_tool("plug_reffy", _UNRESOLVABLE)], plugin_names={"plug_reffy"}
        )

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            pytest.warns(PluginToolWarning, match="plug_reffy"),
            pytest.raises(ToolSchemaUnusableError),
        ):
            validators.validate_tool_input("plug_reffy", dict(_BELOW_THE_MINIMUM))

        messages = [record.getMessage() for record in _own_records(caplog)]
        assert len(messages) == 1, messages
        assert "plug_reffy" in messages[0]
        assert "refused" in messages[0]

    def test_a_builtins_apply_failure_is_logged_but_not_warned(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        validators = LazyToolValidators([_tool("reffy", _UNRESOLVABLE)])

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            warnings.catch_warnings(record=True) as recorded,
            pytest.raises(ToolSchemaUnusableError),
        ):
            warnings.simplefilter("always")
            validators.validate_tool_input("reffy", dict(_BELOW_THE_MINIMUM))

        assert len(_own_records(caplog)) == 1
        assert [w for w in recorded if issubclass(w.category, PluginToolWarning)] == []

    def test_strict_mode_turns_a_plugins_apply_failure_into_an_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The documented strict mode has to see this case too.

        The call is refused either way; strict mode is how an operator who asked
        for plugin faults to be fatal gets to see this one as one.
        """
        validators = LazyToolValidators(
            [_tool("plug_reffy", _UNRESOLVABLE)], plugin_names={"plug_reffy"}
        )

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", PluginToolWarning)
            with pytest.raises(PluginToolWarning, match="plug_reffy"):
                validators.validate_tool_input("plug_reffy", dict(_BELOW_THE_MINIMUM))
            # Reported once; the next call is still refused, quietly.
            with pytest.raises(ToolSchemaUnusableError):
                validators.validate_tool_input("plug_reffy", dict(_BELOW_THE_MINIMUM))

        # The log record went out before the warning raised.
        assert len(_own_records(caplog)) == 1

    def test_repeated_failures_are_logged_in_full_once_then_counted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An agent retrying in a loop must not write a full WARNING per call."""
        validators = LazyToolValidators([_tool("reffy", _UNRESOLVABLE)])

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            for _ in range(3):
                with pytest.raises(ToolSchemaUnusableError):
                    validators.validate_tool_input("reffy", dict(_BELOW_THE_MINIMUM))

        records = _own_records(caplog)
        levels = [record.levelno for record in records]
        assert levels == [logging.WARNING, logging.DEBUG, logging.DEBUG], levels
        assert "3 calls refused" in records[-1].getMessage()

    def test_a_compile_failure_is_reported_once_and_refused_every_time(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        validators = LazyToolValidators([_tool("deep", {"type": "object"})])
        calls: list[object] = []

        def exploding_check(schema: object) -> None:
            calls.append(schema)
            raise RecursionError("maximum recursion depth exceeded")

        with (
            caplog.at_level(logging.WARNING, logger=_LOGGER_NAME),
            patch.object(Draft202012Validator, "check_schema", exploding_check),
        ):
            for _ in range(2):
                with pytest.raises(ToolSchemaUnusableError) as raised:
                    validators.validate_tool_input("deep", {})

        assert len(calls) == 1, f"recompiled {len(calls)} times"
        assert isinstance(raised.value.__cause__, RecursionError)
        assert len(_own_records(caplog)) == 1


@pytest.mark.unit
class TestReportsAreAscii:
    """A report must reach an operator whose console is ASCII-only."""

    def test_a_cut_problem_ends_in_ascii(self) -> None:
        long_problem = SchemaError("x" * 1000)

        line = _tool_validation._one_line(long_problem)

        assert len(line) == _tool_validation._PROBLEM_CHAR_BUDGET
        assert line.endswith("...")
        line.encode("ascii")

    def test_a_report_quoting_a_non_ascii_schema_is_ascii(self) -> None:
        problem = _tool_validation._one_line(SchemaError("予算 は 1 以上 " * 40))

        report = _tool_validation._render([("plug_ja", problem)])

        report.encode("ascii")
        assert "plug_ja" in report

    def test_the_record_reaches_an_ascii_stream(self) -> None:
        """On an ASCII stream one bad character used to cost the whole record."""
        stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger(_LOGGER_NAME)
        logger.addHandler(handler)
        validators = LazyToolValidators([_tool("bad", {"type": "予算" * 200})])
        try:
            validators.get("bad")
        finally:
            logger.removeHandler(handler)

        stream.flush()
        written = stream.buffer.getvalue().decode("ascii")
        assert "tool bad:" in written, written
