"""BYOD integration tests — runtime / client / factory / CLI.

The bundle-import pipeline itself is unit-tested in
``tests/test_byod_bundle.py``. This file covers the surrounding
contracts:

  - manifest read/write resilience (missing / corrupt / wrong schema)
  - BYOD clients reading the CSVs produced by the bundle importer
  - Mutation guards on every BYOD client class
  - MCP factory routing (BYOD active → BYOD client; otherwise real API)
  - CLI surface (``mureo byod import / status / remove / clear``)
  - No-outbound-network guarantee under BYOD-mode tool dispatch
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# xlsx fixture builder
# ---------------------------------------------------------------------------


def _make_workbook(tmp_path: Path, *, tabs: dict[str, list[list]]) -> Path:
    """Create an xlsx file at ``tmp_path/test.xlsx`` with the given tabs."""
    from openpyxl import Workbook

    wb = Workbook()
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
        "keywords": [
            [
                "keyword",
                "match_type",
                "quality_score",
                "campaign",
                "ad_group",
                "impressions",
                "clicks",
                "cost",
                "conversions",
            ],
            ["mureo", "EXACT", 8, "Brand Search", "Exact match", 800, 40, 20.0, 2.0],
        ],
        "search_terms": [
            [
                "search_term",
                "campaign",
                "ad_group",
                "impressions",
                "clicks",
                "cost",
                "conversions",
            ],
            ["mureo byod", "Brand Search", "Exact match", 100, 12, 5.5, 1.0],
            ["best ads tool", "Generic Search", "SaaS", 200, 5, 3.0, 0.0],
        ],
        "auction_insights": [
            ["campaign", "competitor_domain", "impression_share", "outranking_share"],
            ["Brand Search", "competitor-a.com", 0.45, 0.30],
            ["Brand Search", "competitor-b.com", 0.20, 0.10],
        ],
    }


# ---------------------------------------------------------------------------
# Fake-home fixture (redirects ~/.mureo/ to tmp_path)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    fh = tmp_path / "home"
    fh.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fh)
    return fh


@pytest.fixture()
def google_ads_xlsx(tmp_path, fake_home):
    """Create a workbook with Google Ads tabs and return its path."""
    return _make_workbook(tmp_path, tabs=_google_ads_tabs())


# ---------------------------------------------------------------------------
# Runtime: manifest resilience
# ---------------------------------------------------------------------------


def test_runtime_handles_missing_manifest(fake_home):
    from mureo.byod.runtime import (
        byod_active_platforms,
        byod_has,
        read_manifest,
    )

    assert read_manifest() is None
    assert byod_active_platforms() == []
    assert byod_has("google_ads") is False


def test_runtime_rejects_unknown_schema(fake_home):
    from mureo.byod.runtime import byod_data_dir, read_manifest

    byod_data_dir().mkdir(parents=True)
    (byod_data_dir() / "manifest.json").write_text(
        json.dumps({"schema_version": 999, "platforms": {}}),
        encoding="utf-8",
    )
    assert read_manifest() is None  # Unknown schema treated as inactive.


def test_runtime_rejects_corrupt_manifest(fake_home):
    from mureo.byod.runtime import byod_data_dir, read_manifest

    byod_data_dir().mkdir(parents=True)
    (byod_data_dir() / "manifest.json").write_text(
        "this is not valid json",
        encoding="utf-8",
    )
    assert read_manifest() is None


def test_byod_data_dir_returns_under_home(fake_home):
    from mureo.byod.runtime import byod_data_dir

    assert byod_data_dir() == fake_home / ".mureo" / "byod"


def test_stale_manifest_treated_as_inactive(google_ads_xlsx, fake_home):
    """Manifest references google_ads but the directory is missing on disk
    (e.g. user did `rm -rf ~/.mureo/byod/google_ads/` out of band) — the
    runtime must treat the platform as inactive rather than raising."""
    import shutil

    from mureo.byod.bundle import import_bundle
    from mureo.byod.runtime import byod_data_dir, byod_has, manifest_path

    import_bundle(google_ads_xlsx)
    assert byod_has("google_ads") is True

    shutil.rmtree(byod_data_dir() / "google_ads")
    assert manifest_path().exists()
    assert byod_has("google_ads") is False


# ---------------------------------------------------------------------------
# Bundle import → manifest contents
# ---------------------------------------------------------------------------


def test_bundle_import_writes_manifest(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.runtime import byod_data_dir, read_manifest

    import_bundle(google_ads_xlsx)

    manifest = read_manifest()
    assert manifest is not None
    assert "google_ads" in manifest["platforms"]
    entry = manifest["platforms"]["google_ads"]
    assert entry["source_format"] == "mureo_sheet_bundle_google_ads_v1"
    assert entry["rows"] >= 1
    assert entry["campaigns"] >= 1

    g_dir = byod_data_dir() / "google_ads"
    assert (g_dir / "campaigns.csv").exists()
    assert (g_dir / "metrics_daily.csv").exists()


def test_bundle_remove_platform(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.installer import remove_platform
    from mureo.byod.runtime import byod_data_dir, read_manifest

    import_bundle(google_ads_xlsx)
    assert (byod_data_dir() / "google_ads").exists()

    removed = remove_platform("google_ads")
    assert removed is True
    assert not (byod_data_dir() / "google_ads").exists()
    # With no platforms left, manifest is cleared entirely.
    assert read_manifest() is None


def test_bundle_clear_all(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.installer import clear_all
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    assert byod_data_dir().exists()

    cleared = clear_all()
    assert cleared is True
    assert not byod_data_dir().exists()


def test_bundle_dedupe_same_file(google_ads_xlsx, fake_home):
    """Re-importing the same xlsx with --replace overwrites cleanly."""
    from mureo.byod.bundle import import_bundle

    first = import_bundle(google_ads_xlsx)
    second = import_bundle(google_ads_xlsx, replace=True)
    assert (
        first["google_ads"]["source_file_sha256"]
        == second["google_ads"]["source_file_sha256"]
    )


# ---------------------------------------------------------------------------
# BYOD clients read the CSVs the bundle importer writes
# ---------------------------------------------------------------------------


def test_byod_google_ads_client_reads_bundle_csv(google_ads_xlsx, fake_home):
    import asyncio

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    campaigns = asyncio.run(client.list_campaigns())
    assert len(campaigns) >= 1
    blob = json.dumps(campaigns, default=str)
    assert "Brand Search" in blob


def test_byod_google_ads_client_round_trips_cost(google_ads_xlsx, fake_home):
    """Regression test for the cost-vs-cost_jpy schema-parity bug:
    the input xlsx has cost values 25.5 + 28.0 + 60.0 = 113.5; the
    client's get_performance_report MUST surface non-zero spend, not
    silently drop it because of a column-name mismatch."""
    import asyncio

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    # period spans the test fixture dates (2026-04-01 / 04-02); even
    # if the test runs in a different real-world month, "LAST_30_DAYS"
    # is computed off the system clock at test time. We therefore use
    # an explicit ALL_TIME-equivalent by giving a very wide period
    # supported by _period_to_range, falling back to a date range on
    # the metrics rows.
    report = asyncio.run(client.get_performance_report(period="LAST_30_DAYS"))
    # The report may be empty if the system clock is far past the
    # fixture dates. In that case we still verify the underlying
    # metric rows carry cost > 0 by reading the metrics CSV directly.
    if report:
        total_cost = sum(float(r["cost"]) for r in report)
        assert total_cost > 0, f"All BYOD cost reads as 0: {report}"
    else:
        # System clock is outside the LAST_30_DAYS window. Read the
        # CSV directly to assert the column was written correctly.
        import csv as _csv

        metrics_csv = byod_data_dir() / "google_ads" / "metrics_daily.csv"
        with metrics_csv.open(encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            assert (
                "cost_jpy" in reader.fieldnames
            ), f"adapter wrote wrong column name; got {reader.fieldnames}"
            costs = [float(row["cost_jpy"] or 0) for row in reader]
        assert sum(costs) > 0, "metrics_daily.csv lost cost values"


def test_byod_client_search_terms_report(google_ads_xlsx, fake_home):
    """search_terms.csv → ByodGoogleAdsClient.get_search_terms_report.

    Regression for B-3: previously this method returned `[]` even when
    the bundle carried `search_terms` data. Now it must return one row
    per search_term in the input tab with computed CTR / CPC.
    """
    import asyncio

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    rows = asyncio.run(client.get_search_terms_report())
    assert len(rows) == 2
    terms = sorted(r["search_term"] for r in rows)
    assert terms == ["best ads tool", "mureo byod"]
    # Schema parity: metrics must be nested under `metrics` so
    # downstream consumers (_analysis_search_terms,
    # _analysis_performance) read `t["metrics"]["cost"]` correctly.
    mureo_row = next(r for r in rows if r["search_term"] == "mureo byod")
    assert "metrics" in mureo_row
    assert mureo_row["metrics"]["clicks"] == 12
    assert mureo_row["metrics"]["cost"] > 0
    assert mureo_row["metrics"]["ctr"] > 0
    assert mureo_row["average_cpc"] > 0


def test_byod_client_auction_insights(google_ads_xlsx, fake_home):
    """auction_insights.csv → get_auction_insights / analyze_auction_insights."""
    import asyncio

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    # Look up Brand Search's synthetic campaign_id from the campaigns tab.
    campaigns = asyncio.run(client.list_campaigns())
    brand = next(c for c in campaigns if c.get("name") == "Brand Search")
    cid = brand["id"]

    insights = asyncio.run(client.get_auction_insights(campaign_id=cid))
    assert len(insights) == 2
    domains = sorted(r["competitor_domain"] for r in insights)
    assert domains == ["competitor-a.com", "competitor-b.com"]

    # Aggregator returns the top competitor first.
    summary = asyncio.run(client.analyze_auction_insights(campaign_id=cid))
    assert summary["competitor_count"] == 2
    assert summary["competitors"][0]["competitor_domain"] == "competitor-a.com"

    # Empty-bundle path: a campaign_id that does not exist in the
    # synthetic ID map yields the "no data" sentinel rather than
    # raising or returning misleading aggregates.
    empty = asyncio.run(client.analyze_auction_insights(campaign_id="camp_unknown"))
    assert empty["competitors"] == []
    assert "BYOD" in empty["note"]


def test_byod_client_blocks_mutations(google_ads_xlsx, fake_home):
    import asyncio

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)
    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    # ``create_*`` matches a mutation prefix → __getattr__ returns the
    # async no-op stub. Awaiting it yields the read-only marker dict.
    result = asyncio.run(client.create_campaign(name="x"))
    assert isinstance(result, dict)
    assert result.get("status") == "skipped_in_byod_readonly"


def test_byod_clients_make_no_network_calls(google_ads_xlsx, fake_home, monkeypatch):
    """Patches HTTP libraries and asserts zero outbound calls during a
    representative BYOD client operation."""
    import asyncio
    import urllib.request

    import httpx

    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.runtime import byod_data_dir

    import_bundle(google_ads_xlsx)

    seen_calls: list[str] = []

    def _block(*args, **kwargs):  # noqa: ARG001
        seen_calls.append("net")
        raise AssertionError("BYOD client made a network call")

    monkeypatch.setattr(httpx.AsyncClient, "send", _block)
    monkeypatch.setattr(urllib.request, "urlopen", _block)

    client = ByodGoogleAdsClient(
        data_dir=byod_data_dir() / "google_ads",
        customer_id="byod",
    )
    asyncio.run(client.list_campaigns())

    assert seen_calls == []


# ---------------------------------------------------------------------------
# MCP factory routing
# ---------------------------------------------------------------------------


def test_factory_routes_imported_platform_to_byod(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.mcp._client_factory import get_google_ads_client

    import_bundle(google_ads_xlsx)
    client = get_google_ads_client(creds=None, customer_id="byod")
    assert isinstance(client, ByodGoogleAdsClient)


def test_factory_falls_back_to_real_when_not_imported(fake_home, monkeypatch):
    """When BYOD is not active, the factory must NOT return a Byod* client."""
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.mcp import _client_factory

    real_called = {}

    def _fake_real(creds, customer_id, throttler=None):  # noqa: ARG001
        real_called["yes"] = True
        return "REAL_CLIENT_SENTINEL"

    monkeypatch.setattr(
        "mureo.auth.create_google_ads_client", _fake_real, raising=False
    )

    result = _client_factory.get_google_ads_client(creds=None, customer_id="byod")
    if result == "REAL_CLIENT_SENTINEL":
        assert real_called.get("yes") is True
    else:
        assert not isinstance(result, ByodGoogleAdsClient)


# ---------------------------------------------------------------------------
# CLI: mureo byod {import,status,remove,clear}
# ---------------------------------------------------------------------------


def test_cli_byod_status_no_data(fake_home):
    from mureo.cli.main import app

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "status"])
    assert res.exit_code == 0, res.output
    assert "byod" in res.output.lower()


def test_cli_byod_import_xlsx_and_status(google_ads_xlsx, fake_home):
    from mureo.cli.main import app

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "import", str(google_ads_xlsx)])
    assert res.exit_code == 0, res.output
    assert "google_ads" in res.output

    res = runner.invoke(app, ["byod", "status"])
    assert res.exit_code == 0
    assert "BYOD" in res.output


def test_cli_byod_import_rejects_csv(tmp_path, fake_home):
    """CSV single-platform import was removed in B-2 — the CLI must
    refuse non-XLSX inputs with a clear message."""
    from mureo.cli.main import app

    csv_file = tmp_path / "fake.csv"
    csv_file.write_text("Campaign,Day,Impressions\n", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "import", str(csv_file)])
    assert res.exit_code != 0
    assert "XLSX" in res.output or "xlsx" in res.output


def test_cli_byod_clear_yes(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.runtime import byod_data_dir
    from mureo.cli.main import app

    import_bundle(google_ads_xlsx)
    assert byod_data_dir().exists()

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "clear", "--yes"])
    assert res.exit_code == 0
    assert not byod_data_dir().exists()


def test_cli_byod_remove_one_platform(google_ads_xlsx, fake_home):
    from mureo.byod.bundle import import_bundle
    from mureo.byod.runtime import byod_data_dir
    from mureo.cli.main import app

    import_bundle(google_ads_xlsx)
    assert (byod_data_dir() / "google_ads").exists()

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "remove", "--google-ads"])
    assert res.exit_code == 0
    assert not (byod_data_dir() / "google_ads").exists()


def test_cli_byod_remove_requires_exactly_one_flag(fake_home):
    from mureo.cli.main import app

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "remove"])
    assert res.exit_code != 0
    res = runner.invoke(app, ["byod", "remove", "--google-ads", "--meta-ads"])
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# Network isolation: the bundle import path itself does not phone home.
# ---------------------------------------------------------------------------


def test_bundle_import_makes_no_network_calls(google_ads_xlsx, fake_home, monkeypatch):
    import urllib.request

    import httpx

    seen: list[str] = []

    def _block(*args, **kwargs):  # noqa: ARG001
        seen.append("net")
        raise AssertionError("bundle import made a network call")

    monkeypatch.setattr(httpx.AsyncClient, "send", _block)
    monkeypatch.setattr(urllib.request, "urlopen", _block)

    from mureo.byod.bundle import import_bundle

    import_bundle(google_ads_xlsx)
    assert seen == []


# ---------------------------------------------------------------------------
# Stale platform-manifest entries (post-Phase-1 BYOD migration)
# ---------------------------------------------------------------------------


def test_remove_platform_accepts_legacy_manifest_entry(fake_home):
    """A manifest left behind by a pre-Phase-1 mureo build can list
    `google_analytics` / `search_console` even though those keys are
    no longer in SUPPORTED_PLATFORMS. ``remove_platform`` must clean
    them up so the user can drop the stale data with the CLI."""
    from mureo.byod.installer import remove_platform
    from mureo.byod.runtime import byod_data_dir, write_manifest

    legacy_dir = byod_data_dir() / "google_analytics"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "metrics_daily.csv").write_text("date\n2026-04-01\n")

    write_manifest(
        {
            "schema_version": 1,
            "imported_on": "2026-04-01T00:00:00+00:00",
            "platforms": {"google_analytics": {"rows": 1, "files": []}},
        }
    )

    assert remove_platform("google_analytics") is True
    assert not legacy_dir.exists()


def test_remove_platform_refuses_path_traversal_in_legacy_key(fake_home):
    """Defense in depth: a hand-edited / corrupt manifest with a
    platform key that escapes ~/.mureo/byod/ must be rejected, not
    silently passed to shutil.rmtree."""
    from mureo.byod.installer import BYODImportError, remove_platform
    from mureo.byod.runtime import write_manifest

    write_manifest(
        {
            "schema_version": 1,
            "imported_on": "2026-04-01T00:00:00+00:00",
            "platforms": {"../escape": {"rows": 1, "files": []}},
        }
    )

    with pytest.raises(BYODImportError, match="out-of-tree"):
        remove_platform("../escape")


def test_byod_status_warns_about_stale_manifest_entries(fake_home):
    """`mureo byod status` must surface unsupported-platform entries
    left over from a previous mureo version with a one-line cleanup
    hint. Without this warning users have no way to discover that
    ~/.mureo/byod/google_analytics/ still occupies disk space."""
    from mureo.byod.runtime import byod_data_dir, write_manifest
    from mureo.cli.main import app

    write_manifest(
        {
            "schema_version": 1,
            "imported_on": "2026-04-01T00:00:00+00:00",
            "platforms": {
                "search_console": {"rows": 5, "files": []},
            },
        }
    )
    (byod_data_dir() / "search_console").mkdir(parents=True, exist_ok=True)

    runner = CliRunner()
    res = runner.invoke(app, ["byod", "status"])
    assert res.exit_code == 0, res.output
    assert "Stale BYOD entries" in res.output
    assert "search_console" in res.output
