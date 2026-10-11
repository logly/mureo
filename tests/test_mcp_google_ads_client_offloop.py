"""The Google Ads client is built off the event loop (#809).

``create_google_ads_client`` is synchronous and its first call imports the
Google Ads SDK, about a second of CPU. Every async path that builds one runs it
through ``asyncio.to_thread``, so the loop keeps serving other calls while it
happens. These tests replace the constructor with a stub that records the
thread it ran on, and pin that it is not the loop's thread and that a
concurrent coroutine keeps making progress while the stub is busy.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_CUSTOMER_ID = "1234567890"
_SLOW_BUILD_SECONDS = 0.2


def _analytics_fetchers() -> dict[str, Any]:
    from mureo.analytics.builtin import _delivery_clients, _live_clients

    return {
        "delivery_series": lambda: _delivery_clients.fetch_google_ads_delivery_series(
            _CUSTOMER_ID
        ),
        "list": lambda: _live_clients.fetch_google_ads_list(_CUSTOMER_ID),
        "metrics": lambda: _live_clients.fetch_google_ads_metrics(
            _CUSTOMER_ID, window_days=7
        ),
        "per_campaign_metrics": (
            lambda: _live_clients.fetch_google_ads_per_campaign_metrics(
                _CUSTOMER_ID, window_days=7
            )
        ),
        "performance_rows": lambda: _live_clients.fetch_google_ads_performance_rows(
            _CUSTOMER_ID, "LAST_7_DAYS"
        ),
    }


_ANALYTICS_FETCHERS = (
    "delivery_series",
    "list",
    "metrics",
    "per_campaign_metrics",
    "performance_rows",
)

_BYOD_METRICS_SCRIPT = """
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from mureo.analytics.builtin import _live_clients

client = MagicMock()
client.get_performance_report = AsyncMock(return_value=[])
with patch.object(
    _live_clients, "_open_google_ads_client", return_value=(client, "123")
):
    asyncio.run(_live_clients.fetch_google_ads_metrics("123", window_days=7))
    asyncio.run(
        _live_clients.fetch_google_ads_per_campaign_metrics("123", window_days=7)
    )
