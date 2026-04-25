"""Tests for the BYOD pipeline (adapter + installer + runtime + clients).

Covers AC-2/3/5/6/7/8/9 from `mureo-docs/mureo-byod-spec.md` v1.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a tmp directory."""

    def _fake_home() -> Path:
        return tmp_path

    monkeypatch.setattr(Path, "home", staticmethod(_fake_home))
    return tmp_path


@pytest.fixture
def google_ads_csv(tmp_path: Path) -> Path:
    """A minimal Google Ads Report Editor-style CSV."""
    csv_path = tmp_path / "gads-report.csv"
    csv_path.write_text(
        "Campaign,Ad group,Day,Impressions,Clicks,Cost,Conversions,"
        "Campaign state,Advertising channel type\n"
        "Brand Search,Brand - Exact,2026-04-20,4500,360,90000,28.0,ENABLED,SEARCH\n"
        "Brand Search,Brand - Exact,2026-04-21,4400,340,87000,26.0,ENABLED,SEARCH\n"
        "Brand Search,Brand - Phrase,2026-04-20,3000,210,52000,16.0,ENABLED,SEARCH\n"
        "Generic Search,Generic SaaS,2026-04-20,8200,250,45000,9.0,ENABLED,SEARCH\n"
        "Generic Search,Generic SaaS,2026-04-21,8000,240,43000,9.0,ENABLED,SEARCH\n"
    )
    return csv_path


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def test_adapter_detects_google_ads_header():
    from mureo.byod.adapters.google_ads import GoogleAdsAdapter

    assert GoogleAdsAdapter.detect(["Campaign", "Day", "Impressions", "Clicks", "Cost"])
    assert not GoogleAdsAdapter.detect(["foo", "bar"])
    assert GoogleAdsAdapter.detect(["campaign", "day", "impressions", "clicks", "cost"])


def test_adapter_normalizes(tmp_path, google_ads_csv):
    from mureo.byod.adapters.google_ads import GoogleAdsAdapter

    out = tmp_path / "out"
    result = GoogleAdsAdapter().normalize(google_ads_csv, out)

    assert result.rows == 5
    assert result.campaigns == 2
    # 3 distinct (campaign, ad_group) pairs in the fixture
    assert result.ad_groups == 3
    assert result.date_range == ("2026-04-20", "2026-04-21")
    assert "campaigns.csv" in result.files_written
    assert "ad_groups.csv" in result.files_written
    assert "metrics_daily.csv" in result.files_written

    rows = list(csv.DictReader((out / "campaigns.csv").open()))
    names = sorted(r["name"] for r in rows)
    assert names == ["Brand Search", "Generic Search"]

    metrics = list(csv.DictReader((out / "metrics_daily.csv").open()))
    assert {m["date"] for m in metrics} == {"2026-04-20", "2026-04-21"}


def test_adapter_rejects_pii(tmp_path):
    from mureo.byod.adapters.google_ads import (
        GoogleAdsAdapter,
        PIIDetectedError,
    )

    bad = tmp_path / "bad.csv"
    bad.write_text(
        "Campaign,Day,Impressions,Clicks,Cost,email\n"
        "Foo,2026-04-20,1,1,100,a@b.com\n"
    )
    with pytest.raises(PIIDetectedError):
        GoogleAdsAdapter().normalize(bad, tmp_path / "out")


def test_adapter_rejects_unknown_format(tmp_path):
    from mureo.byod.adapters.google_ads import (
        GoogleAdsAdapter,
        UnsupportedFormatError,
    )

    bad = tmp_path / "bad.csv"
    bad.write_text("Foo,Bar\n1,2\n")
    with pytest.raises(UnsupportedFormatError):
        GoogleAdsAdapter().normalize(bad, tmp_path / "out")


def test_adapter_handles_slash_dates(tmp_path):
    from mureo.byod.adapters.google_ads import GoogleAdsAdapter

    src = tmp_path / "slash.csv"
    src.write_text(
        "Campaign,Day,Impressions,Clicks,Cost\n" "Brand,2026/04/20,100,10,1000\n"
    )
    result = GoogleAdsAdapter().normalize(src, tmp_path / "out")
    assert result.date_range == ("2026-04-20", "2026-04-20")


# ---------------------------------------------------------------------------
# Installer + runtime (AC-5/8/9)
# ---------------------------------------------------------------------------


def test_import_writes_manifest(fake_home, google_ads_csv):
    from mureo.byod.installer import import_csv
    from mureo.byod.runtime import (
        byod_active_platforms,
        byod_has,
        manifest_path,
        read_manifest,
    )

    entry = import_csv(google_ads_csv)
    assert entry["rows"] == 5
    assert entry["source_format"] == "google_ads_report_editor_v1"

    assert byod_has("google_ads") is True
    assert byod_has("meta_ads") is False
    assert byod_active_platforms() == ["google_ads"]
    assert manifest_path().exists()

    manifest = read_manifest()
    assert manifest is not None
    assert manifest["schema_version"] == 1
    assert "google_ads" in manifest["platforms"]


def test_import_refuses_replace_without_flag(fake_home, google_ads_csv):
    from mureo.byod.installer import BYODImportError, import_csv

    import_csv(google_ads_csv)
    with pytest.raises(BYODImportError):
        import_csv(google_ads_csv)


def test_import_replace_flag_overwrites(fake_home, google_ads_csv):
    from mureo.byod.installer import import_csv

    import_csv(google_ads_csv)
    entry2 = import_csv(google_ads_csv, replace=True)
    assert entry2["rows"] == 5


