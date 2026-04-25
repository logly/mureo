"""Google Ads Report Editor CSV adapter.

Converts a Google Ads Report Editor CSV export into the mureo internal
schema written to ``~/.mureo/byod/google_ads/``.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

SOURCE_FORMAT = "google_ads_report_editor_v1"

_PII_NEEDLES = ("email", "phone", "user_id", "ip_address", "customer_email")
_REQUIRED_COLS = {"campaign", "day", "impressions", "clicks", "cost"}


@dataclass
class ImportResult:
    rows: int
    date_range: tuple[str, str]
    files_written: list[str]
    source_format: str
    campaigns: int
    ad_groups: int


class PIIDetectedError(ValueError):
    """Raised when an obvious PII column is found in the source CSV."""


class UnsupportedFormatError(ValueError):
    """Raised when the source file does not look like a known format."""


def _strip_currency(v: str) -> str:
    if not v:
        return ""
    return re.sub(r"[¥$€£,\s]", "", str(v))


def _norm_col(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip().lower())


def _synthetic_id(prefix: str, name: str) -> str:
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{h}"


def _parse_day(v: str) -> str:
    s = (v or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return s


class GoogleAdsAdapter:
    """Adapter for Google Ads Report Editor CSV exports."""

    SOURCE_FORMAT = SOURCE_FORMAT

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        norm = {_norm_col(h) for h in header}
        return _REQUIRED_COLS.issubset(norm)

    def normalize(self, src: Path, dst_dir: Path) -> ImportResult:
        dst_dir.mkdir(parents=True, exist_ok=True)

        with src.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise UnsupportedFormatError(f"{src.name}: CSV has no header row")
            header = list(reader.fieldnames)
            rows = list(reader)

        if not self.detect(header):
            raise UnsupportedFormatError(
                f"{src.name}: not a Google Ads Report Editor export. "
                f"Required columns (case-insensitive): {sorted(_REQUIRED_COLS)}"
            )

        for col_name in header:
            low = col_name.lower()
            if any(needle in low for needle in _PII_NEEDLES):
                raise PIIDetectedError(
                    f"{src.name}: refusing to import — column "
                    f"{col_name!r} looks like PII. Remove the column from the "
                    f"export and try again."
                )

        col_map = {_norm_col(c): c for c in header}

        def col(row: dict[str, Any], key: str, default: str = "") -> str:
            actual = col_map.get(key)
            if actual is None:
                return default
            v = row.get(actual)
            if v is None:
                return default
            return str(v).strip()

        campaigns: dict[str, dict[str, str]] = {}
        ad_groups: dict[str, dict[str, str]] = {}
        metrics: list[dict[str, Any]] = []
        all_dates: list[str] = []

        for row in rows:
            camp_name = col(row, "campaign")
            if not camp_name:
                continue
            cid = _synthetic_id("gads", camp_name)
            campaigns.setdefault(
                cid,
                {
                    "campaign_id": cid,
                    "name": camp_name,
                    "status": col(row, "campaign_state") or "ENABLED",
                    "channel_type": col(row, "advertising_channel_type") or "SEARCH",
                    "bidding_strategy_type": col(row, "bid_strategy_type") or "",
                    "daily_budget_jpy": _strip_currency(col(row, "budget")) or "0",
                },
            )

            ag_name = col(row, "ad_group")
            ag_id = ""
            if ag_name:
                ag_id = _synthetic_id("agrp", f"{camp_name}|{ag_name}")
                ad_groups.setdefault(
                    ag_id,
                    {
                        "ad_group_id": ag_id,
                        "campaign_id": cid,
                        "name": ag_name,
                        "status": col(row, "ad_group_state") or "ENABLED",
                    },
                )

            day = _parse_day(col(row, "day"))
            if not day:
                continue
            all_dates.append(day)

            metrics.append(
                {
                    "date": day,
                    "campaign_id": cid,
                    "ad_group_id": ag_id,
                    "impressions": _strip_currency(col(row, "impressions")) or "0",
                    "clicks": _strip_currency(col(row, "clicks")) or "0",
                    "cost_jpy": _strip_currency(col(row, "cost")) or "0",
                    "conversions": _strip_currency(col(row, "conversions")) or "0",
                }
            )

        if not metrics:
            raise UnsupportedFormatError(
                f"{src.name}: 0 usable rows after parsing. "
                "Verify the export has Campaign + Day + Impressions/Clicks/Cost."
            )

        files_written: list[str] = []

        camp_path = dst_dir / "campaigns.csv"
        with camp_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "campaign_id",
                    "name",
                    "status",
                    "channel_type",
                    "bidding_strategy_type",
                    "daily_budget_jpy",
                ],
            )
            w.writeheader()
            w.writerows(campaigns.values())
        files_written.append("campaigns.csv")

        if ad_groups:
            ag_path = dst_dir / "ad_groups.csv"
            with ag_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=["ad_group_id", "campaign_id", "name", "status"],
                )
                w.writeheader()
                w.writerows(ad_groups.values())
            files_written.append("ad_groups.csv")

        m_path = dst_dir / "metrics_daily.csv"
        with m_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "date",
                    "campaign_id",
                    "ad_group_id",
                    "impressions",
                    "clicks",
                    "cost_jpy",
                    "conversions",
                ],
            )
            w.writeheader()
            w.writerows(metrics)
        files_written.append("metrics_daily.csv")

        all_dates.sort()
        return ImportResult(
            rows=len(metrics),
            date_range=(all_dates[0], all_dates[-1]),
            files_written=files_written,
            source_format=SOURCE_FORMAT,
            campaigns=len(campaigns),
            ad_groups=len(ad_groups),
        )
