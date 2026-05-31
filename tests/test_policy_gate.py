"""Tests for the ``mureo.core.policy`` extension point (v0.9.23).

The OSS surface is intentionally tiny: a PolicyGate Protocol, a
PolicyDecision dataclass, and the dispatcher integration that
consults gates registered via the ``mureo.policy_gates`` entry-point
group. mureo OSS itself ships zero gates — third-party packages
(e.g. mureo-agency) supply the policy logic. These tests pin:

1. The Protocol + dataclass shape are stable.
2. The dispatcher consults gates AFTER name resolution but BEFORE
   dispatching to the handler.
3. Per-gate exception isolation — a broken gate must not break
   mureo; the gate is treated as "abstain" (allow) and the call
   continues.
4. Refuse messages surface the gate's ``reason`` to the agent.
5. Default behaviour (no gates registered) is byte-identical to
   v0.9.22 — zero overhead, every call dispatches.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.core.policy import PolicyDecision, PolicyGate

# ---------------------------------------------------------------------------
# Type-level pins
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolicyGateProtocol:
    def test_policy_decision_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        decision = PolicyDecision(allowed=True)
        with pytest.raises(FrozenInstanceError):
            decision.allowed = False  # type: ignore[misc]

    def test_policy_decision_default_reason_is_empty(self) -> None:
        assert PolicyDecision(allowed=True).reason == ""

    def test_policy_gate_is_runtime_checkable(self) -> None:
        class _MyGate:
            def evaluate(
                self, tool_name: str, arguments: dict[str, Any]
            ) -> PolicyDecision:
                return PolicyDecision(allowed=True)

        assert isinstance(_MyGate(), PolicyGate)

    def test_non_gate_object_fails_protocol_check(self) -> None:
        class _NotAGate:
            pass

        assert not isinstance(_NotAGate(), PolicyGate)


# ---------------------------------------------------------------------------
# Dispatcher integration — uses mureo.mcp.server.handle_call_tool
# ---------------------------------------------------------------------------


def _make_gate(decision: PolicyDecision) -> MagicMock:
    gate = MagicMock(spec=PolicyGate)
    gate.evaluate.return_value = decision
    return gate


def _make_raising_gate(exc: Exception) -> MagicMock:
    gate = MagicMock(spec=PolicyGate)
    gate.evaluate.side_effect = exc
    return gate


@pytest.mark.unit
@pytest.mark.asyncio
class TestDispatcherGateIntegration:
    """Pin that ``mureo.mcp.server.handle_call_tool`` consults gates
    before dispatching, with the right ordering and isolation
    semantics."""

    async def test_no_gates_registered_dispatches_as_today(self) -> None:
        from mureo.mcp.server import handle_call_tool

        fake_handler = AsyncMock(return_value=[MagicMock(text="result")])
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=()),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_awaited_once()
        assert result[0].text == "result"

    async def test_single_allowing_gate_dispatches(self) -> None:
        from mureo.mcp.server import handle_call_tool

        gate = _make_gate(PolicyDecision(allowed=True))
        fake_handler = AsyncMock(return_value=[MagicMock(text="result")])
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=(gate,)),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {"k": "v"})
        gate.evaluate.assert_called_once_with("rollback_plan_get", {"k": "v"})
        fake_handler.assert_awaited_once()
        assert result[0].text == "result"

    async def test_denying_gate_refuses_and_surfaces_reason(self) -> None:
        from mureo.mcp.server import handle_call_tool

        gate = _make_gate(
            PolicyDecision(allowed=False, reason="read-only mode is active")
        )
        fake_handler = AsyncMock()
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=(gate,)),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_not_awaited()
        text = result[0].text
        assert "rollback_plan_get" in text
        assert "read-only mode is active" in text
        assert "refused" in text.lower() or "denied" in text.lower()

    async def test_two_gates_any_deny_blocks(self) -> None:
        from mureo.mcp.server import handle_call_tool

        gate_allow = _make_gate(PolicyDecision(allowed=True))
        gate_deny = _make_gate(PolicyDecision(allowed=False, reason="nope"))
        fake_handler = AsyncMock()
        with (
            patch(
                "mureo.mcp.server._load_policy_gates",
                return_value=(gate_allow, gate_deny),
            ),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_not_awaited()
        assert "nope" in result[0].text

    async def test_gate_exception_is_isolated_and_logged(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A broken third-party gate MUST NOT break mureo. The gate
        is treated as 'abstain' (allow) and the failure is logged so
        an operator can diagnose it."""
        from mureo.mcp.server import handle_call_tool

        broken = _make_raising_gate(RuntimeError("gate import explode"))
        fake_handler = AsyncMock(return_value=[MagicMock(text="result")])
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=(broken,)),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
            caplog.at_level(logging.WARNING, logger="mureo.mcp.server"),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_awaited_once()
        assert result[0].text == "result"
        assert any(
            "gate" in r.message.lower() and "abstain" in r.message.lower()
            for r in caplog.records
        )

    @pytest.mark.parametrize(
        "bad_return",
        [None, True, False, "deny", ("deny", "x"), {"allowed": False}, 42],
        ids=["none", "true", "false", "string", "tuple", "dict", "int"],
    )
    async def test_non_policy_decision_return_is_abstain(
        self,
        bad_return: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A buggy gate that returns something other than
        :class:`PolicyDecision` MUST be treated as abstain (allow) +
        WARNING, not crash the dispatcher. Critical because a returned
        ``False`` would otherwise propagate to ``_refuse_text_content``
        and AttributeError there with no surrounding try/except."""
        from mureo.mcp.server import handle_call_tool

        gate = MagicMock(spec=PolicyGate)
        gate.evaluate.return_value = bad_return
        fake_handler = AsyncMock(return_value=[MagicMock(text="result")])
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=(gate,)),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
            caplog.at_level(logging.WARNING, logger="mureo.mcp.server"),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_awaited_once()
        assert result[0].text == "result"
        assert any(
            "not PolicyDecision" in r.message or "abstain" in r.message.lower()
            for r in caplog.records
        )

    async def test_refusal_does_not_echo_arguments(self) -> None:
        """The refusal payload sent to the agent MUST NOT echo the
        ``arguments`` dict. Arguments routinely contain account IDs,
        budget figures, and (for some plugin tools) credentials or
        tokens. The gate author controls ``reason``; the dispatcher
        controls what surrounds it. Pin that the surrounding text
        carries name + reason only."""
        from mureo.mcp.server import handle_call_tool

        sentinel_key = "sentinel_arg_key"
        sentinel_value = "sentinel_arg_value_must_not_leak"
        gate = _make_gate(PolicyDecision(allowed=False, reason="denied"))
        fake_handler = AsyncMock()
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=(gate,)),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool(
                "rollback_plan_get",
                {sentinel_key: sentinel_value},
            )
        text = result[0].text
        assert sentinel_key not in text
        assert sentinel_value not in text

    async def test_other_gate_still_consulted_after_one_raises(self) -> None:
        """After one gate raises, the dispatcher must continue to the
        next gate rather than short-circuiting. A subsequent gate's
        deny still blocks."""
        from mureo.mcp.server import handle_call_tool

        broken = _make_raising_gate(RuntimeError("boom"))
        denier = _make_gate(PolicyDecision(allowed=False, reason="still denied"))
        fake_handler = AsyncMock()
        with (
            patch(
                "mureo.mcp.server._load_policy_gates",
                return_value=(broken, denier),
            ),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {})
        fake_handler.assert_not_awaited()
        assert "still denied" in result[0].text


# ---------------------------------------------------------------------------
# Entry-point discovery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPolicyGateEntryPointDiscovery:
    def test_no_entry_points_returns_empty_tuple(self) -> None:
        """With no third-party packages installed, the discovery
        helper returns an empty tuple (zero overhead in the
        dispatcher)."""
        from mureo.mcp.server import _load_policy_gates

        with patch(
            "mureo.mcp.server._policy_gate_entry_points",
            return_value=(),
        ):
            assert _load_policy_gates() == ()

    def test_entry_point_returning_gate_instance_is_collected(self) -> None:
        from mureo.mcp.server import _load_policy_gates

        class _Gate:
            def evaluate(
                self, tool_name: str, arguments: dict[str, Any]
            ) -> PolicyDecision:
                return PolicyDecision(allowed=True)

        fake_ep = MagicMock()
        fake_ep.name = "test_gate"
        fake_ep.load.return_value = _Gate
        with patch(
            "mureo.mcp.server._policy_gate_entry_points",
            return_value=(fake_ep,),
        ):
            gates = _load_policy_gates()
        assert len(gates) == 1
        assert isinstance(gates[0], PolicyGate)

    def test_entry_point_load_failure_is_isolated(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If a third-party entry point fails to load (e.g. import
        error from a partial install), other gates must still load."""
        from mureo.mcp.server import _load_policy_gates

        class _Gate:
            def evaluate(
                self, tool_name: str, arguments: dict[str, Any]
            ) -> PolicyDecision:
                return PolicyDecision(allowed=True)

        broken_ep = MagicMock()
        broken_ep.name = "broken"
        broken_ep.load.side_effect = ImportError("partial install")
        good_ep = MagicMock()
        good_ep.name = "good"
        good_ep.load.return_value = _Gate
        with (
            patch(
                "mureo.mcp.server._policy_gate_entry_points",
                return_value=(broken_ep, good_ep),
            ),
            caplog.at_level(logging.WARNING, logger="mureo.mcp.server"),
        ):
            gates = _load_policy_gates()
        assert len(gates) == 1
        assert any("broken" in r.message for r in caplog.records)
