"""Tests for ``mureo demo init`` and the demo-mode client factory.

Covers AC-2 (idempotency), AC-3 (no network), AC-8 (schema versioning),
and AC-9 (uninstall) from the spec at
``mureo-docs/mureo-demo-init-spec.md``.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
from datetime import date, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a tmp directory so demo install doesn't touch real ~."""

    def _fake_home() -> Path:
        return tmp_path

    monkeypatch.setattr(Path, "home", staticmethod(_fake_home))
    return tmp_path


def test_demo_init_creates_directory(fake_home):
    from mureo.demo.installer import demo_data_dir, demo_is_installed, install_demo

    assert not demo_is_installed()
    dst = install_demo()
    assert dst == demo_data_dir() == fake_home / ".mureo" / "demo"
    assert dst.exists()
    assert (dst / "STRATEGY.md").exists()
    assert (dst / "expected_output.md").exists()
    assert (dst / "version.json").exists()
    assert (dst / "google_ads" / "campaigns.csv").exists()
    assert (dst / "meta_ads" / "campaigns.csv").exists()
    assert (dst / "search_console" / "queries_daily.csv").exists()


def test_demo_init_resolves_day_offsets_to_today(fake_home):
    from mureo.demo.installer import install_demo

    today = date(2026, 6, 1)
    install_demo(today=today)

    metrics_csv = fake_home / ".mureo" / "demo" / "google_ads" / "metrics_daily.csv"
    rows = list(csv.DictReader(metrics_csv.open()))
    assert rows, "metrics_daily.csv has no data rows"

    expected_dates = {
        (today + timedelta(days=o)).strftime("%Y-%m-%d") for o in range(-13, 1)
    }
    actual_dates = {r["date"] for r in rows}
    assert actual_dates <= expected_dates
    assert today.strftime("%Y-%m-%d") in actual_dates


def test_demo_init_without_force_refuses_overwrite(fake_home):
    from mureo.demo.installer import install_demo

    install_demo()
    with pytest.raises(FileExistsError):
        install_demo()


def test_demo_init_force_replaces(fake_home):
    from mureo.demo.installer import install_demo

    dst = install_demo()
    sentinel = dst / "leftover.txt"
    sentinel.write_text("from a previous run")

    install_demo(force=True)
    assert not sentinel.exists()


def test_demo_init_idempotent_with_force(fake_home):
    """AC-2: Re-running demo init with --force on the same day produces identical CSVs."""
    from mureo.demo.installer import install_demo

    today = date(2026, 6, 1)

    install_demo(today=today)
    csv_path = fake_home / ".mureo" / "demo" / "google_ads" / "metrics_daily.csv"
    first_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    install_demo(force=True, today=today)
    second_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()

    assert first_hash == second_hash


def test_demo_uninstall_removes_dir(fake_home):
    """AC-9: Uninstall completely removes ~/.mureo/demo/."""
    from mureo.demo.installer import (
        demo_data_dir,
        demo_is_installed,
        install_demo,
        uninstall_demo,
    )

    install_demo()
    assert demo_is_installed()

    removed = uninstall_demo()
    assert removed is True
    assert not demo_is_installed()
    assert not demo_data_dir().exists()


def test_demo_uninstall_returns_false_when_not_installed(fake_home):
    from mureo.demo.installer import uninstall_demo

    assert uninstall_demo() is False


def test_demo_installed_schema_version(fake_home):
    """AC-8: version.json carries an integer schema_version."""
    from mureo.demo.installer import install_demo, installed_schema_version

    install_demo()
    assert installed_schema_version() == 1


def test_demo_clients_make_no_network_calls(fake_home, monkeypatch):
    """AC-3: Calling demo clients must not issue any HTTP requests."""
    from mureo.demo.installer import install_demo

    install_demo()

    captured: list[str] = []

    def _trip(*args, **kwargs):
        captured.append("network!")
        raise RuntimeError("Network call attempted in demo mode")

    try:
        import httpx  # type: ignore

        monkeypatch.setattr(httpx.AsyncClient, "send", _trip)
    except ImportError:
        pass

    from mureo.demo.clients import (
        DemoGoogleAdsClient,
        DemoMetaAdsClient,
        DemoSearchConsoleClient,
    )

    g = DemoGoogleAdsClient(
        data_dir=fake_home / ".mureo" / "demo" / "google_ads", customer_id="demo"
    )
    m = DemoMetaAdsClient(
        data_dir=fake_home / ".mureo" / "demo" / "meta_ads", account_id="act_demo"
    )
    s = DemoSearchConsoleClient(
        data_dir=fake_home / ".mureo" / "demo" / "search_console"
    )

    async def _exercise() -> None:
        assert await g.list_campaigns()
        assert await g.get_performance_report(period="LAST_7_DAYS")
        assert await m.list_campaigns()
        assert await s.list_sites()

    asyncio.run(_exercise())
    assert captured == [], f"Demo mode issued network calls: {captured}"


def test_demo_google_ads_brand_search_present(fake_home):
    """The embedded narrative requires a [DEMO] Brand Search campaign."""
    from mureo.demo.clients import DemoGoogleAdsClient
    from mureo.demo.installer import install_demo

    install_demo()
    client = DemoGoogleAdsClient(
        data_dir=fake_home / ".mureo" / "demo" / "google_ads", customer_id="demo"
    )

    async def _check():
        rows = await client.list_campaigns()
        names = {r["name"] for r in rows}
        assert "[DEMO] Brand Search" in names

    asyncio.run(_check())


def test_demo_search_console_brand_query_present(fake_home):
    from mureo.demo.clients import DemoSearchConsoleClient
    from mureo.demo.installer import install_demo

    install_demo()
    client = DemoSearchConsoleClient(
        data_dir=fake_home / ".mureo" / "demo" / "search_console"
    )

    async def _check():
        today = date.today()
        rows = await client.query_analytics(
            site_url="sc-domain:demo.example.com",
            start_date=(today - timedelta(days=14)).strftime("%Y-%m-%d"),
            end_date=today.strftime("%Y-%m-%d"),
            dimensions=["query"],
            row_limit=20,
        )
        keys_flat = {tuple(r["keys"]) for r in rows}
        assert any(
            k[0].startswith("[DEMO] mureo") for k in keys_flat
        ), f"Expected [DEMO] mureo brand query, got {keys_flat}"

    asyncio.run(_check())


def test_factory_demo_mode_default_off():
    from mureo.mcp._client_factory import is_demo_mode, set_demo_mode

    set_demo_mode(False)
    assert is_demo_mode() is False


def test_factory_demo_mode_routes_to_demo_clients(fake_home):
    from mureo.demo.clients import (
        DemoGoogleAdsClient,
        DemoMetaAdsClient,
        DemoSearchConsoleClient,
    )
    from mureo.demo.installer import install_demo
    from mureo.mcp._client_factory import (
        get_google_ads_client,
        get_meta_ads_client,
        get_search_console_client,
        set_demo_mode,
    )

    install_demo()
    set_demo_mode(True)
    try:
        assert isinstance(
            get_google_ads_client(creds=None, customer_id="demo"),
            DemoGoogleAdsClient,
        )
        assert isinstance(
            get_meta_ads_client(creds=None, account_id="act_demo"),
            DemoMetaAdsClient,
        )
        assert isinstance(
            get_search_console_client(creds=None), DemoSearchConsoleClient
        )
    finally:
        set_demo_mode(False)
