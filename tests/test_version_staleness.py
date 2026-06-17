"""Tests for stale-MCP-version detection and its push into tool output.

Covers `mureo.core.version_staleness` (the running-vs-installed comparison) and
the server-side injection that surfaces a restart warning in tool results
without the agent having to ask for a version.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.core import version_staleness as vs

pytestmark = pytest.mark.unit


class TestStalenessWarning:
    def test_running_equals_installed_is_silent(self) -> None:
        assert vs.staleness_warning(running="0.10.6", installed="0.10.6") is None

    def test_running_older_than_installed_warns(self) -> None:
        msg = vs.staleness_warning(running="0.10.5", installed="0.10.6")
        assert msg is not None
        assert "0.10.5" in msg and "0.10.6" in msg
        assert "restart" in msg.lower()

    def test_running_newer_than_installed_is_silent(self) -> None:
        """A dev/editable checkout ahead of the published dist must not nag."""
        assert vs.staleness_warning(running="0.11.0", installed="0.10.6") is None

    def test_missing_installed_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``installed=None`` means "look it up", so to exercise the genuinely
        # missing-metadata path stub the lookup to None. (Passing a literal
        # version would couple this test to the current release number — which
        # is exactly what broke it on a version bump.)
        monkeypatch.setattr(vs, "installed_version", lambda: None)
        assert vs.staleness_warning(running="0.10.6") is None

    def test_invalid_version_is_silent(self) -> None:
        assert vs.staleness_warning(running="0.10.6", installed="not-a-version") is None
        assert vs.staleness_warning(running="garbage", installed="0.10.6") is None

    def test_installed_version_returns_str_or_none(self) -> None:
        v = vs.installed_version()
        assert v is None or isinstance(v, str)


@pytest.mark.asyncio
class TestServerInjection:
    async def _call(self, monkeypatch: pytest.MonkeyPatch, warning: str | None) -> Any:
        import mureo.mcp.server as server

        monkeypatch.setattr(server, "_staleness_warned", False)
        monkeypatch.setattr(
            server, "_dispatch_tool", AsyncMock(return_value=["RESULT"])
        )
        monkeypatch.setattr(
            "mureo.core.version_staleness.staleness_warning",
            lambda: warning,
        )
        return await server.handle_call_tool("some_tool", {})

    async def test_stale_appends_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = await self._call(monkeypatch, "RESTART NEEDED")
        assert result[0] == "RESULT"
        assert getattr(result[-1], "text", None) == "RESTART NEEDED"

    async def test_current_appends_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = await self._call(monkeypatch, None)
        assert result == ["RESULT"]

    async def test_warns_only_once_per_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mureo.mcp.server as server

        monkeypatch.setattr(server, "_staleness_warned", False)
        monkeypatch.setattr(
            server, "_dispatch_tool", AsyncMock(return_value=["RESULT"])
        )
        monkeypatch.setattr(
            "mureo.core.version_staleness.staleness_warning",
            lambda: "RESTART NEEDED",
        )
        first = await server.handle_call_tool("some_tool", {})
        second = await server.handle_call_tool("some_tool", {})
        assert len(first) == 2  # result + warning
        assert second == ["RESULT"]  # latched — no repeat banner

    async def test_gate_refusal_skips_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A policy denial returns its refusal before dispatch — no banner."""
        import mureo.mcp.server as server
        from mureo.core.policy import PolicyDecision

        monkeypatch.setattr(server, "_staleness_warned", False)
        monkeypatch.setattr(
            server,
            "_evaluate_policy_gates",
            lambda name, args: PolicyDecision(allowed=False, reason="blocked"),
        )
        monkeypatch.setattr(
            "mureo.core.version_staleness.staleness_warning",
            lambda: "RESTART NEEDED",
        )
        result = await server.handle_call_tool("some_tool", {})
        text = " ".join(getattr(c, "text", "") for c in result)
        assert "RESTART NEEDED" not in text
        assert "blocked" in text

    async def test_unknown_tool_error_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper does not swallow the real dispatch's Unknown-tool error."""
        import mureo.mcp.server as server

        monkeypatch.setattr(server, "_staleness_warned", False)
        monkeypatch.setattr(
            "mureo.core.version_staleness.staleness_warning", lambda: None
        )
        with pytest.raises(ValueError, match="Unknown tool"):
            await server.handle_call_tool("definitely_not_a_registered_tool_xyz", {})
