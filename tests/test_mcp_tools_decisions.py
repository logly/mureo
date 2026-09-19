"""``mureo_decision_record`` through the dispatcher (#758, phase 3).

The tool is the only way an agent can put a proposal, the operator's answer
to it and the figures it was judged on somewhere that survives the session.
These tests go through ``handle_call_tool`` rather than the handler, because
the schema is half the contract: an unknown status and an over-long title
have to be refused BEFORE anything reaches STATE.json.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.mcp import journal

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """cwd = tmp_path, with the journal pointed inside it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "JOURNAL.jsonl")
    return tmp_path


_VALID: dict[str, Any] = {
    "status": "proposed",
    "title": "Pause the generic ad group",
    "rationale": "CPA has been 3x target for 14 days at 40 conversions.",
}


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from mureo.mcp.server import handle_call_tool

    result = await handle_call_tool(name, arguments)
    return json.loads(result[0].text)


def _journal_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_tool_is_registered_in_the_mureo_context_family() -> None:
    from mureo.mcp.tools_mureo_context import TOOLS

    assert "mureo_decision_record" in {t.name for t in TOOLS}


def test_schema_is_closed_and_requires_the_three_fields() -> None:
    from mureo.mcp.tools_mureo_context import TOOLS

    tool = next(t for t in TOOLS if t.name == "mureo_decision_record")
    schema = tool.inputSchema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["status", "title", "rationale"]
    assert set(schema["properties"]) == {
        "status",
        "title",
        "rationale",
        "metrics",
        "platform",
        "campaign_id",
        "entity_type",
        "entity_id",
        "related_actions",
        "supersedes",
        "batch_id",
        "path",
    }


def test_the_tool_is_not_classified_as_a_platform_mutation() -> None:
    """It writes STATE.json, not an ad account: no strategy reminder, and
    no injected call-level ``reason`` — it carries its own ``rationale``."""
    from mureo.core.strategy_reminder import is_mutating_builtin_tool
    from mureo.mcp._reason_param import (
        REASON_EXEMPT_BUILTINS,
        STATE_WRITING_BUILTINS,
    )

    assert is_mutating_builtin_tool("mureo_decision_record") is False
    assert "mureo_decision_record" not in STATE_WRITING_BUILTINS
    # Declared, not merely implied by the name not ending in a mutating
    # suffix: renaming the tool must not silently start injecting a second
    # rationale beside the one it already carries.
    assert "mureo_decision_record" in REASON_EXEMPT_BUILTINS


def test_the_tool_declares_no_reason_property() -> None:
    from mureo.mcp.server import _ALL_TOOLS

    tool = next(t for t in _ALL_TOOLS if t.name == "mureo_decision_record")
    assert "reason" not in tool.inputSchema["properties"]


# ---------------------------------------------------------------------------
# Schema refusals
# ---------------------------------------------------------------------------


async def test_unknown_status_is_refused_as_invalid_args(workspace: Path) -> None:
    with pytest.raises(ValueError, match="Invalid arguments"):
        await _call("mureo_decision_record", {**_VALID, "status": "maybe"})
    record = _journal_records(workspace / "JOURNAL.jsonl")[-1]
    assert record["tool"] == "mureo_decision_record"
    assert record["outcome"] == "invalid_args"
    assert not (workspace / "STATE.json").exists()


async def test_over_long_title_is_refused_as_invalid_args(workspace: Path) -> None:
    from mureo.context.decisions import DECISION_TITLE_MAX_CHARS

    with pytest.raises(ValueError, match="Invalid arguments"):
        await _call(
            "mureo_decision_record",
            {**_VALID, "title": "x" * (DECISION_TITLE_MAX_CHARS + 1)},
        )
    assert (
        _journal_records(workspace / "JOURNAL.jsonl")[-1]["outcome"] == "invalid_args"
    )


async def test_a_nested_metrics_value_is_refused(workspace: Path) -> None:
    with pytest.raises(ValueError):
        await _call(
            "mureo_decision_record", {**_VALID, "metrics": {"w": {"cpa": 5200}}}
        )


async def test_an_over_long_metric_string_is_refused(workspace: Path) -> None:
    from mureo.context.decisions import DECISION_METRIC_VALUE_MAX_CHARS

    with pytest.raises(ValueError):
        await _call(
            "mureo_decision_record",
            {
                **_VALID,
                "metrics": {"note": "x" * (DECISION_METRIC_VALUE_MAX_CHARS + 1)},
            },
        )
    assert not (workspace / "STATE.json").exists()


