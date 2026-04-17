"""MCP tool tests for analysis.anomalies.check.

Locks in that the tool is registered on the aggregate MCP server, its
schema rejects malformed input, and the handler correctly composes
``baseline_from_history`` with ``detect_anomalies`` over STATE.json.
Path sandboxing mirrors rollback.apply — ``state_file`` must resolve
inside CWD.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import write_state_file
from mureo.mcp.server import handle_list_tools
from mureo.mcp.tools_analysis import TOOLS, handle_tool


def _write_state(path: Path, entries: list[ActionLogEntry]) -> None:
    write_state_file(path, StateDocument(version="2", action_log=tuple(entries)))


def _history_entry(
    *,
    cost: float = 10_000,
    impressions: int = 50_000,
    clicks: int = 500,
    conversions: float = 50,
    cpa: float | None = None,
    ctr: float | None = None,
    timestamp: str = "2026-04-08",
    campaign_id: str = "C1",
) -> ActionLogEntry:
    metrics: dict[str, float] = {
        "cost": cost,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
    }
    if cpa is not None:
        metrics["cpa"] = cpa
    if ctr is not None:
        metrics["ctr"] = ctr
    return ActionLogEntry(
        timestamp=timestamp,
        action="adjust_bid",
        platform="google_ads",
        campaign_id=campaign_id,
        metrics_at_action=metrics,
    )


@pytest.fixture
def sandboxed_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.unit
class TestToolRegistration:
    @pytest.mark.asyncio
    async def test_registered_in_server(self) -> None:
        tools = await handle_list_tools()
        names = {t.name for t in tools}
        assert "analysis.anomalies.check" in names

    def test_schema_requires_current(self) -> None:
        tool = next(t for t in TOOLS if t.name == "analysis.anomalies.check")
        schema = tool.inputSchema
        assert "current" in schema["required"]
        current_props = schema["properties"]["current"]["properties"]
        assert "campaign_id" in current_props


@pytest.mark.unit
class TestAnomalyHandler:
    @pytest.mark.asyncio
    async def test_zero_spend_detected_without_history(
        self, sandboxed_cwd: Path
    ) -> None:
        """With no STATE.json, zero-spend still fires as CRITICAL."""
        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {
                    "campaign_id": "C1",
                    "cost": 0,
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                },
                "had_prior_spend": True,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["campaign_id"] == "C1"
        assert payload["baseline"] is None
        severities = {a["severity"] for a in payload["anomalies"]}
        assert "critical" in severities
        metrics = {a["metric"] for a in payload["anomalies"]}
        assert "cost" in metrics

    @pytest.mark.asyncio
    async def test_cpa_spike_detected_with_history(self, sandboxed_cwd: Path) -> None:
        """CPA spike of 2.3x the historical median fires CRITICAL."""
        entries = [
            _history_entry(cost=10_000, conversions=50, cpa=5000) for _ in range(7)
        ]
        _write_state(sandboxed_cwd / "STATE.json", entries)

        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {
                    "campaign_id": "C1",
                    "cost": 30_000,
                    "impressions": 50_000,
                    "clicks": 500,
                    "conversions": 60,
                    "cpa": 11500,
                },
                "had_prior_spend": True,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["baseline"] is not None
        cpa_anomaly = next(
            a for a in payload["anomalies"] if a["metric"] == "cpa"
        )
        assert cpa_anomaly["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_insufficient_history_no_baseline(
        self, sandboxed_cwd: Path
    ) -> None:
        """Below min_baseline_entries, baseline is None and CPA is not evaluated."""
        _write_state(
            sandboxed_cwd / "STATE.json",
            [_history_entry(cost=10_000, conversions=50, cpa=5000)],
        )
        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {
                    "campaign_id": "C1",
                    "cost": 30_000,
                    "impressions": 50_000,
                    "clicks": 500,
                    "conversions": 60,
                    "cpa": 11500,
                },
                "had_prior_spend": True,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["baseline"] is None
        assert all(a["metric"] != "cpa" for a in payload["anomalies"])

    @pytest.mark.asyncio
    async def test_missing_campaign_id_raises(self, sandboxed_cwd: Path) -> None:
        with pytest.raises(ValueError, match="campaign_id"):
            await handle_tool(
                "analysis.anomalies.check",
                {"current": {"cost": 0}},
            )

    @pytest.mark.asyncio
    async def test_missing_current_raises(self, sandboxed_cwd: Path) -> None:
        with pytest.raises(ValueError, match="current"):
            await handle_tool("analysis.anomalies.check", {})

    @pytest.mark.asyncio
    async def test_path_traversal_refused(self, sandboxed_cwd: Path) -> None:
        outside = sandboxed_cwd.parent / "rogue_STATE.json"
        _write_state(outside, [])
        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {"campaign_id": "C1", "cost": 0},
                "state_file": str(outside),
            },
        )
        payload = json.loads(result[0].text)
        assert (
            "error" in payload
            and "current working directory" in payload["error"]
        )

    @pytest.mark.asyncio
    async def test_ctr_drop_detected_with_history(self, sandboxed_cwd: Path) -> None:
        """CTR drop to 0.3x baseline fires CRITICAL."""
        entries = [
            _history_entry(
                cost=10_000,
                impressions=50_000,
                clicks=500,
                ctr=0.01,
                conversions=50,
            )
            for _ in range(7)
        ]
        _write_state(sandboxed_cwd / "STATE.json", entries)

        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {
                    "campaign_id": "C1",
                    "cost": 10_000,
                    "impressions": 50_000,
                    "clicks": 100,  # 0.2% CTR = 0.2× baseline
                    "conversions": 50,
                    "ctr": 0.002,
                },
                "had_prior_spend": True,
            },
        )
        payload = json.loads(result[0].text)
        ctr_anomaly = next(a for a in payload["anomalies"] if a["metric"] == "ctr")
        assert ctr_anomaly["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_had_prior_spend_false_suppresses_zero_spend(
        self, sandboxed_cwd: Path
    ) -> None:
        """Fresh campaigns never trigger zero-spend alerts."""
        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {"campaign_id": "C_NEW", "cost": 0},
                "had_prior_spend": False,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["anomalies"] == []

    @pytest.mark.asyncio
    async def test_symlink_state_file_refused(self, sandboxed_cwd: Path) -> None:
        """A symlink inside CWD pointing outside must be refused even if the
        resolved target happens to also live under CWD (defense in depth:
        swapping the symlink target is agent-writable)."""
        outside = sandboxed_cwd.parent / "rogue_STATE.json"
        _write_state(outside, [])
        link = sandboxed_cwd / "STATE.json"
        link.symlink_to(outside)

        result = await handle_tool(
            "analysis.anomalies.check",
            {"current": {"campaign_id": "C1", "cost": 0}, "state_file": "STATE.json"},
        )
        payload = json.loads(result[0].text)
        assert "error" in payload

    @pytest.mark.asyncio
    async def test_min_baseline_entries_zero_refused(
        self, sandboxed_cwd: Path
    ) -> None:
        with pytest.raises(ValueError, match="min_baseline_entries"):
            await handle_tool(
                "analysis.anomalies.check",
                {
                    "current": {"campaign_id": "C1", "cost": 0},
                    "min_baseline_entries": 0,
                },
            )

    @pytest.mark.asyncio
    async def test_malformed_metrics_row_tolerated(
        self, sandboxed_cwd: Path
    ) -> None:
        """A history entry with string-typed / N/A metrics must not break detection."""
        entries: list[ActionLogEntry] = [
            ActionLogEntry(
                timestamp=f"2026-04-0{i}",
                action="adjust_bid",
                platform="google_ads",
                campaign_id="C1",
                metrics_at_action={
                    "cost": "N/A" if i == 0 else 10_000,
                    "conversions": 50,
                    "cpa": 5000,
                    "impressions": 50_000,
                    "clicks": 500,
                    "ctr": 0.01,
                },
            )
            for i in range(8)
        ]
        _write_state(sandboxed_cwd / "STATE.json", entries)

        result = await handle_tool(
            "analysis.anomalies.check",
            {
                "current": {
                    "campaign_id": "C1",
                    "cost": 10_000,
                    "impressions": 50_000,
                    "clicks": 500,
                    "conversions": 50,
                },
                "had_prior_spend": True,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["baseline"] is not None
