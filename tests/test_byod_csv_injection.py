"""CSV-injection regression tests for the BYOD bundle adapters.

A user-supplied workbook is untrusted input: a campaign / ad-group /
keyword / search-term name of ``=HYPERLINK(...)`` or ``@SUM(...)`` would
auto-execute as a formula if the normalized CSV were later re-opened in
Excel / Google Sheets. Every adapter must prefix such cells with a
single quote (OWASP "CSV Injection") via the shared
``mureo.byod.adapters._csv_safe.sanitize_cell`` helper.

These tests drive the adapters directly (in-memory openpyxl workbook →
tmp output dir) so they never touch ``~/.mureo``.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

import pytest

from mureo.byod.adapters.google_ads import GoogleAdsAdapter
from mureo.byod.adapters.meta_ads import MetaAdsAdapter

if TYPE_CHECKING:
    from pathlib import Path

_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _make_workbook(tabs: dict[str, list[list]]):
    """Build an in-memory openpyxl workbook from ``{tab: rows}``."""
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in tabs.items():
        sheet = wb.create_sheet(name)
        for row in rows:
            sheet.append(row)
    return wb


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _assert_defanged(value: str) -> None:
    """A sanitized cell must start with ``'`` when its payload begins
    with a formula trigger character."""
    assert value.startswith("'"), f"cell not defanged: {value!r}"
    # The original payload (minus the guarding quote) is preserved.
    assert value[1] in _FORMULA_TRIGGERS


@pytest.mark.unit
class TestGoogleAdsCsvInjection:
    def test_names_and_terms_are_sanitized(self, tmp_path: Path) -> None:
        """Malicious campaign / ad-group / keyword / search-term names
        are prefixed with a single quote in every output CSV."""
        tabs = {
            "campaigns": [
                ["day", "campaign", "impressions", "clicks", "cost", "conversions"],
                ["2026-04-01", "=HYPERLINK('http://evil')", 1000, 50, 25.5, 3.0],
            ],
            "ad_groups": [
                ["day", "campaign", "ad_group", "impressions", "clicks", "cost"],
                [
                    "2026-04-01",
                    "=HYPERLINK('http://evil')",
                    "@SUM(A1:A9)",
                    800,
                    40,
                    20.0,
                ],
            ],
            "keywords": [
                ["keyword", "match_type", "campaign", "ad_group", "impressions"],
                ["+running shoes", "-EXACT", "=HYPERLINK('http://evil')", "@grp", 100],
            ],
            "search_terms": [
                ["search_term", "campaign", "ad_group", "clicks"],
                ["=cmd|'/c calc'!A1", "=HYPERLINK('http://evil')", "-grp", 5],
            ],
        }
        dst = tmp_path / "google_ads"
        GoogleAdsAdapter().normalize_from_workbook(_make_workbook(tabs), dst)

        camp = _read_rows(dst / "campaigns.csv")
        assert len(camp) == 1
        _assert_defanged(camp[0]["name"])

        ag = _read_rows(dst / "ad_groups.csv")
        assert len(ag) == 1
        _assert_defanged(ag[0]["name"])

        kw = _read_rows(dst / "keywords.csv")
        assert len(kw) == 1
        _assert_defanged(kw[0]["keyword"])
        _assert_defanged(kw[0]["match_type"])
        _assert_defanged(kw[0]["campaign"])
        _assert_defanged(kw[0]["ad_group"])

        st = _read_rows(dst / "search_terms.csv")
        assert len(st) == 1
        _assert_defanged(st[0]["search_term"])
        _assert_defanged(st[0]["campaign"])
        _assert_defanged(st[0]["ad_group"])

    def test_benign_names_are_untouched(self, tmp_path: Path) -> None:
        """A normal campaign name must not gain a spurious quote."""
        tabs = {
            "campaigns": [
                ["day", "campaign", "impressions", "clicks", "cost", "conversions"],
                ["2026-04-01", "Brand Search", 1000, 50, 25.5, 3.0],
            ],
        }
        dst = tmp_path / "google_ads"
        GoogleAdsAdapter().normalize_from_workbook(_make_workbook(tabs), dst)
        camp = _read_rows(dst / "campaigns.csv")
        assert camp[0]["name"] == "Brand Search"

    def test_numeric_columns_are_not_quoted(self, tmp_path: Path) -> None:
        """Numeric metric columns stay verbatim so the BYOD client can
        still parse them (they are out of scope for the guard)."""
        tabs = {
            "campaigns": [
                ["day", "campaign", "impressions", "clicks", "cost", "conversions"],
                ["2026-04-01", "Brand Search", 1000, 50, 25.5, 3.0],
            ],
            "keywords": [
                ["keyword", "campaign", "ad_group", "clicks", "cost"],
                ["shoes", "Brand Search", "grp", 5, 12.5],
            ],
        }
        dst = tmp_path / "google_ads"
        GoogleAdsAdapter().normalize_from_workbook(_make_workbook(tabs), dst)
        kw = _read_rows(dst / "keywords.csv")
        assert kw[0]["clicks"] == "5"
        assert kw[0]["cost"] == "12.5"


@pytest.mark.unit
class TestMetaAdsResultIndicatorSanitized:
    def test_result_indicator_is_sanitized(self, tmp_path: Path) -> None:
        """The ``result_indicator`` column in metrics_daily.csv is
        user-controlled and must be defanged like every other name
        column (previously the only unsanitized Meta column)."""
        tabs = {
            "Sheet1": [
                [
                    "Day",
                    "Campaign name",
                    "Impressions",
                    "Clicks (all)",
                    "Amount spent (JPY)",
                    "Results",
                    "Result indicator",
                ],
                [
                    "2026-04-01",
                    "Brand Awareness",
                    1000,
                    50,
                    2500,
                    3,
                    "=cmd|'/c calc'!A1",
                ],
            ],
        }
        dst = tmp_path / "meta_ads"
        MetaAdsAdapter().normalize_from_workbook(_make_workbook(tabs), dst)
        rows = _read_rows(dst / "metrics_daily.csv")
        assert len(rows) == 1
        _assert_defanged(rows[0]["result_indicator"])
