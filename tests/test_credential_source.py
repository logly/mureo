"""The per-call credential source and the factories it feeds (#821).

``mureo.mcp.credential_source`` lets a caller hand the built-in handlers the
credentials for one call. These tests pin the context-variable contract
(scope, reset, propagation into worker threads and child tasks) and the
``oauth_credentials`` pass-through of the three Google factories. The handler
wiring is covered in ``test_credential_source_handlers.py``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.auth import GoogleAdsCredentials
from mureo.mcp.credential_source import (
    CredentialSource,
    current_credential_source,
    current_google_source,
    current_meta_source,
    use_credential_source,
)

pytestmark = pytest.mark.unit

_CREDS = GoogleAdsCredentials(
    client_id="cid",
    client_secret="csecret",
    refresh_token="rtoken",
    developer_token="dtoken",
    login_customer_id="9998887777",
    customer_id="1112223333",
)


def _refuse_oauth_build(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("google.oauth2 Credentials must not be built")


class _LoadOnly:
    def load_credentials(self) -> Any:
        return None


class _FullGoogle(_LoadOnly):
    def oauth_credentials(self, credentials: Any) -> Any:
        return object()


# ---------------------------------------------------------------------------
# Per-platform helpers
# ---------------------------------------------------------------------------


class TestPlatformHelpers:
    def test_none_without_a_source(self) -> None:
        assert current_google_source() is None
        assert current_meta_source() is None

    def test_return_the_entries_of_the_active_source(self) -> None:
        google, meta = _FullGoogle(), _LoadOnly()
        with use_credential_source(CredentialSource(google=google, meta_ads=meta)):
            assert current_google_source() is google
            assert current_meta_source() is meta
        assert current_google_source() is None
        assert current_meta_source() is None

    def test_platform_left_unset_is_none(self) -> None:
        with use_credential_source(CredentialSource(meta_ads=_LoadOnly())):
            assert current_google_source() is None
        with use_credential_source(CredentialSource(google=_FullGoogle())):
            assert current_meta_source() is None


# ---------------------------------------------------------------------------
# Context variable contract
# ---------------------------------------------------------------------------


class TestUseCredentialSource:
    def test_default_is_none(self) -> None:
        assert current_credential_source() is None

    def test_sets_and_resets(self) -> None:
        source = CredentialSource()
        with use_credential_source(source):
            assert current_credential_source() is source
        assert current_credential_source() is None

    def test_resets_on_exception(self) -> None:
        source = CredentialSource()
        with (
            pytest.raises(RuntimeError, match="boom"),
            use_credential_source(source),
        ):
            raise RuntimeError("boom")
        assert current_credential_source() is None

    def test_nested_use_restores_outer_source(self) -> None:
        outer = CredentialSource()
        inner = CredentialSource()
        with use_credential_source(outer):
            with use_credential_source(inner):
                assert current_credential_source() is inner
            assert current_credential_source() is outer
        assert current_credential_source() is None

    def test_rejects_non_source(self) -> None:
        with (
            pytest.raises(TypeError, match="CredentialSource"),
            use_credential_source(object()),  # type: ignore[arg-type]
        ):
            pass
        assert current_credential_source() is None

    def test_rejects_google_without_oauth_credentials(self) -> None:
        source = CredentialSource(google=_LoadOnly())  # type: ignore[arg-type]
        with (
            pytest.raises(TypeError, match="google must have callable oauth"),
            use_credential_source(source),
        ):
            pass
        assert current_credential_source() is None

    def test_rejects_google_with_non_callable_method(self) -> None:
        google = _LoadOnly()
        google.oauth_credentials = "not callable"  # type: ignore[attr-defined]
        with (
            pytest.raises(TypeError, match="oauth_credentials"),
            use_credential_source(CredentialSource(google=google)),  # type: ignore[arg-type]
        ):
            pass
        assert current_credential_source() is None

    def test_rejects_meta_without_load_credentials(self) -> None:
        source = CredentialSource(meta_ads=object())  # type: ignore[arg-type]
        with (
            pytest.raises(TypeError, match="meta_ads must have callable load_cred"),
            use_credential_source(source),
        ):
            pass
        assert current_credential_source() is None

    def test_rejects_google_class_instead_of_instance(self) -> None:
        source = CredentialSource(google=_FullGoogle)  # type: ignore[arg-type]
        with (
            pytest.raises(TypeError, match="google must be an instance"),
            use_credential_source(source),
        ):
            pass
        assert current_credential_source() is None

    def test_rejects_meta_class_instead_of_instance(self) -> None:
        source = CredentialSource(meta_ads=_LoadOnly)  # type: ignore[arg-type]
        with (
            pytest.raises(TypeError, match="meta_ads must be an instance"),
            use_credential_source(source),
        ):
            pass
        assert current_credential_source() is None

    def test_accepts_well_formed_entries(self) -> None:
        source = CredentialSource(google=_FullGoogle(), meta_ads=_LoadOnly())
        with use_credential_source(source):
            assert current_credential_source() is source

    def test_source_is_frozen(self) -> None:
        source = CredentialSource()
        with pytest.raises(AttributeError):
            source.google = MagicMock()  # type: ignore[misc]

    async def test_visible_inside_to_thread(self) -> None:
        source = CredentialSource()
        with use_credential_source(source):
            seen = await asyncio.to_thread(current_credential_source)
        assert seen is source

    def test_not_visible_in_plain_thread(self) -> None:
        """Documented limit: a plain ``threading.Thread`` does not copy the
        context, so work started that way does not see the source."""
        seen: list[CredentialSource | None] = []
        with use_credential_source(CredentialSource()):
            thread = threading.Thread(
                target=lambda: seen.append(current_credential_source())
            )
            thread.start()
            thread.join()
        assert seen == [None]

    async def test_visible_in_child_task_created_inside(self) -> None:
        source = CredentialSource()

        async def probe() -> CredentialSource | None:
            return current_credential_source()

        with use_credential_source(source):
            task = asyncio.create_task(probe())
        assert await task is source

    async def test_not_visible_in_task_created_outside(self) -> None:
        source = CredentialSource()
        started = asyncio.Event()
        release = asyncio.Event()

        async def probe() -> CredentialSource | None:
            started.set()
            await release.wait()
            return current_credential_source()

        task = asyncio.create_task(probe())
        await started.wait()
        with use_credential_source(source):
            release.set()
            seen = await task
        assert seen is None


# ---------------------------------------------------------------------------
# Factories: oauth_credentials pass-through
# ---------------------------------------------------------------------------


class TestCreateGoogleAdsClient:
    def test_uses_injected_oauth_credentials(self) -> None:
        from mureo.auth import create_google_ads_client

        injected = object()
        throttler = MagicMock()
        with (
            patch("google.oauth2.credentials.Credentials", _refuse_oauth_build),
            patch("mureo.google_ads.GoogleAdsApiClient") as api_client,
        ):
            client = create_google_ads_client(
                _CREDS, "1112223333", throttler, oauth_credentials=injected
            )
        assert client is api_client.return_value
        api_client.assert_called_once_with(
            credentials=injected,
            customer_id="1112223333",
            developer_token="dtoken",
            login_customer_id="9998887777",
            throttler=throttler,
        )

    def test_without_injection_builds_oauth_credentials(self) -> None:
        from mureo.auth import create_google_ads_client

        with (
            patch("google.oauth2.credentials.Credentials") as oauth_cls,
            patch("mureo.google_ads.GoogleAdsApiClient") as api_client,
        ):
            create_google_ads_client(_CREDS, "1112223333")
        oauth_cls.assert_called_once_with(
            token=None,
            refresh_token="rtoken",
            client_id="cid",
            client_secret="csecret",
            token_uri="https://oauth2.googleapis.com/token",
        )
        assert api_client.call_args.kwargs["credentials"] is oauth_cls.return_value


class TestCreateSearchConsoleClient:
    def test_uses_injected_oauth_credentials(self) -> None:
        from mureo.auth import create_search_console_client

        injected = object()
        throttler = MagicMock()
        with (
            patch("google.oauth2.credentials.Credentials", _refuse_oauth_build),
            patch("mureo.search_console.SearchConsoleApiClient") as api_client,
        ):
            client = create_search_console_client(
                _CREDS, throttler, oauth_credentials=injected
            )
        assert client is api_client.return_value
        api_client.assert_called_once_with(credentials=injected, throttler=throttler)

    def test_without_injection_builds_scoped_oauth_credentials(self) -> None:
        from mureo.auth import create_search_console_client

        with (
            patch("google.oauth2.credentials.Credentials") as oauth_cls,
            patch("mureo.search_console.SearchConsoleApiClient") as api_client,
        ):
            create_search_console_client(_CREDS)
        assert oauth_cls.call_args.kwargs["scopes"] == [
            "https://www.googleapis.com/auth/webmasters"
        ]
        assert api_client.call_args.kwargs["credentials"] is oauth_cls.return_value


class TestListAccessibleAccounts:
    @staticmethod
    def _sdk_client() -> MagicMock:
        sdk = MagicMock()
        service = sdk.return_value.get_service.return_value
        service.list_accessible_customers.return_value = MagicMock(resource_names=[])
        return sdk

    async def test_uses_injected_oauth_credentials(self) -> None:
        from mureo.google_ads import list_accessible_accounts

        injected = object()
        sdk = self._sdk_client()
        with (
            patch("google.oauth2.credentials.Credentials", _refuse_oauth_build),
            patch("google.ads.googleads.client.GoogleAdsClient", sdk),
        ):
            accounts = await list_accessible_accounts(
                _CREDS, oauth_credentials=injected
            )
        assert accounts == []
        sdk.assert_called_once()
        kwargs = sdk.call_args.kwargs
        assert kwargs["credentials"] is injected
        assert kwargs["developer_token"] == "dtoken"
        assert kwargs["login_customer_id"] == "9998887777"

    async def test_without_injection_builds_oauth_credentials(self) -> None:
        from mureo.google_ads import list_accessible_accounts

        sdk = self._sdk_client()
        with (
            patch("google.oauth2.credentials.Credentials") as oauth_cls,
            patch("google.ads.googleads.client.GoogleAdsClient", sdk),
        ):
            await list_accessible_accounts(_CREDS)
        oauth_cls.assert_called_once()
        assert sdk.call_args.kwargs["credentials"] is oauth_cls.return_value
