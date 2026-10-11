"""Non-handler paths that load credentials during a tool call (#821).

The analytics live clients (``mureo_analytics_run``, delivery-collapse) and
the Google Ads change feed (``external_changes_import``) open their own
clients instead of going through a handler's ``_get_client``. With a
credential source active they must take the credentials from it, ahead of
BYOD mode and the credentials file, exactly as the handlers do.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials
from mureo.mcp.credential_source import CredentialSource, use_credential_source

pytestmark = pytest.mark.unit

_GOOGLE = GoogleAdsCredentials(
    client_id="placeholder",
    client_secret="placeholder",
    refresh_token="placeholder",
    customer_id="1112223333",
)
_META = MetaAdsCredentials(access_token="source-token")


class _GoogleSource:
    def __init__(self, creds: GoogleAdsCredentials | None) -> None:
        self.creds = creds
        self.oauth = object()

    def load_credentials(self) -> GoogleAdsCredentials | None:
        return self.creds

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        return self.oauth


class _MetaSource:
    def __init__(self, creds: MetaAdsCredentials | None) -> None:
        self.creds = creds

    def load_credentials(self) -> MetaAdsCredentials | None:
        return self.creds


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("must not be called while a source is active")


@pytest.fixture(autouse=True)
def _live_unscoped(monkeypatch: pytest.MonkeyPatch) -> None:
    import mureo.mcp._handlers_google_ads as gh
    import mureo.mcp._handlers_meta_ads as mh

    monkeypatch.setattr(gh, "runtime_google_ads_customer_ids", lambda: None)
    monkeypatch.setattr(mh, "runtime_meta_account_ids", lambda: None)
    monkeypatch.setattr("mureo.byod.runtime.byod_has", lambda platform: True)
    monkeypatch.setattr("mureo.auth.load_google_ads_credentials", _refuse)
    monkeypatch.setattr("mureo.auth.load_meta_ads_credentials", _refuse)
    monkeypatch.setattr("mureo.mcp._client_factory.get_google_ads_client", _refuse)
    monkeypatch.setattr("mureo.mcp._client_factory.get_meta_ads_client", _refuse)


class TestAnalyticsGoogle:
    def test_source_wins_over_byod_and_file(self) -> None:
        from mureo.analytics.builtin._live_clients import _open_google_ads_client

        source = _GoogleSource(_GOOGLE)
        with (
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            client, account_id = _open_google_ads_client("123-456-7890")
        assert client is factory.return_value
        assert account_id == "123-456-7890"
        factory.assert_called_once_with(
            _GOOGLE, "123-456-7890", oauth_credentials=source.oauth
        )

    def test_source_without_credentials_raises_no_credentials(self) -> None:
        from mureo.analytics.builtin._live_clients import (
            NoCredentialsError,
            _open_google_ads_client,
        )

        with (
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=_GoogleSource(None))),
            pytest.raises(NoCredentialsError),
        ):
            _open_google_ads_client("1112223333")
        factory.assert_not_called()


class TestAnalyticsMeta:
    async def test_source_wins_and_skips_refresh(self) -> None:
        from mureo.analytics.builtin._live_clients import _open_meta_ads_client

        refresh = AsyncMock(side_effect=AssertionError("refresh must not run"))
        with (
            patch("mureo.auth.refresh_meta_token_if_needed", refresh),
            patch("mureo.auth.create_meta_ads_client") as factory,
            use_credential_source(CredentialSource(meta_ads=_MetaSource(_META))),
        ):
            client, account_id = await _open_meta_ads_client("123")
        assert client is factory.return_value
        assert account_id == "act_123"
        factory.assert_called_once_with(_META, "act_123")
        refresh.assert_not_awaited()

    async def test_source_without_credentials_raises_no_credentials(self) -> None:
        from mureo.analytics.builtin._live_clients import (
            NoCredentialsError,
            _open_meta_ads_client,
        )

        with (
            patch("mureo.auth.create_meta_ads_client") as factory,
            use_credential_source(CredentialSource(meta_ads=_MetaSource(None))),
            pytest.raises(NoCredentialsError),
        ):
            await _open_meta_ads_client("act_123")
        factory.assert_not_called()


class TestChangeFeedGoogle:
    def test_source_wins_over_byod_and_file(self) -> None:
        from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

        source = _GoogleSource(_GOOGLE)
        with (
            patch("mureo.auth.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            client = GoogleAdsChangeFeed()._open_client("1112223333")
        assert client is factory.return_value
        factory.assert_called_once_with(
            _GOOGLE, "1112223333", oauth_credentials=source.oauth
        )

    def test_source_without_credentials_raises(self) -> None:
        from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

        with (
            patch("mureo.auth.create_google_ads_client", MagicMock()),
            use_credential_source(CredentialSource(google=_GoogleSource(None))),
            pytest.raises(RuntimeError, match="not configured"),
        ):
            GoogleAdsChangeFeed()._open_client("1112223333")

    def test_allow_list_still_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import mureo.mcp._handlers_google_ads as gh
        from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

        monkeypatch.setattr(
            gh, "runtime_google_ads_customer_ids", lambda: frozenset({"1"})
        )
        with (
            use_credential_source(CredentialSource(google=_GoogleSource(_GOOGLE))),
            pytest.raises(ValueError, match="refused"),
        ):
            GoogleAdsChangeFeed()._open_client("222")
