"""The analytics live-client helpers must enforce the #411 allow-list (#413)
and stay consistent after resolution (#435).

``_open_google_ads_client`` / ``_open_meta_ads_client`` route the caller
``account_id`` through the same ``_resolve_customer_id`` / ``_resolve_account_id``
the MCP handlers use: a non-tenant-scoped run passes it through unchanged; a
tenant-scoped run refuses an out-of-allow-list id. Per #435 the helpers now
(1) surface a refusal as :class:`AccountNotAvailableError`, a
:class:`NoCredentialsError` subclass so adapters degrade gracefully instead of
crashing, and (2) return the RESOLVED id so callers label / look up conversions
with the same (possibly canonicalized) value the client was opened with.
"""

from __future__ import annotations

import pytest

from mureo.analytics.builtin import _live_clients
from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule

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


# --- scope enforcement + resolved-id return (#413/#435) --------------------


def test_google_refuses_out_of_allowlist(monkeypatch, stub_factories) -> None:
    _scope_google(monkeypatch, frozenset({"111"}))
    with pytest.raises(_live_clients.AccountNotAvailableError):
        _live_clients._open_google_ads_client("999")


def test_google_allows_in_allowlist(monkeypatch, stub_factories) -> None:
    sentinel_g, _sm, calls = stub_factories
    _scope_google(monkeypatch, frozenset({"111"}))
    client, resolved = _live_clients._open_google_ads_client("111")
    assert client is sentinel_g
    assert resolved == "111"
    assert calls["google"] == "111"


def test_google_not_tenant_scoped_passes_through(monkeypatch, stub_factories) -> None:
    sentinel_g, _sm, calls = stub_factories
    _scope_google(monkeypatch, None)  # no allow-list active
    client, resolved = _live_clients._open_google_ads_client("acct-x")
    assert client is sentinel_g
    assert resolved == "acct-x"
    assert calls["google"] == "acct-x"


def test_meta_refuses_out_of_allowlist(monkeypatch, stub_factories) -> None:
    _scope_meta(monkeypatch, frozenset({"act_111"}))
    with pytest.raises(_live_clients.AccountNotAvailableError):
        _live_clients._open_meta_ads_client("act_999")


def test_meta_allows_in_allowlist(monkeypatch, stub_factories) -> None:
    _sg, sentinel_m, calls = stub_factories
    _scope_meta(monkeypatch, frozenset({"act_111"}))
    client, resolved = _live_clients._open_meta_ads_client("act_111")
    assert client is sentinel_m
    assert resolved == "act_111"
    assert calls["meta"] == "act_111"


def test_meta_not_tenant_scoped_passes_through(monkeypatch, stub_factories) -> None:
    _sg, sentinel_m, calls = stub_factories
    _scope_meta(monkeypatch, None)
    client, resolved = _live_clients._open_meta_ads_client("act_x")
    assert client is sentinel_m
    assert resolved == "act_x"
    assert calls["meta"] == "act_x"


# --- #435 WARNING 2: resolved id is returned AND used ----------------------


def test_meta_returns_and_uses_canonical_resolved_id(
    monkeypatch, stub_factories
) -> None:
    """A bare ``111`` matching allow-list ``act_111`` resolves to the canonical
    ``act_111`` — the client is opened with it AND it is returned, so callers
    label / look up conversions with the same id (no #435 format skew)."""
    _sg, sentinel_m, calls = stub_factories
    _scope_meta(monkeypatch, frozenset({"act_111"}))
    client, resolved = _live_clients._open_meta_ads_client("111")
    assert client is sentinel_m
    assert resolved == "act_111"
    assert calls["meta"] == "act_111"


# --- #435 WARNING 1: a scope refusal degrades gracefully -------------------


def test_scope_refusal_is_a_no_credentials_subclass() -> None:
    """``AccountNotAvailableError`` subclasses ``NoCredentialsError`` so every
    adapter's existing ``except NoCredentialsError`` renders the graceful
    sentinel — a scope violation degrades like missing credentials."""
    assert issubclass(
        _live_clients.AccountNotAvailableError, _live_clients.NoCredentialsError
    )


async def test_module_detect_anomalies_empty_on_scope_refusal(monkeypatch) -> None:
    """End-to-end: a workspace-scope refusal makes ``detect_anomalies`` return
    the empty sentinel (config state), not raise (#435 WARNING 1)."""
    _scope_google(monkeypatch, frozenset({"111"}))  # refuses "999"
    module = GoogleAdsAnalyticsModule()
    assert await module.detect_anomalies("999") == ()
