"""The analytics live path refreshes the Meta token like the MCP path (#726).

``mureo/mcp/_handlers_meta_ads.py`` has always called
``refresh_meta_token_if_needed`` before building a client. The analytics
adapters' ``_open_meta_ads_client`` did not, so an install whose Meta traffic
is analytics-only (``mureo_analytics_run``, the report skills' anomaly and
diagnosis passes) never renewed a refresh-eligible credential — the token
aged out under a code path that was perfectly able to extend it.

The helper is a coroutine now: every one of its four callers already is, and
the refresh it has to await is.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mureo.analytics.builtin import _live_clients
from mureo.auth import MetaAdsCredentials

pytestmark = pytest.mark.unit


@pytest.fixture
def stub_meta(monkeypatch: pytest.MonkeyPatch):
    """Stub the client factory and the scope resolver; return the opened creds."""
    opened: dict[str, object] = {}

    def fake_client(creds=None, account_id=None):
        opened["creds"] = creds
        opened["account_id"] = account_id
        return object()

    monkeypatch.setattr("mureo.mcp._client_factory.get_meta_ads_client", fake_client)
    monkeypatch.setattr("mureo.byod.runtime.byod_has", lambda platform: False)

    import mureo.mcp._handlers_meta_ads as mh

    monkeypatch.setattr(mh, "runtime_meta_account_ids", lambda: None)
    return opened


_STORED = MetaAdsCredentials(
    access_token="old-token",
    app_id="app-123",
    app_secret="secret-456",
    token_obtained_at="2026-07-01T00:00:00+00:00",
    token_expires_at="2026-09-01T00:00:00+00:00",
)
_REFRESHED = MetaAdsCredentials(
    access_token="new-token",
    app_id="app-123",
    app_secret="secret-456",
    token_obtained_at="2026-08-29T00:00:00+00:00",
    token_expires_at="2026-10-28T00:00:00+00:00",
)


@pytest.mark.asyncio
async def test_opens_the_client_with_the_refreshed_credentials(stub_meta) -> None:
    refresh = AsyncMock(return_value=_REFRESHED)
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=_STORED),
        patch("mureo.auth.refresh_meta_token_if_needed", new=refresh),
    ):
        _client, resolved = await _live_clients._open_meta_ads_client("act_1")

    refresh.assert_awaited_once()
    assert refresh.await_args.args[0] is _STORED
    assert stub_meta["creds"] is _REFRESHED
    assert resolved == "act_1"


@pytest.mark.asyncio
async def test_byod_never_touches_the_refresh(monkeypatch) -> None:
    """BYOD carries no credentials to renew; calling the refresh there would
    be a pointless read of a credentials file that may not exist."""

    monkeypatch.setattr("mureo.byod.runtime.byod_has", lambda platform: True)
    monkeypatch.setattr(
        "mureo.mcp._client_factory.get_meta_ads_client",
        lambda creds=None, account_id=None: object(),
    )
    import mureo.mcp._handlers_meta_ads as mh

    monkeypatch.setattr(mh, "runtime_meta_account_ids", lambda: None)

    refresh = AsyncMock(return_value=_REFRESHED)
    with patch("mureo.auth.refresh_meta_token_if_needed", new=refresh):
        await _live_clients._open_meta_ads_client("act_1")

    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_credentials_still_raise_before_the_refresh(stub_meta) -> None:
    refresh = AsyncMock(return_value=None)
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
        patch("mureo.auth.refresh_meta_token_if_needed", new=refresh),
        pytest.raises(_live_clients.NoCredentialsError),
    ):
        await _live_clients._open_meta_ads_client("act_1")

    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_every_meta_fetcher_goes_through_the_helper() -> None:
    """The wiring is only worth anything if all four entry points use it —
    a fetcher that opened its own client would keep the old hole open."""

    import inspect

    source = inspect.getsource(_live_clients)
    assert source.count("await _open_meta_ads_client(") == 4


def test_the_delivery_fetcher_awaits_the_helper_too() -> None:
    """``_delivery_clients`` imports the same helper for the delivery-collapse
    series. It is a second module, so the count above cannot see it — and an
    un-awaited call there would unpack a coroutine, not a client."""

    import inspect

    from mureo.analytics.builtin import _delivery_clients

    source = inspect.getsource(_delivery_clients)
    assert "await _open_meta_ads_client(" in source
    assert source.count("_open_meta_ads_client(account_id)") == 1
