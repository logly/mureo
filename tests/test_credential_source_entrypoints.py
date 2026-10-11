"""The documented entry points honour an active credential source (#821).

``docs/plugin-authoring.md`` tells a plugin to wrap the public
``tools_google_ads`` / ``tools_search_console`` / ``tools_meta_ads``
``handle_tool`` call in ``use_credential_source(...)``. These tests drive
exactly that path, one tool per platform, with only the client factory (or
the Meta client constructor) replaced, and check that what reached it came
from the stub source and that no file-based loader ran.
"""

from __future__ import annotations

import json
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
    customer_id="1112223333",
)
_META = MetaAdsCredentials(access_token="source-token", account_id="act_555")


class _GoogleSource:
    def __init__(self) -> None:
        self.oauth = object()

    def load_credentials(self) -> GoogleAdsCredentials:
        return _GOOGLE

    def oauth_credentials(self, credentials: GoogleAdsCredentials) -> Any:
        assert credentials is _GOOGLE
        return self.oauth


class _MetaSource:
    def load_credentials(self) -> MetaAdsCredentials:
        return _META


def _refusing_loader() -> MagicMock:
    """A loader that fails loudly and records any call.

    ``api_error_handler`` turns an exception into an error result, so the
    tests also assert ``assert_not_called`` rather than relying on a raise.
    """
    return MagicMock(side_effect=AssertionError("file loader must not run"))


def _fake_client(method: str, rows: Any) -> MagicMock:
    client = MagicMock()
    setattr(client, method, AsyncMock(return_value=rows))
    client.close = AsyncMock()
    return client


class _Spy:
    """A stand-in factory that records its arguments and returns ``client``."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.client


@pytest.fixture(autouse=True)
def _unscoped() -> Iterator[None]:
    """Run untenanted, so the allow-lists do not filter the stub rows."""
    with (
        patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_search_console.runtime_search_console_sites",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=None,
        ),
    ):
        yield


async def test_google_ads_handle_tool_uses_the_source() -> None:
    from mureo.mcp import _handlers_google_ads as handlers
    from mureo.mcp import tools_google_ads

    rows = [{"id": "1", "name": "Brand"}]
    spy = _Spy(_fake_client("list_campaigns", rows))
    file_loader, auth_loader = _refusing_loader(), _refusing_loader()
    source = _GoogleSource()
    with (
        patch.object(handlers, "load_google_ads_credentials", file_loader),
        patch("mureo.auth.load_google_ads_credentials", auth_loader),
        patch.object(handlers, "create_google_ads_client", spy),
        use_credential_source(CredentialSource(google=source)),
    ):
        result = await tools_google_ads.handle_tool(
            "google_ads_campaigns_list", {"customer_id": "1112223333"}
        )

    assert json.loads(result[0].text) == rows
    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args == (_GOOGLE, "1112223333")
    assert kwargs["oauth_credentials"] is source.oauth
    file_loader.assert_not_called()
    auth_loader.assert_not_called()


async def test_search_console_handle_tool_uses_the_source() -> None:
    from mureo.mcp import _handlers_search_console as handlers
    from mureo.mcp import tools_search_console

    sites = [{"siteUrl": "https://example.com/"}]
    client = _fake_client("list_sites", sites)
    spy = _Spy(client)
    file_loader, auth_loader = _refusing_loader(), _refusing_loader()
    source = _GoogleSource()
    with (
        patch.object(handlers, "load_google_ads_credentials", file_loader),
        patch("mureo.auth.load_google_ads_credentials", auth_loader),
        patch.object(handlers, "create_search_console_client", spy),
        use_credential_source(CredentialSource(google=source)),
    ):
        result = await tools_search_console.handle_tool("search_console_sites_list", {})

    assert json.loads(result[0].text) == sites
    assert len(spy.calls) == 1
    args, kwargs = spy.calls[0]
    assert args == (_GOOGLE,)
    assert kwargs["oauth_credentials"] is source.oauth
    file_loader.assert_not_called()
    auth_loader.assert_not_called()
    client.close.assert_awaited_once()


async def test_meta_ads_handle_tool_uses_the_source() -> None:
    from mureo.mcp import _handlers_meta_ads as handlers
    from mureo.mcp import tools_meta_ads

    rows = [{"id": "c1", "name": "Prospecting"}]
    client = _fake_client("list_campaigns", rows)
    constructor = MagicMock(return_value=client)
    file_loader, auth_loader = _refusing_loader(), _refusing_loader()
    refresh = AsyncMock(side_effect=AssertionError("refresh must not run"))
    with (
        patch.object(handlers, "load_meta_ads_credentials", file_loader),
        patch("mureo.auth.load_meta_ads_credentials", auth_loader),
        patch.object(handlers, "refresh_meta_token_if_needed", refresh),
        patch("mureo.meta_ads.MetaAdsApiClient", constructor),
        use_credential_source(CredentialSource(meta_ads=_MetaSource())),
    ):
        result = await tools_meta_ads.handle_tool(
            "meta_ads_campaigns_list", {"account_id": "act_123"}
        )

    assert json.loads(result[0].text) == rows
    constructor.assert_called_once()
    kwargs = constructor.call_args.kwargs
    assert kwargs["access_token"] == "source-token"
    assert kwargs["ad_account_id"] == "act_123"
    file_loader.assert_not_called()
    auth_loader.assert_not_called()
    refresh.assert_not_awaited()
    client.close.assert_awaited_once()
