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
6. The dispatch path enumerates and loads the gate set once per
   process (#633), without ever caching a *failure* — and therefore
   without picking up a mid-process install.
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
        # ``rollback_plan_get`` requires ``index`` — dispatch now runs the
        # inputSchema validation pass (#277), so pass schema-valid args.
        with (
            patch("mureo.mcp.server._load_policy_gates", return_value=()),
            patch("mureo.mcp.server.handle_rollback_tool", new=fake_handler),
        ):
            result = await handle_call_tool("rollback_plan_get", {"index": 0})
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
            result = await handle_call_tool("rollback_plan_get", {"index": 0})
        gate.evaluate.assert_called_once_with("rollback_plan_get", {"index": 0})
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
            result = await handle_call_tool("rollback_plan_get", {"index": 0})
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
            result = await handle_call_tool("rollback_plan_get", {"index": 0})
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


# ---------------------------------------------------------------------------
# What the dispatch path pays for the gate set (#633)
# ---------------------------------------------------------------------------


class _FakeEntryPoint:
    """A ``mureo.policy_gates`` entry point that counts its ``load()``.

    ``loader`` is called on every ``load()``, so a test can make the first
    load fail and a later one succeed.
    """

    def __init__(self, name: str, loader: Any) -> None:
        self.name = name
        self._loader = loader
        self.loads = 0

    def load(self) -> Any:
        self.loads += 1
        return self._loader()


class _AllowGate:
    """Minimal conforming gate — abstains on everything."""

    def evaluate(self, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        return PolicyDecision(allowed=True)


@pytest.mark.unit
class TestPolicyGateLoadCost:
    """``_load_policy_gates`` runs on every tool dispatch.

    Measured on Python 3.10 with four gates installed, the uncached version
    cost 11.76 ms per dispatch — of which 11.43 ms was
    ``importlib.metadata.entry_points(group=...)``, which re-stats and
    re-parses the environment on every call rather than costing
    "microseconds". These pin the cost away without weakening the isolation
    the loader exists to provide.
    """

    def test_the_entry_points_are_enumerated_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import server

        calls = 0

        def _enumerate() -> tuple[Any, ...]:
            nonlocal calls
            calls += 1
            return (_FakeEntryPoint("acme", lambda: _AllowGate),)

        monkeypatch.setattr(server, "_policy_gate_entry_points", _enumerate)

        for _ in range(5):
            assert len(server._load_policy_gates()) == 1

        assert calls == 1

    def test_each_gate_class_is_loaded_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``ep.load()`` imports third-party code; once per process is enough."""
        from mureo.mcp import server

        ep = _FakeEntryPoint("acme", lambda: _AllowGate)
        monkeypatch.setattr(server, "_policy_gate_entry_points", lambda: (ep,))

        for _ in range(5):
            assert len(server._load_policy_gates()) == 1

        assert ep.loads == 1

    def test_the_dispatch_path_does_not_re_enumerate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property that matters is on ``_evaluate_policy_gates``."""
        from mureo.mcp import server

        ep = _FakeEntryPoint("acme", lambda: _AllowGate)
        calls = 0

        def _enumerate() -> tuple[Any, ...]:
            nonlocal calls
            calls += 1
            return (ep,)

        monkeypatch.setattr(server, "_policy_gate_entry_points", _enumerate)

        for _ in range(5):
            assert server._evaluate_policy_gates("mureo_state_get", {}) is None

        assert (calls, ep.loads) == (1, 1)

    def test_a_fresh_instance_is_constructed_per_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The class is cached; the instance is not.

        ``mureo.core.policy.PolicyGate`` promises third-party authors that
        "instance attributes do NOT persist across calls" and that a gate
        needing cross-call state must put it on a class attribute. Reusing
        one instance would silently break every gate written to that
        contract, so what is memoized is the loaded class.
        """
        from mureo.mcp import server

        monkeypatch.setattr(
            server,
            "_policy_gate_entry_points",
            lambda: (_FakeEntryPoint("acme", lambda: _AllowGate),),
        )

        first = server._load_policy_gates()
        second = server._load_policy_gates()

        assert type(first[0]) is type(second[0])
        assert first[0] is not second[0]

    def test_a_failed_load_is_retried_not_remembered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A dropped gate is a missing guardrail; never cache one.

        A transient import error must not remove a gate for the life of the
        process, so the failure is re-attempted on the next dispatch while
        the gates that did load keep loading.
        """
        from mureo.mcp import server

        outcomes: list[Any] = [ImportError("partial install"), _AllowGate]

        def _load_flaky() -> Any:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        flaky = _FakeEntryPoint("flaky", _load_flaky)
        healthy = _FakeEntryPoint("healthy", lambda: _AllowGate)
        monkeypatch.setattr(
            server, "_policy_gate_entry_points", lambda: (flaky, healthy)
        )

        with caplog.at_level(logging.WARNING, logger="mureo.mcp.server"):
            first = server._load_policy_gates()
        assert len(first) == 1  # the healthy gate still loaded
        assert any("flaky" in record.message for record in caplog.records)

        assert len(server._load_policy_gates()) == 2
        assert (flaky.loads, healthy.loads) == (2, 1)

    def test_a_failed_enumeration_is_never_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Could not enumerate" is a moment, not a fact about the machine.

        Same rule as :func:`mureo.context.platform_guards.installed_platform_names`
        — caching it would mean one unlucky call runs the rest of the process
        with zero third-party gates.
        """
        from mureo.mcp import server

        outcomes: list[tuple[Any, ...] | None] = [
            None,
            (_FakeEntryPoint("acme", lambda: _AllowGate),),
        ]
        monkeypatch.setattr(
            server, "_policy_gate_entry_points", lambda: outcomes.pop(0)
        )

        assert server._load_policy_gates() == ()
        assert len(server._load_policy_gates()) == 1

    def test_the_environment_is_re_read_when_the_enumerator_is_swapped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The memo is keyed by the enumerator, so a test's pin cannot leak.

        Every test installs a fake gate by replacing
        ``_policy_gate_entry_points``; a different function object structurally
        misses the memo, so no test can be served the previous test's gates and
        nothing has to remember to clear a cache (the #631 pattern).
        """
        from mureo.mcp import server

        class _DenyGate:
            def evaluate(
                self, tool_name: str, arguments: dict[str, Any]
            ) -> PolicyDecision:
                return PolicyDecision(allowed=False, reason="nope")

        monkeypatch.setattr(
            server,
            "_policy_gate_entry_points",
            lambda: (_FakeEntryPoint("allow", lambda: _AllowGate),),
        )
        assert isinstance(server._load_policy_gates()[0], _AllowGate)

        monkeypatch.setattr(
            server,
            "_policy_gate_entry_points",
            lambda: (_FakeEntryPoint("deny", lambda: _DenyGate),),
        )
        assert isinstance(server._load_policy_gates()[0], _DenyGate)

    def test_a_gate_installed_mid_process_is_not_picked_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deliberate trade, pinned so it cannot be changed by accident.

        A distribution pip-installed into a running server registers no tools
        (``_PLUGIN_TOOLS`` / ``_PLUGIN_DISPATCH`` / ``_PLUGIN_SEMANTICS`` are
        module-import-time) and no runtime context
        (``get_runtime_context`` caches the first one it resolves), so picking
        its *gate* up alone produced a half-configured process. The gate set is
        now fixed at the first dispatch; changing it costs a restart, which is
        what changing the tool set already cost.
        """
        from mureo.mcp import server

        installed = [_FakeEntryPoint("acme", lambda: _AllowGate)]
        monkeypatch.setattr(
            server, "_policy_gate_entry_points", lambda: tuple(installed)
        )

        assert len(server._load_policy_gates()) == 1

        installed.append(_FakeEntryPoint("late", lambda: _AllowGate))

        assert len(server._load_policy_gates()) == 1
