"""Hardening of the credential source hook (#824).

- ``CredentialSource(strict=True)`` fails closed for a platform it leaves at
  ``None`` instead of letting the handler read the host's own credentials.
- A nested ``use_credential_source`` replaces the outer source; merging is
  explicit (``merged_with``).
- An exception raised by a source reaches the MCP client only as a curated
  ``CredentialSourceError`` naming the platform and the exception class.
- The tracking pre-flight snapshot cache is keyed by the active source too.
- Without a source the Google Ads factory is not passed ``oauth_credentials``.
"""

from __future__ import annotations

import gc
import json
import logging
import weakref
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials
from mureo.core.auth_failure import AUTH_ERROR_STATUS, PlatformAuthError
from mureo.mcp.credential_source import (
    CredentialSource,
    CredentialSourceError,
    active_source_identity,
    call_source,
    current_credential_source,
    current_google_source,
    current_meta_source,
    use_credential_source,
)

pytestmark = pytest.mark.unit

_SECRET = "ya29.secret-looking-token-value"

_GOOGLE = GoogleAdsCredentials(
    client_id="placeholder",
    client_secret="placeholder",
    refresh_token="placeholder",
    developer_token="dtoken",
    customer_id="1112223333",
)
_META = MetaAdsCredentials(access_token="source-token", account_id="act_555")


class _GoogleSource:
    def __init__(
        self,
        creds: GoogleAdsCredentials | None = _GOOGLE,
        *,
        load_error: Exception | None = None,
        oauth_error: Exception | None = None,
    ) -> None:
        self.creds = creds
        self.load_error = load_error
        self.oauth_error = oauth_error
        self.oauth = object()

    def load_credentials(self) -> GoogleAdsCredentials | None:
        if self.load_error is not None:
            raise self.load_error
        return self.creds

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        if self.oauth_error is not None:
            raise self.oauth_error
        return self.oauth


class _MetaSource:
    def __init__(
        self,
        creds: MetaAdsCredentials | None = _META,
        *,
        load_error: Exception | None = None,
    ) -> None:
        self.creds = creds
        self.load_error = load_error

    def load_credentials(self) -> MetaAdsCredentials | None:
        if self.load_error is not None:
            raise self.load_error
        return self.creds


