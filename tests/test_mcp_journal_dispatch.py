"""The journal is wired into every exit of ``handle_call_tool`` (#758).

One record per call, whatever the family and whatever the outcome —
including the exits that never reach a handler (policy denial, invalid
arguments, exclusion-preflight refusal) and the one that raises. The
existing recorders are untouched: a plugin call still writes its own
``plugin_audit.jsonl`` line beside the journal one.
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.types import TextContent, Tool

from mureo.core.policy import PolicyDecision, PolicyGate
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry
from mureo.mcp import journal

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "JOURNAL.jsonl"
    monkeypatch.setattr(journal, "journal_path", lambda: path)
    return path


def _records(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _only(log: Path) -> dict[str, Any]:
    records = _records(log)
    assert len(records) == 1, records  # exactly one record per call
    return records[0]


async def test_ok_builtin_read_is_recorded(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock(return_value=[TextContent(type="text", text="plan")])
    with patch("mureo.mcp.server.handle_rollback_tool", new=handler):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    record = _only(log)
    assert record["tool"] == "rollback_plan_get"
    assert record["family"] == "rollback"
    assert record["outcome"] == "ok"
    assert record["mutating"] is False
    assert "reason" not in record
    assert record["args"] == {"index": 0}
    assert isinstance(record["duration_ms"], int)
    assert "source" not in record


async def test_arguments_are_snapshotted_at_entry(log: Path) -> None:
    """The journal records what was REQUESTED, not what the handler left.

    A handler that normalises, defaults or pops its arguments in place would
    otherwise rewrite history in the trail — precisely the trail an operator
    reaches for when asking what the agent actually asked for.
    """
    from mureo.mcp.server import handle_call_tool

    async def _mutating_handler(name: str, arguments: dict[str, Any]) -> list[Any]:
        arguments["index"] = 99
        arguments["injected"] = True
        return [TextContent(type="text", text="plan")]

    with patch("mureo.mcp.server.handle_rollback_tool", new=_mutating_handler):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    assert _only(log)["args"] == {"index": 0}


async def test_platform_error_envelope_is_not_recorded_as_ok(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    envelope = [TextContent(type="text", text="API error: PERMISSION_DENIED")]
    handler = AsyncMock(return_value=envelope)
    with patch("mureo.mcp.server.handle_rollback_tool", new=handler):
        await handle_call_tool("rollback_apply", {"index": 0, "confirm": True})

    record = _only(log)
    assert record["outcome"] == "platform_error"
    assert record["reason"] == "API error: PERMISSION_DENIED"
    assert record["mutating"] is True


async def test_policy_denial_is_recorded_as_denied(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    gate = MagicMock(spec=PolicyGate)
    gate.evaluate.return_value = PolicyDecision(
        allowed=False, reason="read-only mode is active"
    )
    handler = AsyncMock()
    with (
        patch("mureo.mcp.server._load_policy_gates", return_value=(gate,)),
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
    ):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    handler.assert_not_awaited()
    record = _only(log)
    assert record["outcome"] == "denied"
    assert record["reason"] == "read-only mode is active"


async def test_invalid_arguments_are_recorded_and_still_raise(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock()
    with (
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
        pytest.raises(ValueError, match="Invalid arguments"),
    ):
        await handle_call_tool("rollback_apply", {"index": -1, "confirm": True})

    handler.assert_not_awaited()
    record = _only(log)
    assert record["outcome"] == "invalid_args"
    assert "Invalid arguments for rollback_apply" in record["reason"]


async def test_preflight_refusal_is_recorded_as_refused(log: Path) -> None:
    from mureo.mcp import server as mod
    from mureo.mcp.exclusion_preflight import ExclusionPreflight

    refusal = ExclusionPreflight(
        tool="rollback_plan_get", refusal_reason="would silence 42% of delivery"
    )
    handler = AsyncMock()
    with (
        patch.object(
            mod, "exclusion_impact_preflight", AsyncMock(return_value=refusal)
        ),
        patch.object(mod, "handle_rollback_tool", new=handler),
    ):
        await mod.handle_call_tool("rollback_plan_get", {"index": 0})

    handler.assert_not_awaited()
    record = _only(log)
    assert record["outcome"] == "refused"
    assert record["reason"] == "would silence 42% of delivery"


async def test_raising_handler_is_recorded_and_still_propagates(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock(side_effect=RuntimeError("upstream exploded"))
    with (
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
        pytest.raises(RuntimeError, match="upstream exploded"),
    ):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    record = _only(log)
    assert record["outcome"] == "exception"
    assert record["reason"] == "RuntimeError: upstream exploded"


class _FakeGoogleAdsError(Exception):
    """A ``GoogleAdsException``-shaped failure, leaky ``__str__`` and all.

    The real one prints the ``grpc.Call`` repr — request metadata, developer
    token and ``authorization`` header included — so the journal must record
    the curated ``failure.errors[0].message`` instead (#603).
    """

    SECRET = "SECRET123"

    def __init__(self) -> None:
        super().__init__("grpc call repr")
        self.failure = SimpleNamespace(
            errors=[SimpleNamespace(message="CAMPAIGN_BUDGET_NOT_FOUND")]
        )

    def __str__(self) -> str:
        return f'debug_error_string = {{"developer-token": "{self.SECRET}"}}'


async def test_a_platform_exception_is_journalled_curated_not_repr(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock(side_effect=_FakeGoogleAdsError())
    with (
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
        pytest.raises(_FakeGoogleAdsError),
    ):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    record = _only(log)
    assert record["outcome"] == "exception"
    assert record["reason"] == "_FakeGoogleAdsError: CAMPAIGN_BUDGET_NOT_FOUND"
    assert _FakeGoogleAdsError.SECRET not in record["reason"]


async def test_a_cancelled_dispatch_is_journalled_once_and_still_propagates(
    log: Path,
) -> None:
    """Cancellation is an outcome of the call, so it is recorded.

    ``asyncio.CancelledError`` is a ``BaseException``: a hook that caught
    only ``Exception`` would let a cancelled call vanish from the trail,
    and one that swallowed it would break structured concurrency.
    """
    import asyncio

    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock(side_effect=asyncio.CancelledError())
    with (
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
        pytest.raises(asyncio.CancelledError),
    ):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    record = _only(log)
    assert record["outcome"] == "exception"
    assert record["reason"] == "CancelledError"


async def test_unknown_tool_is_recorded_as_an_unknown_family(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    with pytest.raises(ValueError, match="Unknown tool"):
        await handle_call_tool("not_a_tool_at_all", {})

    record = _only(log)
    assert record["family"] == "unknown"
    assert record["outcome"] == "exception"


async def test_rollback_leg_is_flagged(log: Path) -> None:
    from mureo.mcp.server import handle_call_tool

    handler = AsyncMock(return_value=[TextContent(type="text", text="ok")])
    with (
        patch("mureo.mcp._journal_hook.is_rollback_dispatch_active", return_value=True),
        patch("mureo.mcp.server.handle_rollback_tool", new=handler),
    ):
        await handle_call_tool("rollback_plan_get", {"index": 0})

    assert _only(log)["rollback"] is True


# ---------------------------------------------------------------------------
# Plugin branch — the journal is additive, plugin_audit keeps its own line
# ---------------------------------------------------------------------------


class _Plugin:
    name = "journal_plugin"
    display_name = "Journalled"
    capabilities = frozenset({Capability.READ_CAMPAIGNS})

    def mcp_tools(self) -> tuple[Tool, ...]:
        return (
            Tool(
                name="journal_plugin_echo",
                description="echo",
                inputSchema={
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                },
            ),
        )

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        return [TextContent(type="text", text=arguments.get("msg", ""))]


def _fake_discover(**_kw: Any) -> tuple[ProviderEntry, ...]:
    return (
        ProviderEntry(
            name=_Plugin.name,
            display_name=_Plugin.display_name,
            capabilities=_Plugin.capabilities,
            provider_class=_Plugin,
            source_distribution="journal-dist",
        ),
    )


@pytest.fixture
def server_with_plugin():
    """Reload server.py with discovery returning one plugin, then restore it.

    The discovery patch is a context manager rather than ``monkeypatch`` on
    purpose: a function-scoped ``monkeypatch`` is undone AFTER this
    fixture's teardown, so the restoring reload would run with the fake
    discovery still installed and leave the plugin tool in ``_ALL_TOOLS``
    for every later test module.
    """
    from mureo.mcp import server as mod

    with patch("mureo.core.providers.registry.discover_providers", new=_fake_discover):
        yield importlib.reload(mod)
    importlib.reload(mod)


async def test_plugin_call_writes_both_trails(
    log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_with_plugin
) -> None:
    from mureo.mcp import plugin_audit

    audit = tmp_path / "plugin_audit.jsonl"
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: audit)

    await server_with_plugin.handle_call_tool("journal_plugin_echo", {"msg": "hi"})

    record = _only(log)
    assert record["family"] == "plugin"
    assert record["source"] == "journal-dist"
    assert record["outcome"] == "ok"
    assert record["mutating"] is True  # undeclared ⇒ conservative
    # The pre-#758 plugin trail is untouched and still gets its own line.
    audit_lines = audit.read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["tool"] == "journal_plugin_echo"


async def test_raising_plugin_is_recorded_once_in_the_journal(
    log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server_with_plugin
) -> None:
    from mureo.mcp import plugin_audit

    monkeypatch.setattr(
        plugin_audit, "_audit_path", lambda: tmp_path / "plugin_audit.jsonl"
    )

    async def _boom(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        raise RuntimeError("plugin exploded")

    monkeypatch.setattr(_Plugin, "handle_mcp_tool", _boom)
    with pytest.raises(RuntimeError, match="plugin exploded"):
        await server_with_plugin.handle_call_tool("journal_plugin_echo", {"msg": "hi"})

    record = _only(log)
    assert record["family"] == "plugin"
    assert record["outcome"] == "exception"
    assert record["reason"] == "RuntimeError: plugin exploded"


def test_client_info_is_read_from_the_sdk_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Built from the SDK's own types, so a rename upstream fails here."""
    from mcp.types import ClientCapabilities, Implementation, InitializeRequestParams

    from mureo.mcp._journal_hook import capture_client_info

    monkeypatch.setattr(journal, "_client", None)
    params = InitializeRequestParams(
        protocolVersion="2025-06-18",
        capabilities=ClientCapabilities(),
        clientInfo=Implementation(name="Claude Code", version="1.4.2"),
    )
    server = SimpleNamespace(
        request_context=SimpleNamespace(session=SimpleNamespace(client_params=params))
    )
    capture_client_info(server)
    assert journal.client_info() == "Claude Code/1.4.2"


def test_client_info_stays_null_outside_a_request_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mureo.mcp._journal_hook import capture_client_info

    class _NoContext:
        @property
        def request_context(self) -> Any:
            raise LookupError("called outside of a request context")

    monkeypatch.setattr(journal, "_client", None)
    capture_client_info(_NoContext())  # must not raise
    assert journal.client_info() is None


def test_every_builtin_family_has_its_own_journal_label() -> None:
    """``tool_family`` answers from the dispatcher's own name sets."""
    from mureo.mcp._journal_hook import tool_family

    assert tool_family("rollback_plan_get") == "rollback"
    assert tool_family("mureo_batch_begin") == "batch"
    assert tool_family("mureo_external_changes_import") == "change_import"
    assert tool_family("search_console_sites_get") == "search_console"
    assert tool_family("mureo_learning_reset_preflight") == "learning_preflight"
    assert tool_family("definitely_not_a_tool") == "unknown"
