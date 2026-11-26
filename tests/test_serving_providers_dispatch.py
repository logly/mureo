"""Built-in tools in a workspace whose account a serving plugin holds.

The refusal a built-in tool answers with when the workspace scopes its
platform to no built-in account, and the pointer to the plugin's tool family
appended to the built-in no-credentials messages. An explicit id outside the
allow-list keeps its own refusal, with no pointer. Driven through the real
dispatcher with every credential load and network path replaced by a failing
spy.
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.byod.runtime import SCHEMA_VERSION
from mureo.client_factory import AccountIdRefused
from mureo.core.credential_source import CredentialSource, use_credential_source
from mureo.mcp import _plugin_tables, _server_slots, journal
from mureo.mcp import server as mcp_server
from mureo.mcp import serving_providers as sp
from mureo.mcp._google_ads_client import _NO_CREDS_MSG as _GOOGLE_NO_CREDS_MSG
from mureo.mcp._google_ads_client import _get_client as _google_get_client
from mureo.mcp._google_ads_client import _no_google_creds
from mureo.mcp._handlers_search_console import _NO_CREDS_MSG as _SC_NO_CREDS_MSG
from mureo.mcp._handlers_search_console import _no_sc_creds, _resolve_site_url
from mureo.mcp._journal_hook import PLUGIN_FAMILY, tool_family
from mureo.mcp._meta_ads_client import _NO_CREDS_MSG as _META_NO_CREDS_MSG
from mureo.mcp._meta_ads_client import _get_client as _meta_get_client
from mureo.mcp._meta_ads_client import _no_meta_creds
from mureo.rollback import executor as rollback_executor
from tests._server_reload import reloaded_server
from tests._serving_providers_support import (
    ACME,
    ALL_CONFIGURED,
    CONFIGURED,
    GATES,
    GOOGLE_ACME,
    PROVIDER,
    REFUSAL,
    SC_ACME,
    SERVED_POINTER,
    NoneSource,
    Store,
    detail,
    discover_for,
    install_backend,
    journal_records,
    plugin_class,
    scoped_backend,
    serve,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "JOURNAL.jsonl"
    monkeypatch.setattr(journal, "journal_path", lambda: path)
    return path


# ---------------------------------------------------------------------------
# 1. Dispatch refusal in an account-scoped workspace
# ---------------------------------------------------------------------------


@pytest.fixture
def no_network() -> Iterator[dict[str, MagicMock]]:
    """Every way a built-in call could reach a platform, each a failing spy."""
    spies = {
        "async_send": AsyncMock(side_effect=AssertionError("network call")),
        "sync_send": MagicMock(side_effect=AssertionError("network call")),
        "meta_creds": MagicMock(side_effect=AssertionError("meta creds")),
        "meta_client": MagicMock(side_effect=AssertionError("meta client")),
        "google_creds": MagicMock(side_effect=AssertionError("google creds")),
        "google_client": MagicMock(side_effect=AssertionError("google client")),
        "accessible": AsyncMock(side_effect=AssertionError("accessible")),
        "sc_creds": MagicMock(side_effect=AssertionError("sc creds")),
        "sc_client": MagicMock(side_effect=AssertionError("sc client")),
    }
    targets = {
        "async_send": "httpx.AsyncClient.send",
        "sync_send": "httpx.Client.send",
        "meta_creds": "mureo.auth.load_meta_ads_credentials",
        "meta_client": "mureo.auth.create_meta_ads_client",
        "google_creds": "mureo.auth.load_google_ads_credentials",
        "google_client": "mureo.auth.create_google_ads_client",
        "accessible": "mureo.google_ads.list_accessible_accounts",
        "sc_creds": "mureo.mcp._handlers_search_console.load_google_ads_credentials",
        "sc_client": "mureo.mcp._handlers_search_console.create_search_console_client",
    }
    with contextlib.ExitStack() as stack:
        for key, target in targets.items():
            stack.enter_context(patch(target, new=spies[key]))
        yield spies
    for spy in spies.values():
        spy.assert_not_called()


async def test_meta_builtin_refuses_with_a_pointer(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    result = await mcp_server.handle_call_tool("meta_ads_campaigns_list", {})
    assert detail(result) == REFUSAL
    records = journal_records(log)
    assert [record["outcome"] for record in records] == ["refused"]


async def test_google_accounts_list_refuses_without_a_customer_id(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "google_ads", GOOGLE_ACME)
    result = await mcp_server.handle_call_tool("google_ads_accounts_list", {})
    assert detail(result) == (
        "The built-in google_ads_* tools have no Google Ads account configured "
        "in this workspace, so google_ads_accounts_list was not run. This "
        "workspace's Google Ads account is configured under the google_ads_acme_* "
        "tools — use those instead."
    )


async def test_search_console_sites_list_refuses_without_a_client(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "search_console", SC_ACME)
    result = await mcp_server.handle_call_tool("search_console_sites_list", {})
    assert "search_console_acme_*" in detail(result)


async def test_mutation_refuses_before_capture_and_journals_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    log: Path,
    no_network: dict[str, MagicMock],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "STATE.json").write_text("{}", encoding="utf-8")
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    capture = AsyncMock()
    handler = AsyncMock()
    with (
        patch("mureo.mcp.server.capture_before_state", new=capture),
        patch("mureo.mcp.server.handle_meta_ads_tool", new=handler),
    ):
        result = await mcp_server.handle_call_tool(
            "meta_ads_campaigns_pause", {"campaign_id": "123"}
        )
    capture.assert_not_awaited()
    handler.assert_not_awaited()
    assert "meta_ads_acme_*" in detail(result)
    records = journal_records(log)
    assert len(records) == 1
    assert records[0]["tool"] == "meta_ads_campaigns_pause"
    assert records[0]["outcome"] == "refused"
    assert records[0]["reason"] == detail(result)
    assert (tmp_path / "STATE.json").read_text(encoding="utf-8") == "{}"


async def test_no_serving_plugin_means_no_refusal(
    monkeypatch: pytest.MonkeyPatch, log: Path
) -> None:
    scoped_backend(monkeypatch)
    assert sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads") is None
    with patch("mureo.auth.load_meta_ads_credentials", return_value=None):
        result = await mcp_server.handle_call_tool("meta_ads_campaigns_list", {})
    assert detail(result) == _META_NO_CREDS_MSG


def test_non_empty_allow_list_means_no_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped_backend(monkeypatch, {"meta_account_ids": frozenset({"act_111"})})
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads") is None


def test_unserved_platform_and_plugin_tools_are_never_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.builtin_refusal("google_ads_campaigns_list", "google_ads") is None
    assert sp.builtin_refusal("meta_ads_acme_campaigns_list", "plugin") is None
    assert sp.builtin_refusal("mureo_state_get", "mureo_context") is None


async def test_two_serving_families_are_joined_in_the_refusal(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    beta = sp.ServingProvider("meta_ads_beta", "meta_ads_beta_", ("token",))
    sections = {**ALL_CONFIGURED, "meta_ads_beta": {"token": "x"}}
    install_backend(monkeypatch, Store(sections, multi_account=True))
    serve(monkeypatch, "meta_ads", ACME, beta)
    result = await mcp_server.handle_call_tool("meta_ads_campaigns_list", {})
    assert detail(result).endswith(
        "configured under the meta_ads_acme_* or meta_ads_beta_* tools — use "
        "those instead."
    )


async def test_rollback_reentry_of_a_builtin_is_refused_and_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    handler = AsyncMock()
    token = rollback_executor._rollback_dispatch_active.set(True)
    try:
        with patch("mureo.mcp.server.handle_meta_ads_tool", new=handler):
            result = await _server_slots.require_dispatcher()(
                "meta_ads_campaigns_pause", {"campaign_id": "123"}
            )
    finally:
        rollback_executor._rollback_dispatch_active.reset(token)
    handler.assert_not_awaited()
    assert "meta_ads_acme_*" in detail(result)
    records = journal_records(log)
    assert [(r["outcome"], r["rollback"]) for r in records] == [("refused", True)]


def test_a_byod_platform_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    byod_dir = tmp_path / "byod"
    (byod_dir / "meta_ads").mkdir(parents=True)
    monkeypatch.setenv("MUREO_BYOD_DIR", str(byod_dir))
    manifest = {"schema_version": SCHEMA_VERSION, "platforms": {"meta_ads": {}}}
    (byod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    assert sp.builtin_refusal("meta_ads_campaigns_list", "meta_ads") is None


async def test_an_explicit_id_gets_the_same_refusal_naming_no_id(
    monkeypatch: pytest.MonkeyPatch, log: Path, no_network: dict[str, MagicMock]
) -> None:
    scoped_backend(monkeypatch)
    serve(monkeypatch, "meta_ads", ACME)
    result = await mcp_server.handle_call_tool(
        "meta_ads_campaigns_list", {"account_id": "act_222"}
    )
    assert detail(result) == REFUSAL
    assert "act_222" not in result[0].text
    assert [record["outcome"] for record in journal_records(log)] == ["refused"]
    no_network["meta_creds"].assert_not_called()


async def test_the_plugin_family_itself_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, log: Path
) -> None:
    plugin = plugin_class("meta_ads")
    plugin.calls.clear()
    with reloaded_server(discover_for(plugin), env=GATES) as server_mod:
        scoped_backend(monkeypatch)
        assert _plugin_tables._SERVING_PROVIDERS == {"meta_ads": (ACME,)}
        assert "meta_ads_acme_campaigns_list" in _plugin_tables._PLUGIN_DISPATCH
        assert tool_family("meta_ads_acme_campaigns_list") == PLUGIN_FAMILY
        await server_mod.handle_call_tool("meta_ads_acme_campaigns_list", {})
    assert plugin.calls == ["meta_ads_acme_campaigns_list"]
    outcomes = [record["outcome"] for record in journal_records(log)]
    assert len(outcomes) == 1
    assert outcomes != ["refused"]


# ---------------------------------------------------------------------------
# 2. Not account-scoped, built-in credentials missing
# ---------------------------------------------------------------------------


async def test_missing_builtin_credentials_point_at_the_serving_family(
    monkeypatch: pytest.MonkeyPatch, log: Path
) -> None:
    install_backend(monkeypatch, Store({PROVIDER: CONFIGURED}))
    serve(monkeypatch, "meta_ads", ACME)
    send = AsyncMock(side_effect=AssertionError("network call"))
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
        patch("httpx.AsyncClient.send", new=send),
    ):
        result = await mcp_server.handle_call_tool("meta_ads_campaigns_list", {})
    assert detail(result) == f"{_META_NO_CREDS_MSG} {SERVED_POINTER}"
    send.assert_not_called()


async def test_missing_builtin_credentials_text_is_unchanged_without_a_plugin(
    monkeypatch: pytest.MonkeyPatch, log: Path
) -> None:
    install_backend(monkeypatch, Store({PROVIDER: CONFIGURED}))
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
        patch("mureo.auth.load_google_ads_credentials", return_value=None),
    ):
        meta = await mcp_server.handle_call_tool("meta_ads_campaigns_list", {})
        google = await mcp_server.handle_call_tool(
            "google_ads_campaigns_list", {"customer_id": "1112223333"}
        )
    assert detail(meta) == _META_NO_CREDS_MSG
    assert detail(google) == _GOOGLE_NO_CREDS_MSG


def test_search_console_missing_credentials_point_at_the_serving_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_backend(monkeypatch, Store(ALL_CONFIGURED))
    assert detail(_no_sc_creds()) == _SC_NO_CREDS_MSG
    serve(monkeypatch, "search_console", SC_ACME)
    assert detail(_no_sc_creds()) == (
        f"{_SC_NO_CREDS_MSG} This workspace's Search Console account is configured "
        "under the search_console_acme_* tools — use those instead."
    )


# ---------------------------------------------------------------------------
# 3. A pointer never sends a credential-source call to itself
# ---------------------------------------------------------------------------


def test_no_pointer_while_a_credential_source_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_backend(monkeypatch, Store(ALL_CONFIGURED))
    serve(monkeypatch, "meta_ads", ACME)
    serve(monkeypatch, "google_ads", GOOGLE_ACME)
    serve(monkeypatch, "search_console", SC_ACME)
    source = CredentialSource(google=NoneSource(), meta_ads=NoneSource())
    with use_credential_source(source):
        assert detail(_no_meta_creds()) == _META_NO_CREDS_MSG
        assert detail(_no_google_creds()) == _GOOGLE_NO_CREDS_MSG
        assert detail(_no_sc_creds()) == _SC_NO_CREDS_MSG
    assert detail(_no_meta_creds()) == f"{_META_NO_CREDS_MSG} {SERVED_POINTER}"


# ---------------------------------------------------------------------------
# 4. An explicit id outside the allow-list ends the call
# ---------------------------------------------------------------------------


async def test_out_of_scope_meta_id_is_refused_without_a_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scoped_backend(monkeypatch, {"meta_account_ids": frozenset({"act_111"})})
    serve(monkeypatch, "meta_ads", ACME)
    creds = SimpleNamespace(account_id=None)
    with (
        patch("mureo.auth.load_meta_ads_credentials", return_value=creds),
        pytest.raises(AccountIdRefused) as refused,
    ):
        await _meta_get_client({"account_id": "act_222"})
    assert str(refused.value) == (
        "account_id 'act_222' is not one of this client's configured ad accounts "
        "and was refused."
    )


async def test_out_of_scope_google_id_is_refused_without_a_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = frozenset({"1112223333"})
    scoped_backend(monkeypatch, {"google_ads_customer_ids": allowed})
    serve(monkeypatch, "google_ads", GOOGLE_ACME)
    creds = SimpleNamespace(customer_id=None, login_customer_id=None)
    with (
        patch("mureo.auth.load_google_ads_credentials", return_value=creds),
        pytest.raises(AccountIdRefused) as refused,
    ):
        await _google_get_client({"customer_id": "9998887777"})
    assert str(refused.value) == (
        "customer_id '9998887777' is not one of this client's configured "
        "accounts and was refused."
    )


def test_out_of_scope_site_url_is_refused_without_a_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = frozenset({"https://acme.example/"})
    scoped_backend(monkeypatch, {"search_console_sites": allowed})
    serve(monkeypatch, "search_console", SC_ACME)
    with pytest.raises(ValueError) as refused:
        _resolve_site_url({"site_url": "https://other.example/"})
    assert str(refused.value) == (
        "site_url 'https://other.example/' is not one of this client's "
        "configured Search Console properties and was refused. Use "
        "search_console_sites_list to see the allowed properties."
    )
