"""The CSV-backed BYOD Meta Ads client.

Split out of :mod:`mureo.byod.clients` (#546), which had grown past the
project's 800-line file budget. Import it from ``mureo.byod.clients``;
that module re-exports this class and remains the public path.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.byod._client_common import (
    _DAILY_DELIVERY_DEFAULT_DAYS,
    _MUTATION_PREFIXES,
    _async_byod_blocked,
    _async_empty_list,
    _byod_delivery_rows,
    _max_date,
    _parse_date,
    _period_to_range,
    _read_csv,
    _to_float,
    _to_int,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------


class ByodMetaAdsClient:
    """CSV-backed read-only mock of MetaAdsApiClient."""

    def __init__(self, data_dir: Path, account_id: str = "act_byod") -> None:
        self._dir = Path(data_dir)
        self.account_id = account_id

    def _campaigns(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "campaigns.csv")

    def _ad_sets(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ad_sets.csv")

    def _ads(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ads.csv")

    def _metrics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "metrics_daily.csv")

    async def list_campaigns(
        self, status_filter: str | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        rows = self._campaigns()
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        return [
            {
                "id": r.get("campaign_id"),
                "name": r.get("name"),
                "status": r.get("status"),
                "objective": r.get("objective"),
                "daily_budget": _to_float(r.get("daily_budget_jpy")),
                "account_id": self.account_id,
            }
            for r in rows
        ]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        for r in self._campaigns():
            if r.get("campaign_id") == str(campaign_id):
                return {
                    "id": r.get("campaign_id"),
                    "name": r.get("name"),
                    "status": r.get("status"),
                    "objective": r.get("objective"),
                    "daily_budget": _to_float(r.get("daily_budget_jpy")),
                    "account_id": self.account_id,
                }
        return None

    async def list_ad_sets(
        self, campaign_id: str | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        rows = self._ad_sets()
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        return [
            {
                "id": r.get("ad_set_id"),
                "campaign_id": r.get("campaign_id"),
                "name": r.get("name"),
                "status": r.get("status"),
            }
            for r in rows
        ]

    async def list_ads(
        self, ad_set_id: str | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        rows = self._ads()
        if ad_set_id:
            rows = [r for r in rows if r.get("ad_set_id") == str(ad_set_id)]
        return [
            {
                "id": r.get("ad_id"),
                "ad_set_id": r.get("ad_set_id"),
                "name": r.get("name"),
                "status": r.get("status"),
            }
            for r in rows
        ]

    async def get_performance_report(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = self._metrics()
        start, end = _period_to_range(period, anchor=_max_date(rows))
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]

        agg: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "impressions": 0,
                "clicks": 0,
                "cost": 0.0,
                "conversions": 0.0,
            }
        )
        # First non-empty result_indicator seen per campaign. Lets the
        # agent tell what the "results" / "conversions" column actually
        # counts (e.g. ``actions:link_click`` vs
        # ``actions:offsite_conversion.fb_pixel_lead``) — critical for
        # detecting CV-definition mismatches across campaigns where a
        # link_click-optimized campaign would otherwise look like a
        # high-CV-rate winner against a true lead-optimized one.
        indicators: dict[str, str] = {}
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            key = r.get("campaign_id") or ""
            agg[key]["impressions"] += _to_int(r.get("impressions"))
            agg[key]["clicks"] += _to_int(r.get("clicks"))
            agg[key]["cost"] += _to_float(r.get("cost_jpy"))
            agg[key]["conversions"] += _to_float(r.get("conversions"))
            ri = (r.get("result_indicator") or "").strip()
            if ri and key not in indicators:
                indicators[key] = ri

        names = {r.get("campaign_id"): r.get("name", "") for r in self._campaigns()}
        out = []
        for cid, m in agg.items():
            ctr = (m["clicks"] / m["impressions"]) if m["impressions"] else 0
            cpc = (m["cost"] / m["clicks"]) if m["clicks"] else 0
            cpa = (m["cost"] / m["conversions"]) if m["conversions"] else 0
            out.append(
                {
                    "campaign_id": cid,
                    "campaign_name": names.get(cid, ""),
                    "impressions": int(m["impressions"]),
                    "clicks": int(m["clicks"]),
                    "spend": m["cost"],
                    "conversions": m["conversions"],
                    "ctr": round(ctr, 4),
                    "cpc": round(cpc, 2),
                    "cpa": round(cpa, 2),
                    "result_indicator": indicators.get(cid, ""),
                }
            )
        return out

    # ------------------------------------------------------------------
    # Phase 3 readers — daily time-series + finer grain + breakdowns
    # ------------------------------------------------------------------

    def _ad_set_metrics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ad_set_metrics_daily.csv")

    def _ad_metrics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ad_metrics_daily.csv")

    def _demographics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "demographics_daily.csv")

    def _creatives(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "creatives.csv")

    async def get_metrics_daily(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Per-day campaign metrics — the time-series view that
        ``get_performance_report`` aggregates away. Each row covers
        impressions / clicks / spend / conversions / reach / frequency
        / result_indicator for a single (date, campaign).
        """
        rows = self._metrics()
        start, end = _period_to_range(period, anchor=_max_date(rows))
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            out.append(
                {
                    "date": r.get("date", ""),
                    "campaign_id": r.get("campaign_id", ""),
                    "impressions": _to_int(r.get("impressions")),
                    "clicks": _to_int(r.get("clicks")),
                    "spend": _to_float(r.get("cost_jpy")),
                    "conversions": _to_float(r.get("conversions")),
                    "reach": _to_int(r.get("reach")),
                    "frequency": _to_float(r.get("frequency")),
                    "result_indicator": r.get("result_indicator", ""),
                }
            )
        return out

    async def get_ad_set_insights_daily(
        self,
        campaign_id: str | None = None,
        ad_set_id: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Per-day ad-set metrics — populated when the source export
        has Ad set name + Day breakdown. Empty list when absent."""
        rows = self._ad_set_metrics()
        start, end = _period_to_range(period, anchor=_max_date(rows))
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        if ad_set_id:
            rows = [r for r in rows if r.get("ad_set_id") == str(ad_set_id)]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            out.append(
                {
                    "date": r.get("date", ""),
                    "campaign_id": r.get("campaign_id", ""),
                    "ad_set_id": r.get("ad_set_id", ""),
                    "impressions": _to_int(r.get("impressions")),
                    "clicks": _to_int(r.get("clicks")),
                    "spend": _to_float(r.get("cost_jpy")),
                    "conversions": _to_float(r.get("conversions")),
                    "reach": _to_int(r.get("reach")),
                }
            )
        return out

    async def get_ad_insights_daily(
        self,
        ad_set_id: str | None = None,
        ad_id: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Per-day per-ad metrics — populated when the source export
        has Ad name + Day breakdown. Empty list when absent."""
        rows = self._ad_metrics()
        start, end = _period_to_range(period, anchor=_max_date(rows))
        if ad_set_id:
            rows = [r for r in rows if r.get("ad_set_id") == str(ad_set_id)]
        if ad_id:
            rows = [r for r in rows if r.get("ad_id") == str(ad_id)]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            out.append(
                {
                    "date": r.get("date", ""),
                    "campaign_id": r.get("campaign_id", ""),
                    "ad_set_id": r.get("ad_set_id", ""),
                    "ad_id": r.get("ad_id", ""),
                    "impressions": _to_int(r.get("impressions")),
                    "clicks": _to_int(r.get("clicks")),
                    "spend": _to_float(r.get("cost_jpy")),
                    "conversions": _to_float(r.get("conversions")),
                    "reach": _to_int(r.get("reach")),
                }
            )
        return out

    async def get_breakdown_report(
        self,
        campaign_id: str | None = None,
        dimension: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Demographics breakdown (age / gender / region / placement).

        Returns one row per (date, campaign, dimension, value).
        ``dimension`` filters to a single breakdown axis when set.
        Empty list when the source export carried no breakdown columns.
        """
        rows = self._demographics()
        start, end = _period_to_range(period, anchor=_max_date(rows))
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        if dimension:
            rows = [r for r in rows if r.get("dimension") == dimension]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            out.append(
                {
                    "date": r.get("date", ""),
                    "campaign_id": r.get("campaign_id", ""),
                    "dimension": r.get("dimension", ""),
                    "value": r.get("value", ""),
                    "impressions": _to_int(r.get("impressions")),
                    "clicks": _to_int(r.get("clicks")),
                    "spend": _to_float(r.get("cost_jpy")),
                    "conversions": _to_float(r.get("conversions")),
                    "reach": _to_int(r.get("reach")),
                }
            )
        return out

    async def get_creatives(
        self,
        ad_id: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Creative info per ad. Best-effort — populated only when the
        source export carried image / video / headline / body / cta
        columns. Empty list otherwise."""
        rows = self._creatives()
        if ad_id:
            rows = [r for r in rows if r.get("ad_id") == str(ad_id)]
        return [
            {
                "ad_id": r.get("ad_id", ""),
                "name": r.get("name", ""),
                "image_url": r.get("image_url", ""),
                "video_url": r.get("video_url", ""),
                "headline": r.get("headline", ""),
                "body": r.get("body", ""),
                "cta": r.get("cta", ""),
            }
            for r in rows
        ]

    async def get_leads(self, **_: Any) -> list[dict[str, Any]]:
        return []

    async def get_ad_leads(self, **_: Any) -> list[dict[str, Any]]:
        return []

    async def get_daily_delivery_report(
        self, days: int = _DAILY_DELIVERY_DEFAULT_DAYS
    ) -> list[dict[str, Any]]:
        """Day-grain delivery rows for the collapse detector (#546).

        Same rationale as the Google BYOD twin: implemented explicitly so
        the ``__getattr__`` empty-list fallback cannot pass a bundle off
        as "checked, nothing collapsed".
        """
        return _byod_delivery_rows(
            self._metrics(), self._campaigns(), days=days, name_key="name"
        )

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> ByodMetaAdsClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        if any(name.startswith(verb) for verb in _MUTATION_PREFIXES):
            return _async_byod_blocked(name)
        return _async_empty_list()