async def test_too_many_related_actions_are_refused(workspace: Path) -> None:
    from mureo.context.decisions import DECISION_RELATED_ACTIONS_MAX

    with pytest.raises(ValueError, match="Invalid arguments"):
        await _call(
            "mureo_decision_record",
            {
                **_VALID,
                "related_actions": list(range(DECISION_RELATED_ACTIONS_MAX + 1)),
            },
        )


async def test_the_schema_states_the_same_bounds_the_model_enforces() -> None:
    """A schema looser than the model turns a caller error into an mureo
    error: the dispatcher would accept it and the handler would raise."""
    from mureo.context.decisions import (
        DECISION_METRIC_VALUE_MAX_CHARS,
        DECISION_METRICS_MAX_KEYS,
        DECISION_RELATED_ACTIONS_MAX,
    )
    from mureo.mcp.tools_mureo_context import TOOLS

    props = next(t for t in TOOLS if t.name == "mureo_decision_record").inputSchema[
        "properties"
    ]
    assert props["related_actions"]["maxItems"] == DECISION_RELATED_ACTIONS_MAX
    assert props["metrics"]["maxProperties"] == DECISION_METRICS_MAX_KEYS
    assert (
        props["metrics"]["additionalProperties"]["maxLength"]
        == DECISION_METRIC_VALUE_MAX_CHARS
    )


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_a_valid_call_appends_and_is_journalled(workspace: Path) -> None:
    payload = await _call(
        "mureo_decision_record",
        {**_VALID, "metrics": {"cpa_7d": 5200, "conversions_7d": 45}},
    )

    assert payload["index"] == 0
    assert payload["decisions_total"] == 1
    decision = payload["decision"]
    assert decision["status"] == "proposed"
    assert decision["title"] == _VALID["title"]
    assert decision["metrics"] == {"cpa_7d": 5200, "conversions_7d": 45}
    assert decision["decision_id"].startswith("dec-")
    assert decision["recorded_at"]
    assert decision["session_id"]

    stored = json.loads((workspace / "STATE.json").read_text(encoding="utf-8"))
    assert stored["decisions"][0]["decision_id"] == decision["decision_id"]

    record = _journal_records(workspace / "JOURNAL.jsonl")[-1]
    assert record["tool"] == "mureo_decision_record"
    assert record["family"] == "mureo_context"
    assert record["outcome"] == "ok"
    assert record["mutating"] is False


async def test_the_server_mints_the_id_and_the_timestamp(workspace: Path) -> None:
    """Neither is caller-supplied: the schema has no property for them, so an
    agent's idea of 'now' can never be persisted (#460)."""
    first = await _call("mureo_decision_record", _VALID)
    second = await _call("mureo_decision_record", _VALID)
    assert first["decision"]["decision_id"] != second["decision"]["decision_id"]
    assert second["index"] == 1
    assert second["decisions_total"] == 2


async def test_state_get_shows_the_section_afterwards(workspace: Path) -> None:
    await _call("mureo_decision_record", _VALID)
    state = await _call("mureo_state_get", {})
    assert [d["title"] for d in state["decisions"]] == [_VALID["title"]]


async def test_a_superseding_record_is_a_second_record(workspace: Path) -> None:
    proposed = await _call("mureo_decision_record", _VALID)
    adopted = await _call(
        "mureo_decision_record",
        {
            **_VALID,
            "status": "adopted",
            "rationale": "Operator approved on the morning call.",
            "supersedes": proposed["decision"]["decision_id"],
        },
    )
    assert adopted["index"] == 1
    assert adopted["decisions_total"] == 2

    state = await _call("mureo_state_get", {})
    assert [d["status"] for d in state["decisions"]] == ["proposed", "adopted"]
    assert state["decisions"][1]["supersedes"] == proposed["decision"]["decision_id"]


async def test_an_unknown_supersedes_is_a_caller_error(workspace: Path) -> None:
    with pytest.raises(ValueError, match="supersedes"):
        await _call("mureo_decision_record", {**_VALID, "supersedes": "dec-nope"})
    assert not (workspace / "STATE.json").exists()


async def test_an_unknown_batch_id_is_a_caller_error(workspace: Path) -> None:
    """``BatchError`` is mapped onto the dispatcher's caller-error channel so
    the journal classifies it like any other bad argument."""
    with pytest.raises(ValueError, match="batch_id"):
        await _call("mureo_decision_record", {**_VALID, "batch_id": "batch-nope"})