def _refuse(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("the host's own credentials must not be read")


def _text(result: list[Any]) -> str:
    return "".join(getattr(item, "text", "") for item in result)


@pytest.fixture(autouse=True)
def _unscoped_live() -> Iterator[None]:
    """Untenanted, non-BYOD resolution on every platform; no host credentials."""
    with (
        patch(
            "mureo.mcp._google_ads_client.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_google_ads_analysis.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids", return_value=None
        ),
        patch(
            "mureo.mcp._handlers_search_console.runtime_search_console_sites",
            return_value=None,
        ),
        patch("mureo.mcp._google_ads_client.byod_has", return_value=False),
        patch("mureo.mcp._handlers_meta_ads.byod_has", return_value=False),
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.mcp._google_ads_client.load_google_ads_credentials", _refuse),
        patch(
            "mureo.mcp._handlers_search_console.load_google_ads_credentials", _refuse
        ),
        patch("mureo.mcp._handlers_meta_ads.load_meta_ads_credentials", _refuse),
        patch("mureo.auth.load_google_ads_credentials", _refuse),
    ):
        yield


# ---------------------------------------------------------------------------
# strict
# ---------------------------------------------------------------------------


class TestStrictField:
    def test_defaults_to_false(self) -> None:
        assert CredentialSource().strict is False

    def test_is_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            CredentialSource(None, None, True)  # type: ignore[misc]

    def test_non_bool_is_refused_before_anything_is_set(self) -> None:
        with (
            pytest.raises(TypeError, match="strict"),
            use_credential_source(CredentialSource(strict="yes")),  # type: ignore[arg-type]
        ):
            pass
        assert current_credential_source() is None


class TestStrictAccessors:
    def test_google_missing_fails_closed(self) -> None:
        source = CredentialSource(meta_ads=_MetaSource(), strict=True)
        with (
            use_credential_source(source),
            pytest.raises(CredentialSourceError, match="google"),
        ):
            current_google_source()

    def test_meta_missing_fails_closed(self) -> None:
        source = CredentialSource(google=_GoogleSource(), strict=True)
        with (
            use_credential_source(source),
            pytest.raises(CredentialSourceError, match="meta_ads"),
        ):
            current_meta_source()

    def test_covered_platform_is_returned(self) -> None:
        google = _GoogleSource()
        with use_credential_source(CredentialSource(google=google, strict=True)):
            assert current_google_source() is google

    def test_non_strict_missing_platform_is_none(self) -> None:
        with use_credential_source(CredentialSource(google=_GoogleSource())):
            assert current_meta_source() is None

    def test_no_active_source_is_none_either_way(self) -> None:
        assert current_google_source() is None
        assert current_meta_source() is None


class TestStrictHandlers:
    async def test_google_ads_handler_fails_closed(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        factory = MagicMock()
        with (
            patch("mureo.mcp._google_ads_client.byod_has", return_value=True),
            patch("mureo.mcp._google_ads_client.create_google_ads_client", factory),
            patch("mureo.mcp._google_ads_client.get_google_ads_client", _refuse),
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(), strict=True)
            ),
        ):
            result = await handlers.handle_campaigns_list({"customer_id": "1"})
        text = _text(result)
        assert "google" in text
        assert "strict" in text
        factory.assert_not_called()

    async def test_search_console_handler_fails_closed(self) -> None:
        from mureo.mcp import _handlers_search_console as handlers

        with (
            patch.object(handlers, "create_search_console_client", _refuse),
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(), strict=True)
            ),
            pytest.raises(CredentialSourceError, match="google"),
        ):
            await handlers._get_client({})

    async def test_accounts_list_fails_closed(self) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as mod

        with (
            patch("mureo.google_ads.list_accessible_accounts", _refuse),
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(), strict=True)
            ),
        ):
            result = await mod.handle_accounts_list({})
        assert "google" in _text(result)

    async def test_meta_handler_fails_closed(self) -> None:
        from mureo.mcp import _handlers_meta_ads as handlers

        with (
            patch.object(handlers, "byod_has", return_value=True),
            patch.object(handlers, "get_meta_ads_client", _refuse),
            patch.object(handlers, "create_meta_ads_client", _refuse),
            use_credential_source(
                CredentialSource(google=_GoogleSource(), strict=True)
            ),
        ):
            result = await handlers.handle_campaigns_list({})
        text = _text(result)
        assert "meta_ads" in text
        assert "strict" in text

    async def test_strict_source_covering_the_platform_runs_normally(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        google = _GoogleSource()
        with (
            patch("mureo.mcp._google_ads_client.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=google, strict=True)),
        ):
            client = await handlers._get_client({"customer_id": "1"})
        assert client is factory.return_value
        assert factory.call_args.kwargs["oauth_credentials"] is google.oauth

    async def test_non_strict_missing_platform_keeps_host_resolution(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        loader = MagicMock(return_value=None)
        with (
            patch("mureo.mcp._google_ads_client.load_google_ads_credentials", loader),
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(), strict=False)
            ),
        ):
            assert await handlers._get_client({"customer_id": "1"}) is None
        loader.assert_called_once_with()

    def test_analytics_live_client_fails_closed(self) -> None:
        from mureo.analytics.builtin import _live_clients

        with (
            use_credential_source(
                CredentialSource(meta_ads=_MetaSource(), strict=True)
            ),
            pytest.raises(CredentialSourceError, match="google"),
        ):
            _live_clients._open_google_ads_client("1112223333")


# ---------------------------------------------------------------------------
# nesting
# ---------------------------------------------------------------------------


class TestNesting:
    def test_inner_source_replaces_the_outer_one(self) -> None:
        meta, google = _MetaSource(), _GoogleSource()
        outer = CredentialSource(meta_ads=meta)
        with use_credential_source(outer):
            with use_credential_source(CredentialSource(google=google)):
                assert current_google_source() is google
                assert current_meta_source() is None
            assert current_credential_source() is outer
            assert current_meta_source() is meta

    def test_merged_with_keeps_both_platforms(self) -> None:
        meta, google = _MetaSource(), _GoogleSource()
        outer = CredentialSource(meta_ads=meta)
        merged = outer.merged_with(CredentialSource(google=google))
        assert merged.google is google
        assert merged.meta_ads is meta
        assert merged.strict is False

    def test_merged_with_prefers_the_other_entries(self) -> None:
        first, second = _GoogleSource(), _GoogleSource()
        merged = CredentialSource(google=first).merged_with(
            CredentialSource(google=second)
        )
        assert merged.google is second

    def test_merged_with_stays_strict_if_either_is(self) -> None:
        merged = CredentialSource(strict=True).merged_with(CredentialSource())
        assert merged.strict is True
        merged = CredentialSource().merged_with(CredentialSource(strict=True))
        assert merged.strict is True

    def test_merged_with_refuses_other_types(self) -> None:
        with pytest.raises(TypeError, match="CredentialSource"):
            CredentialSource().merged_with(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# curated errors
# ---------------------------------------------------------------------------


class TestCallSource:
    def test_returns_the_result(self) -> None:
        assert call_source("google", lambda value: value * 2, 21) == 42

    def test_wraps_with_class_name_only(self, caplog: pytest.LogCaptureFixture) -> None:
        def boom() -> None:
            raise RuntimeError(f"refresh failed: {_SECRET}")

        with (
            caplog.at_level(logging.DEBUG),
            pytest.raises(CredentialSourceError) as info,
        ):
            call_source("google", boom)
        assert str(info.value) == "credential source failed for google (RuntimeError)"
        assert info.value.__cause__ is None
        assert info.value.__suppress_context__ is True
        assert _SECRET not in caplog.text
        assert "RuntimeError" in caplog.text

    def test_is_a_runtime_error(self) -> None:
        assert issubclass(CredentialSourceError, RuntimeError)


class TestCuratedErrorsReachTheClient:
    async def _google_ads(
        self, source: _GoogleSource, caplog: pytest.LogCaptureFixture
    ) -> str:
        from mureo.mcp import _handlers_google_ads as handlers

        with (
            caplog.at_level(logging.DEBUG),
            patch("mureo.mcp._google_ads_client.create_google_ads_client"),
            use_credential_source(CredentialSource(google=source)),
        ):
            result = await handlers.handle_campaigns_list({"customer_id": "1"})
        return _text(result)

    async def test_google_load_credentials(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        source = _GoogleSource(load_error=RuntimeError(f"bad token {_SECRET}"))
        text = await self._google_ads(source, caplog)
        assert "credential source failed for google (RuntimeError)" in text
        assert _SECRET not in text
        assert _SECRET not in caplog.text

    async def test_google_oauth_credentials(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A ValueError would otherwise be re-raised past api_error_handler
        # with its text intact.
        source = _GoogleSource(oauth_error=ValueError(f"refresh: {_SECRET}"))
        text = await self._google_ads(source, caplog)
        assert "credential source failed for google (ValueError)" in text
        assert _SECRET not in text
        assert _SECRET not in caplog.text

    async def test_source_auth_failure_stays_an_auth_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        source = _GoogleSource(load_error=PlatformAuthError(f"expired {_SECRET}"))
        text = await self._google_ads(source, caplog)
        payload = json.loads(text)
        assert payload["status"] == AUTH_ERROR_STATUS
        assert payload["detail"] == (
            "credential source failed for google (PlatformAuthError)"
        )
        assert _SECRET not in text

    async def test_search_console(self, caplog: pytest.LogCaptureFixture) -> None:
        from mureo.mcp import _handlers_search_console as handlers

        source = _GoogleSource(oauth_error=RuntimeError(f"refresh {_SECRET}"))
        with (
            caplog.at_level(logging.DEBUG),
            patch.object(handlers, "create_search_console_client", _refuse),
            use_credential_source(CredentialSource(google=source)),
        ):
            result = await handlers.handle_sites_list({})
        text = _text(result)
        assert "credential source failed for google (RuntimeError)" in text
        assert _SECRET not in text
        assert _SECRET not in caplog.text

    async def test_accounts_list_discovery(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from mureo.mcp import _handlers_google_ads_analysis as mod

        source = _GoogleSource(load_error=OSError(f"vault {_SECRET}"))
        with (
            caplog.at_level(logging.DEBUG),
            patch("mureo.google_ads.list_accessible_accounts", _refuse),
            use_credential_source(CredentialSource(google=source)),
        ):
            result = await mod.handle_accounts_list({})
        text = _text(result)
        assert "credential source failed for google (OSError)" in text
        assert _SECRET not in text

    async def test_meta_load_credentials(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from mureo.mcp import _handlers_meta_ads as handlers

        source = _MetaSource(load_error=KeyError(_SECRET))
        with (
            caplog.at_level(logging.DEBUG),
            patch.object(handlers, "create_meta_ads_client", _refuse),
            use_credential_source(CredentialSource(meta_ads=source)),
        ):
            result = await handlers.handle_campaigns_list({})
        text = _text(result)
        assert "credential source failed for meta_ads (KeyError)" in text
        assert _SECRET not in text
        assert _SECRET not in caplog.text

    def test_analytics_live_client(self) -> None:
        from mureo.analytics.builtin import _live_clients

        source = _GoogleSource(load_error=RuntimeError(_SECRET))
        with (
            use_credential_source(CredentialSource(google=source)),
            pytest.raises(CredentialSourceError) as info,
        ):
            _live_clients._open_google_ads_client("1112223333")
        assert _SECRET not in str(info.value)

    def test_change_feed(self) -> None:
        from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

        source = _GoogleSource(oauth_error=RuntimeError(_SECRET))
        with (
            patch("mureo.auth.create_google_ads_client", _refuse),
            use_credential_source(CredentialSource(google=source)),
            pytest.raises(CredentialSourceError) as info,
        ):
            GoogleAdsChangeFeed()._open_client("1112223333")
        assert _SECRET not in str(info.value)


# ---------------------------------------------------------------------------
# source identity and the pre-flight snapshot cache
# ---------------------------------------------------------------------------


class TestActiveSourceIdentity:
    def test_none_without_a_source(self) -> None:
        assert active_source_identity("google") is None

    def test_identity_of_the_entry(self) -> None:
        google = _GoogleSource()
        with use_credential_source(CredentialSource(google=google)):
            assert active_source_identity("google") == id(google)
            assert active_source_identity("meta_ads") is None

    def test_unknown_platform_is_refused(self) -> None:
        with pytest.raises(ValueError, match="platform"):
            active_source_identity("tiktok_ads")


class TestPreflightCacheKey:
    @pytest.fixture(autouse=True)
    def _fresh_cache(self) -> Iterator[None]:
        from mureo.mcp._tracking_preflight import reset_preflight_cache

        reset_preflight_cache()
        yield
        reset_preflight_cache()

    @staticmethod
    def _client(rows: list[dict[str, Any]]) -> MagicMock:
        client = MagicMock()
        client._customer_id = "1112223333"
        client.list_ads = AsyncMock(return_value=rows)
        return client

    async def test_two_sources_same_customer_get_their_own_snapshot(self) -> None:
        from mureo.mcp._tracking_preflight import _account_snapshot

        rows_a, rows_b = [{"ad_id": "a"}], [{"ad_id": "b"}]
        client_a, client_b = self._client(rows_a), self._client(rows_b)
        with use_credential_source(CredentialSource(google=_GoogleSource())):
            assert await _account_snapshot(client_a) == rows_a
        with use_credential_source(CredentialSource(google=_GoogleSource())):
            assert await _account_snapshot(client_b) == rows_b
        client_b.list_ads.assert_awaited_once()

    async def test_same_source_reuses_the_snapshot(self) -> None:
        from mureo.mcp._tracking_preflight import _account_snapshot

        rows = [{"ad_id": "a"}]
        first, second = self._client(rows), self._client([{"ad_id": "other"}])
        google = _GoogleSource()
        with use_credential_source(CredentialSource(google=google)):
            assert await _account_snapshot(first) == rows
            assert await _account_snapshot(second) == rows
        second.list_ads.assert_not_awaited()

    async def test_source_and_no_source_do_not_share(self) -> None:
        from mureo.mcp._tracking_preflight import _account_snapshot

        host_rows, source_rows = [{"ad_id": "host"}], [{"ad_id": "source"}]
        assert await _account_snapshot(self._client(host_rows)) == host_rows
        with use_credential_source(CredentialSource(google=_GoogleSource())):
            assert await _account_snapshot(self._client(source_rows)) == source_rows

    async def test_cached_entry_keeps_its_source_alive(self) -> None:
        """A freed source's ``id()`` could be handed to the next tenant's
        source; the cache entry holds the source so that cannot happen."""
        from mureo.mcp._tracking_preflight import _account_snapshot

        google = _GoogleSource()
        ref = weakref.ref(google)
        with use_credential_source(CredentialSource(google=google)):
            await _account_snapshot(self._client([{"ad_id": "a"}]))
        del google
        gc.collect()
        assert ref() is not None

    async def test_expired_entries_are_dropped_on_store(self) -> None:
        from mureo.mcp import _tracking_preflight as tp

        clock = [1000.0]
        with patch.object(tp.time, "monotonic", lambda: clock[0]):
            for _ in range(3):
                with use_credential_source(CredentialSource(google=_GoogleSource())):
                    await tp._account_snapshot(self._client([]))
            assert len(tp._snapshot_cache) == 3
            clock[0] += tp.SNAPSHOT_TTL_SECONDS
            await tp._account_snapshot(self._client([]))
        assert len(tp._snapshot_cache) == 1


# ---------------------------------------------------------------------------
# no-source path: oauth_credentials is not passed
# ---------------------------------------------------------------------------


class TestNoSourceFactoryCall:
    async def test_factory_without_the_keyword_still_works(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        built: list[tuple[Any, str]] = []

        def narrow_factory(creds: Any, customer_id: str, *, throttler: Any) -> str:
            built.append((creds, customer_id))
            return "client"

        with (
            patch(
                "mureo.mcp._google_ads_client.load_google_ads_credentials",
                return_value=_GOOGLE,
            ),
            patch(
                "mureo.mcp._google_ads_client.create_google_ads_client",
                narrow_factory,
            ),
        ):
            assert await handlers._get_client({"customer_id": "1"}) == "client"
        assert built == [(_GOOGLE, "1")]

    async def test_source_path_still_passes_the_keyword(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        google = _GoogleSource()
        with (
            patch("mureo.mcp._google_ads_client.create_google_ads_client") as factory,
            use_credential_source(CredentialSource(google=google)),
        ):
            await handlers._get_client({"customer_id": "1"})
        assert factory.call_args.kwargs["oauth_credentials"] is google.oauth
