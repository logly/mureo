"""Tenant scoping for Search Console (#365-adjacent multi-tenancy fix).

Search Console reuses the operator-shared Google OAuth, and its MCP tools
take ``site_url`` as a free caller argument. In a multi-account (agency)
deployment the shared identity can reach EVERY client's property, so nothing
otherwise stops one client's workspace from querying a sibling's property —
a cross-client data leak.

Two halves are tested here:

1. ``runtime_search_console_sites`` — the store-capability resolver that a
   multi-account backend uses to declare the active client's allowed
   ``site_url``s (mirrors ``runtime_multi_account_auth`` #198).
2. The Search Console handlers' ``_resolve_site_url`` / ``list_sites``
   filtering — which fail-close an out-of-scope ``site_url`` and hide
   sibling properties.

Standalone OSS (no ``mureo.runtime_context_factory`` registered) is
unaffected: the resolver returns ``None`` and ``site_url`` stays a plain
required argument used verbatim.
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.core.runtime_context import (
    RuntimeContextFactoryError,
    default_runtime_context,
    reset_runtime_context,
    runtime_search_console_sites,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


_GROUP = "mureo.runtime_context_factory"


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_eps(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == _GROUP
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


def _ctx_with_store(store: Any) -> Any:
    """A default RuntimeContext whose secret_store is ``store``."""
    return dataclasses.replace(default_runtime_context(), secret_store=store)


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------
# runtime_search_console_sites resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRuntimeSearchConsoleSites:
    def test_none_when_no_factory_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Standalone OSS: no factory → not scoped (byte-identical to today)."""
        _patch_eps(monkeypatch, [])
        assert runtime_search_console_sites() is None

    def test_none_when_store_silent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Factory present but the store never declares the attribute → not
        scoped (no opt-in)."""
        _patch_eps(monkeypatch, [_FakeEP("agency", default_runtime_context)])
        assert runtime_search_console_sites() is None

    def test_returns_declared_sites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Store:
            search_console_sites = [
                "https://a.example/",
                "sc-domain:b.example",
            ]

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() == frozenset(
            {"https://a.example/", "sc-domain:b.example"}
        )

    def test_blank_and_non_str_entries_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Store:
            search_console_sites = ["https://a.example/", "  ", "", 123, None]

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() == frozenset({"https://a.example/"})

    def test_empty_declared_collection_is_empty_frozenset_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Declaring the attribute opts INTO scoping — an empty collection is
        'scoped with zero sites' (→ handlers fail-fast), NOT 'no scoping'."""

        class _Store:
            search_console_sites: list[str] = []

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        result = runtime_search_console_sites()
        assert result == frozenset()
        assert result is not None

    def test_bare_str_declaration_on_single_account_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mistyped scalar must NOT become a one-element allow-list. On a
        single-account backend (no shared-OAuth risk) an unusable declaration
        stays 'not scoped'."""

        class _Store:
            search_console_sites = "https://a.example/"

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() is None

    def test_all_invalid_entries_is_empty_frozenset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A usable-but-all-junk collection is 'scoped, zero sites' (errs
        CLOSED → handlers fail-fast), never 'not scoped'."""

        class _Store:
            search_console_sites = ["", "  ", 123, None]

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        result = runtime_search_console_sites()
        assert result == frozenset()
        assert result is not None

    # -- Fail-closed coupling to multi_account_auth (shared-OAuth backends) --
    #
    # The whole cross-client leak lives in a shared-OAuth (multi-account)
    # deployment. Such a backend that FORGETS or MISTYPES search_console_sites
    # must scope to NOTHING (fail-fast), never silently reopen the leak.

    def test_multi_account_without_sites_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Store:
            multi_account_auth = True

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        result = runtime_search_console_sites()
        assert result == frozenset()
        assert result is not None

    def test_multi_account_with_bare_str_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Store:
            multi_account_auth = True
            search_console_sites = "https://a.example/"

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() == frozenset()

    def test_multi_account_with_generator_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lazy/generator declaration is not a Collection → unusable → a
        multi-account backend still scopes to nothing (not unrestricted)."""

        class _Store:
            multi_account_auth = True
            search_console_sites = (s for s in ["https://a.example/"])

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() == frozenset()

    def test_multi_account_with_usable_sites_returns_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A properly-declared multi-account backend scopes to its own list."""

        class _Store:
            multi_account_auth = True
            search_console_sites = ["https://a.example/"]

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("agency", lambda: ctx)])
        assert runtime_search_console_sites() == frozenset({"https://a.example/"})

    def test_multiple_factories_propagate_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A misconfigured (>1) factory surfaces its error rather than
        silently resolving to unrestricted — fail-closed at the seam."""
        _patch_eps(
            monkeypatch,
            [
                _FakeEP("a", default_runtime_context),
                _FakeEP("b", default_runtime_context),
            ],
        )
        with pytest.raises(RuntimeContextFactoryError):
            runtime_search_console_sites()


# ---------------------------------------------------------------------------
# Handler enforcement — _resolve_site_url + list_sites filtering
# ---------------------------------------------------------------------------


def _handlers() -> Any:
    from mureo.mcp import _handlers_search_console

    return _handlers_search_console


def _mock_client_ctx(h: Any, client: AsyncMock) -> Any:
    """Patch creds + client factory so a handler reaches the mock client."""
    return (
        patch.object(h, "load_google_ads_credentials", return_value=MagicMock()),
        patch.object(h, "create_search_console_client", return_value=client),
    )


def _scoped(h: Any, sites: frozenset[str] | None) -> Any:
    """Patch the handler-module's scoping resolver to ``sites``."""
    return patch.object(h, "runtime_search_console_sites", return_value=sites)