async def test_related_actions_are_validated_against_the_log(
    workspace: Path,
) -> None:
    with pytest.raises(ValueError, match="related_actions"):
        await _call("mureo_decision_record", {**_VALID, "related_actions": [0]})

    await _call(
        "mureo_state_action_log_append",
        {"entry": {"action": "paused the generic ad group", "platform": "google_ads"}},
    )
    payload = await _call("mureo_decision_record", {**_VALID, "related_actions": [0]})
    assert payload["decision"]["related_actions"] == [0]


async def test_a_path_outside_the_workspace_is_refused(workspace: Path) -> None:
    with pytest.raises(ValueError):
        await _call(
            "mureo_decision_record", {**_VALID, "path": "../outside/STATE.json"}
        )


async def test_the_journal_records_the_rationale_and_no_injected_reason(
    workspace: Path,
) -> None:
    """``rationale`` is a declared parameter of THIS tool, so it rides in
    ``args`` like any other. The dispatcher must not also file it under the
    journal's own ``rationale`` key, which belongs to the injected
    call-level ``reason`` this tool deliberately does not take."""
    await _call("mureo_decision_record", _VALID)
    record = _journal_records(workspace / "JOURNAL.jsonl")[-1]
    assert record["args"]["rationale"] == _VALID["rationale"]
    # The journal's own ``rationale`` key belongs to the INJECTED call-level
    # reason. This tool takes none, so the key must be absent entirely: its
    # presence would mean two sentences about one call, one of them filed as
    # if it answered "why was this dispatched".
    assert "rationale" not in record
    assert "reason" not in record["args"]


async def test_a_secret_in_the_rationale_is_redacted_before_it_is_stored(
    workspace: Path,
) -> None:
    """A model that quotes the failing request into its reasoning must not
    leak the key into the file the operator commits.

    STATE.json and the response, which is the record as stored. The
    journal's ``args`` are a separate, pre-existing question: it masks by
    KEY name (``mask_arguments``) and does not scrub string VALUES, so an
    ``action_log`` entry's own ``reason`` survives there verbatim too.
    Changing that changes every plugin-audit record as well, so it is not
    settled here.
    """
    payload = await _call(
        "mureo_decision_record",
        {**_VALID, "rationale": "retrying after api_key=sk-live-ABCDEF was rejected"},
    )
    assert "sk-live-ABCDEF" not in payload["decision"]["rationale"]
    assert "api_key=***" in payload["decision"]["rationale"]
    state = (workspace / "STATE.json").read_text(encoding="utf-8")
    assert "sk-live-ABCDEF" not in state


async def test_control_characters_never_reach_state_json(workspace: Path) -> None:
    payload = await _call("mureo_decision_record", {**_VALID, "title": "a\x00b\x1bc"})
    assert payload["decision"]["title"] == "abc"


# ---------------------------------------------------------------------------
# mureo_state_get scoping
# ---------------------------------------------------------------------------


async def test_state_get_returns_every_decision_by_default(workspace: Path) -> None:
    await _call("mureo_decision_record", _VALID)
    await _call("mureo_decision_record", {**_VALID, "status": "deferred"})
    state = await _call("mureo_state_get", {})
    assert len(state["decisions"]) == 2
    assert state["decisions_total"] == 2
    assert "decisions_scope" not in state


async def test_state_get_none_omits_the_section_and_keeps_the_count(
    workspace: Path,
) -> None:
    await _call("mureo_decision_record", _VALID)
    state = await _call("mureo_state_get", {"decisions": "none"})
    assert "decisions" not in state
    assert state["decisions_total"] == 1
    assert state["decisions_scope"] == "none"


async def test_a_document_with_no_decisions_gains_no_marker(workspace: Path) -> None:
    """The legacy response shape is unchanged for a workspace that has never
    recorded one — no empty list, no zero count."""
    state = await _call("mureo_state_get", {})
    assert "decisions" not in state
    assert "decisions_total" not in state


async def test_scoping_the_action_log_does_not_hide_the_decisions(
    workspace: Path,
) -> None:
    """Two independent switches. Dropping the log to save context must not
    silently drop the reasoning trail with it."""
    await _call("mureo_decision_record", _VALID)
    state = await _call("mureo_state_get", {"action_log": "none"})
    assert "action_log" not in state
    assert len(state["decisions"]) == 1


async def test_an_unknown_decisions_scope_is_refused(workspace: Path) -> None:
    with pytest.raises(ValueError, match="Invalid arguments"):
        await _call("mureo_state_get", {"decisions": "pending"})
