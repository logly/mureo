"""``mureo_state_action_log_append`` fills a missing baseline (#890).

A campaign-level entry appended without ``metrics_at_action`` gets the
campaign's current snapshot from STATE.json — ``period``, ``fetched_at`` and
the day count included — so the automatic closure no longer skips it with
``no_baseline`` and can compare counts per day. A baseline the caller passes
is kept exactly as given. The response says where the baseline came from
under a top-level ``baseline`` key, which is never written to STATE.json.

The decision rules themselves are pinned in tests/test_action_baseline.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.expected_eval import build_evaluation
from mureo.core import clock
from mureo.core.runtime_context import reset_runtime_context
from mureo.mcp import tools_mureo_context

pytestmark = pytest.mark.unit

_JST = timezone(timedelta(hours=9))
_DAY0 = datetime(2026, 7, 28, 10, 0, 0, tzinfo=_JST)

SNAPSHOT_METRICS: dict[str, Any] = {
    "cpa": 5000,
    "conversions": 100,
    "clicks": 2000,
    "period": "LAST_30_DAYS",
    "fetched_at": "2026-07-27T09:00:00+09:00",
}


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    _set_clock(monkeypatch, _DAY0)
    _write_state(tmp_path, dict(SNAPSHOT_METRICS))
    return tmp_path


def _set_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr(clock, "server_now", lambda: now)


def _write_state(root: Path, metrics: dict[str, Any]) -> None:
    document = {
        "version": "2",
        "platforms": {
            "google_ads": {
                "account_id": "acct-1",
                "campaigns": [
                    {
                        "campaign_id": "camp_1",
                        "campaign_name": "Brand",
                        "status": "ENABLED",
                        "metrics": metrics,
                    }
                ],
            }
        },
        "action_log": [],
    }
    (root / "STATE.json").write_text(json.dumps(document), encoding="utf-8")


def _stored(root: Path) -> dict[str, Any]:
    stored: dict[str, Any] = json.loads(
        (root / "STATE.json").read_text(encoding="utf-8")
    )
    return stored


async def _call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await tools_mureo_context.handle_tool(tool, arguments)
    payload: dict[str, Any] = json.loads(result[0].text)
    return payload


async def _append(**fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "action": "google_ads_budget_update",
        "platform": "google_ads",
        "campaign_id": "camp_1",
        "observation_due": "2026-08-11",
    }
    entry.update(fields)
    return await _call("mureo_state_action_log_append", {"entry": entry})


# ---------------------------------------------------------------------------
# What is stored
# ---------------------------------------------------------------------------


async def test_an_omitted_baseline_is_filled_from_the_snapshot(
    workspace: Path,
) -> None:
    payload = await _append()

    expected = {**SNAPSHOT_METRICS, "days": 30}
    assert _stored(workspace)["action_log"][0]["metrics_at_action"] == expected
    assert payload["action_log"][0]["metrics_at_action"] == expected
    # The snapshot itself is unchanged.
    campaign = _stored(workspace)["platforms"]["google_ads"]["campaigns"][0]
    assert campaign["metrics"] == SNAPSHOT_METRICS


async def test_a_passed_baseline_is_stored_as_given(workspace: Path) -> None:
    given = {"mtd_spend": 120000, "period": "THIS_MONTH"}

    payload = await _append(metrics_at_action=given)

    assert _stored(workspace)["action_log"][0]["metrics_at_action"] == given
    assert payload["baseline"] == {"source": "caller"}


async def test_an_external_change_is_not_filled(workspace: Path) -> None:
    payload = await _append(origin="external", external_id="chg-1")

    assert "metrics_at_action" not in _stored(workspace)["action_log"][0]
    assert payload["baseline"] == {"source": "none"}


async def test_an_evaluation_record_is_not_filled(workspace: Path) -> None:
    await _append(metrics_at_action={"cpa": 10000, "conversions": 50})
    table = build_evaluation(
        {"cpa": 10000, "conversions": 50},
        {"cpa": 5000, "conversions": 100},
        (),
        window_from="2026-07-28",
        window_to="2026-08-11",
    ).table

    payload = await _append(
        action="outcome_evaluated",
        observation_due=None,
        evaluation_of=0,
        evaluation=table,
    )

    assert "metrics_at_action" not in _stored(workspace)["action_log"][1]
    assert payload["baseline"] == {"source": "none"}


async def test_an_entry_without_a_campaign_is_not_filled(workspace: Path) -> None:
    payload = await _append(campaign_id=None)

    assert "metrics_at_action" not in _stored(workspace)["action_log"][0]
    assert payload["baseline"] == {"source": "none"}


# ---------------------------------------------------------------------------
# The response's ``baseline`` key
# ---------------------------------------------------------------------------


async def test_the_response_says_the_baseline_came_from_the_snapshot(
    workspace: Path,
) -> None:
    payload = await _append()

    assert payload["baseline"] == {"source": "state_snapshot"}


async def test_the_response_says_why_no_baseline_was_filled(
    workspace: Path,
) -> None:
    _write_state(workspace, {**SNAPSHOT_METRICS, "fetched_at": "2026-07-25"})

    payload = await _append()

    assert payload["baseline"] == {"source": "none", "reason": "baseline_stale"}
    assert "metrics_at_action" not in _stored(workspace)["action_log"][0]


async def test_the_baseline_key_is_never_written_to_state(workspace: Path) -> None:
    await _append()

    stored = _stored(workspace)
    assert "baseline" not in stored
    assert "baseline" not in stored["action_log"][0]


def test_the_tool_description_says_an_omitted_baseline_is_filled() -> None:
    tool = next(
        t
        for t in tools_mureo_context.TOOLS
        if t.name == "mureo_state_action_log_append"
    )
    entry = tool.inputSchema["properties"]["entry"]
    prop = entry["properties"]["metrics_at_action"]

    assert "metrics_at_action" in tool.description
    assert "baseline" in tool.description
    assert "2 days" in tool.description
    assert prop["type"] == "object"
    assert "omit" in prop["description"].lower()


# ---------------------------------------------------------------------------
# End to end: the filled baseline is what the automatic closure scores
# ---------------------------------------------------------------------------


async def test_a_filled_entry_is_closed_automatically_per_day(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _append(
        reason="Lift conversions with more budget.",
        expected=[{"metric": "conversions", "direction": "up"}],
    )
    # Collected after the window closed: same 30-day window, more conversions.
    stored = _stored(workspace)
    stored["platforms"]["google_ads"]["campaigns"][0]["metrics"] = {
        "cpa": 4000,
        "conversions": 150,
        "clicks": 2400,
        "period": "LAST_30_DAYS",
        "fetched_at": "2026-08-12T09:00:00+09:00",
    }
    (workspace / "STATE.json").write_text(json.dumps(stored), encoding="utf-8")
    _set_clock(monkeypatch, datetime(2026, 8, 12, 10, 0, 0, tzinfo=_JST))

    payload = await _call("mureo_state_get", {})

    assert payload["auto_evaluation_skipped"] == []
    assert [c["index"] for c in payload["auto_evaluations"]] == [0]
    table = _stored(workspace)["action_log"][1]["evaluation"]
    assert table["primary"] == "conversions"
    assert table.get("reason") != "period_unknown"
    assert table["overall"] == "improved"
    rows = {row["metric"]: row for row in table["metrics"]}
    assert "per day over 30d / 30d" in rows["conversions"]["note"]
    assert "per day over 30d / 30d" in rows["clicks"]["note"]
