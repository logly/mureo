"""Meta Ads BYOD adapter — consumes the user's Ads Manager Excel export.

Meta does not offer a "scripts inside the Ads UI" runtime equivalent
to Google Ads Scripts, and bundling a mureo-managed Marketing API
client would violate the project's "no SaaS" contract. The pragmatic
no-OAuth path is the manual XLSX export users can run themselves
from Ads Manager:

  Ads Manager → Reports → Customize → set columns → Export → Excel

This adapter normalizes that single-tab export into the 4 CSVs the
existing ``ByodMetaAdsClient`` (``mureo/byod/clients.py``) reads
under ``~/.mureo/byod/meta_ads/``:

  campaigns.csv      campaign_id, name, status, objective, daily_budget_jpy
  ad_sets.csv        ad_set_id, campaign_id, name, status
  ads.csv            ad_id, ad_set_id, name, status
  metrics_daily.csv  date, campaign_id, impressions, clicks, cost_jpy, conversions

Identity is synthesized from name (deterministic SHA-256 hash) because
the Ads Manager export does not include numeric IDs by default. The
hash is stable across re-imports so STATE.json references continue
to resolve.

Recognized header names (English Ads Manager UI for v1):

  Date column         "Day" / "Reporting starts" / "Date"
  Campaign            "Campaign name"
  Ad set              "Ad set name" (optional)
  Ad                  "Ad name" (optional)
  Impressions         "Impressions"
  Clicks              "Clicks (all)" / "Link clicks" / "Clicks"
  Spend               "Amount spent (JPY)" / "Amount spent" / "Spend"
  Conversions         "Results" / "Conversions" (optional)

Other locales (Japanese, etc.) are not supported in v1; users on
non-English Ads Manager UIs can switch the report language to English
under Reports → Account language for the export. v2 may add locale
aliasing similar to v0.6's Google Ads CSV path.
"""

from __future__ import annotations

import csv as _csv
import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from openpyxl.workbook.workbook import Workbook

SOURCE_FORMAT = "mureo_meta_ads_export_v1"


@dataclass
class ImportResult:
    """Per-platform return value from a normalize_from_workbook call."""

    rows: int
    date_range: tuple[str, str]
    files_written: list[str]
    source_format: str
    campaigns: int
    ad_groups: int  # repurposed as ad_sets count for Meta


class UnsupportedFormatError(ValueError):
    """Raised when no sheet in the workbook matches the expected schema."""


# ---------------------------------------------------------------------------
# Header alias map — lowercased, stripped, multiple Ads Manager wordings →
# canonical column names used internally by this adapter.
# ---------------------------------------------------------------------------

_DATE_ALIASES = ("day", "reporting starts", "date")
_CAMPAIGN_ALIASES = ("campaign name",)
_AD_SET_ALIASES = ("ad set name",)
_AD_ALIASES = ("ad name",)
_IMPRESSIONS_ALIASES = ("impressions",)
_CLICKS_ALIASES = ("clicks (all)", "link clicks", "clicks")
_SPEND_ALIASES = ("amount spent (jpy)", "amount spent", "spend")
_CONVERSIONS_ALIASES = ("results", "conversions")