loaded = [m for m in sys.modules if m == "google.ads" or m.startswith("google.ads.")]
print(f"google.ads modules: {len(loaded)}")
"""


class _RecordingFactory:
    """Stand-in for ``create_google_ads_client`` that records its thread."""

    def __init__(self, client: Any, delay: float = 0.0) -> None:
        self._client = client
        self._delay = delay
        self.threads: list[threading.Thread] = []
        self.building = threading.Event()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.threads.append(threading.current_thread())
        self.building.set()
        try:
            if self._delay:
                time.sleep(self._delay)
        finally:
            self.building.clear()
        return self._client


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.list_campaigns = AsyncMock(return_value=[{"id": "1", "name": "c"}])
    client.get_campaign = AsyncMock(return_value={"id": "1", "status": "ENABLED"})
    return client


def _creds() -> MagicMock:
    return MagicMock(customer_id=_CUSTOMER_ID, login_customer_id=None)


@pytest.fixture
def live_google_ads():
    """Pin the handler module to the live (non-BYOD, unscoped) path."""
    from mureo.mcp import _handlers_google_ads as handlers

    with (
        patch.object(handlers, "byod_has", return_value=False),
        patch.object(handlers, "load_google_ads_credentials", return_value=_creds()),
        patch.object(handlers, "runtime_google_ads_customer_ids", return_value=None),
    ):
        yield handlers


async def _ticks_while_building(factory: _RecordingFactory, work: Any) -> int:
    """Run ``work`` and count loop ticks observed while the factory is busy."""
    ticks = 0
    done = False

    async def ticker() -> None:
        nonlocal ticks
        while not done:
            if factory.building.is_set():
                ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    try:
        await work
    finally:
        done = True
        await task
    return ticks


@pytest.mark.unit
class TestHandlerClientHelper:
    async def test_client_is_built_on_a_worker_thread(self, live_google_ads) -> None:
        client = _fake_client()
        factory = _RecordingFactory(client)
        loop_thread = threading.current_thread()
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            result = await live_google_ads._get_client({})
        assert result is client
        assert len(factory.threads) == 1
        assert factory.threads[0] is not loop_thread

    async def test_loop_stays_responsive_while_building(self, live_google_ads) -> None:
        factory = _RecordingFactory(_fake_client(), delay=_SLOW_BUILD_SECONDS)
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            ticks = await _ticks_while_building(
                factory, live_google_ads._get_client({})
            )
        assert ticks >= 10

    async def test_constructor_arguments_are_unchanged(self, live_google_ads) -> None:
        with patch.object(live_google_ads, "create_google_ads_client") as factory:
            await live_google_ads._get_client({"customer_id": "111-222-3333"})
        factory.assert_called_once()
        assert factory.call_args.args[1] == "111-222-3333"
        # Without a credential source (#821) oauth_credentials is the
        # factory's own default, so the client is built exactly as before.
        assert factory.call_args.kwargs == {
            "throttler": live_google_ads._throttler,
            "oauth_credentials": None,
        }

    async def test_missing_credentials_still_return_none(self, live_google_ads) -> None:
        with (
            patch.object(
                live_google_ads, "load_google_ads_credentials", return_value=None
            ),
            patch.object(live_google_ads, "create_google_ads_client") as factory,
        ):
            assert await live_google_ads._get_client({}) is None
        factory.assert_not_called()


@pytest.mark.unit
class TestHandlerEndToEnd:
    async def test_campaigns_list_awaits_the_client(self, live_google_ads) -> None:
        client = _fake_client()
        factory = _RecordingFactory(client)
        loop_thread = threading.current_thread()
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            result = await live_google_ads.handle_campaigns_list({})
        assert json.loads(result[0].text) == [{"id": "1", "name": "c"}]
        client.list_campaigns.assert_awaited_once()
        assert factory.threads[0] is not loop_thread

    async def test_extensions_handler_awaits_the_client(self, live_google_ads) -> None:
        from mureo.mcp import _handlers_google_ads_extensions as ext

        client = MagicMock()
        client.list_sitelinks = AsyncMock(return_value=[])
        factory = _RecordingFactory(client)
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            result = await ext.handle_sitelinks_list({"campaign_id": "1"})
        assert json.loads(result[0].text) == []
        client.list_sitelinks.assert_awaited_once()

    async def test_analysis_handler_awaits_the_client(self, live_google_ads) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as analysis

        client = MagicMock()
        client.get_network_performance_report = AsyncMock(return_value=[])
        factory = _RecordingFactory(client)
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            result = await analysis.handle_network_performance_report({})
        assert json.loads(result[0].text) == []
        client.get_network_performance_report.assert_awaited_once()


@pytest.mark.unit
class TestOtherAsyncCallers:
    async def test_exclusion_sources_client_is_awaited(self, live_google_ads) -> None:
        from mureo.mcp import exclusion_sources

        client = _fake_client()
        factory = _RecordingFactory(client)
        loop_thread = threading.current_thread()
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            result = await exclusion_sources.google_ads_client({})
        assert result is client
        assert factory.threads[0] is not loop_thread

    async def test_native_reversal_status_read_is_awaited(
        self, live_google_ads
    ) -> None:
        from mureo.mcp import native_reversal

        client = _fake_client()
        factory = _RecordingFactory(client)
        loop_thread = threading.current_thread()
        with patch.object(live_google_ads, "create_google_ads_client", factory):
            status = await native_reversal._read_status(
                ("google_ads", "campaigns", ()), {"campaign_id": "1"}
            )
        assert status == "ENABLED"
        assert factory.threads[0] is not loop_thread

    async def test_change_import_opens_client_off_loop(self) -> None:
        from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

        client = MagicMock()
        client.list_change_history = AsyncMock(return_value=[])
        factory = _RecordingFactory(client, delay=_SLOW_BUILD_SECONDS)
        loop_thread = threading.current_thread()
        feed = GoogleAdsChangeFeed()
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.auth.load_google_ads_credentials", return_value=_creds()),
            patch(
                "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
                return_value=None,
            ),
            patch("mureo.auth.create_google_ads_client", factory),
        ):
            now = datetime(2026, 10, 1, tzinfo=timezone.utc)
            ticks = await _ticks_while_building(
                factory, feed.fetch_change_events(_CUSTOMER_ID, since=now, until=now)
            )
        assert factory.threads[0] is not loop_thread
        assert ticks >= 10

    @pytest.mark.parametrize("fetcher", _ANALYTICS_FETCHERS)
    async def test_analytics_opens_client_off_loop(self, fetcher: str) -> None:
        client = MagicMock()
        client.list_ads = AsyncMock(return_value=[])
        client.get_performance_report = AsyncMock(return_value=[])
        client.get_daily_delivery_report = AsyncMock(return_value=[])
        factory = _RecordingFactory(client, delay=_SLOW_BUILD_SECONDS)
        loop_thread = threading.current_thread()
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.auth.load_google_ads_credentials", return_value=_creds()),
            patch(
                "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
                return_value=None,
            ),
            patch("mureo.auth.create_google_ads_client", factory),
        ):
            ticks = await _ticks_while_building(
                factory, _analytics_fetchers()[fetcher]()
            )
        assert factory.threads[0] is not loop_thread
        assert ticks >= 10

    def test_byod_metrics_import_no_sdk(self, tmp_path: Any) -> None:
        """With a client that needs no SDK (BYOD), the comparison-window
        helper must not pull the SDK in on the loop either: it is pure date
        arithmetic, so it lives in an SDK-free module. Run in a child
        interpreter because this process has the SDK loaded already."""
        result = subprocess.run(
            [sys.executable, "-c", _BYOD_METRICS_SCRIPT],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(tmp_path)},
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert result.stdout.strip().splitlines()[-1] == "google.ads modules: 0"


def _sdk_client(customer_id: str) -> MagicMock:
    """A fake ``GoogleAdsClient`` reaching one non-manager account."""
    response = MagicMock()
    response.resource_names = [f"customers/{customer_id}"]
    customer_service = MagicMock()
    customer_service.list_accessible_customers.return_value = response
    row = MagicMock()
    row.customer.descriptive_name = "Acct"
    row.customer.manager = False
    row.customer.status.name = "ENABLED"
    ga_service = MagicMock()
    ga_service.search.return_value = [row]
    client = MagicMock()
    client.get_service.side_effect = lambda name: (
        customer_service if name == "CustomerService" else ga_service
    )
    return client


_EXPECTED_ROSTER = [
    {
        "id": _CUSTOMER_ID,
        "name": "Acct",
        "is_manager": False,
        "parent_id": None,
        "level": 0,
        "status": "ENABLED",
    }
]


def _listing_creds() -> Any:
    from mureo.auth import GoogleAdsCredentials

    return GoogleAdsCredentials(
        client_id="cid", client_secret="csec", refresh_token="rtok"
    )


@pytest.mark.unit
class TestAccountListing:
    async def test_public_listing_runs_the_sdk_off_loop(self) -> None:
        from mureo.google_ads import list_accessible_accounts

        factory = _RecordingFactory(_sdk_client(_CUSTOMER_ID))
        loop_thread = threading.current_thread()
        with patch("google.ads.googleads.client.GoogleAdsClient", factory):
            accounts = await list_accessible_accounts(_listing_creds())
        assert accounts == _EXPECTED_ROSTER
        assert factory.threads
        assert all(thread is not loop_thread for thread in factory.threads)

    async def test_accounts_list_without_customer_id_keeps_loop_responsive(
        self,
    ) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as analysis

        factory = _RecordingFactory(
            _sdk_client(_CUSTOMER_ID), delay=_SLOW_BUILD_SECONDS
        )
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch(
                "mureo.auth.load_google_ads_credentials",
                return_value=_listing_creds(),
            ),
            patch.object(
                analysis, "runtime_google_ads_customer_ids", return_value=None
            ),
            patch("google.ads.googleads.client.GoogleAdsClient", factory),
        ):
            results: list[Any] = []

            async def call() -> None:
                results.append(await analysis.handle_accounts_list({}))

            ticks = await _ticks_while_building(factory, call())
        result = results[0]
        assert json.loads(result[0].text) == _EXPECTED_ROSTER
        assert ticks >= 10
