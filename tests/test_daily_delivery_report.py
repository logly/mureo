"""``get_daily_delivery_report`` across every client that has one (#546).

Four implementations — Google live, Meta live, and the two BYOD clients
— must emit the SAME normalised row shape, because the collapse detector
and its baseline are shared code and only the fetch is per-platform. A
drift in any one of them silently degrades detection for that platform,
so the shape is asserted from one table.

No network: the Google client's ``_search`` and Meta's ``_get`` are
mocked, and the BYOD clients read CSVs from a tmp_path.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.analysis.delivery_collapse import delivery_series_from_rows
from mureo.byod.clients import ByodGoogleAdsClient, ByodMetaAdsClient
from mureo.google_ads._analysis_performance import _PerformanceAnalysisMixin
from mureo.meta_ads._insights import InsightsMixin

REQUIRED_KEYS = {
    "campaign_id",
    "campaign_name",
    "status",
    "end_date",
    "date",
    "impressions",
    "clicks",
    "cost",
}

FROZEN_NOW = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.core.clock.server_now", lambda: FROZEN_NOW)


# ---------------------------------------------------------------------------
# Google Ads (live)
# ---------------------------------------------------------------------------


class _GoogleClient(_PerformanceAnalysisMixin):
    def __init__(self, rows: list[Any]) -> None:
        self._search = AsyncMock(return_value=rows)  # type: ignore[method-assign]


def _google_row(day: date, impressions: int) -> Any:
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=123,
            name="Display / Prospecting",
            status="ENABLED",
            end_date="2037-12-30",
        ),
        segments=SimpleNamespace(date=day.isoformat()),
        metrics=SimpleNamespace(
            impressions=impressions, clicks=impressions // 100, cost_micros=1_500_000
        ),
    )


@pytest.mark.asyncio
async def test_google_daily_delivery_shape_and_window() -> None:
    day = date(2026, 5, 31)
    client = _GoogleClient([_google_row(day, 350_000)])

    rows = await client.get_daily_delivery_report(days=45)

    assert set(rows[0]) == REQUIRED_KEYS
    assert rows[0]["campaign_id"] == "123"
    assert rows[0]["date"] == "2026-05-31"
    assert rows[0]["impressions"] == 350_000
    assert rows[0]["cost"] == pytest.approx(1.5)
    query = client._search.call_args.args[0]  # type: ignore[attr-defined]
    assert "segments.date BETWEEN '2026-04-17' AND '2026-06-01'" in query
    assert "campaign.status" in query


@pytest.mark.asyncio
async def test_google_daily_delivery_rejects_an_absurd_window() -> None:
    from mureo.google_ads._gaql_validator import GAQLValidationError

    client = _GoogleClient([])

    with pytest.raises(GAQLValidationError):
        await client.get_daily_delivery_report(days=100_000)


# ---------------------------------------------------------------------------
# Meta Ads (live)
# ---------------------------------------------------------------------------


class _MetaClient(InsightsMixin):
    def __init__(self, insights: list[dict[str, Any]], campaigns: list[dict]) -> None:
        self._ad_account_id = "act_1"
        self._insights = insights
        self._campaigns = campaigns
        self.params: dict[str, Any] = {}

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.params = dict(params or {})
        return {"data": self._insights}

    async def list_campaigns(
        self, *, status_filter: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.limit = limit
        return self._campaigns


@pytest.mark.asyncio
async def test_meta_daily_delivery_joins_status_from_campaigns() -> None:
    client = _MetaClient(
        insights=[
            {
                "campaign_id": "9",
                "campaign_name": "Prospecting",
                "date_start": "2026-05-31",
                "impressions": "350000",
                "clicks": "3500",
                "spend": "1200.50",
            }
        ],
        campaigns=[
            {
                "id": "9",
                "name": "Prospecting",
                "status": "ACTIVE",
                "effective_status": "CAMPAIGN_PAUSED",
                "stop_time": "2026-12-31T00:00:00+0900",
            }
        ],
    )

    rows = await client.get_daily_delivery_report(days=45)

    assert set(rows[0]) == REQUIRED_KEYS
    # effective_status wins: a campaign the platform has actually stopped
    # is not "serving but silent".
    assert rows[0]["status"] == "CAMPAIGN_PAUSED"
    assert rows[0]["end_date"] == "2026-12-31"
    assert rows[0]["cost"] == pytest.approx(1200.50)
    assert client.params["time_increment"] == 1


@pytest.mark.asyncio
async def test_meta_daily_delivery_drops_rows_with_no_status_join() -> None:
    """Without a status there is no serving contradiction to evaluate;
    defaulting such a row to ENABLED would invent the signal."""
    client = _MetaClient(
        insights=[{"campaign_id": "9", "date_start": "2026-05-31", "impressions": "1"}],
        campaigns=[],
    )

    assert await client.get_daily_delivery_report(days=45) == []


# ---------------------------------------------------------------------------
# BYOD — the empty-list trap
# ---------------------------------------------------------------------------


def _write_byod(root: Path, cost_column: str = "cost_jpy") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "campaigns.csv").write_text(
        "campaign_id,name,status\nc1,Prospecting,ENABLED\n", encoding="utf-8"
    )
    anchor = date(2026, 5, 31)
    lines = ["date,campaign_id,impressions,clicks,cost_jpy,conversions"]
    for offset in range(30):
        day = anchor - timedelta(days=offset)
        impressions = 0 if offset == 0 else 350_000
        lines.append(f"{day.isoformat()},c1,{impressions},3500,120000,10")
    (root / "metrics_daily.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("client_cls", [ByodGoogleAdsClient, ByodMetaAdsClient])
@pytest.mark.asyncio
async def test_byod_daily_delivery_is_real_not_the_getattr_stub(
    client_cls: type, tmp_path: Path
) -> None:
    """``__getattr__`` answers any unknown read method with ``[]``, which
    the detector would read as 'no campaigns to check' — a false
    all-clear. Both BYOD clients must implement this for real."""
    client = client_cls(_write_byod(tmp_path / "byod"))

    rows = await client.get_daily_delivery_report(days=45)

    assert rows, "BYOD returned nothing — the __getattr__ stub is answering"
    assert set(rows[0]) == REQUIRED_KEYS
    assert {r["status"] for r in rows} == {"ENABLED"}


@pytest.mark.parametrize("client_cls", [ByodGoogleAdsClient, ByodMetaAdsClient])
@pytest.mark.asyncio
async def test_byod_rows_feed_the_shared_detector(
    client_cls: type, tmp_path: Path
) -> None:
    """End-to-end on the normalisation seam: bundle rows -> series."""
    from mureo.analysis.delivery_collapse import detect_delivery_collapse

    client = client_cls(_write_byod(tmp_path / "byod"))
    rows = await client.get_daily_delivery_report(days=45)

    series = delivery_series_from_rows(rows, platform="google_ads")
    signal = detect_delivery_collapse(series[0], as_of=date(2026, 6, 1))

    assert signal is not None
    assert signal.collapse_start_date == "2026-05-31"
