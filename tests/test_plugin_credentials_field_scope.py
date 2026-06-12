"""#207 — a multi-account backend can scope which plugin credential
fields the dashboard renders, via an optional ``SecretStore`` capability.

Standalone OSS (no factory / default stores) is unchanged: every declared
``AccountCredentialField`` renders, account ids included. An agency-style
backend advertises ``ui_plugin_credential_fields`` (provider → allowed
field keys); the dashboard then shows only the listed keys for those
providers (e.g. operator-shared auth only, dropping per-client account
ids that belong on the agency's own per-client form). Providers absent
from the mapping keep all fields; a mis-typed (non-Mapping) declaration
is ignored so it cannot silently hide fields.

Mirrors the #196 / #198 store-capability + home-gate pattern: the
capability is resolved behind a ``home is None`` gate in the handler, so
these tests and every existing plugin-credentials test stay isolated from
whatever ``mureo.runtime_context_factory`` is installed in the dev venv.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import urllib.request
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from mureo.core.providers import AccountCredentialField
from mureo.core.providers.registry import ProviderEntry, default_registry
from mureo.core.runtime_context import (
    default_runtime_context,
    reset_runtime_context,
    runtime_ui_plugin_credential_fields,
)
from mureo.web.plugin_credentials import list_plugin_credential_fields
from mureo.web.server import ConfigureWizard

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse
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


@pytest.fixture(autouse=True)
def _reset_ctx() -> Iterator[None]:
    reset_runtime_context()
    yield
    reset_runtime_context()


def _ctx_with(store: Any) -> Any:
    return dataclasses.replace(default_runtime_context(), secret_store=store)


# ---------------------------------------------------------------------------
# runtime_ui_plugin_credential_fields resolver
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolver_none_when_no_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_eps(monkeypatch, [])
    assert runtime_ui_plugin_credential_fields() is None


@pytest.mark.unit
def test_resolver_returns_normalized_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(
        ui_plugin_credential_fields={
            "yahoo_ads": {"client_id", "client_secret"},
            "line_ads": ["access_key", "secret_key"],
        }
    )
    _patch_eps(monkeypatch, [_FakeEP("agency", lambda: _ctx_with(store))])
    result = runtime_ui_plugin_credential_fields()
    assert result == {
        "yahoo_ads": frozenset({"client_id", "client_secret"}),
        "line_ads": frozenset({"access_key", "secret_key"}),
    }


@pytest.mark.unit
def test_resolver_none_when_store_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_eps(monkeypatch, [_FakeEP("x", default_runtime_context)])
    assert runtime_ui_plugin_credential_fields() is None


@pytest.mark.unit
def test_resolver_none_when_not_a_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mis-typed declaration (list, not Mapping) must be ignored — it
    must NOT silently hide fields."""
    store = _store(ui_plugin_credential_fields=["yahoo_ads"])
    _patch_eps(monkeypatch, [_FakeEP("bad", lambda: _ctx_with(store))])
    assert runtime_ui_plugin_credential_fields() is None


# ---------------------------------------------------------------------------
# list_plugin_credential_fields(field_scope=...)
# ---------------------------------------------------------------------------


def _provider(name: str, *keys: str) -> ProviderEntry:
    class _P:
        pass

    _P.name = name  # type: ignore[attr-defined]
    _P.display_name = name  # type: ignore[attr-defined]
    _P.capabilities = frozenset()  # type: ignore[attr-defined]
    _P.account_credential_fields = tuple(  # type: ignore[attr-defined]
        AccountCredentialField(key=k, display_name=k) for k in keys
    )
    return ProviderEntry(
        name=name,
        display_name=name,
        capabilities=frozenset(),
        provider_class=_P,
        source_distribution=None,
    )


@pytest.fixture
def two_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        default_registry,
        "_entries",
        {
            "yahoo_ads": _provider(
                "yahoo_ads", "client_id", "client_secret", "account_id"
            ),
            "demo_ads": _provider("demo_ads", "api_key", "account_id"),
        },
    )


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["provider_name"]: r for r in rows}


@pytest.mark.unit
def test_list_unchanged_when_scope_none(two_providers: None) -> None:
    by_name = _by_name(list_plugin_credential_fields(field_scope=None))
    assert [f["key"] for f in by_name["yahoo_ads"]["fields"]] == [
        "client_id",
        "client_secret",
        "account_id",
    ]
    assert [f["key"] for f in by_name["demo_ads"]["fields"]] == [
        "api_key",
        "account_id",
    ]


@pytest.mark.unit
def test_list_filters_listed_provider_keeps_absent(two_providers: None) -> None:
    scope = {"yahoo_ads": frozenset({"client_id", "client_secret"})}
    by_name = _by_name(list_plugin_credential_fields(field_scope=scope))
    # yahoo_ads scoped to auth only — account_id dropped.
    assert [f["key"] for f in by_name["yahoo_ads"]["fields"]] == [
        "client_id",
        "client_secret",
    ]
    # demo_ads absent from the mapping → all fields kept.
    assert [f["key"] for f in by_name["demo_ads"]["fields"]] == [
        "api_key",
        "account_id",
    ]


@pytest.mark.unit
def test_list_drops_provider_when_no_keys_remain(two_providers: None) -> None:
    scope = {"yahoo_ads": frozenset({"does_not_exist"})}
    by_name = _by_name(list_plugin_credential_fields(field_scope=scope))
    assert "yahoo_ads" not in by_name
    assert "demo_ads" in by_name


# ---------------------------------------------------------------------------
# Handler home-gate (#195/#198 pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def home_wizard(tmp_path: Path, two_providers: None) -> Iterator[ConfigureWizard]:
    home = tmp_path / "home"
    for sub in ("", ".claude", ".claude/commands", ".mureo"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    wiz = ConfigureWizard(home=home)
    thread = threading.Thread(target=wiz.serve, daemon=True)
    thread.start()
    wiz.wait_until_ready(timeout=5.0)
    try:
        yield wiz
    finally:
        wiz.shutdown()
        thread.join(timeout=2.0)


def _get(wiz: ConfigureWizard, path: str) -> HTTPResponse:
    return urllib.request.urlopen(f"http://127.0.0.1:{wiz.port}{path}", timeout=2.0)


@pytest.mark.unit
def test_handler_suppresses_scope_when_home_injected(
    home_wizard: ConfigureWizard,
) -> None:
    """SAFETY/isolation (#198 pattern): a home-injected wizard must NOT
    apply a process-global factory's field scope — the dashboard keeps
    every field. Guards the dev-venv agency factory from leaking into a
    sandboxed wizard."""
    scope = {"yahoo_ads": frozenset({"client_id"})}
    with patch(
        "mureo.web.handlers.runtime_ui_plugin_credential_fields", return_value=scope
    ):
        body = json.loads(_get(home_wizard, "/api/credentials/plugins").read())
    by_name = {p["provider_name"]: p for p in body["plugins"]}
    # Scope ignored under injected home → account_id still rendered.
    assert [f["key"] for f in by_name["yahoo_ads"]["fields"]] == [
        "client_id",
        "client_secret",
        "account_id",
    ]
