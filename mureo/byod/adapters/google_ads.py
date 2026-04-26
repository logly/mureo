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

# Per-canonical Google Ads Report Editor column aliases (lowercase, with
# whitespace replaced by `_` to match _norm_col output). Covers the 15
# most common Google Ads UI languages (en, ja, zh, ko, es, pt, fr, de,
# it, ru, ar, vi, th, id, plus regional variants). Add more as users
# report missing locales.
_COLUMN_ALIASES: dict[str, set[str]] = {
    # Required
    "campaign": {
        "campaign",
        "キャンペーン",
        "广告系列",
        "廣告活動",
        "캠페인",
        "campaña",
        "campanha",
        "campagne",
        "kampagne",
        "campagna",
        "кампания",
        "حملة",
        "chiến_dịch",
        "แคมเปญ",
        "kampanye",
    },
    "day": {
        "day",
        "date",
        "日",
        "日付",
        "日期",
        "일",
        "날짜",
        "día",
        "fecha",
        "dia",
        "data",
        "jour",
        "tag",
        "datum",
        "giorno",
        "день",
        "اليوم",
        "تاريخ",
        "ngày",
        "วัน",
        "hari",
        "tanggal",
    },
    "impressions": {
        "impressions",
        "impr.",
        "impr",
        "表示回数",
        "インプレッション数",
        "展示次数",
        "曝光次數",
        "노출수",
        "노출_수",
        "impresiones",
        "impressões",
        "impressionen",
        "impressioni",
        "показы",
        "مرات_الظهور",
        "số_lần_hiển_thị",
        "การแสดงผล",
        "tayangan",
    },
    "clicks": {
        "clicks",
        "クリック数",
        "点击次数",
        "點擊次數",
        "클릭수",
        "클릭_수",
        "clics",
        "cliques",
        "klicks",
        "clic",
        "клики",
        "النقرات",
        "số_lần_nhấp",
        "คลิก",
        "klik",
    },
    "cost": {
        "cost",
        "spend",
        "費用",
        "费用",
        "비용",
        "costo",
        "coste",
        "custo",
        "coût",
        "kosten",
        "ausgaben",
        "стоимость",
        "затраты",
        "التكلفة",
        "chi_phí",
        "ค่าใช้จ่าย",
        "biaya",
    },
    # Optional
    "ad_group": {
        "ad_group",
        "広告グループ",
        "广告组",
        "廣告群組",
        "광고그룹",
        "광고_그룹",
        "grupo_de_anuncios",
        "anzeigengruppe",
        "groupe_d'annonces",
        "gruppo_di_annunci",
        "группа_объявлений",
        "مجموعة_الإعلانات",
        "nhóm_quảng_cáo",
        "กลุ่มโฆษณา",
        "grup_iklan",
    },
    "conversions": {
        "conversions",
        "コンバージョン",
        "コンバージョン数",
        "转化",
        "转化次数",
        "轉換",
        "전환수",
        "전환_수",
        "conversiones",
        "conversões",
        "konversionen",
        "conversioni",
        "конверсии",
        "تحويلات",
        "chuyển_đổi",
        "การแปลง",
        "konversi",
    },
    "campaign_state": {
        "campaign_state",
        "campaign_status",
        "キャンペーンの状態",
        "キャンペーンのステータス",
        "广告系列状态",
        "캠페인_상태",
        "estado_de_la_campaña",
        "kampagnenstatus",
        "état_de_la_campagne",
        "stato_della_campagna",
        "статус_кампании",
        "trạng_thái_chiến_dịch",
    },
    "advertising_channel_type": {
        "advertising_channel_type",
        "channel_type",
        "広告タイプ",
        "广告渠道类型",
        "광고_채널_유형",
        "tipo_de_canal",
        "kanaltyp",
        "type_de_canal_publicitaire",
    },
    "bid_strategy_type": {
        "bid_strategy_type",
        "bidding_strategy",
        "入札戦略",
        "出价策略",
        "입찰_전략",
        "estrategia_de_oferta",
        "gebotsstrategie",
        "stratégie_d'enchères",
    },
    "budget": {
        "budget",
        "予算",
        "1日の予算",
        "预算",
        "예산",
        "presupuesto",
        "orçamento",
        "tagesbudget",
        "budget_quotidien",
    },
    "ad_group_state": {
        "ad_group_state",
        "ad_group_status",
        "広告グループの状態",
        "广告组状态",
        "광고그룹_상태",
    },
}

# Reverse map: alias -> canonical key.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _COLUMN_ALIASES.items()
    for alias in aliases
}


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


def _row_canonicals(row: list[str]) -> set[str]:
    """Return the set of canonical column keys present in a header row."""
    return {
        canonical
        for cell in row
        if (canonical := _ALIAS_TO_CANONICAL.get(_norm_col(cell))) is not None
    }


def _find_header_row(src: Path, max_lines: int = 5) -> int | None:
    """Scan up to ``max_lines`` lines and return the 0-indexed row whose
    cells satisfy ``_REQUIRED_COLS`` (after alias resolution). Used to
    skip Report Editor preamble across multiple UI languages.
    """
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i >= max_lines:
                break
            if not row:
                continue
            if _REQUIRED_COLS.issubset(_row_canonicals(row)):
                return i
    return None


_TOTALS_NEEDLES = ("total", "grand total", "合計")


class GoogleAdsAdapter:
    """Adapter for Google Ads Report Editor CSV exports."""

    SOURCE_FORMAT = SOURCE_FORMAT

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        return _REQUIRED_COLS.issubset(_row_canonicals(header))

    def normalize(self, src: Path, dst_dir: Path) -> ImportResult:
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Google Ads Report Editor often prepends a 1-3 line preamble
        # (account name, report name, date range) before the column
        # header. Find the header row by sniffing for required columns.
        header_idx = _find_header_row(src)
        if header_idx is None:
            raise UnsupportedFormatError(
                f"{src.name}: not a Google Ads Report Editor export. "
                f"Required columns (case-insensitive): {sorted(_REQUIRED_COLS)}"
            )

        with src.open("r", encoding="utf-8-sig", newline="") as f:
            for _ in range(header_idx):
                f.readline()
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise UnsupportedFormatError(f"{src.name}: CSV has no header row")
            header = list(reader.fieldnames)
            rows = list(reader)

        for col_name in header:
            low = col_name.lower()
            if any(needle in low for needle in _PII_NEEDLES):
                raise PIIDetectedError(
                    f"{src.name}: refusing to import — column "
                    f"{col_name!r} looks like PII. Remove the column from the "
                    f"export and try again."
                )

        # Build canonical-key -> original-header-cell map via alias resolution.
        col_map: dict[str, str] = {}
        for h in header:
            canonical = _ALIAS_TO_CANONICAL.get(_norm_col(h))
            if canonical is not None:
                col_map.setdefault(canonical, h)

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
            # Skip "Total" / "Grand total" / "合計" rows.
            if any(needle in camp_name.lower() for needle in _TOTALS_NEEDLES):
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
