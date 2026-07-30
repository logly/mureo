"""Amazon bridge ↔ server #114 safety-layer wiring (TDD, #113 task #25).

The internal Amazon bridge must ride the SAME collect/dispatch path as
entry-point plugins: tools exposed, audited, throttled, and mutating
calls promoted to STATE.json action_log — with NO change to dispatch.
Manifest absent ⇒ no Amazon tools (regression-safe).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

_MANIFEST = {
    "generated_at": "2026-05-18T00:00:00+00:00",
    "region": "na",
    "endpoint": "https://advertising-ai.amazon.com/mcp",
    "account_mode": "dynamic",
    "tools": [
        {
            "name": "account_management-query_advertiser_account",
            "description": "List advertiser accounts.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "campaign_management-create_campaign",
            "description": "Create an SP campaign.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
}


class _FakeSession:
    async def initialize(self) -> None: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        from mcp.types import TextContent

        return type(
            "R", (), {"content": [TextContent(type="text", text=f"ok:{name}")]}
        )()


def _fake_connect(url, headers):
    class _CM:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *e):
            return False

    return _CM()


def _no_thirdparty(**_kw):
    return ()


def _reload_server(monkeypatch, tmp_path: Path, *, with_manifest: bool):
    from mureo.amazon_ads import bridge as bmod
    from mureo.auth import AmazonAdsCredentials
    from mureo.mcp import plugin_audit

    mp = tmp_path / "amazon_tools.json"
    if with_manifest:
        mp.write_text(json.dumps(_MANIFEST))
    monkeypatch.setattr(
        "mureo.core.providers.registry.discover_providers", _no_thirdparty
    )
    monkeypatch.setattr(bmod, "manifest_path", lambda: mp)
    monkeypatch.setattr(
        bmod,
        "load_amazon_ads_credentials",
        lambda *a, **k: AmazonAdsCredentials(
            client_id="cid", access_token="Atza|SECRET"
        ),
    )
    monkeypatch.setattr(bmod, "_default_connect", _fake_connect)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    from mureo.mcp import server as mod

    return importlib.reload(mod)


def _seed_state(d: Path) -> None:
    from mureo.context.models import StateDocument
    from mureo.context.state import write_state_file

    write_state_file(d / "STATE.json", StateDocument())


@pytest.mark.unit
class TestAmazonServerWiring:
    def test_amazon_tools_collected_and_dispatched_to_bridge(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.amazon_ads.bridge import AmazonAdsBridge

        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            assert "campaign_management-create_campaign" in mod._PLUGIN_NAMES
            assert "account_management-query_advertiser_account" in mod._PLUGIN_NAMES
            disp = mod._PLUGIN_DISPATCH["campaign_management-create_campaign"]
            assert isinstance(disp, AmazonAdsBridge)
        finally:
            importlib.reload(mod)

    async def test_mutating_amazon_call_audited_and_promoted(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            out = await mod.handle_call_tool(
                "campaign_management-create_campaign", {"name": "X"}
            )
            assert out  # forwarded content returned
            audit = [
                json.loads(x)
                for x in (tmp_path / "audit.jsonl").read_text().splitlines()
            ]
            assert audit and audit[-1]["source"] == "mureo-amazon-ads-bridge"
            doc = read_state_file(tmp_path / "STATE.json")
            assert len(doc.action_log) == 1
            e = doc.action_log[0]
            assert e.action == "campaign_management-create_campaign"
            assert e.platform == "plugin:mureo-amazon-ads-bridge"
            assert e.observation_due is not None  # Phase 4 window
        finally:
            importlib.reload(mod)

    async def test_readonly_amazon_call_not_promoted(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.context.state import read_state_file

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            await mod.handle_call_tool(
                "account_management-query_advertiser_account", {}
            )
            doc = read_state_file(tmp_path / "STATE.json")
            assert doc.action_log == ()  # read-only ⇒ jsonl audit only
            assert (tmp_path / "audit.jsonl").exists()
        finally:
            importlib.reload(mod)

    def test_no_manifest_means_no_amazon_tools_regression_safe(
        self, monkeypatch, tmp_path
    ) -> None:
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=False)
        try:
            amazon = [
                n
                for n in mod._PLUGIN_NAMES
                if "campaign_management" in n or "account_management" in n
            ]
            assert amazon == []
        finally:
            importlib.reload(mod)


@pytest.mark.unit
class TestAmazonRegistryRegistration:
    """#121 — the bridge is registered ONCE, and only once.

    The synthetic ``ProviderEntry`` is now single-sourced in
    ``mureo.amazon_ads.provider`` and registered into
    ``default_registry`` (so the configure UI can see it) *and* fed to
    ``collect_plugin_tools`` (so the MCP server exposes its tools).
    Both paths must not double-count.
    """

    def test_startup_registers_amazon_in_the_default_registry(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            assert "amazon_ads" in default_registry
            assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge
        finally:
            importlib.reload(mod)

    def test_discover_yields_the_amazon_entry_exactly_once(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            names = [e.name for e in mod._discover_with_amazon()]
            assert names.count("amazon_ads") == 1
            # Idempotent: calling again (as a re-discovery would) does not
            # duplicate the entry either.
            names = [e.name for e in mod._discover_with_amazon()]
            assert names.count("amazon_ads") == 1
        finally:
            importlib.reload(mod)

    def test_each_amazon_tool_is_collected_exactly_once(
        self, monkeypatch, tmp_path
    ) -> None:
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=True)
        try:
            names = [t.name for t in mod._PLUGIN_TOOLS]
            assert names.count("campaign_management-create_campaign") == 1
            assert names.count("account_management-query_advertiser_account") == 1
            assert len(mod._ALL_TOOLS) == len({t.name for t in mod._ALL_TOOLS})
        finally:
            importlib.reload(mod)

    def test_registration_contributes_zero_tools_without_a_manifest(
        self, monkeypatch, tmp_path
    ) -> None:
        """Registry presence must not create tools out of thin air."""
        from mureo.core.providers import default_registry

        monkeypatch.setattr(default_registry, "_entries", {})
        mod = _reload_server(monkeypatch, tmp_path, with_manifest=False)
        try:
            assert "amazon_ads" in default_registry  # UI can still configure it
            assert mod._PLUGIN_TOOLS == []
        finally:
            importlib.reload(mod)


@pytest.mark.unit
class TestBuiltInShadowingPolicy:
    """#121 review follow-up — the built-in wins a name clash, everywhere.

    ``Registry`` is first-wins, so *when* the in-tree bridge registers
    decides whether a third-party distribution publishing a
    ``mureo.providers`` entry point named ``amazon_ads`` can take the
    slot. Both in-tree startup paths must therefore register the
    built-in BEFORE running entry-point discovery. These tests pin that
    property from the observable side (which entry comes back), not by
    asserting call order.
    """

    def _foreign_entry(self):
        from mureo.core.providers.registry import ProviderEntry

        class _Squatter:
            name = "amazon_ads"
            display_name = "Amazon Ads (third party)"
            capabilities = frozenset()

        return ProviderEntry(
            name="amazon_ads",
            display_name="Amazon Ads (third party)",
            capabilities=frozenset(),
            provider_class=_Squatter,
            source_distribution="squatter-plugin",
        )

    def _discover_publishing_foreign_amazon(self, foreign):
        """Fake entry-point discovery that ships an ``amazon_ads`` provider.

        Mirrors ``Registry._load_entry_point``: it attempts registration
        and returns ONLY the entries actually inserted, so an entry
        dropped by first-wins is absent from the result — exactly what
        the real discovery pass does.
        """
        import warnings

        from mureo.core.providers import default_registry
        from mureo.core.providers.registry import RegistryWarning

        def _discover(*_a, **_kw):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RegistryWarning)
                default_registry.register(foreign)
            stored = default_registry.get("amazon_ads")
            return (foreign,) if stored is foreign else ()

        return _discover

    def test_builtin_beats_a_same_named_entry_point_plugin(
        self, monkeypatch, tmp_path
    ) -> None:
        """Registering first means the entry-point squatter is dropped."""
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.amazon_ads.provider import AMAZON_SOURCE_DISTRIBUTION
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        monkeypatch.setattr(default_registry, "_entries", {})
        foreign = self._foreign_entry()
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers",
            self._discover_publishing_foreign_amazon(foreign),
        )

        entries = mod._discover_with_amazon()

        amazon = [e for e in entries if e.name == "amazon_ads"]
        assert len(amazon) == 1  # still exactly once
        assert amazon[0].source_distribution == AMAZON_SOURCE_DISTRIBUTION
        assert amazon[0].provider_class is AmazonAdsBridge
        # ...and the registry agrees, so the configure UI renders the
        # built-in's credential fields rather than the squatter's.
        assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge

    def test_a_genuinely_pre_registered_foreign_entry_still_wins(
        self, monkeypatch, tmp_path
    ) -> None:
        """First-wins is not overridden — it is only made deterministic.

        A foreign ``amazon_ads`` already in the registry BEFORE the
        startup path runs keeps the slot, matching the registry's
        documented shadowing contract.
        """
        from mureo.core.providers import default_registry
        from mureo.mcp import server as mod

        foreign = self._foreign_entry()
        monkeypatch.setattr(default_registry, "_entries", {"amazon_ads": foreign})
        monkeypatch.setattr(
            "mureo.core.providers.registry.discover_providers", _no_thirdparty
        )

        entries = mod._discover_with_amazon()

        amazon = [e for e in entries if e.name == "amazon_ads"]
        assert len(amazon) == 1
        assert amazon[0] is foreign
        assert default_registry.get("amazon_ads") is foreign

    def test_configure_path_also_registers_before_discovery(self, monkeypatch) -> None:
        """The configure process resolves the name identically (#121).

        Same scenario as the MCP test above, through
        ``ConfigureWizard._discover_providers_safely`` — the two
        processes must not disagree about who owns ``amazon_ads``.
        """
        from mureo.amazon_ads.bridge import AmazonAdsBridge
        from mureo.core.providers import default_registry
        from mureo.web.server import ConfigureWizard

        monkeypatch.setattr(default_registry, "_entries", {})
        foreign = self._foreign_entry()
        monkeypatch.setattr(
            "mureo.web.server.discover_providers",
            self._discover_publishing_foreign_amazon(foreign),
        )

        ConfigureWizard._discover_providers_safely()

        assert default_registry.get("amazon_ads").provider_class is AmazonAdsBridge
