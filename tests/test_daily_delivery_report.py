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

from mureo.analysis.delivery_collapse import (
    delivery_series_from_rows,
    detect_delivery_collapse,
    last_reported_day,
)
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


def _google_row(day: date, impressions: int, campaign_id: int = 123) -> Any:
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=campaign_id,
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
async def test_google_sparse_response_is_reconciled_to_what_was_reported() -> None:
    """GAQL omits a (campaign, date) row when nothing served that day.

    That is the exact symptom this feature exists for, so a raw 1:1
    mapping would end the series at the last active day and nothing would
    ever fire on the built-in path.

    Reconciliation is bounded by what the report PROVES was covered — the
    still-delivering campaign here — never by the range requested. Filling
    to the requested end instead turns normal reporting lag into a
    CRITICAL on every healthy campaign (see
    ``test_delivery_collapse_reporting_lag.py``).
    """
    # "dead" stops on 2026-05-01; "alive" keeps reporting to 2026-05-31,
    # which is what proves the platform covered 2026-05-02..05-31.
    last_active = date(2026, 5, 1)
    rows_in = [
        _google_row(last_active - timedelta(days=offset), 350_000)
        for offset in reversed(range(30))
    ]
    rows_in += [
        _google_row(date(2026, 5, 31) - timedelta(days=offset), 200_000, campaign_id=99)
        for offset in reversed(range(60))
    ]
    client = _GoogleClient(rows_in)

    rows = await client.get_daily_delivery_report(days=60)

    dead_rows = {r["date"]: r for r in rows if r["campaign_id"] == "123"}
    assert dead_rows["2026-05-31"]["impressions"] == 0
    assert dead_rows["2026-05-31"]["status"] == "ENABLED"
    # Never past the last reported day: 06-01 was reported by nobody.
    assert "2026-06-01" not in dead_rows

    series = {
        s.campaign_id: s for s in delivery_series_from_rows(rows, platform="google_ads")
    }
    signal = detect_delivery_collapse(series["123"], as_of=date(2026, 6, 1))
    assert signal is not None
    assert signal.collapse_start_date == "2026-05-02"
    assert signal.days_at_collapse == 30
    assert detect_delivery_collapse(series["99"], as_of=date(2026, 6, 1)) is None


@pytest.mark.asyncio
async def test_google_report_that_simply_stops_yields_no_signal() -> None:
    """A single-campaign account going quiet is the residual blind spot.

    Nothing proves the platform covered the missing days, so the detector
    has no opinion — the caller surfaces it via ``last_reported_day`` /
    ``unreported_days`` instead of being handed a CRITICAL that might be
    a reporting outage.
    """
    last_active = date(2026, 5, 1)
    client = _GoogleClient(
        [
            _google_row(last_active - timedelta(days=offset), 350_000)
            for offset in reversed(range(30))
        ]
    )

    rows = await client.get_daily_delivery_report(days=60)
    series = delivery_series_from_rows(rows, platform="google_ads")

    assert detect_delivery_collapse(series[0], as_of=date(2026, 6, 1)) is None
    assert last_reported_day(series) == last_active


@pytest.mark.asyncio
async def test_google_dense_response_is_left_alone() -> None:
    """If the API does return explicit zero rows, this is a no-op.

    The reconciliation must not depend on knowing which way the API
    behaves — that is a fact that can change underneath us.
    """
    days = [date(2026, 5, 1) + timedelta(days=i) for i in range(3)]
    client = _GoogleClient(
        [_google_row(d, 0 if i else 100) for i, d in enumerate(days)]
    )

    rows = await client.get_daily_delivery_report(days=2)

    # All three supplied days survive untouched, and nothing is added
    # past the last one the report covered.
    assert len([r for r in rows if r["date"] in {d.isoformat() for d in days}]) == 3
    assert max(r["date"] for r in rows) == days[-1].isoformat()
    assert sum(1 for r in rows if r["date"] == "2026-05-01") == 1


@pytest.mark.asyncio
async def test_meta_sparse_response_is_reconciled_to_what_was_reported() -> None:
    """Meta twin: the still-delivering ad account proves the coverage."""

    def _insight(campaign_id: str, day: date, impressions: int) -> dict[str, Any]:
        return {
            "campaign_id": campaign_id,
            "campaign_name": f"Campaign {campaign_id}",
            "date_start": day.isoformat(),
            "impressions": str(impressions),
            "clicks": "3500",
            "spend": "1200.50",
        }

    client = _MetaClient(
        insights=[
            *[
                _insight("9", date(2026, 5, 1) - timedelta(days=offset), 350_000)
                for offset in reversed(range(30))
            ],
            *[
                _insight("10", date(2026, 5, 31) - timedelta(days=offset), 200_000)
                for offset in reversed(range(60))
            ],
        ],
        campaigns=[
            {"id": "9", "name": "Prospecting", "status": "ACTIVE"},
            {"id": "10", "name": "Retargeting", "status": "ACTIVE"},
        ],
    )

    rows = await client.get_daily_delivery_report(days=60)

    dead_rows = {r["date"]: r for r in rows if r["campaign_id"] == "9"}
    assert dead_rows["2026-05-31"]["impressions"] == 0
    assert dead_rows["2026-05-31"]["status"] == "ACTIVE"
    assert "2026-06-01" not in dead_rows
    series = {
        s.campaign_id: s for s in delivery_series_from_rows(rows, platform="meta_ads")
    }
    assert detect_delivery_collapse(series["9"], as_of=date(2026, 6, 1)) is not None
    assert detect_delivery_collapse(series["10"], as_of=date(2026, 6, 1)) is None


@pytest.mark.asyncio
async def test_fill_never_invents_days_before_a_campaign_first_appeared() -> None:
    """A campaign created mid-window has no history before it existed.

    Fabricating leading zeros would fabricate the very history the
    baseline is computed from.
    """
    first = date(2026, 5, 20)
    client = _GoogleClient(
        [_google_row(first + timedelta(days=i), 350_000) for i in range(5)]
    )

    rows = await client.get_daily_delivery_report(days=60)

    assert min(row["date"] for row in rows) == first.isoformat()


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
