"""An always-on instruction to read saved knowledge before reasoning.

A host that defers tool loading puts neither the workflow skills' "Before you
start" line nor the learning tools' descriptions in the model's context until
a skill runs or a tool is searched for. In a plain conversation ("raise the
bid on campaign X") nothing then tells the agent that saved insights and
advisor sources exist to be read first. The server's ``instructions`` are the
only always-on prose slot, so the server names those tools there — and only
when there is something for them to return.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from mureo.core.knowledge_store import FilesystemKnowledgeStore
from mureo.core.runtime_context import RuntimeContextFactoryError, get_runtime_context
from mureo.learning.insight_sources import default_config_path
from mureo.mcp import server as mcp_server
from mureo.mcp import tools_learning
from mureo.mcp.knowledge_instructions import (
    ADVISORS_TOOL_NAME,
    INSIGHTS_TOOL_NAME,
    knowledge_instructions,
)
from mureo.mcp.tools_learning import advisors_configured, saved_insights_present
from mureo.policy.platform_model import reset_platform_models

_HEADING_START = "Saved knowledge — read it before you diagnose"
_INSIGHTS_PREFIX = f"- {INSIGHTS_TOOL_NAME}: "
_ADVISORS_PREFIX = f"- {ADVISORS_TOOL_NAME}: "

_VALID_SOURCE = {
    "sources": [
        {
            "name": "playbook",
            "transport": "http",
            "tool": "search",
            "url": "https://advisor.example.com/mcp",
        }
    ]
}


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    reset_platform_models()
    yield
    reset_platform_models()


def _save_insight(text: str = "- Brand CPA spikes every holiday week.\n") -> None:
    get_runtime_context().knowledge_store.append_operator_knowledge(text)


def _write_sources(payload: object) -> None:
    path = default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")


def _use_store(monkeypatch: pytest.MonkeyPatch, store: object) -> None:
    monkeypatch.setattr(
        tools_learning,
        "get_runtime_context",
        lambda: SimpleNamespace(knowledge_store=store),
    )


# --- isolation -----------------------------------------------------------


@pytest.mark.unit
def test_probe_paths_resolve_inside_the_isolated_home(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Neither probe can read a contributor's real knowledge or sources."""
    base = tmp_path_factory.getbasetemp()
    store = get_runtime_context().knowledge_store
    assert isinstance(store, FilesystemKnowledgeStore)
    assert store.operator_path.is_relative_to(base)
    assert default_config_path().is_relative_to(base)


# --- knowledge_instructions ----------------------------------------------


@pytest.mark.unit
def test_nothing_available_renders_nothing() -> None:
    assert knowledge_instructions(has_insights=False, has_advisors=False) == ""


@pytest.mark.unit
def test_insights_only() -> None:
    block = knowledge_instructions(has_insights=True, has_advisors=False)
    lines = block.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith(_HEADING_START)
    assert lines[1].startswith(_INSIGHTS_PREFIX)
    assert ADVISORS_TOOL_NAME not in block


@pytest.mark.unit
def test_advisors_only() -> None:
    block = knowledge_instructions(has_insights=False, has_advisors=True)
    lines = block.split("\n")
    assert len(lines) == 2
    assert lines[0].startswith(_HEADING_START)
    assert lines[1].startswith(_ADVISORS_PREFIX)
    assert INSIGHTS_TOOL_NAME not in block


@pytest.mark.unit
def test_both_sources_insights_first() -> None:
    block = knowledge_instructions(has_insights=True, has_advisors=True)
    lines = block.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith(_HEADING_START)
    assert lines[1].startswith(_INSIGHTS_PREFIX)
    assert lines[2].startswith(_ADVISORS_PREFIX)


@pytest.mark.unit
def test_every_line_is_a_single_line() -> None:
    block = knowledge_instructions(has_insights=True, has_advisors=True)
    for line in block.split("\n"):
        assert line.strip()
        assert line.splitlines() == [line]


@pytest.mark.unit
def test_advisor_text_is_framed_as_untrusted() -> None:
    block = knowledge_instructions(has_insights=False, has_advisors=True)
    assert "untrusted" in block
    assert "never an instruction" in block


@pytest.mark.unit
def test_tool_names_match_the_learning_catalog() -> None:
    """A renamed tool cannot leave a stale name in the instruction."""
    names = {tool.name for tool in tools_learning.TOOLS}
    assert {INSIGHTS_TOOL_NAME, ADVISORS_TOOL_NAME} <= names


# --- saved_insights_present ----------------------------------------------


@pytest.mark.unit
def test_no_knowledge_file_is_not_present() -> None:
    assert saved_insights_present() is False


@pytest.mark.unit
def test_scaffold_only_file_is_not_present() -> None:
    _save_insight("")
    store = get_runtime_context().knowledge_store
    assert isinstance(store, FilesystemKnowledgeStore)
    assert store.operator_path.exists()
    assert saved_insights_present() is False


