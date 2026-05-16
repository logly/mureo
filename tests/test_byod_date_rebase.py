"""Unit tests: BYOD/demo relative windows rebase onto the dataset.

The demo/BYOD dataset has fixed historical dates. The MCP tools query
relative windows ("LAST_7_DAYS" etc.). Anchoring those on
``date.today()`` (the pre-fix behaviour) makes the demo silently return
``[]`` as wall-clock time moves past the dataset — exactly the reported
symptom. The read clients must instead anchor relative windows on the
dataset's own latest date so the demo is immune to date drift.

``@pytest.mark.unit``; all FS via ``tmp_path``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# _period_to_range anchor semantics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPeriodToRangeAnchor:
    def test_anchor_none_preserves_legacy_today_behaviour(self) -> None:
        from mureo.byod.clients import _period_to_range

        today = date.today()
        assert _period_to_range("LAST_7_DAYS") == (
            today - timedelta(days=7),
            today - timedelta(days=1),
        )
        assert _period_to_range("LAST_30_DAYS", anchor=None) == (
            today - timedelta(days=30),
            today - timedelta(days=1),
        )

    def test_anchor_rebases_window_end_to_anchor(self) -> None:
        from mureo.byod.clients import _period_to_range

        anchor = date(2026, 4, 25)
        assert _period_to_range("LAST_7_DAYS", anchor=anchor) == (
            date(2026, 4, 19),
            anchor,
        )
        assert _period_to_range("LAST_30_DAYS", anchor=anchor) == (
            date(2026, 3, 27),
            anchor,
        )

    def test_yesterday_today_collapse_to_anchor(self) -> None:
        from mureo.byod.clients import _period_to_range

        anchor = date(2026, 4, 25)
        assert _period_to_range("YESTERDAY", anchor=anchor) == (anchor, anchor)
        assert _period_to_range("TODAY", anchor=anchor) == (anchor, anchor)


# ---------------------------------------------------------------------------
# Clients rebase a stale dataset so windows are non-empty
# ---------------------------------------------------------------------------


_FAR_PAST_END = date(2026, 4, 25)  # well before any plausible test "today"


def _google_dir(tmp_path: Path) -> Path:
    d = tmp_path / "g"
    _write(
        d / "campaigns.csv",
        "campaign_id,name,status,objective,daily_budget_jpy,start_date\n"
        "1,Demo Camp,ENABLED,SALES,5000,2026-03-01\n",
    )
    # 10 consecutive days ending 2026-04-25 (stale relative to today).
    lines = ["date,campaign_id,ad_group_id,impressions,clicks,cost_jpy,conversions"]
    for i in range(10):
        day = _FAR_PAST_END - timedelta(days=i)
        lines.append(f"{day.isoformat()},1,11,1000,50,3000,2.0")
    _write(d / "metrics_daily.csv", "\n".join(lines) + "\n")
    return d


def _meta_dir(tmp_path: Path) -> Path:
    d = tmp_path / "m"
    _write(
        d / "campaigns.csv",
        "campaign_id,name,status,objective,daily_budget_jpy,start_date\n"
        "9,Demo Meta,ACTIVE,OUTCOME_LEADS,4000,2026-03-01\n",
    )
    lines = ["date,campaign_id,ad_set_id,impressions,clicks,cost_jpy,conversions"]
    for i in range(10):
        day = _FAR_PAST_END - timedelta(days=i)
        lines.append(f"{day.isoformat()},9,99,2000,80,5000,4.0")
    _write(d / "metrics_daily.csv", "\n".join(lines) + "\n")
    return d


@pytest.mark.unit
@pytest.mark.asyncio
async def test_google_perf_report_non_empty_despite_stale_dates(
    tmp_path: Path,
) -> None:
    from mureo.byod.clients import ByodGoogleAdsClient

    client = ByodGoogleAdsClient(_google_dir(tmp_path))
    # LAST_7_DAYS would be empty under today-anchored filtering (data ends
    # 2026-04-25). Rebased on the dataset it must return data.
    rows = await client.get_performance_report(period="LAST_7_DAYS")
    assert rows, "stale demo data must still return the last 7 dataset days"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_metrics_daily_non_empty_despite_stale_dates(
    tmp_path: Path,
) -> None:
    from mureo.byod.clients import ByodMetaAdsClient

    client = ByodMetaAdsClient(_meta_dir(tmp_path))
    rows = await client.get_metrics_daily(period="LAST_7_DAYS")
    assert rows, "stale Meta demo data must still return the last 7 days"
    # Window must be the dataset's last 7 days, not wall-clock anchored.
    days = sorted({r["date"] for r in rows})
    assert days[-1] == _FAR_PAST_END.isoformat()
    assert len(days) == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_get_performance_report_non_empty(tmp_path: Path) -> None:
    from mureo.byod.clients import ByodMetaAdsClient

    client = ByodMetaAdsClient(_meta_dir(tmp_path))
    rows = await client.get_performance_report(period="LAST_30_DAYS")
    assert rows