@pytest.mark.unit
@pytest.mark.asyncio
class TestSiteUrlEnforcement:
    async def test_standalone_requires_site_url(self) -> None:
        """Not scoped (None) + no site_url arg → the usual required-param error."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, None), pytest.raises(ValueError):
            await h.handle_sites_get({})
        client.get_site.assert_not_awaited()

    async def test_standalone_uses_site_url_verbatim(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.get_site.return_value = {"siteUrl": "https://x.example/"}
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, None):
            await h.handle_sites_get({"site_url": "https://x.example/"})
        client.get_site.assert_awaited_once_with("https://x.example/")

    async def test_scoped_in_set_is_allowed(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.get_site.return_value = {"siteUrl": "https://a.example/"}
        p_creds, p_client = _mock_client_ctx(h, client)
        allowed = frozenset({"https://a.example/", "https://b.example/"})
        with p_creds, p_client, _scoped(h, allowed):
            await h.handle_sites_get({"site_url": "https://a.example/"})
        client.get_site.assert_awaited_once_with("https://a.example/")

    async def test_scoped_out_of_set_is_refused(self) -> None:
        """Fail-closed: a sibling client's property is refused before any API
        call."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        allowed = frozenset({"https://a.example/"})
        with p_creds, p_client, _scoped(h, allowed), pytest.raises(ValueError):
            await h.handle_sites_get({"site_url": "https://sibling.example/"})
        client.get_site.assert_not_awaited()

    async def test_scoped_omitted_single_site_resolves(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.get_site.return_value = {"siteUrl": "https://only.example/"}
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, frozenset({"https://only.example/"})):
            await h.handle_sites_get({})
        client.get_site.assert_awaited_once_with("https://only.example/")

    async def test_scoped_omitted_multiple_sites_is_ambiguous(self) -> None:
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        allowed = frozenset({"https://a.example/", "https://b.example/"})
        with p_creds, p_client, _scoped(h, allowed), pytest.raises(ValueError):
            await h.handle_sites_get({})
        client.get_site.assert_not_awaited()

    async def test_scoped_empty_set_fails_fast(self) -> None:
        """Scoped with zero configured sites → fail-fast, even with a site_url."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, frozenset()), pytest.raises(ValueError):
            await h.handle_sites_get({"site_url": "https://a.example/"})
        client.get_site.assert_not_awaited()

    async def test_analytics_query_enforces_site_url(self) -> None:
        """Enforcement is centralized: an analytics tool refuses an
        out-of-scope site_url too."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        args = {
            "site_url": "https://sibling.example/",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }
        with (
            p_creds,
            p_client,
            _scoped(h, frozenset({"https://a.example/"})),
            pytest.raises(ValueError),
        ):
            await h.handle_analytics_top_queries(args)
        client.query_analytics.assert_not_awaited()

    async def test_sitemaps_submit_write_path_enforces_site_url(self) -> None:
        """The WRITE path is gated too: submitting a sitemap to a sibling's
        property is refused before any mutation."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        args = {
            "site_url": "https://sibling.example/",
            "feedpath": "https://sibling.example/sitemap.xml",
        }
        with (
            p_creds,
            p_client,
            _scoped(h, frozenset({"https://a.example/"})),
            pytest.raises(ValueError),
        ):
            await h.handle_sitemaps_submit(args)
        client.submit_sitemap.assert_not_awaited()

    async def test_compare_periods_enforces_site_url(self) -> None:
        """The structurally-distinct compare-periods handler (one resolve
        reused across two queries) enforces the allow-list too."""
        h = _handlers()
        client = AsyncMock()
        p_creds, p_client = _mock_client_ctx(h, client)
        args = {
            "site_url": "https://sibling.example/",
            "start_date_1": "2026-01-01",
            "end_date_1": "2026-01-31",
            "start_date_2": "2026-02-01",
            "end_date_2": "2026-02-28",
        }
        with (
            p_creds,
            p_client,
            _scoped(h, frozenset({"https://a.example/"})),
            pytest.raises(ValueError),
        ):
            await h.handle_analytics_compare_periods(args)
        client.query_analytics.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
class TestSitesListFiltering:
    async def test_scoped_list_hides_sibling_properties(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.list_sites.return_value = [
            {"siteUrl": "https://a.example/", "permissionLevel": "siteOwner"},
            {"siteUrl": "https://sibling.example/", "permissionLevel": "siteOwner"},
        ]
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, frozenset({"https://a.example/"})):
            result = await h.handle_sites_list({})
        parsed = json.loads(result[0].text)
        urls = [row["siteUrl"] for row in parsed]
        assert urls == ["https://a.example/"]

    async def test_scoped_empty_set_lists_nothing(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.list_sites.return_value = [{"siteUrl": "https://sibling.example/"}]
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, frozenset()):
            result = await h.handle_sites_list({})
        assert json.loads(result[0].text) == []

    async def test_standalone_list_is_unfiltered(self) -> None:
        h = _handlers()
        client = AsyncMock()
        client.list_sites.return_value = [
            {"siteUrl": "https://a.example/"},
            {"siteUrl": "https://b.example/"},
        ]
        p_creds, p_client = _mock_client_ctx(h, client)
        with p_creds, p_client, _scoped(h, None):
            result = await h.handle_sites_list({})
        urls = [row["siteUrl"] for row in json.loads(result[0].text)]
        assert urls == ["https://a.example/", "https://b.example/"]
