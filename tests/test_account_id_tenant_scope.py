"""Workspace scoping for Meta ``account_id`` / Google Ads ``customer_id`` (#411).

Most Meta Ads and Google Ads MCP tools accept the per-account id as a free
caller argument, and the shared handler choke point (``_get_client``) used
it with the operator-shared credentials without validating it against the
active workspace's bound account. On a multi-account backend the shared
token reaches EVERY managed account, so a conversation bound to workspace A
could read — and with write tools, mutate — workspace B's account simply by
passing B's id. #375 closed the identical hole for Search Console
(``site_url``); this generalizes that seam.

Two halves are tested here, mirroring test_search_console_tenant_scope.py:

1. ``runtime_meta_account_ids`` / ``runtime_google_ads_customer_ids`` — the
   store-capability resolvers (fail-closed on a multi-account backend that
   declares nothing).
2. The handlers' ``_resolve_account_id`` / ``_resolve_customer_id`` and the
   ``_get_client`` wiring — out-of-set ids refused, unconfigured fails
   fast, single-entry default, id normalization (``act_`` prefix, hyphens).

Standalone OSS (no ``mureo.runtime_context_factory`` registered) is
unaffected: the resolvers return ``None`` and the ids behave exactly as
before.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
    runtime_google_ads_customer_ids,
    runtime_meta_account_ids,
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
    return dataclasses.replace(default_runtime_context(), secret_store=store)


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------
# Resolvers — same contract as runtime_search_console_sites (#375)
# ---------------------------------------------------------------------------

_RESOLVERS = [
    (runtime_meta_account_ids, "meta_account_ids", "act_111"),
    (runtime_google_ads_customer_ids, "google_ads_customer_ids", "111-222-3333"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("resolver", "attribute", "sample"), _RESOLVERS, ids=["meta", "google"]
)
class TestAccountIdResolvers:
    def test_none_when_no_factory_registered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        resolver: Any,
        attribute: str,
        sample: str,
    ) -> None:
        _patch_eps(monkeypatch, [])
        assert resolver() is None

    def test_none_when_store_silent_on_single_account(
        self,
        monkeypatch: pytest.MonkeyPatch,
        resolver: Any,
        attribute: str,
        sample: str,
    ) -> None:
        _patch_eps(monkeypatch, [_FakeEP("x", default_runtime_context)])
        assert resolver() is None

    def test_fail_closed_when_store_silent_on_multi_account(
        self,
        monkeypatch: pytest.MonkeyPatch,
        resolver: Any,
        attribute: str,
        sample: str,
    ) -> None:
        """A shared-auth backend that forgets the allow-list must scope to
        NOTHING, not everything."""

        class _Store:
            multi_account_auth = True

        ctx = _ctx_with_store(_Store())
        _patch_eps(monkeypatch, [_FakeEP("x", lambda: ctx)])
        assert resolver() == frozenset()

    def test_returns_declared_ids(
        self,
        monkeypatch: pytest.MonkeyPatch,
        resolver: Any,
        attribute: str,
        sample: str,
    ) -> None:
        store = MagicMock(spec=[])
        setattr(store, attribute, [sample, "  ", 123])
        ctx = _ctx_with_store(store)
        _patch_eps(monkeypatch, [_FakeEP("x", lambda: ctx)])
        assert resolver() == frozenset({sample})

    def test_bare_str_declaration_is_not_an_allow_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
        resolver: Any,
        attribute: str,
        sample: str,
    ) -> None:
        """A mistyped scalar on a multi-account backend fails CLOSED."""
        store = MagicMock(spec=[])
        setattr(store, attribute, sample)  # bare str, not a collection
        store.multi_account_auth = True
        ctx = _ctx_with_store(store)
        _patch_eps(monkeypatch, [_FakeEP("x", lambda: ctx)])
        assert resolver() == frozenset()


# ---------------------------------------------------------------------------
# Meta handler — _resolve_account_id + _get_client wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAccountIdScoping:
    def _resolve(self, requested: str | None, default: str | None) -> str:
        from mureo.mcp._handlers_meta_ads import _resolve_account_id

        return _resolve_account_id(requested, default)

    def test_unscoped_keeps_existing_behavior(self) -> None:
        with patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=None,
        ):
            assert self._resolve("act_222", "act_111") == "act_222"
            assert self._resolve(None, "act_111") == "act_111"
            with pytest.raises(ValueError, match="account_id is required"):
                self._resolve(None, None)

    def test_unconfigured_client_fails_fast(self) -> None:
        with (
            patch(
                "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
                return_value=frozenset(),
            ),
            pytest.raises(ValueError, match="not configured"),
        ):
            self._resolve("act_222", "act_111")

    def test_out_of_set_explicit_id_is_refused(self) -> None:
        with (
            patch(
                "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
                return_value=frozenset({"act_111"}),
            ),
            pytest.raises(ValueError, match="refused"),
        ):
            self._resolve("act_999", "act_111")

    def test_out_of_set_credentials_default_is_refused(self) -> None:
        """The workspace default from shared credentials is enforced too —
        it may be an operator-level value that does not belong here."""
        with (
            patch(
                "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
                return_value=frozenset({"act_111", "act_222"}),
            ),
            pytest.raises(ValueError, match="refused|required"),
        ):
            self._resolve(None, "act_999")

    def test_multi_entry_default_in_set_is_used(self) -> None:
        """The common production path: creds default already one of several
        configured accounts, no explicit argument."""
        with patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=frozenset({"act_111", "act_222"}),
        ):
            assert self._resolve(None, "act_111") == "act_111"

    def test_in_set_explicit_id_allowed(self) -> None:
        with patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=frozenset({"act_111", "act_222"}),
        ):
            assert self._resolve("act_222", "act_111") == "act_222"

    def test_single_entry_defaults_and_gains_prefix(self) -> None:
        """One configured account: omitted id resolves to it, and a bare
        numeric allow-list entry is canonicalized to the act_ form the
        client factory requires."""
        with patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=frozenset({"123456"}),
        ):
            assert self._resolve(None, None) == "act_123456"

    def test_prefix_insensitive_membership(self) -> None:
        """act_-prefixed argument matches a bare-numeric allow-list entry."""
        with patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=frozenset({"123456"}),
        ):
            assert self._resolve("act_123456", None) == "act_123456"

    @pytest.mark.asyncio
    async def test_get_client_refuses_out_of_set_argument(self) -> None:
        """The wiring: every Meta tool goes through _get_client, which must
        raise before any API client is constructed."""
        from mureo.mcp import _handlers_meta_ads as handlers

        creds = MagicMock(account_id="act_111")
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(
                handlers,
                "runtime_meta_account_ids",
                return_value=frozenset({"act_111"}),
            ),
            patch.object(handlers, "refresh_meta_token_if_needed", new=AsyncMock()),
            patch.object(handlers, "create_meta_ads_client") as factory,
        ):
            with pytest.raises(ValueError, match="refused"):
                await handlers._get_client({"account_id": "act_999"})
            factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_client_builds_client_for_allowed_argument(self) -> None:
        from mureo.mcp import _handlers_meta_ads as handlers

        creds = MagicMock(account_id=None)
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(
                handlers, "runtime_meta_account_ids", return_value=frozenset({"111"})
            ),
            patch.object(
                handlers,
                "refresh_meta_token_if_needed",
                new=AsyncMock(return_value=creds),
            ),
            patch.object(handlers, "register_client_for_cleanup"),
            patch.object(handlers, "create_meta_ads_client") as factory,
        ):
            await handlers._get_client({"account_id": "act_111"})
        factory.assert_called_once()
        assert factory.call_args.args[1] == "act_111"


# ---------------------------------------------------------------------------
# Google Ads handler — _resolve_customer_id + _get_client wiring
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleCustomerIdScoping:
    def _resolve(self, requested: str | None, default: str | None) -> str:
        from mureo.mcp._handlers_google_ads import _resolve_customer_id

        return _resolve_customer_id(requested, default)

    def test_unscoped_keeps_existing_behavior(self) -> None:
        with patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=None,
        ):
            assert self._resolve("222", "111") == "222"
            assert self._resolve(None, "111") == "111"
            with pytest.raises(ValueError, match="customer_id is required"):
                self._resolve(None, None)

    def test_unconfigured_client_fails_fast(self) -> None:
        with (
            patch(
                "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
                return_value=frozenset(),
            ),
            pytest.raises(ValueError, match="not configured"),
        ):
            self._resolve("222", "111")

    def test_out_of_set_explicit_id_is_refused(self) -> None:
        with (
            patch(
                "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
                return_value=frozenset({"111-222-3333"}),
            ),
            pytest.raises(ValueError, match="refused"),
        ):
            self._resolve("999-888-7777", None)

    def test_hyphen_insensitive_membership(self) -> None:
        """1112223333 matches the configured 111-222-3333 and vice versa."""
        with patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=frozenset({"111-222-3333"}),
        ):
            assert self._resolve("1112223333", None) == "1112223333"

    def test_multi_entry_default_in_set_is_used(self) -> None:
        with patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=frozenset({"111", "222"}),
        ):
            assert self._resolve(None, "111") == "111"

    def test_single_entry_defaults_when_omitted(self) -> None:
        with patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=frozenset({"111-222-3333"}),
        ):
            assert self._resolve(None, None) == "111-222-3333"

    def test_out_of_set_mcc_default_falls_back_to_single_entry(self) -> None:
        """The shared login_customer_id (MCC) is usually NOT the client's
        account — with one configured id, resolution lands there instead."""
        with patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=frozenset({"111-222-3333"}),
        ):
            assert self._resolve(None, "999-000-1111") == "111-222-3333"

    def test_get_client_refuses_out_of_set_argument(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        creds = MagicMock(customer_id="111", login_customer_id="999")
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_google_ads_credentials", return_value=creds),
            patch.object(
                handlers,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"111"}),
            ),
            patch.object(handlers, "create_google_ads_client") as factory,
        ):
            with pytest.raises(ValueError, match="refused"):
                handlers._get_client({"customer_id": "222"})
            factory.assert_not_called()

    def test_get_client_builds_client_for_allowed_argument(self) -> None:
        from mureo.mcp import _handlers_google_ads as handlers

        creds = MagicMock(customer_id=None, login_customer_id=None)
        with (
            patch.object(handlers, "byod_has", return_value=False),
            patch.object(handlers, "load_google_ads_credentials", return_value=creds),
            patch.object(
                handlers,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"111-222-3333"}),
            ),
            patch.object(handlers, "create_google_ads_client") as factory,
        ):
            handlers._get_client({"customer_id": "1112223333"})
        factory.assert_called_once()
        assert factory.call_args.args[1] == "1112223333"


# ---------------------------------------------------------------------------
# google_ads_accounts_list — the id-free discovery tool must not enumerate
# sibling clients' accounts under shared auth (#411 review CRITICAL).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAccountsListScoping:
    _ROWS = [
        {"id": "1112223333", "name": "Mine"},
        {"id": "9990001111", "name": "Sibling client"},
    ]

    async def _call(self, allowed: frozenset[str] | None) -> list[dict[str, Any]]:
        import json as _json

        from mureo.mcp import _handlers_google_ads_analysis as mod

        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch("mureo.auth.load_google_ads_credentials", return_value=MagicMock()),
            patch(
                "mureo.google_ads.list_accessible_accounts",
                new=AsyncMock(return_value=list(self._ROWS)),
            ),
            patch.object(mod, "runtime_google_ads_customer_ids", return_value=allowed),
        ):
            result = await mod.handle_accounts_list({})
        payload: list[dict[str, Any]] = _json.loads(result[0].text)
        return payload

    @pytest.mark.asyncio
    async def test_recovery_path_filters_to_allowed(self) -> None:
        rows = await self._call(frozenset({"111-222-3333"}))
        assert [row["id"] for row in rows] == ["1112223333"]

    @pytest.mark.asyncio
    async def test_recovery_path_unscoped_is_unchanged(self) -> None:
        rows = await self._call(None)
        assert [row["id"] for row in rows] == ["1112223333", "9990001111"]

    @pytest.mark.asyncio
    async def test_recovery_path_fail_closed_when_unconfigured(self) -> None:
        rows = await self._call(frozenset())
        assert rows == []

    @pytest.mark.asyncio
    async def test_explicit_customer_id_branch_filters_response(self) -> None:
        """The customer-scoped client's list_accounts() enumerates the same
        shared-auth reachable set — its response is filtered too."""
        import json as _json

        from mureo.mcp import _handlers_google_ads_analysis as mod

        # Real shape from mureo/google_ads/client.py list_accounts():
        # {"customer_id": "<resource_name>"} with a "customers/" prefix.
        rows = [
            {"customer_id": "customers/1112223333"},
            {"customer_id": "customers/9990001111"},
        ]
        client = MagicMock()
        client.list_accounts = AsyncMock(return_value=rows)
        with (
            patch("mureo.byod.runtime.byod_has", return_value=False),
            patch.object(mod, "_get_client", return_value=client),
            patch.object(
                mod,
                "runtime_google_ads_customer_ids",
                return_value=frozenset({"111-222-3333"}),
            ),
        ):
            result = await mod.handle_accounts_list({"customer_id": "111-222-3333"})
        payload = _json.loads(result[0].text)
        assert payload == [{"customer_id": "customers/1112223333"}]
