"""#511 — a multi-tenant host can bind the Amazon bridge's token writes.

``AmazonAdsBridge`` is constructed zero-arg by the plugin collection path,
so its DEFAULT ``token_saver`` is the only one a deployment ever gets.
That default writes through ``mureo.auth.save_amazon_access_token``, which
since #512 resolves to the runtime-resolved credentials file — in a
multi-tenant deployment the operator-shared base, whose reads strip the
per-client token fields. Runtime-refreshed tokens therefore round-tripped
into a file nobody reads back (no leak, but no reuse either).

The active ``RuntimeContext``'s ``SecretStore`` may now offer its own
``amazon_token_saver`` capability; the default saver consults it at persist
time and writes to the ACTIVE tenant's store instead. Same store-capability
family as ``runtime_credentials_path`` (#196),
``runtime_multi_account_auth`` (#198), and
``runtime_ui_plugin_credential_fields`` (#207): entry-point gated,
``getattr`` off the store, ``None`` when absent or unusable.

An explicitly injected ``token_saver`` always wins — single-tenant OSS and
every existing test path are byte-identical.

Entry-point stubs mirror ``tests/test_auth_amazon.py`` /
``tests/test_plugin_credentials_field_scope.py``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import TYPE_CHECKING, Any

import pytest

from mureo.amazon_ads.bridge import AmazonAdsBridge, AmazonBridgeError
from mureo.amazon_ads.lwa import LwaTokens
from mureo.auth import AmazonAdsCredentials
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
    runtime_amazon_token_saver,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


# ---------------------------------------------------------------------------
# Entry-point + store stubs
# ---------------------------------------------------------------------------


class _FakeEP:
    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _patch_eps(monkeypatch: pytest.MonkeyPatch, eps: list[_FakeEP]) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "mureo.runtime_context_factory"
        return eps

    monkeypatch.setattr("mureo.core.runtime_context.entry_points", fake_entry_points)


def _store(**attrs: Any) -> Any:
    class _S:
        def load(self, key: str) -> dict[str, Any]:
            return {}

        def save(self, key: str, value: dict[str, Any]) -> None:
            return None

        def delete(self, key: str) -> None:
            return None

    s = _S()
    for k, v in attrs.items():
        setattr(s, k, v)
    return s


def _ctx_with(store: Any) -> Any:
    return dataclasses.replace(default_runtime_context(), secret_store=store)


def _install_store(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    """Register a single factory entry point serving ``store``."""
    ctx = _ctx_with(store)
    _patch_eps(monkeypatch, [_FakeEP("tenant", lambda: ctx)])


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


# ---------------------------------------------------------------------------
# runtime_amazon_token_saver resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolver_none_when_no_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standalone OSS never consults the default store."""
    _patch_eps(monkeypatch, [])
    assert runtime_amazon_token_saver() is None


@pytest.mark.unit
def test_resolver_returns_the_declared_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str | None]] = []

    def saver(access: str, refresh: str | None) -> None:
        seen.append((access, refresh))

    _install_store(monkeypatch, _store(amazon_token_saver=saver))

    resolved = runtime_amazon_token_saver()
    assert resolved is not None
    resolved("Atza|NEW", "Atzr|NEW")
    assert seen == [("Atza|NEW", "Atzr|NEW")]


@pytest.mark.unit
def test_resolver_none_when_attribute_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A store that does not opt in keeps the legacy writer."""
    _install_store(monkeypatch, _store())
    assert runtime_amazon_token_saver() is None


@pytest.mark.unit
@pytest.mark.parametrize("declared", ["not-a-callable", 7, {"a": 1}, None])
def test_resolver_none_when_attribute_not_callable(
    monkeypatch: pytest.MonkeyPatch, declared: object
) -> None:
    """A mis-typed declaration must not be called; it collapses to the
    legacy writer rather than crashing the refresh path."""
    _install_store(monkeypatch, _store(amazon_token_saver=declared))
    assert runtime_amazon_token_saver() is None


# ---------------------------------------------------------------------------
# Bridge — the DEFAULT saver honors the capability
# ---------------------------------------------------------------------------

_MANIFEST = {
    "generated_at": "2026-05-18T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [],
}


def _connect_seq(attempts: list[str], *, fail_first: int) -> Any:
    """Connect factory whose first ``fail_first`` calls raise (a 401-ish
    failure), so the bridge takes its refresh-persist-retry path."""

    class _Sess:
        def __init__(self, n: int) -> None:
            self._n = n

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            if self._n <= fail_first:
                raise RuntimeError("401 token expired")
            return type("R", (), {"content": [f"ok#{self._n}"]})()

    class _CM:
        def __init__(self, url: str, headers: dict[str, str]) -> None:
            attempts.append(headers["Authorization"])
            self._n = len(attempts)

        async def __aenter__(self) -> _Sess:
            return _Sess(self._n)

        async def __aexit__(self, *e: Any) -> bool:
            return False

    return lambda url, headers: _CM(url, headers)


def _creds() -> AmazonAdsCredentials:
    return AmazonAdsCredentials(
        client_id="cid",
        access_token="Atza|OLD",
        refresh_token="Atzr|R",
        client_secret="sec",
    )


def _bridge(tmp_path: Path, connect: Any, **kw: Any) -> AmazonAdsBridge:
    mp = tmp_path / "amazon_tools.json"
    mp.write_text(json.dumps(_MANIFEST))
    return AmazonAdsBridge(
        manifest_path=mp,
        creds_loader=_creds,
        connect=connect,
        refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R2", 3600),
        token_saver=kw.get("token_saver"),
    )


def _stub_legacy_saver(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    """Replace ``save_amazon_access_token`` as the default saver sees it, so a
    fallback is observable and the real ``~/.mureo`` is never touched.

    That default lives in ``session_auth`` — the credential seam the
    single-call path and the #520 session batch share — not in ``bridge``."""
    legacy: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "mureo.amazon_ads.session_auth.save_amazon_access_token",
        lambda access, refresh=None, **kw: legacy.append((access, refresh)),
    )
    return legacy


