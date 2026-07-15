"""The analytics live-client helpers must enforce the #411 allow-list (#413).

``_open_google_ads_client`` / ``_open_meta_ads_client`` used to pass the caller
``account_id`` verbatim to the client factory, bypassing the workspace account
allow-list the MCP handlers enforce via ``_resolve_customer_id`` /
``_resolve_account_id``. Dormant (no wired tool fed a caller id into the
AnalyticsModule Protocol), but a future tool that did would silently escape
#411 tenant scoping. The helpers now route the id through the same resolvers:
a non-tenant-scoped run passes it through unchanged; a tenant-scoped run
refuses an out-of-allow-list id (fail-closed).
"""

from __future__ import annotations

import pytest

from mureo.analytics.builtin import _live_clients

pytestmark = pytest.mark.unit


@pytest.fixture
def stub_factories(monkeypatch: pytest.MonkeyPatch):
    """Stub BYOD + the client factories so a test exercises only the scoping
    step, never real credentials or the network. Returns (sentinels, calls)."""
    monkeypatch.setattr("mureo.byod.runtime.byod_has", lambda platform: True)
    sentinel_g, sentinel_m = object(), object()
    calls: dict[str, str | None] = {}

    def fake_google(creds=None, customer_id=None):
        calls["google"] = customer_id
        return sentinel_g

    def fake_meta(creds=None, account_id=None):
        calls["meta"] = account_id
        return sentinel_m

    monkeypatch.setattr("mureo.mcp._client_factory.get_google_ads_client", fake_google)
    monkeypatch.setattr("mureo.mcp._client_factory.get_meta_ads_client", fake_meta)
    return sentinel_g, sentinel_m, calls


def _scope_google(monkeypatch: pytest.MonkeyPatch, allowed) -> None:
    import mureo.mcp._handlers_google_ads as gh

    monkeypatch.setattr(gh, "runtime_google_ads_customer_ids", lambda: allowed)


def _scope_meta(monkeypatch: pytest.MonkeyPatch, allowed) -> None:
    import mureo.mcp._handlers_meta_ads as mh

    monkeypatch.setattr(mh, "runtime_meta_account_ids", lambda: allowed)


# --- Google Ads ------------------------------------------------------------


def test_google_refuses_out_of_allowlist(monkeypatch, stub_factories) -> None:
    _scope_google(monkeypatch, frozenset({"111"}))
    with pytest.raises(ValueError):
        _live_clients._open_google_ads_client("999")


def test_google_allows_in_allowlist(monkeypatch, stub_factories) -> None:
    sentinel_g, _sm, calls = stub_factories
    _scope_google(monkeypatch, frozenset({"111"}))
    assert _live_clients._open_google_ads_client("111") is sentinel_g
    assert calls["google"] == "111"


def test_google_not_tenant_scoped_passes_through(monkeypatch, stub_factories) -> None:
    sentinel_g, _sm, calls = stub_factories
    _scope_google(monkeypatch, None)  # no allow-list active
    assert _live_clients._open_google_ads_client("acct-x") is sentinel_g
    assert calls["google"] == "acct-x"


# --- Meta Ads --------------------------------------------------------------


def test_meta_refuses_out_of_allowlist(monkeypatch, stub_factories) -> None:
    _scope_meta(monkeypatch, frozenset({"act_111"}))
    with pytest.raises(ValueError):
        _live_clients._open_meta_ads_client("act_999")


def test_meta_allows_in_allowlist(monkeypatch, stub_factories) -> None:
    _sg, sentinel_m, calls = stub_factories
    _scope_meta(monkeypatch, frozenset({"act_111"}))
    assert _live_clients._open_meta_ads_client("act_111") is sentinel_m
    assert calls["meta"] == "act_111"


def test_meta_not_tenant_scoped_passes_through(monkeypatch, stub_factories) -> None:
    _sg, sentinel_m, calls = stub_factories
    _scope_meta(monkeypatch, None)
    assert _live_clients._open_meta_ads_client("act_x") is sentinel_m
    assert calls["meta"] == "act_x"