_DATE_RE_DASH = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATE_RE_SLASH_ISO = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
_DATE_RE_SLASH_US = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _parse_day(value: str) -> str:
    """Normalize a date cell to YYYY-MM-DD; return '' on failure.

    Recognized formats:
      - ``YYYY-MM-DD`` (ISO)
      - ``YYYY/MM/DD`` (slash-form ISO)
      - ``MM/DD/YYYY`` (US-locale Ads Manager export)
    EU-locale ``DD/MM/YYYY`` is intentionally **not** recognized: it is
    indistinguishable from ``MM/DD/YYYY`` for days <= 12, so accepting
    both would silently mis-aggregate metrics half the time. EU-locale
    users are instructed in ``docs/byod.md`` to switch *Reports →
    Account language* to English (which produces ``MM/DD/YYYY``).
    """
    s = (value or "").strip()
    m = _DATE_RE_DASH.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_RE_SLASH_ISO.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_RE_SLASH_US.match(s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def _synthetic_id(prefix: str, name: str) -> str:
    """Deterministic short ID from a name (stable across imports)."""
    h = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{h}"


def _header_row(sheet: object) -> list[str]:
    """Return the first row of an openpyxl sheet, lowercased + stripped."""
    rows = list(sheet.iter_rows(values_only=True, max_row=1))  # type: ignore[attr-defined]
    if not rows:
        return []
    return [str(c).strip().lower() if c is not None else "" for c in rows[0]]


def _resolve_alias(header: list[str], aliases: tuple[str, ...]) -> int | None:
    """Return the column index of the first matching alias, or None."""
    for alias in aliases:
        if alias in header:
            return header.index(alias)
    return None


def _iter_data_rows(sheet: object) -> Any:
    """Yield rows after the header, skipping fully-blank lines."""
    first = True
    for row in sheet.iter_rows(values_only=True):  # type: ignore[attr-defined]
        if first:
            first = False
            continue
        if row is None or all(c is None or str(c).strip() == "" for c in row):
            continue
        yield row


def _cell_at(row: tuple[Any, ...], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    val = row[idx]
    return "" if val is None else str(val).strip()


def _detect_meta_sheet(workbook: Workbook) -> str | None:
    """Return the name of the first sheet that looks like a Meta export.

    The Google Ads Script tabs use the column ``campaign`` (short
    form), while the Meta Ads Manager export uses ``Campaign name``
    (long form). Requiring the long form keeps the two adapters
    disjoint when both data sources are bundled in a single workbook.
    """
    for sheet_name in workbook.sheetnames:
        header = _header_row(workbook[sheet_name])
        if not header:
            continue
        has_date = any(a in header for a in _DATE_ALIASES)
        has_campaign = "campaign name" in header
        has_impressions = "impressions" in header
        if has_date and has_campaign and has_impressions:
            return str(sheet_name)
    return None


@dataclass
class MetaAdsAdapter:
    """Workbook-aware Meta Ads BYOD adapter."""

    @classmethod
    def has_tab(cls, workbook: Workbook) -> bool:
        """True when the workbook contains a sheet whose header looks
        like a Meta Ads Manager export."""
        return _detect_meta_sheet(workbook) is not None

    def normalize_from_workbook(
        self, workbook: Workbook, dst_dir: Path
    ) -> ImportResult:
        sheet_name = _detect_meta_sheet(workbook)
        if sheet_name is None:
            raise UnsupportedFormatError(
                "No sheet matched the Meta Ads export schema. Expected a "
                "tab with at least: a date column (Day / Reporting starts "
                "/ Date), 'Campaign name', and 'Impressions'."
            )

        sheet = workbook[sheet_name]
        header = _header_row(sheet)

        date_idx = _resolve_alias(header, _DATE_ALIASES)
        camp_idx = _resolve_alias(header, _CAMPAIGN_ALIASES)
        impr_idx = _resolve_alias(header, _IMPRESSIONS_ALIASES)
        clicks_idx = _resolve_alias(header, _CLICKS_ALIASES)
        spend_idx = _resolve_alias(header, _SPEND_ALIASES)
        conv_idx = _resolve_alias(header, _CONVERSIONS_ALIASES)
        ad_set_idx = _resolve_alias(header, _AD_SET_ALIASES)
        ad_idx = _resolve_alias(header, _AD_ALIASES)

        if date_idx is None or camp_idx is None or impr_idx is None:
            raise UnsupportedFormatError(
                f"{sheet_name}: missing required columns. Need a date, "
                f"'Campaign name', and 'Impressions'. Found: {header}"
            )

        dst_dir.mkdir(parents=True, exist_ok=True)
        files_written: list[str] = []
        all_dates: list[str] = []

        # Aggregate across rows. The export may have multiple rows per
        # (day, campaign) pair when Ad set / Ad breakdown is enabled,
        # so metrics need summing per day×campaign rather than
        # passthrough.
        campaign_ids: dict[str, str] = {}
        ad_set_ids: dict[tuple[str, str], str] = {}  # (campaign, ad_set) -> id
        # Keying ads by (campaign, ad_set, ad) — not (ad_set, ad) — so
        # that two campaigns reusing the same ad set name (e.g.
        # "Default", "Lookalike 1%") get distinct ad_set_id rows in
        # ads.csv. Earlier `(ad_set, ad)` keying caused a cross-campaign
        # collision flagged in code review of this PR.
        ad_records: list[tuple[str, str, str, str]] = []  # (camp, ad_set, ad, id)
        seen_ad_keys: set[tuple[str, str, str]] = set()

        # day×campaign → metrics
        metrics_agg: dict[tuple[str, str], dict[str, float]] = {}

        # Currency validation is interleaved with the main loop below
        # rather than pre-scanned, because openpyxl's ``read_only=True``
        # sheets are effectively single-pass — a separate scan loop
        # would consume the row iterator and leave the main loop with
        # no rows to process.

        for raw in _iter_data_rows(sheet):
            day = _parse_day(_cell_at(raw, date_idx))
            if not day:
                continue
            camp_name = _cell_at(raw, camp_idx)
            if not camp_name:
                continue

            cid = campaign_ids.setdefault(camp_name, _synthetic_id("camp", camp_name))

            ad_set_name = _cell_at(raw, ad_set_idx)
            if ad_set_name:
                key = (camp_name, ad_set_name)
                if key not in ad_set_ids:
                    ad_set_ids[key] = _synthetic_id("as", f"{camp_name}::{ad_set_name}")

            ad_name = _cell_at(raw, ad_idx)
            if ad_name and ad_set_name:
                ad_key = (camp_name, ad_set_name, ad_name)
                if ad_key not in seen_ad_keys:
                    seen_ad_keys.add(ad_key)
                    ad_records.append(
                        (
                            camp_name,
                            ad_set_name,
                            ad_name,
                            _synthetic_id(
                                "ad",
                                f"{camp_name}::{ad_set_name}::{ad_name}",
                            ),
                        )
                    )

            spend_raw = _cell_at(raw, spend_idx)
            if spend_raw and spend_raw[0] in _NON_JPY_CURRENCY_PREFIXES:
                raise UnsupportedFormatError(
                    f"{sheet_name}: spend column contains non-JPY value "
                    f"{spend_raw!r}. The BYOD pipeline assumes JPY; "
                    f"switch Ads Manager → Account currency to JPY "
                    f"before export."
                )

            agg_key = (day, cid)
            cell = metrics_agg.setdefault(
                agg_key,
                {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "conv": 0.0},
            )
            cell["impressions"] += _to_float(_cell_at(raw, impr_idx))
            cell["clicks"] += _to_float(_cell_at(raw, clicks_idx))
            cell["cost"] += _to_float(spend_raw)
            cell["conv"] += _to_float(_cell_at(raw, conv_idx))

            all_dates.append(day)

        if not metrics_agg:
            raise UnsupportedFormatError(
                f"{sheet_name}: no data rows after the header."
            )

        # ---- campaigns.csv ---------------------------------------------------
        campaigns_path = dst_dir / "campaigns.csv"
        with campaigns_path.open("w", encoding="utf-8", newline="") as f:
            writer = _csv.DictWriter(
                f,
                fieldnames=[
                    "campaign_id",
                    "name",
                    "status",
                    "objective",
                    "daily_budget_jpy",
                ],
            )
            writer.writeheader()
            for name, cid in campaign_ids.items():
                writer.writerow(
                    {
                        "campaign_id": cid,
                        "name": _sanitize_cell(name),
                        # Ads Manager export does not carry status /
                        # objective / budget. Empty strings keep the
                        # column shape stable for the BYOD client's
                        # _to_float / _to_int helpers.
                        "status": "",
                        "objective": "",
                        "daily_budget_jpy": "",
                    }
                )
        files_written.append("campaigns.csv")

        # ---- ad_sets.csv -----------------------------------------------------
        if ad_set_ids:
            ad_sets_path = dst_dir / "ad_sets.csv"
            with ad_sets_path.open("w", encoding="utf-8", newline="") as f:
                writer = _csv.DictWriter(
                    f,
                    fieldnames=["ad_set_id", "campaign_id", "name", "status"],
                )
                writer.writeheader()
                for (camp_name, ad_set_name), asid in ad_set_ids.items():
                    writer.writerow(
                        {
                            "ad_set_id": asid,
                            "campaign_id": campaign_ids[camp_name],
                            "name": _sanitize_cell(ad_set_name),
                            "status": "",
                        }
                    )
            files_written.append("ad_sets.csv")

        # ---- ads.csv ---------------------------------------------------------
        if ad_records:
            ads_path = dst_dir / "ads.csv"
            with ads_path.open("w", encoding="utf-8", newline="") as f:
                writer = _csv.DictWriter(
                    f,
                    fieldnames=["ad_id", "ad_set_id", "name", "status"],
                )
                writer.writeheader()
                for camp_name, ad_set_name, ad_name, aid in ad_records:
                    # Direct lookup keyed by (campaign, ad_set) — fixes
                    # the cross-campaign collision flagged in review.
                    asid = ad_set_ids.get((camp_name, ad_set_name), "")
                    writer.writerow(
                        {
                            "ad_id": aid,
                            "ad_set_id": asid,
                            "name": _sanitize_cell(ad_name),
                            "status": "",
                        }
                    )
            files_written.append("ads.csv")

        # ---- metrics_daily.csv ----------------------------------------------
        metrics_path = dst_dir / "metrics_daily.csv"
        with metrics_path.open("w", encoding="utf-8", newline="") as f:
            writer = _csv.DictWriter(
                f,
                fieldnames=[
                    "date",
                    "campaign_id",
                    "impressions",
                    "clicks",
                    "cost_jpy",
                    "conversions",
                ],
            )
            writer.writeheader()
            for (day, cid), m in sorted(metrics_agg.items()):
                writer.writerow(
                    {
                        "date": day,
                        "campaign_id": cid,
                        "impressions": int(m["impressions"]),
                        "clicks": int(m["clicks"]),
                        "cost_jpy": _round2(m["cost"]),
                        "conversions": _round2(m["conv"]),
                    }
                )
        files_written.append("metrics_daily.csv")

        sorted_dates = sorted(all_dates)
        return ImportResult(
            rows=len(metrics_agg),
            date_range=(sorted_dates[0], sorted_dates[-1]),
            files_written=files_written,
            source_format=SOURCE_FORMAT,
            campaigns=len(campaign_ids),
            # ImportResult.ad_groups is repurposed for Meta as ad-set
            # count for parity with the Google Ads adapter; the
            # `ad_groups` manifest key documents downstream as
            # "second-level identity rows" rather than the literal
            # Google Ads ad-group concept.
            ad_groups=len(ad_set_ids),
        )


def _to_float(value: str) -> float:
    """Parse a numeric cell that may include a currency symbol or
    thousands separators (Ads Manager export sometimes wraps ``Amount
    spent`` as ``¥1,234.56`` or ``"1,234"``). Returns 0.0 on failure.

    Only ¥ (JPY) and bare numerics are tolerated. Non-JPY currency
    symbols (``$``, ``€``, ``£``) leak through as 0.0 and are caught
    upstream by :func:`_scan_non_jpy_currency` before this function
    is reached on a real spend cell.
    """
    s = (value or "").strip()
    if not s:
        return 0.0
    s = s.replace(",", "").replace("¥", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _round2(value: float) -> str:
    return f"{value:.2f}"


_NON_JPY_CURRENCY_PREFIXES = ("$", "€", "£", "₩", "₹", "¢")


# Cells starting with one of these characters are treated as formulas
# by Excel / Google Sheets when the CSV is re-opened. A campaign named
# ``=cmd|...`` would auto-execute on re-open, exfiltrating data. We
# sanitize untrusted cell values by prefixing a single quote.
# OWASP "CSV Injection" — the leading quote is stripped on display by
# Excel and renders as a literal at the start of the field elsewhere.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: str) -> str:
    """Defang user-controlled cell content against CSV-injection."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value