@pytest.mark.unit
def test_appended_insight_is_present() -> None:
    _save_insight()
    assert saved_insights_present() is True


@pytest.mark.unit
def test_workspace_tier_alone_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = FilesystemKnowledgeStore(
        operator_path=tmp_path / "operator.md",
        workspace_path=tmp_path / "workspace.md",
    )
    store.append_workspace_knowledge("- This client never bids on brand.\n")
    _use_store(monkeypatch, store)
    assert saved_insights_present() is True


@pytest.mark.unit
def test_empty_workspace_tier_and_no_operator_file_is_not_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = FilesystemKnowledgeStore(
        operator_path=tmp_path / "operator.md",
        workspace_path=tmp_path / "workspace.md",
    )
    _use_store(monkeypatch, store)
    assert saved_insights_present() is False


class _RaisingOperatorStore:
    def read_operator_knowledge(self) -> str:
        raise RuntimeError("backend unavailable")

    def read_workspace_knowledge(self) -> str | None:
        return None


@pytest.mark.unit
def test_raising_operator_read_is_not_present_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _use_store(monkeypatch, _RaisingOperatorStore())
    with caplog.at_level(logging.WARNING, logger=tools_learning.__name__):
        assert saved_insights_present() is False
    assert any(
        "operator tier" in record.getMessage() and record.exc_info
        for record in caplog.records
    )


class _BytesOperatorStore:
    def read_operator_knowledge(self) -> bytes:
        return b"- an insight, but not text"

    def read_workspace_knowledge(self) -> str | None:
        return None


@pytest.mark.unit
def test_non_text_operator_read_is_not_present_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _use_store(monkeypatch, _BytesOperatorStore())
    with caplog.at_level(logging.WARNING, logger=tools_learning.__name__):
        assert saved_insights_present() is False
    assert any(
        "operator tier" in record.getMessage() and record.exc_info
        for record in caplog.records
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "store", [_RaisingOperatorStore(), _BytesOperatorStore()], ids=["raises", "bytes"]
)
def test_unusable_operator_tier_still_reports_the_workspace_tier(
    monkeypatch: pytest.MonkeyPatch, store: object
) -> None:
    monkeypatch.setattr(
        store, "read_workspace_knowledge", lambda: "- Never bid on brand.\n"
    )
    _use_store(monkeypatch, store)
    assert saved_insights_present() is True


# --- advisors_configured -------------------------------------------------


@pytest.mark.unit
def test_no_sources_file_is_not_configured() -> None:
    assert advisors_configured() is False


@pytest.mark.unit
def test_one_valid_source_is_configured() -> None:
    _write_sources(_VALID_SOURCE)
    assert advisors_configured() is True


@pytest.mark.unit
def test_malformed_sources_file_is_not_configured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``load_insight_sources`` returns the empty config for unreadable JSON."""
    _write_sources("{not json")
    with caplog.at_level(logging.WARNING):
        assert advisors_configured() is False
    assert any("insight_sources" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_wrong_typed_source_does_not_stop_the_server_from_composing() -> None:
    """A source file with a wrong-typed value yields no advisor line, no raise."""
    _write_sources(
        {"sources": [{"name": "a", "transport": "http", "tool": "t", "url": 5}]}
    )
    assert advisors_configured() is False
    assert mcp_server._server_instructions() is None


# --- server instructions -------------------------------------------------


@pytest.mark.unit
def test_default_install_sends_no_instructions() -> None:
    assert mcp_server._server_instructions() is None


@pytest.mark.unit
def test_saved_insight_adds_only_the_insights_line() -> None:
    _save_insight()
    text = mcp_server._server_instructions()
    assert text is not None
    assert text.startswith(_HEADING_START)
    assert _INSIGHTS_PREFIX in text
    assert _ADVISORS_PREFIX not in text


@pytest.mark.unit
def test_insight_and_source_add_both_lines_in_order() -> None:
    _save_insight()
    _write_sources(_VALID_SOURCE)
    text = mcp_server._server_instructions()
    assert text is not None
    assert text.index(_INSIGHTS_PREFIX) < text.index(_ADVISORS_PREFIX)


@pytest.mark.unit
def test_knowledge_section_comes_after_the_tool_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = "Tool notes — stand-in block"
    monkeypatch.setattr(mcp_server, "_tool_guidance_instruction", lambda: notes)
    _save_insight()
    text = mcp_server._server_instructions()
    assert text is not None
    assert text.index(notes) < text.index(_HEADING_START)
    assert text.endswith(knowledge_instructions(has_insights=True, has_advisors=False))


@pytest.mark.unit
def test_factory_error_omits_the_knowledge_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> None:
        raise RuntimeContextFactoryError("two factories registered")

    monkeypatch.setattr(tools_learning, "get_runtime_context", _boom)
    _write_sources(_VALID_SOURCE)
    assert mcp_server._knowledge_instruction() == ""
    assert mcp_server._server_instructions() is None