@pytest.mark.unit
class TestBridgeDefaultTokenSaverFollowsRuntimeContext:
    def test_capability_receives_the_refreshed_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The host-bound saver persists the refresh; the operator-shared
        legacy writer is not touched."""
        legacy = _stub_legacy_saver(monkeypatch)
        tenant: list[tuple[str, str | None]] = []
        _install_store(
            monkeypatch,
            _store(amazon_token_saver=lambda a, r: tenant.append((a, r))),
        )

        attempts: list[str] = []
        b = _bridge(tmp_path, _connect_seq(attempts, fail_first=1))
        out = asyncio.run(b.handle_mcp_tool("x", {}))

        assert out == ["ok#2"]
        assert tenant == [("Atza|NEW", "Atzr|R2")]
        assert legacy == []
        assert attempts[1] == "Bearer Atza|NEW"  # retry used the refreshed token

    def test_without_the_capability_the_legacy_writer_is_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No factory registered → byte-identical to today."""
        legacy = _stub_legacy_saver(monkeypatch)
        _patch_eps(monkeypatch, [])

        attempts: list[str] = []
        b = _bridge(tmp_path, _connect_seq(attempts, fail_first=1))
        out = asyncio.run(b.handle_mcp_tool("x", {}))

        assert out == ["ok#2"]
        assert legacy == [("Atza|NEW", "Atzr|R2")]

    def test_a_store_without_the_attribute_uses_the_legacy_writer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A registered backend that does not opt in keeps #512's behavior."""
        legacy = _stub_legacy_saver(monkeypatch)
        _install_store(monkeypatch, _store())

        attempts: list[str] = []
        b = _bridge(tmp_path, _connect_seq(attempts, fail_first=1))
        asyncio.run(b.handle_mcp_tool("x", {}))

        assert legacy == [("Atza|NEW", "Atzr|R2")]

    def test_injected_token_saver_wins_over_the_capability(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit constructor argument is never second-guessed."""
        legacy = _stub_legacy_saver(monkeypatch)
        tenant: list[tuple[str, str | None]] = []
        _install_store(
            monkeypatch,
            _store(amazon_token_saver=lambda a, r: tenant.append((a, r))),
        )

        injected: list[tuple[str, str | None]] = []
        attempts: list[str] = []
        b = _bridge(
            tmp_path,
            _connect_seq(attempts, fail_first=1),
            token_saver=lambda a, r: injected.append((a, r)),
        )
        asyncio.run(b.handle_mcp_tool("x", {}))

        assert injected == [("Atza|NEW", "Atzr|R2")]
        assert tenant == []
        assert legacy == []

    def test_a_failing_capability_surfaces_the_same_bridge_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A host saver raising ``OSError`` maps to the same actionable,
        scrubbed ``AmazonBridgeError`` a failed local save produces."""
        _stub_legacy_saver(monkeypatch)

        def saver(access: str, refresh: str | None) -> None:
            raise OSError(
                "tenant store write failed: payload was "
                "Atza|LEAKED-access-token-abc123"
            )

        _install_store(monkeypatch, _store(amazon_token_saver=saver))

        attempts: list[str] = []
        b = _bridge(tmp_path, _connect_seq(attempts, fail_first=1))
        with pytest.raises(AmazonBridgeError) as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))

        message = str(ei.value)
        assert "could not be saved" in message
        assert "LEAKED" not in message
        assert "Atza|" not in message
        assert isinstance(ei.value.__cause__, RuntimeError)  # original chained
