"""CSV-backed demo clients used in --demo mode.

These mock the public ad-platform clients
(:class:`mureo.google_ads.client.GoogleAdsApiClient`,
:class:`mureo.meta_ads.client.MetaAdsApiClient`,
:class:`mureo.search_console.client.SearchConsoleApiClient`) by reading
from the static CSVs installed by ``mureo demo init``.

Methods that drive the embedded narrative (CPA spike, organic ranking
drop, Meta CTR stability) are implemented to return realistic shapes.
Any method not implemented here falls back to an empty result via
``__getattr__`` so the agent does not crash on calls outside the demo
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
    try:
        return int(v)
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


def _async_empty_list() -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> list[Any]:
        return []

    return _stub


def _async_demo_blocked(name: str) -> Callable[..., Any]:
    async def _stub(*_: Any, **__: Any) -> dict[str, Any]:
        return {
            "status": "skipped_in_demo",
            "operation": name,
            "note": (
                "Mutations are disabled in mureo demo mode. "
                "This call would have written to a real ad account."
            ),
        }

    return _stub


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------


class DemoGoogleAdsClient:
    """CSV-backed read-only mock of GoogleAdsApiClient."""

    def __init__(self, data_dir: Path, customer_id: str = "demo") -> None:
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

    def _metrics(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "metrics_daily.csv")

    async def list_accounts(self) -> list[dict[str, Any]]:
        return [{"customer_id": self.customer_id or "demo"}]

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
            lambda: {"impressions": 0, "clicks": 0, "cost": 0.0, "conversions": 0.0}
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
        period: str = "LAST_30_DAYS",
        **_: Any,
    ) -> list[dict[str, Any]]:
        return []

    async def diagnose_campaign_delivery(
        self, campaign_id: str, **_: Any
    ) -> dict[str, Any]:
        camp = await self.get_campaign(campaign_id)
        if camp is None:
            return {"campaign_id": campaign_id, "issues": []}
        issues: list[dict[str, Any]] = []
        if str(camp.get("name", "")).lower().find("brand") >= 0:
            issues.append(
                {
                    "code": "DEMO_CPA_REGRESSION",
                    "severity": "HIGH",
                    "description": (
                        "Demo-mode synthetic incident: CPA on this brand "
                        "campaign rose ~45% starting 7 days ago. The data "
                        "ALSO shows the brand keyword's organic position "
                        "fell from #1 to #5 over the same window; check "
                        "Search Console before adjusting bids."
                    ),
                    "remediation_hint": (
                        "Investigate organic ranking regression first; "
                        "lowering paid bids would compound the loss."
                    ),
                }
            )
        return {"campaign_id": campaign_id, "issues": issues}

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
        if any(
            name.startswith(verb)
            for verb in ("create_", "update_", "remove_", "add_", "upload_")
        ):
            return _async_demo_blocked(name)
        return _async_empty_list()


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------


class DemoMetaAdsClient:
    """CSV-backed read-only mock of MetaAdsApiClient."""

    def __init__(self, data_dir: Path, account_id: str = "act_demo") -> None:
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

    async def get_breakdown_report(self, **_: Any) -> list[dict[str, Any]]:
        return []

    async def get_leads(self, **_: Any) -> list[dict[str, Any]]:
        return []

    async def get_ad_leads(self, **_: Any) -> list[dict[str, Any]]:
        return []

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> DemoMetaAdsClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)
        if any(
            name.startswith(verb)
            for verb in (
                "create_",
                "update_",
                "delete_",
                "send_",
                "upload_",
                "add_",
            )
        ):
            return _async_demo_blocked(name)
        return _async_empty_list()


# ---------------------------------------------------------------------------
# Search Console
# ---------------------------------------------------------------------------


class DemoSearchConsoleClient:
    """CSV-backed read-only mock of SearchConsoleApiClient."""

    SITE_URL = "sc-domain:demo.example.com"

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)

    def _queries(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "queries_daily.csv")

    def _pages(self) -> list[dict[str, Any]]:
        return _read_csv(self._dir / "pages_daily.csv")

    async def list_sites(self) -> list[dict[str, Any]]:
        return [{"siteUrl": self.SITE_URL, "permissionLevel": "siteOwner"}]

    async def get_site(self, site_url: str) -> dict[str, Any]:
        return {"siteUrl": site_url, "permissionLevel": "siteOwner"}

    async def query_analytics(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        dimensions: list[str] | None = None,
        row_limit: int = 100,
        dimension_filter_groups: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        start = _parse_date(start_date) or date.today() - timedelta(days=14)
        end = _parse_date(end_date) or date.today()

        dims = dimensions or ["query"]
        wants_query = "query" in dims
        wants_page = "page" in dims
        wants_date = "date" in dims

        if wants_page:
            src = self._pages()
            key_field = "page"
        else:
            src = self._queries()
            key_field = "query"

        agg: dict[tuple[str, ...], dict[str, float]] = defaultdict(
            lambda: {"clicks": 0, "impressions": 0, "position_sum": 0.0, "n": 0}
        )
        for r in src:
            d = _parse_date(r.get("date", ""))
            if d is None or d < start or d > end:
                continue
            keys_buf: list[str] = []
            if wants_query and "query" in r:
                keys_buf.append(r.get("query", ""))
            if wants_page and "page" in r:
                keys_buf.append(r.get("page", ""))
            if wants_date:
                keys_buf.append(r.get("date", ""))
            if not keys_buf:
                keys_buf = [r.get(key_field, "")]
            tup: tuple[str, ...] = tuple(keys_buf)
            cell = agg[tup]
            cell["clicks"] += _to_int(r.get("clicks"))
            cell["impressions"] += _to_int(r.get("impressions"))
            cell["position_sum"] += _to_float(r.get("position"))
            cell["n"] += 1

        out: list[dict[str, Any]] = []
        for tup, cell in agg.items():
            avg_pos = cell["position_sum"] / cell["n"] if cell["n"] else 0
            ctr = cell["clicks"] / cell["impressions"] if cell["impressions"] else 0
            out.append(
                {
                    "keys": list(tup),
                    "clicks": int(cell["clicks"]),
                    "impressions": int(cell["impressions"]),
                    "ctr": round(ctr, 4),
                    "position": round(avg_pos, 2),
                }
            )
        out.sort(key=lambda r: int(r["clicks"]), reverse=True)
        return out[:row_limit]

    async def list_sitemaps(self, site_url: str) -> list[dict[str, Any]]:
        return []

    async def submit_sitemap(self, site_url: str, feedpath: str) -> dict[str, Any]:
        return {
            "status": "skipped_in_demo",
            "operation": "submit_sitemap",
            "note": "Sitemap submissions are disabled in demo mode.",
        }

    async def inspect_url(self, site_url: str, inspection_url: str) -> dict[str, Any]:
        return {
            "status": "skipped_in_demo",
            "inspection_url": inspection_url,
            "note": "URL inspection is not available in demo mode.",
        }

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> DemoSearchConsoleClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None
