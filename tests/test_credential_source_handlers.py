"""Built-in handlers honour an active credential source (#821).

With a :class:`~mureo.mcp.credential_source.CredentialSource` in effect, the
Google Ads, Search Console and Meta Ads paths that resolve credentials during
a tool call take them from the source — never from the credentials file, and
ahead of BYOD mode — while the id resolution and allow-list enforcement stay
exactly as they are. Without a source nothing changes; the rest of the suite
pins that.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
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
    developer_token="dtoken",
    login_customer_id="9998887777",
    customer_id="1112223333",
)
_META = MetaAdsCredentials(access_token="source-token", account_id="act_555")


class _GoogleSource:
    def __init__(self, creds: GoogleAdsCredentials | None) -> None:
        self.creds = creds
        self.oauth = object()
        self.seen: list[GoogleAdsCredentials] = []

    def load_credentials(self) -> GoogleAdsCredentials | None:
        return self.creds

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        self.seen.append(credentials)
        return self.oauth


class _MetaSource:
    def __init__(self, creds: MetaAdsCredentials | None) -> None:
        self.creds = creds

    def load_credentials(self) -> MetaAdsCredentials | None:
        return self.creds


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the credentials file must not be read")


@pytest.fixture(autouse=True)
def _unscoped() -> Iterator[None]:
    """Pin every test to the untenanted resolution unless it patches its own."""
    with (
        patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_google_ads_analysis.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=None,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Google Ads _get_client
# ---------------------------------------------------------------------------


class TestGoogleAdsGetClient:
    async def _get(
        self, source: _GoogleSource, args: dict[str, Any], *, byod: bool = False
    ) -> tuple[Any, MagicMock]:
        from mureo.mcp import _handlers_google_ads as handlers

        with (
            patch.object(handlers, "byod_has", return_value=byod),
            patch.object(handlers, "load_google_ads_credentials", _refuse),
            patch.object(handlers, "get_google_ads_client", _refuse),
            patch.object(handlers, "create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            client = await handlers._get_client(args)
        return client, factory

    async def test_source_credentials_and_oauth_reach_the_factory(self) -> None:
        source = _GoogleSource(_GOOGLE)
        client, factory = await self._get(source, {"customer_id": "123-456-7890"})
        assert client is factory.return_value
        factory.assert_called_once()
        assert factory.call_args.args == (_GOOGLE, "123-456-7890")
        assert factory.call_args.kwargs["oauth_credentials"] is source.oauth
        assert factory.call_args.kwargs["throttler"] is not None
        assert source.seen == [_GOOGLE]

    async def test_customer_id_defaults_from_source_credentials(self) -> None:
        _, factory = await self._get(_GoogleSource(_GOOGLE), {})
        assert factory.call_args.args[1] == "1112223333"

    async def test_login_customer_id_is_the_last_fallback(self) -> None:
        creds = GoogleAdsCredentials(
            client_id="p", client_secret="p", refresh_token="p", login_customer_id="77"
        )
        _, factory = await self._get(_GoogleSource(creds), {})
        assert factory.call_args.args[1] == "77"

    async def test_allow_list_still_refuses(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        with (
            patch.object(
                handlers,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"1112223333"}),
            ),
            pytest.raises(ValueError, match="refused"),
        ):
            await self._get(_GoogleSource(_GOOGLE), {"customer_id": "222"})

    async def test_format_check_still_applies(self) -> None:
        with pytest.raises(ValueError, match="Invalid customer_id format"):
            await self._get(_GoogleSource(_GOOGLE), {"customer_id": "abc"})

    async def test_source_without_credentials_returns_none(self) -> None:
        client, factory = await self._get(_GoogleSource(None), {"customer_id": "1"})
        assert client is None
        factory.assert_not_called()

    async def test_source_wins_over_byod(self) -> None:
        source = _GoogleSource(_GOOGLE)
        _, factory = await self._get(source, {"customer_id": "1"}, byod=True)
        factory.assert_called_once()
        assert factory.call_args.kwargs["oauth_credentials"] is source.oauth

    async def test_handler_reports_missing_credentials(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_google_ads_credentials", _refuse),
            use_credential_source(CredentialSource(google=_GoogleSource(None))),
        ):
            result = await handlers.handle_campaigns_list({"customer_id": "1"})
        assert result == handlers._no_google_creds()

    async def test_meta_only_source_leaves_google_on_the_file(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        loader = MagicMock(return_value=None)
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_google_ads_credentials", loader),
            use_credential_source(CredentialSource(meta_ads=_MetaSource(_META))),
        ):
            assert await handlers._get_client({"customer_id": "1"}) is None
        loader.assert_called_once_with()


# ---------------------------------------------------------------------------
# google_ads_accounts_list
# ---------------------------------------------------------------------------


class TestAccountsList:
    async def test_discovery_passes_source_oauth_through(self) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as mod

        source = _GoogleSource(_GOOGLE)
        rows = [{"id": "1112223333"}, {"id": "9990001111"}]
        lister = AsyncMock(return_value=rows)
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.auth.load_google_ads_credentials", _refuse),
            patch("mureo.google_ads.list_accessible_accounts", new=lister),
            patch.object(
                mod,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"111-222-3333"}),
            ),
            use_credential_source(CredentialSource(google=source)),
        ):
            result = await mod.handle_accounts_list({})
        lister.assert_awaited_once_with(_GOOGLE, oauth_credentials=source.oauth)
        assert [row["id"] for row in json.loads(result[0].text)] == ["1112223333"]

    async def test_discovery_without_source_credentials(self) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as mod

        lister = AsyncMock()
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.google_ads.list_accessible_accounts", new=lister),
            use_credential_source(CredentialSource(google=_GoogleSource(None))),
        ):
            result = await mod.handle_accounts_list({})
        lister.assert_not_awaited()
        assert result == mod._no_google_creds()

    async def test_byod_manifest_does_not_skip_the_allow_list(self) -> None:
        """With a source active the customer-scoped branch is a live client,
        so its roster is filtered even when a BYOD manifest is present."""
        from mureo.mcp import _handlers_google_ads_analysis as mod

        client = MagicMock()
        client.list_accounts = AsyncMock(
            return_value=[
                {"customer_id": "customers/1112223333"},
                {"customer_id": "customers/9990001111"},
            ]
        )
        with (
            patch("mureo.byod.runtime.byod_has", return_value=True),
            patch.object(mod, "_get_client", AsyncMock(return_value=client)),
            patch.object(
                mod,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"1112223333"}),
            ),
            use_credential_source(CredentialSource(google=_GoogleSource(_GOOGLE))),
        ):
            result = await mod.handle_accounts_list({"customer_id": "1112223333"})
        rows = json.loads(result[0].text)
        assert rows == [{"customer_id": "customers/1112223333"}]


# ---------------------------------------------------------------------------
# Search Console _get_client
# ---------------------------------------------------------------------------


class TestSearchConsoleGetClient:
    async def test_source_oauth_reaches_the_factory(self) -> None:
        from mureo.mcp import _handlers_search_console as handlers

        source = _GoogleSource(_GOOGLE)
        with (
            patch.object(handlers, "load_google_ads_credentials", _refuse),
            patch.object(handlers, "create_search_console_client") as factory,
            patch.object(handlers, "register_client_for_cleanup") as cleanup,
            use_credential_source(CredentialSource(google=source)),
        ):
            client = await handlers._get_client({})
        assert client is factory.return_value
        assert factory.call_args.args == (_GOOGLE,)
        assert factory.call_args.kwargs["oauth_credentials"] is source.oauth
        assert factory.call_args.kwargs["throttler"] is handlers._throttler
        cleanup.assert_called_once_with(client)

    async def test_source_without_credentials_reports_missing(self) -> None:
        from mureo.mcp import _handlers_search_console as handlers

        with (
            patch.object(handlers, "load_google_ads_credentials", _refuse),
            patch.object(handlers, "create_search_console_client") as factory,
            use_credential_source(CredentialSource(google=_GoogleSource(None))),
        ):
            assert await handlers._get_client({}) is None
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# Meta Ads _get_client
# ---------------------------------------------------------------------------


class TestMetaGetClient:
    async def _get(
        self, source: _MetaSource, args: dict[str, Any], *, byod: bool = False
    ) -> tuple[Any, MagicMock, AsyncMock]:
        from mureo.mcp import _handlers_meta_ads as handlers

        refresh = AsyncMock(side_effect=AssertionError("refresh must not run"))
        with (
            patch.object(handlers, "byod_has", return_value=byod),
            patch.object(handlers, "load_meta_ads_credentials", _refuse),
            patch.object(handlers, "get_meta_ads_client", _refuse),
            patch.object(handlers, "refresh_meta_token_if_needed", refresh),
            patch.object(handlers, "register_client_for_cleanup"),
            patch.object(handlers, "create_meta_ads_client") as factory,
            use_credential_source(CredentialSource(meta_ads=source)),
        ):
            client = await handlers._get_client(args)
        return client, factory, refresh

    async def test_source_credentials_reach_the_factory_unrefreshed(self) -> None:
        from mureo.mcp import _handlers_meta_ads as handlers

        client, factory, refresh = await self._get(
            _MetaSource(_META), {"account_id": "act_123"}
        )
        assert client is factory.return_value
        factory.assert_called_once_with(_META, "act_123", throttler=handlers._throttler)
        refresh.assert_not_awaited()

    async def test_account_id_defaults_from_source_credentials(self) -> None:
        _, factory, _ = await self._get(_MetaSource(_META), {})
        assert factory.call_args.args[1] == "act_555"

    async def test_act_prefix_check_still_applies(self) -> None:
        with pytest.raises(ValueError, match="must start with 'act_'"):
            await self._get(_MetaSource(_META), {"account_id": "123"})

    async def test_source_without_credentials_returns_none(self) -> None:
        client, factory, _ = await self._get(_MetaSource(None), {})
        assert client is None
        factory.assert_not_called()

    async def test_source_wins_over_byod(self) -> None:
        _, factory, _ = await self._get(_MetaSource(_META), {}, byod=True)
        factory.assert_called_once()
        assert factory.call_args.args[0] is _META

    def test_live_result_is_not_labelled_as_byod_snapshot(self) -> None:
        """When the source wins over a BYOD manifest the response is live, so
        it must not carry the BYOD import marker."""
        from mureo.mcp import _handlers_meta_ads as handlers

        rows = [{"id": "1"}]
        with (
            patch.object(handlers, "byod_has", return_value=True),
            patch.object(
                handlers,
                "byod_freshness",
                return_value={"source": "byod_import", "as_of": "2026-01-01"},
            ),
            use_credential_source(CredentialSource(meta_ads=_MetaSource(_META))),
        ):
            result = handlers._entity_result(rows)
        assert json.loads(result[0].text) == rows

    def test_byod_snapshot_still_labelled_without_source(self) -> None:
        from mureo.mcp import _handlers_meta_ads as handlers

        marker = {"source": "byod_import", "as_of": "2026-01-01"}
        with (
            patch.object(handlers, "byod_has", return_value=True),
            patch.object(handlers, "byod_freshness", return_value=marker),
        ):
            result = handlers._entity_result([{"id": "1"}])
        assert json.loads(result[0].text) == {**marker, "data": [{"id": "1"}]}


# ---------------------------------------------------------------------------
# oauth_credentials() may block (a token refresh); it must run off the loop
# ---------------------------------------------------------------------------


class _ThreadRecordingSource(_GoogleSource):
    def __init__(self, creds: GoogleAdsCredentials | None) -> None:
        super().__init__(creds)
        self.oauth_threads: list[int] = []

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        self.oauth_threads.append(threading.get_ident())
        return super().oauth_credentials(credentials)


class TestOAuthCredentialsOffTheLoop:
    """The loop's thread is captured inside the test body itself, so the
    check holds however the test runner hosts the event loop."""

    async def test_google_ads_handler(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        loop_thread = threading.get_ident()
        source = _ThreadRecordingSource(_GOOGLE)
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=source)),
        ):
            await handlers._get_client({"customer_id": "1"})
        assert factory.call_args.kwargs["oauth_credentials"] is source.oauth
        assert len(source.oauth_threads) == 1
        assert source.oauth_threads[0] != loop_thread

    async def test_search_console_handler(self) -> None:
        from mureo.mcp import _handlers_search_console as handlers

        loop_thread = threading.get_ident()
        source = _ThreadRecordingSource(_GOOGLE)
        with (
            patch.object(handlers, "create_search_console_client") as factory,
            patch.object(handlers, "register_client_for_cleanup"),
            use_credential_source(CredentialSource(google=source)),
        ):
            await handlers._get_client({})
        assert factory.call_args.kwargs["oauth_credentials"] is source.oauth
        assert len(source.oauth_threads) == 1
        assert source.oauth_threads[0] != loop_thread

    async def test_accounts_list_discovery(self) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as mod

        loop_thread = threading.get_ident()
        source = _ThreadRecordingSource(_GOOGLE)
        lister = AsyncMock(return_value=[])
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.google_ads.list_accessible_accounts", new=lister),
            use_credential_source(CredentialSource(google=source)),
        ):
            await mod.handle_accounts_list({})
        lister.assert_awaited_once_with(_GOOGLE, oauth_credentials=source.oauth)
        assert len(source.oauth_threads) == 1
        assert source.oauth_threads[0] != loop_thread
