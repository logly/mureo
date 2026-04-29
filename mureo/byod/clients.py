"""CSV-backed BYOD clients.

These mock the public ad-platform clients
(:class:`mureo.google_ads.client.GoogleAdsApiClient`,
:class:`mureo.meta_ads.client.MetaAdsApiClient`) by reading the
user-supplied CSV exports normalized into
``~/.mureo/byod/<platform>/`` by ``mureo byod import``.

Read paths return realistic shapes that the existing MCP handlers and
skills already understand. Mutation methods (``create_*``, ``update_*``,
``delete_*``, ``send_*``, etc.) return
``{"status": "skipped_in_byod_readonly"}`` so a curious agent never
accidentally writes anywhere; BYOD mode is analysis-only by design.

Methods not implemented here fall back to an empty result via
``__getattr__`` so the agent does not crash on calls outside the v1
scope; the agent simply sees no data for those tools.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_int(v: Any, default: int = 0) -> int:
    # Tolerate float-formatted strings like "98.0" emitted by the Google
    # Ads Apps Script bundle (and by Sheets exports in general). The
    # strict ``int()`` parser raises on the dot, which used to silently
    # zero out impressions/clicks for Google Ads BYOD — breaking CTR,
    # CPC, and search-term diagnostics downstream even though the CSV
    # itself was complete.
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_date(v: str) -> date | None:
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _period_to_range(period: str) -> tuple[date, date]:
    today = date.today()
    if period == "LAST_7_DAYS":
        return today - timedelta(days=7), today - timedelta(days=1)
    if period == "LAST_14_DAYS":
        return today - timedelta(days=14), today - timedelta(days=1)
    if period == "LAST_30_DAYS":
        return today - timedelta(days=30), today - timedelta(days=1)
    if period == "YESTERDAY":
        d = today - timedelta(days=1)
        return d, d
    if period == "TODAY":
        return today, today
    return today - timedelta(days=7), today - timedelta(days=1)


# Verb prefixes that should never silently no-op in BYOD mode.
# Anything matching one of these returns ``skipped_in_byod_readonly``
# instead of an empty list, so a curious agent never mistakes a mutation
# for a successful call.
_MUTATION_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "send_",
    "upload_",
    "pause_",
    "resume_",
    "enable_",
    "disable_",
    "apply_",
    "publish_",
    "submit_",
    "attach_",
    "detach_",
    "approve_",
    "reject_",
    "cancel_",
    "set_",
    "patch_",
)


def _async_empty_list() -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> list[Any]:
        return []

    return _stub


def _async_byod_blocked(name: str) -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "status": "skipped_in_byod_readonly",
            "operation": name,
            "note": (
                "BYOD mode is analysis-only. "
                "This call would have written to a real ad account."
            ),
        }

    return _stub


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------


class ByodGoogleAdsClient:
    """CSV-backed read-only mock of GoogleAdsApiClient."""

    def __init__(self, data_dir: Path, customer_id: str = "byod") -> None:
        self._dir = Path(data_dir)
        self.customer_id = customer_id

    def _campaigns(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "campaigns.csv")

    def _ad_groups(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ad_groups.csv")

    def _ads(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "ads.csv")

    def _keywords(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "keywords.csv")

    def _search_terms(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "search_terms.csv")

    def _auction_insights(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "auction_insights.csv")

    def _metrics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "metrics_daily.csv")

    async def list_accounts(self) -> list[dict[str, Any]]:
        return [{"customer_id": self.customer_id or "byod"}]

    @staticmethod
    def _campaign_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("campaign_id"),
            "name": row.get("name"),
            "status": row.get("status"),
            "channel_type": row.get("channel_type"),
            "bidding_strategy_type": row.get("bidding_strategy_type"),
            "serving_status": "SERVING",
            "primary_status": (
                "ELIGIBLE" if row.get("status") == "ENABLED" else row.get("status")
            ),
            "primary_status_reasons": [],
            "bidding_strategy_system_status": "UNSPECIFIED",
            "daily_budget": _to_float(row.get("daily_budget_jpy")),
            "budget_amount_micros": str(
                _to_int(row.get("daily_budget_jpy")) * 1_000_000
            ),
        }

    async def list_campaigns(
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]:
        rows = self._campaigns()
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        return [self._campaign_to_dict(r) for r in rows]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        for r in self._campaigns():
            if r.get("campaign_id") == str(campaign_id):
                base = self._campaign_to_dict(r)
                base["budget_daily"] = base["daily_budget"]
                base["budget_status"] = "ENABLED"
                base["bidding_details"] = {}
                return base
        return None

    async def get_budget(self, campaign_id: str) -> dict[str, Any] | None:
        for r in self._campaigns():
            if r.get("campaign_id") == str(campaign_id):
                amt = _to_float(r.get("daily_budget_jpy"))
                return {
                    "campaign_id": campaign_id,
                    "amount_micros": int(amt * 1_000_000),
                    "amount": amt,
                    "delivery_method": "STANDARD",
                    "status": "ENABLED",
                }
        return None

    async def list_ad_groups(
        self,
        campaign_id: str | None = None,
        status_filter: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = self._ad_groups()
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        return [
            {
                "id": r.get("ad_group_id"),
                "campaign_id": r.get("campaign_id"),
                "name": r.get("name"),
                "status": r.get("status"),
                "type": "SEARCH_STANDARD",
            }
            for r in rows
        ]

    async def list_ads(
        self,
        ad_group_id: str | None = None,
        status_filter: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = self._ads()
        if ad_group_id:
            rows = [r for r in rows if r.get("ad_group_id") == str(ad_group_id)]
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        return [
            {
                "id": r.get("ad_id"),
                "ad_group_id": r.get("ad_group_id"),
                "headlines": [r.get("headline_1", ""), r.get("headline_2", "")],
                "descriptions": [r.get("description", "")],
                "final_url": r.get("final_url", ""),
                "status": r.get("status"),
                "type": "RESPONSIVE_SEARCH_AD",
            }
            for r in rows
        ]

    async def list_keywords(
        self,
        ad_group_id: str | None = None,
        status_filter: str | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = self._keywords()
        if ad_group_id:
            rows = [r for r in rows if r.get("ad_group_id") == str(ad_group_id)]
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        return [
            {
                "id": r.get("keyword_id"),
                "ad_group_id": r.get("ad_group_id"),
                "text": r.get("text"),
                "match_type": r.get("match_type"),
                "status": r.get("status"),
            }
            for r in rows
        ]

    async def list_negative_keywords(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def _aggregate_metrics(
        self,
        rows: Iterable[dict[str, Any]],
        start: date,
        end: date,
        group_by: str = "campaign_id",
    ) -> dict[str, dict[str, float]]:
        agg: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "impressions": 0,
                "clicks": 0,
                "cost": 0.0,
                "conversions": 0.0,
            }
        )
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            key = r.get(group_by) or ""
            agg[key]["impressions"] += _to_int(r.get("impressions"))
            agg[key]["clicks"] += _to_int(r.get("clicks"))
            agg[key]["cost"] += _to_float(r.get("cost_jpy"))
            agg[key]["conversions"] += _to_float(r.get("conversions"))
        return agg

    async def get_performance_report(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        start, end = _period_to_range(period)
        rows = self._metrics()
        if campaign_id:
            rows = [r for r in rows if r.get("campaign_id") == str(campaign_id)]
        agg = self._aggregate_metrics(rows, start, end, group_by="campaign_id")

        name_lookup = {
            r.get("campaign_id"): r.get("name", "") for r in self._campaigns()
        }
        out = []
        for cid, m in agg.items():
            ctr = (m["clicks"] / m["impressions"]) if m["impressions"] else 0
            avg_cpc = (m["cost"] / m["clicks"]) if m["clicks"] else 0
            cost_per_conv = (m["cost"] / m["conversions"]) if m["conversions"] else 0
            out.append(
                {
                    "campaign_id": cid,
                    "campaign_name": name_lookup.get(cid, ""),
                    "impressions": int(m["impressions"]),
                    "clicks": int(m["clicks"]),
                    "cost": m["cost"],
                    "conversions": m["conversions"],
                    "ctr": round(ctr, 4),
                    "average_cpc": round(avg_cpc, 2),
                    "cost_per_conversion": round(cost_per_conv, 2),
                }
            )
        return out

    async def get_search_terms_report(
        self,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        period: str = "LAST_30_DAYS",  # noqa: ARG002
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Return search-term-level performance from the BYOD bundle.

        The Apps Script (`google-ads-script.js`) emits a `search_terms`
        tab with one row per search-term; the bundle adapter writes
        ``search_terms.csv``. The Apps Script does not stamp the rows
        with a date (it aggregates over its own DAYS_LOOKBACK), so the
        ``period`` kwarg is accepted for signature parity with the
        real-API client but does not actually filter rows.

        ``campaign_id`` / ``ad_group_id`` filter against the synthetic
        IDs (``camp_<sha10>`` / ``ag_<sha10>``) the adapter assigns.
        Filtering by these requires the caller to first call
        ``list_campaigns`` / ``list_ad_groups`` and translate names.
        """
        rows = self._search_terms()
        if not rows:
            return []
        # Build name->id maps so we can match the caller's ID filters
        # against the campaign/ad_group name columns the Apps Script
        # writes (it does not export numeric IDs).
        camp_name_by_id = {
            r.get("campaign_id"): r.get("name", "") for r in self._campaigns()
        }
        ag_name_by_id = {
            r.get("ad_group_id"): r.get("name", "") for r in self._ad_groups()
        }
        out: list[dict[str, Any]] = []
        for r in rows:
            if campaign_id and r.get("campaign") != camp_name_by_id.get(
                str(campaign_id)
            ):
                continue
            if ad_group_id and r.get("ad_group") != ag_name_by_id.get(str(ad_group_id)):
                continue
            impressions = _to_int(r.get("impressions"))
            clicks = _to_int(r.get("clicks"))
            cost = _to_float(r.get("cost"))
            conversions = _to_float(r.get("conversions"))
            ctr = (clicks / impressions) if impressions else 0
            avg_cpc = (cost / clicks) if clicks else 0
            # Schema parity: the real-API client's map_search_term in
            # mureo/google_ads/mappers.py returns metrics as a nested
            # dict so downstream consumers (_analysis_search_terms,
            # _analysis_performance) can read `t["metrics"]["cost"]`.
            # If we returned flat keys those consumers would silently
            # treat every BYOD row's cost as 0.
            out.append(
                {
                    "search_term": r.get("search_term", ""),
                    "campaign_name": r.get("campaign", ""),
                    "ad_group_name": r.get("ad_group", ""),
                    "metrics": {
                        "impressions": impressions,
                        "clicks": clicks,
                        "cost": cost,
                        "cost_micros": int(cost * 1_000_000),
                        "conversions": conversions,
                        "ctr": round(ctr, 4),
                    },
                    "average_cpc": round(avg_cpc, 2),
                }
            )
        return out

    async def get_auction_insights(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",  # noqa: ARG002
        **_: Any,
    ) -> list[dict[str, Any]]:
        """Return per-competitor auction insight rows for ``campaign_id``.

        The Apps Script's ``auction_insights`` tab carries one row per
        (campaign, competitor_domain) pair with impression_share and
        outranking_share. The BYOD path does not have access to the
        deeper metrics the live Google Ads UI exposes (overlap rate,
        position-above rate, etc.), so this method returns only the
        two share fields plus identifiers.
        """
        rows = self._auction_insights()
        if not rows:
            return []
        camp_name_by_id = {
            r.get("campaign_id"): r.get("name", "") for r in self._campaigns()
        }
        target_name = camp_name_by_id.get(str(campaign_id))
        if target_name is None:
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            if r.get("campaign") != target_name:
                continue
            out.append(
                {
                    "campaign_id": campaign_id,
                    "campaign_name": target_name,
                    "competitor_domain": r.get("competitor_domain", ""),
                    "impression_share": _to_float(r.get("impression_share")),
                    "outranking_share": _to_float(r.get("outranking_share")),
                }
            )
        return out

    async def analyze_auction_insights(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> dict[str, Any]:
        """Aggregate auction-insight rows for one campaign.

        Returns the campaign's own impression_share (averaged across
        the rows in the tab) plus the top 5 competitors ranked by
        impression_share, mirroring the live API client's
        ``analyze_auction_insights`` shape closely enough that the
        BYOD path can fill in for `/daily-check`.
        """
        rows = await self.get_auction_insights(campaign_id=campaign_id, period=period)
        if not rows:
            return {
                "campaign_id": campaign_id,
                "competitors": [],
                "note": (
                    "BYOD: no auction_insights data for this campaign in "
                    "the imported bundle."
                ),
            }
        rows_sorted = sorted(rows, key=lambda r: r["impression_share"], reverse=True)
        return {
            "campaign_id": campaign_id,
            "campaign_name": rows[0]["campaign_name"],
            "competitors": rows_sorted[:5],
            "competitor_count": len(rows_sorted),
        }

    async def diagnose_campaign_delivery(
        self, campaign_id: str, **_: Any
    ) -> dict[str, Any]:
        camp = await self.get_campaign(campaign_id)
        if camp is None:
            return {"campaign_id": campaign_id, "issues": []}
        return {
            "campaign_id": campaign_id,
            "issues": [],
            "note": (
                "BYOD mode: delivery diagnostics derive from the imported "
                "CSV only -- fields like primary_status_reasons are not in "
                "the export, so this returns an empty issue list."
            ),
        }

    async def detect_cpc_trend(self, campaign_id: str, **_: Any) -> dict[str, Any]:
        rows = [r for r in self._metrics() if r.get("campaign_id") == str(campaign_id)]
        rows.sort(key=lambda r: r.get("date", ""))
        if len(rows) < 7:
            return {
                "campaign_id": campaign_id,
                "direction": "insufficient_data",
            }
        midpoint = len(rows) // 2
        early = rows[:midpoint]
        late = rows[midpoint:]

        def _avg_cpc(rows_: list[dict[str, Any]]) -> float:
            cost = sum(_to_float(r.get("cost_jpy")) for r in rows_)
            clicks = sum(_to_int(r.get("clicks")) for r in rows_)
            return cost / clicks if clicks else 0.0

        early_cpc = _avg_cpc(early)
        late_cpc = _avg_cpc(late)
        change = (late_cpc - early_cpc) / early_cpc * 100 if early_cpc else 0.0
        direction = "rising" if change > 5 else "falling" if change < -5 else "stable"
        return {
            "campaign_id": campaign_id,
            "direction": direction,
            "early_cpc": round(early_cpc, 2),
            "recent_cpc": round(late_cpc, 2),
            "change_rate_per_day_pct": round(change / max(midpoint, 1), 2),
        }

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        if any(name.startswith(verb) for verb in _MUTATION_PREFIXES):
            return _async_byod_blocked(name)
        return _async_empty_list()


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
        start, end = _period_to_range(period)
        rows = self._metrics()
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
        for r in rows:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            key = r.get("campaign_id") or ""
            agg[key]["impressions"] += _to_int(r.get("impressions"))
            agg[key]["clicks"] += _to_int(r.get("clicks"))
            agg[key]["cost"] += _to_float(r.get("cost_jpy"))
            agg[key]["conversions"] += _to_float(r.get("conversions"))

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
        start, end = _period_to_range(period)
        rows = self._metrics()
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
        start, end = _period_to_range(period)
        rows = self._ad_set_metrics()
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
        start, end = _period_to_range(period)
        rows = self._ad_metrics()
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
        start, end = _period_to_range(period)
        rows = self._demographics()
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
