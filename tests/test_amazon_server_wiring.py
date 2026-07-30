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
