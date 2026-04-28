"""Tests for the BYOD Sheet bundle importer.

Covers:
  - Happy path with Google Ads tabs (the sole BYOD platform after the
    Phase 1 BYOD redesign)
  - Workbook with no recognized tabs -> BundleImportError
  - Replace semantics (refuse on conflict / overwrite with replace=True)
  - Missing required column -> error + rollback (no partial CSVs left)
  - Non-XLSX file -> BundleImportError
  - Manifest entry shape matches the existing schema
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# xlsx fixture builders
# ---------------------------------------------------------------------------


def _make_workbook(tmp_path: Path, *, tabs: dict[str, list[list]]) -> Path:
    """Create an xlsx file at ``tmp_path/test.xlsx`` with the given tabs.

    ``tabs`` maps tab name -> list of rows (first row is the header).
    """
    from openpyxl import Workbook

    wb = Workbook()
    # The first sheet is created automatically; remove it so the
    # workbook only contains tabs explicitly listed.
    default = wb.active
    wb.remove(default)

    for name, rows in tabs.items():
        sheet = wb.create_sheet(name)
        for row in rows:
            sheet.append(row)

    out = tmp_path / "test.xlsx"
    wb.save(out)
    return out


def _google_ads_tabs() -> dict[str, list[list]]:
    return {
        "campaigns": [
            ["day", "campaign", "impressions", "clicks", "cost", "conversions"],
            ["2026-04-01", "Brand Search", 1000, 50, 25.5, 3.0],
            ["2026-04-02", "Brand Search", 1100, 55, 28.0, 4.0],
            ["2026-04-01", "Generic Search", 2000, 80, 60.0, 5.0],
        ],
        "ad_groups": [
            [
                "day",
                "campaign",
                "ad_group",
                "impressions",
                "clicks",
                "cost",
                "conversions",
            ],
            ["2026-04-01", "Brand Search", "Exact match", 800, 40, 20.0, 2.0],
        ],
    }


# ---------------------------------------------------------------------------
# tmp_path BYOD root
# ---------------------------------------------------------------------------


@pytest.fixture()
def byod_root(tmp_path, monkeypatch):
    """Redirect ``~/.mureo/byod/`` to ``tmp_path/.mureo/byod/``."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    return fake_home / ".mureo" / "byod"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_import_bundle_writes_google_ads(tmp_path, byod_root):
    from mureo.byod.bundle import import_bundle

    src = _make_workbook(tmp_path, tabs=_google_ads_tabs())

    results = import_bundle(src)

    assert set(results.keys()) == {"google_ads"}

    ga_root = byod_root / "google_ads"
    assert (ga_root / "campaigns.csv").exists()
    assert (ga_root / "metrics_daily.csv").exists()
    assert results["google_ads"]["rows"] >= 1
    assert results["google_ads"]["date_range"]["start"] == "2026-04-01"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_import_bundle_no_recognized_tabs(tmp_path, byod_root):
    from mureo.byod.bundle import BundleImportError, import_bundle

    src = _make_workbook(
        tmp_path,
        tabs={"unrelated_data": [["foo", "bar"], [1, 2]]},
    )

    with pytest.raises(BundleImportError, match="no recognized tabs"):
        import_bundle(src)


def test_import_bundle_missing_required_column_rolls_back(
    tmp_path, byod_root
):
    """Adapter rejects a workbook whose ``campaigns`` tab lacks
    required columns; the bundle importer must roll back any partial
    on-disk artifact."""
    from mureo.byod.bundle import BundleImportError, import_bundle

    src = _make_workbook(
        tmp_path,
        tabs={
            "campaigns": [
                # Missing 'impressions', 'clicks', etc.
                ["day", "campaign"],
                ["2026-04-01", "Brand"],
            ],
        },
    )

    with pytest.raises(BundleImportError):
        import_bundle(src)

    assert not (byod_root / "google_ads").exists()


def test_import_bundle_non_xlsx_file(tmp_path, byod_root):
    from mureo.byod.bundle import BundleImportError, import_bundle

    not_xlsx = tmp_path / "fake.xlsx"
    not_xlsx.write_text("this is not really an xlsx", encoding="utf-8")

    with pytest.raises(BundleImportError, match="failed to open as XLSX"):
        import_bundle(not_xlsx)


def test_import_bundle_missing_file(tmp_path, byod_root):
    from mureo.byod.bundle import BundleImportError, import_bundle

    with pytest.raises(BundleImportError, match="file not found"):
        import_bundle(tmp_path / "does-not-exist.xlsx")


# ---------------------------------------------------------------------------
# Replace semantics
# ---------------------------------------------------------------------------


def test_import_bundle_refuses_existing_without_replace(tmp_path, byod_root):
    from mureo.byod.bundle import BundleImportError, import_bundle

    src = _make_workbook(tmp_path, tabs=_google_ads_tabs())
    import_bundle(src)  # first import succeeds

    with pytest.raises(BundleImportError, match="already exists"):
        import_bundle(src)


def test_import_bundle_replace_overwrites(tmp_path, byod_root):
    from mureo.byod.bundle import import_bundle

    src1 = _make_workbook(tmp_path, tabs=_google_ads_tabs())
    import_bundle(src1)

    src2_dir = tmp_path / "second"
    src2_dir.mkdir()
    new_tabs = {
        "campaigns": [
            ["day", "campaign", "impressions", "clicks", "cost", "conversions"],
            ["2026-05-10", "Refreshed", 2000, 100, 50.0, 8.0],
        ],
    }
    src2 = _make_workbook(src2_dir, tabs=new_tabs)

    import_bundle(src2, replace=True)
    csv_text = (
        byod_root / "google_ads" / "metrics_daily.csv"
    ).read_text(encoding="utf-8")
    assert "2026-04-01" not in csv_text
    assert "2026-05-10" in csv_text


# ---------------------------------------------------------------------------
# Manifest schema
# ---------------------------------------------------------------------------


def test_import_bundle_manifest_entry_shape(tmp_path, byod_root):
    from mureo.byod.bundle import import_bundle

    src = _make_workbook(tmp_path, tabs=_google_ads_tabs())
    import_bundle(src)

    manifest = json.loads(
        (byod_root / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == 1
    assert set(manifest["platforms"].keys()) == {"google_ads"}
    entry = manifest["platforms"]["google_ads"]
    for key in (
        "files",
        "date_range",
        "rows",
        "campaigns",
        "ad_groups",
        "source_format",
        "imported_at",
        "source_file_sha256",
        "source_filename",
    ):
        assert key in entry, f"missing manifest key: {key}"
    assert entry["source_filename"] == "test.xlsx"
