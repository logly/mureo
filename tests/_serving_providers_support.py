"""Fakes and expected strings shared by the served-platform routing tests.

The example provider ``meta_ads_acme`` serves Meta Ads under the
``meta_ads_acme_`` prefix; the Google Ads and Search Console rows follow the
same naming.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent, Tool

from mureo.core.providers import AccountCredentialField
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry
from mureo.core.runtime_context import reset_runtime_context
from mureo.mcp import _plugin_tables
from mureo.mcp import serving_providers as sp
from tests._runtime_context_fakes import install_runtime_store

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

PROVIDER = "meta_ads_acme"
PREFIX = "meta_ads_acme_"
SECRET = "tok-SECRET-VALUE-0123456789"
FIELDS = (
    AccountCredentialField(
        key="access_token", display_name="Access token", required=True, secret=True
    ),
    AccountCredentialField(key="account_id", display_name="Ad account", required=True),
    AccountCredentialField(key="note", display_name="Note"),
)
CONFIGURED = {"access_token": SECRET, "account_id": "act_999"}
ACME = sp.ServingProvider(
    provider=PROVIDER,
    tool_prefix=PREFIX,
    required_keys=("access_token", "account_id"),
)
GOOGLE_ACME = sp.ServingProvider(
    provider="google_ads_acme",
    tool_prefix="google_ads_acme_",
    required_keys=("refresh_token",),
)
SC_ACME = sp.ServingProvider(
    provider="search_console_acme",
    tool_prefix="search_console_acme_",
    required_keys=("refresh_token",),
)
ALL_CONFIGURED = {
    PROVIDER: CONFIGURED,
    "google_ads_acme": {"refresh_token": SECRET},
    "search_console_acme": {"refresh_token": SECRET},
}

HEADING = (
    "Platform tool families — which tools reach this workspace's account. "
    "A plugin can serve a built-in platform under its own tool prefix: same "
    "operations, separate credentials."
)
LINE_NONE = (
    "- Meta Ads: use the meta_ads_acme_* tools. The built-in meta_ads_* tools "
    "have no account configured in this workspace and refuse."
)
LINE_BOTH = (
    "- Meta Ads: accounts are configured under both the built-in meta_ads_* "
    "tools and the meta_ads_acme_* tools. Use each family only for the account "
    "configured under it, and never read or change one account through both."
)
LINE_UNKNOWN = (
    "- Meta Ads: this workspace's account is configured under the "
    "meta_ads_acme_* tools; use them. The built-in meta_ads_* tools work only "
    "if the built-in connection is set up too."
)
SERVED_POINTER = (
    "This workspace's Meta Ads account is configured under the meta_ads_acme_* "
    "tools — use those instead."
)
REFUSAL = (
    "The built-in meta_ads_* tools have no Meta Ads account configured in this "
    "workspace, so meta_ads_campaigns_list was not run. " + SERVED_POINTER
)


class NoneSource:
    """A credential source entry that resolves no credentials."""

    def load_credentials(self) -> None:
        return None

    def oauth_credentials(self, credentials: Any) -> Any:
        raise AssertionError("no credentials, so no OAuth")


class Store:
    """A secret store standing in for a backend's, recording every load."""

    def __init__(
        self,
        sections: dict[str, dict[str, Any]] | None = None,
        *,
        multi_account: bool = False,
        allow_lists: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._sections = sections or {}
        self.multi_account_auth = multi_account
        for attribute, value in (allow_lists or {}).items():
            setattr(self, attribute, value)
        self.loaded: list[str] = []

    def load(self, key: str) -> dict[str, Any]:
        self.loaded.append(key)
        return dict(self._sections.get(key, {}))

    def save(self, key: str, value: dict[str, Any]) -> None:
        raise AssertionError("no credential write is expected")

    def delete(self, key: str) -> None:
        raise AssertionError("no credential delete is expected")


def install_backend(monkeypatch: pytest.MonkeyPatch, store: Store) -> None:
    """Register ``store`` behind a runtime-context factory, as a backend does."""
    install_runtime_store(monkeypatch, store)
    reset_runtime_context()


def scoped_backend(
    monkeypatch: pytest.MonkeyPatch,
    allow_lists: dict[str, frozenset[str]] | None = None,
) -> Store:
    """A multi-account backend: an absent allow-list scopes to no account."""
    store = Store(ALL_CONFIGURED, multi_account=True, allow_lists=allow_lists)
    install_backend(monkeypatch, store)
    return store


def serve(monkeypatch: pytest.MonkeyPatch, platform: str, *rows: Any) -> None:
    monkeypatch.setitem(_plugin_tables._SERVING_PROVIDERS, platform, tuple(rows))


def journal_records(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def detail(result: list[Any]) -> str:
    payload = json.loads(result[0].text)
    assert payload["status"] == "auth_error"
    assert payload["auth_cause"] == "no_credentials"
    detail: str = payload["detail"]
    return detail


class AcmeProvider:
    name = PROVIDER
    serves_platform = "meta_ads"
    account_credential_fields = FIELDS
    _mureo_provider_name = PROVIDER


def owned(provider: object, *names: str) -> tuple[dict[str, str], dict[str, object]]:
    owner = getattr(provider, "name", "")
    return dict.fromkeys(names, owner), dict.fromkeys(names, provider)


def plugin_class(serves: str) -> type:
    """A plugin serving ``serves`` with one tool, recording each call."""

    class _Plugin:
        name = PROVIDER
        display_name = "Meta Ads (Acme)"
        serves_platform = serves
        account_credential_fields = FIELDS
        calls: list[str] = []

        def mcp_tools(self) -> tuple[Tool, ...]:
            return (
                Tool(
                    name="meta_ads_acme_campaigns_list",
                    description="list",
                    inputSchema={"type": "object", "properties": {}},
                ),
            )

        async def handle_mcp_tool(
            self, name: str, arguments: dict[str, Any]
        ) -> list[Any]:
            self.calls.append(name)
            return [TextContent(type="text", text="[]")]

    return _Plugin


def discover_for(plugin: type) -> Any:
    """A provider discovery returning only ``plugin``."""

    def _discover(**_kw: Any) -> tuple[ProviderEntry, ...]:
        return (
            ProviderEntry(
                name=PROVIDER,
                display_name="Meta Ads (Acme)",
                capabilities=frozenset({Capability.READ_CAMPAIGNS}),
                provider_class=plugin,
                source_distribution="acme-dist",
            ),
        )

    return _discover


GATES = {"MUREO_DISABLE_GOOGLE_ADS": None, "MUREO_DISABLE_META_ADS": None}