def test_remove_platform_clears_manifest_when_empty(fake_home, google_ads_csv):
    """AC-5: removing the only imported platform clears the manifest."""
    from mureo.byod.installer import import_csv, remove_platform
    from mureo.byod.runtime import byod_has, manifest_path

    import_csv(google_ads_csv)
    assert byod_has("google_ads")
    assert remove_platform("google_ads") is True
    assert byod_has("google_ads") is False
    assert not manifest_path().exists()


def test_clear_all_removes_directory(fake_home, google_ads_csv):
    """AC-9: clear removes the whole directory."""
    from mureo.byod.installer import clear_all, import_csv
    from mureo.byod.runtime import byod_data_dir

    import_csv(google_ads_csv)
    assert byod_data_dir().exists()
    assert clear_all() is True
    assert not byod_data_dir().exists()
    assert clear_all() is False


def test_dedupe_same_source_file(fake_home, google_ads_csv):
    """AC-9 (dedupe): re-importing the same file is a fast no-op refresh."""
    from mureo.byod.installer import import_csv
    from mureo.byod.runtime import byod_platform_info

    import_csv(google_ads_csv)
    info1 = byod_platform_info("google_ads")

    info2 = import_csv(google_ads_csv, replace=True)
    assert info2["source_file_sha256"] == info1["source_file_sha256"]


def test_runtime_handles_missing_manifest(fake_home):
    from mureo.byod.runtime import byod_active_platforms, byod_has, read_manifest

    assert read_manifest() is None
    assert byod_has("google_ads") is False
    assert byod_active_platforms() == []


def test_runtime_rejects_unknown_schema(fake_home):
    """AC-8: unknown schema_version → BYOD inactive."""
    import json

    from mureo.byod.runtime import byod_data_dir, byod_has, manifest_path

    byod_data_dir().mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(
        json.dumps({"schema_version": 999, "platforms": {"google_ads": {}}})
    )
    assert byod_has("google_ads") is False


def test_runtime_rejects_corrupt_manifest(fake_home):
    from mureo.byod.runtime import byod_data_dir, byod_has, manifest_path

    byod_data_dir().mkdir(parents=True, exist_ok=True)
    manifest_path().write_text("{not valid json")
    assert byod_has("google_ads") is False


# ---------------------------------------------------------------------------
# Clients (AC-3 read-only / no-network)
# ---------------------------------------------------------------------------


def test_byod_google_ads_client_reads_csv(fake_home, google_ads_csv):
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.installer import import_csv
    from mureo.byod.runtime import byod_data_dir

    import_csv(google_ads_csv)
    client = ByodGoogleAdsClient(data_dir=byod_data_dir() / "google_ads")

    async def _check():
        rows = await client.list_campaigns()
        names = {r["name"] for r in rows}
        assert names == {"Brand Search", "Generic Search"}

    asyncio.run(_check())


def test_byod_client_blocks_mutations(fake_home, google_ads_csv):
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.installer import import_csv
    from mureo.byod.runtime import byod_data_dir

    import_csv(google_ads_csv)
    client = ByodGoogleAdsClient(data_dir=byod_data_dir() / "google_ads")

    async def _check():
        result = await client.create_campaign({"name": "Should not work"})
        assert result["status"] == "skipped_in_byod_readonly"

    asyncio.run(_check())


def test_byod_clients_make_no_network_calls(fake_home, google_ads_csv, monkeypatch):
    """AC-3: BYOD clients must not issue any HTTP requests."""
    from mureo.byod.installer import import_csv

    import_csv(google_ads_csv)

    captured: list[str] = []

    def _trip(*args, **kwargs):
        captured.append("network!")
        raise RuntimeError("Network call attempted in BYOD mode")

    try:
        import httpx  # type: ignore

        monkeypatch.setattr(httpx.AsyncClient, "send", _trip)
    except ImportError:
        pass

    from mureo.byod.clients import (
        ByodGoogleAdsClient,
        ByodMetaAdsClient,
        ByodSearchConsoleClient,
    )
    from mureo.byod.runtime import byod_data_dir

    g = ByodGoogleAdsClient(data_dir=byod_data_dir() / "google_ads")
    m = ByodMetaAdsClient(data_dir=byod_data_dir() / "meta_ads")
    s = ByodSearchConsoleClient(data_dir=byod_data_dir() / "search_console")

    async def _exercise() -> None:
        assert await g.list_campaigns()
        assert await g.get_performance_report(period="LAST_7_DAYS")
        assert await m.list_campaigns() == []
        assert await s.list_sites()

    asyncio.run(_exercise())
    assert captured == [], f"BYOD mode issued network calls: {captured}"


# ---------------------------------------------------------------------------
# Factory routing (AC-2)
# ---------------------------------------------------------------------------


def test_factory_routes_imported_platform_to_byod(fake_home, google_ads_csv):
    from mureo.byod.clients import ByodGoogleAdsClient
    from mureo.byod.installer import import_csv
    from mureo.mcp._client_factory import get_google_ads_client

    import_csv(google_ads_csv)
    client = get_google_ads_client(creds=None, customer_id="byod")
    assert isinstance(client, ByodGoogleAdsClient)


def test_factory_falls_back_to_real_when_not_imported(fake_home, monkeypatch):
    """For an un-imported platform, the factory should not produce a Byod client."""
    from mureo.byod.clients import ByodMetaAdsClient
    from mureo.mcp import _client_factory

    sentinel = object()

    def _fake_real(creds, account_id, throttler=None):
        return sentinel

    monkeypatch.setattr("mureo.auth.create_meta_ads_client", _fake_real, raising=False)

    client = _client_factory.get_meta_ads_client(creds=object(), account_id="act_123")
    assert client is sentinel
    assert not isinstance(client, ByodMetaAdsClient)
