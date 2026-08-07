"""MCP surface for delivery-collapse detection and diagnosis (#546).

The two tools are the platform-agnostic half: any platform that can
produce day-grain rows — a hosted connector, an official-MCP bridge, a
plugin — gets the same detector and the same elimination ladder without
mureo needing a client for it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from mureo.mcp.server import handle_list_tools
from mureo.mcp.tools_analysis import TOOLS, handle_tool

AS_OF = date(2026, 6, 1)


def _rows(
    *,
    campaign_id: str = "c-1",
    status: str = "ENABLED",
    collapsed_days: int = 1,
    history_days: int = 28,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    first = AS_OF - timedelta(days=history_days + collapsed_days)
    for offset in range(history_days):
        rows.append(
            {
                "campaign_id": campaign_id,
                "campaign_name": "Display / Prospecting",
                "status": status,
                "date": (first + timedelta(days=offset)).isoformat(),
                "impressions": 350_000,
                "clicks": 3_500,
                "cost": 120_000.0,
            }
        )
    for offset in range(collapsed_days):
        rows.append(
            {
                "campaign_id": campaign_id,
                "campaign_name": "Display / Prospecting",
                "status": status,
                "date": (AS_OF - timedelta(days=collapsed_days - offset)).isoformat(),
                "impressions": 0,
                "clicks": 0,
                "cost": 0.0,
            }
        )
    return rows


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await handle_tool(name, arguments)
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tools_are_registered() -> None:
    names = {tool.name for tool in TOOLS}
    assert "analysis_delivery_collapse_check" in names
    assert "analysis_delivery_collapse_diagnose" in names


@pytest.mark.asyncio
async def test_tools_are_exposed_on_the_server() -> None:
    names = {tool.name for tool in await handle_list_tools()}
    assert "analysis_delivery_collapse_check" in names
    assert "analysis_delivery_collapse_diagnose" in names


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_flags_an_enabled_campaign_at_zero_impressions() -> None:
    payload = await _call(
        "analysis_delivery_collapse_check",
        {"platform": "tiktok_ads", "rows": _rows(), "as_of": AS_OF.isoformat()},
    )

    assert payload["platform"] == "tiktok_ads"
    assert payload["evaluated_campaigns"] == 1
    assert payload["baseline_source"] == "platform_daily_delivery"
    assert len(payload["signals"]) == 1
    signal = payload["signals"][0]
    assert signal["campaign_id"] == "c-1"
    assert signal["severity"] == "critical"
    assert signal["days_at_collapse"] == 1


@pytest.mark.asyncio
async def test_check_stays_quiet_for_a_paused_campaign() -> None:
    payload = await _call(
        "analysis_delivery_collapse_check",
        {
            "platform": "tiktok_ads",
            "rows": _rows(status="PAUSED"),
            "as_of": AS_OF.isoformat(),
        },
    )

    assert payload["signals"] == []
    assert payload["evaluated_campaigns"] == 1


@pytest.mark.asyncio
async def test_check_reports_the_thresholds_it_used() -> None:
    payload = await _call(
        "analysis_delivery_collapse_check",
        {"platform": "tiktok_ads", "rows": _rows(), "as_of": AS_OF.isoformat()},
    )

    assert payload["thresholds"]["drop_pct"] == 90.0
    assert payload["thresholds"]["consecutive_days"] == 1
    assert payload["thresholds_source"] in {"defaults", "strategy_guardrails"}


@pytest.mark.asyncio
async def test_check_rejects_a_malformed_date() -> None:
    payload = await _call(
        "analysis_delivery_collapse_check",
        {
            "platform": "tiktok_ads",
            "rows": [{"campaign_id": "c-1", "date": "yesterday", "impressions": 1}],
        },
    )

    assert "error" in payload
    assert payload["signals"] == []


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagnose_returns_the_timeline_and_the_open_questions() -> None:
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
            "changes": [
                {
                    "occurred_at": (AS_OF - timedelta(days=2)).isoformat(),
                    "source": "google_ads_change_history",
                    "resource_type": "campaign_criterion",
                    "summary": "1,842 placement exclusions added",
                }
            ],
        },
    )

    assert payload["status"] == "ok"
    assert payload["collapse_start_date"] == (AS_OF - timedelta(days=1)).isoformat()
    assert payload["changes_before_cliff"][0]["summary"].endswith("exclusions added")
    assert payload["most_likely_cause"] is None
    assert payload["confidence"] == "undetermined"
    assert payload["unresolved"]
    assert payload["limitations"]


@pytest.mark.asyncio
async def test_diagnose_lookback_window_is_caller_settable() -> None:
    """A cause with a delayed effect must be reachable.

    A billing hold placed five days before delivery stopped falls outside
    the 3-day default; asking the operator to supply everything they know
    and then narrowing it silently is the wrong trade.
    """
    change = {
        "occurred_at": (AS_OF - timedelta(days=6)).isoformat(),
        "source": "action_log",
        "resource_type": "billing",
        "summary": "payment method declined",
    }
    args: dict[str, Any] = {
        "platform": "google_ads",
        "campaign_id": "c-1",
        "rows": _rows(),
        "as_of": AS_OF.isoformat(),
        "changes": [change],
    }

    default = await _call("analysis_delivery_collapse_diagnose", args)
    assert default["changes_before_cliff"] == []

    widened = await _call(
        "analysis_delivery_collapse_diagnose", {**args, "change_lookback_days": 7}
    )
    assert widened["changes_before_cliff"][0]["summary"] == "payment method declined"


@pytest.mark.asyncio
async def test_diagnose_timeline_window_is_caller_settable() -> None:
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
            "timeline_days": 5,
        },
    )

    assert len(payload["timeline"]) == 5


@pytest.mark.asyncio
async def test_diagnose_folds_in_supplied_evidence() -> None:
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
            "evidence": [
                {
                    "check": "ad_approval_policy",
                    "outcome": "implicated",
                    "detail": "all ads DISAPPROVED",
                }
            ],
        },
    )

    assert payload["most_likely_cause"] == "ad_approval_policy"
    assert payload["confidence"] == "likely"


@pytest.mark.asyncio
async def test_diagnose_reports_when_there_is_no_collapse_to_explain() -> None:
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(status="PAUSED"),
            "as_of": AS_OF.isoformat(),
        },
    )

    assert payload["status"] == "no_collapse_detected"


@pytest.mark.asyncio
async def test_diagnose_rejects_an_unknown_check_name() -> None:
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
            "evidence": [{"check": "vibes", "outcome": "implicated"}],
        },
    )

    assert "error" in payload
    assert "vibes" in payload["error"]


@pytest.mark.asyncio
async def test_diagnose_rejects_a_boolean_window() -> None:
    """`bool` is an `int` subclass, so a bare int() would read true as 1.

    The sibling `analysis_anomalies_check` rejects booleans on its
    numeric fields and is documented as doing so; these tools sit beside
    it and must not disagree.
    """
    payload = await _call(
        "analysis_delivery_collapse_diagnose",
        {
            "platform": "google_ads",
            "campaign_id": "c-1",
            "rows": _rows(),
            "as_of": AS_OF.isoformat(),
            "timeline_days": True,
        },
    )

    assert "error" in payload
    assert "timeline_days" in payload["error"]


@pytest.mark.asyncio
async def test_check_reports_how_far_the_platform_has_reported() -> None:
    """An empty `signals` list is only an all-clear when the platform is
    current — `unreported_days` is what tells the caller which it is."""
    rows = _rows(collapsed_days=0, history_days=30)
    payload = await _call(
        "analysis_delivery_collapse_check",
        {"platform": "tiktok_ads", "rows": rows, "as_of": AS_OF.isoformat()},
    )

    assert payload["signals"] == []
    assert payload["reported_through"] == (AS_OF - timedelta(days=1)).isoformat()
    assert payload["unreported_days"] == 0


@pytest.mark.asyncio
async def test_check_surfaces_a_silent_account_instead_of_calling_it_healthy() -> None:
    """Every campaign stopping at once is the one case the detector has
    no opinion on: a total outage and a reporting failure look identical.
    It must be reported as a gap, never swallowed as 'no signals'."""
    rows = [
        row
        for row in _rows(collapsed_days=0, history_days=30)
        if row["date"] < (AS_OF - timedelta(days=5)).isoformat()
    ]

    payload = await _call(
        "analysis_delivery_collapse_check",
        {"platform": "tiktok_ads", "rows": rows, "as_of": AS_OF.isoformat()},
    )

    assert payload["signals"] == []
    assert payload["unreported_days"] == 5
