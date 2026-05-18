"""Amazon MCP tool-manifest generator (TDD, #113 Phase 1, task #23).

Credentialed/network in production, but the MCP client session is
dependency-injected so this is a fast, hermetic unit test. The manifest
is what the bridge's pure ``mcp_tools()`` reads at server start.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.types import Tool

from mureo.amazon_ads.manifest import generate_manifest, manifest_path
from mureo.auth import AmazonAdsCredentials


class _FakeSession:
    def __init__(self, tools: list[Tool], calls: list[str]) -> None:
        self._tools = tools
        self._calls = calls

    async def initialize(self) -> None:
        self._calls.append("initialize")

    async def list_tools(self):
        self._calls.append("list_tools")
        return type("R", (), {"tools": self._tools})()


def _fake_connect(tools, calls, captured):
    class _CM:
        def __init__(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers

        async def __aenter__(self):
            return _FakeSession(tools, calls)

        async def __aexit__(self, *exc):
            return False

    return _CM


def _creds(**kw) -> AmazonAdsCredentials:
    base = {"client_id": "cid", "access_token": "Atza|SECRET"}
    base.update(kw)
    return AmazonAdsCredentials(**base)


@pytest.mark.unit
class TestGenerateManifest:
    def _tools(self) -> list[Tool]:
        return [
            Tool(
                name="account_management-query_advertiser_account",
                description="List advertiser accounts.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="campaign_management-create_campaign",
                description="Create an SP campaign.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    def test_writes_manifest_with_expected_shape(self, tmp_path: Path) -> None:
        out = tmp_path / "amazon_tools.json"
        calls: list[str] = []
        captured: dict = {}
        creds = _creds(region="eu")
        path = asyncio.run(
            generate_manifest(
                creds,
                connect=_fake_connect(self._tools(), calls, captured),
                out_path=out,
            )
        )
        assert path == out
        doc = json.loads(out.read_text())
        assert doc["region"] == "eu"
        assert doc["endpoint"] == "https://advertising-ai-eu.amazon.com/mcp"
        assert doc["account_mode"] == "dynamic"
        assert "generated_at" in doc
        names = [t["name"] for t in doc["tools"]]
        assert names == [
            "account_management-query_advertiser_account",
            "campaign_management-create_campaign",
        ]
        assert doc["tools"][0]["inputSchema"] == {
            "type": "object",
            "properties": {},
        }

    def test_initialize_called_before_list_tools(self, tmp_path: Path) -> None:
        calls: list[str] = []
        asyncio.run(
            generate_manifest(
                _creds(),
                connect=_fake_connect(self._tools(), calls, {}),
                out_path=tmp_path / "m.json",
            )
        )
        assert calls == ["initialize", "list_tools"]

    def test_uses_region_endpoint_and_auth_headers(self, tmp_path: Path) -> None:
        captured: dict = {}
        asyncio.run(
            generate_manifest(
                _creds(region="fe"),
                connect=_fake_connect(self._tools(), [], captured),
                out_path=tmp_path / "m.json",
            )
        )
        assert captured["url"] == "https://advertising-ai-fe.amazon.com/mcp"
        assert captured["headers"]["Authorization"] == "Bearer Atza|SECRET"
        assert captured["headers"]["Amazon-Ads-ClientId"] == "cid"

    def test_manifest_does_not_persist_secrets(self, tmp_path: Path) -> None:
        out = tmp_path / "amazon_tools.json"
        asyncio.run(
            generate_manifest(
                _creds(),
                connect=_fake_connect(self._tools(), [], {}),
                out_path=out,
            )
        )
        blob = out.read_text()
        assert "SECRET" not in blob
        assert "cid" not in blob

    def test_connection_failure_propagates(self, tmp_path: Path) -> None:
        class _Boom:
            def __init__(self, *a, **k): ...

            async def __aenter__(self):
                raise RuntimeError("amazon unreachable")

            async def __aexit__(self, *exc):
                return False

        with pytest.raises(RuntimeError, match="amazon unreachable"):
            asyncio.run(
                generate_manifest(
                    _creds(),
                    connect=lambda url, headers: _Boom(),
                    out_path=tmp_path / "m.json",
                )
            )
        assert not (tmp_path / "m.json").exists()  # no partial file

    def test_manifest_path_default_under_mureo_home(self) -> None:
        p = manifest_path()
        assert p.name == "amazon_tools.json"
        assert p.parent.name == ".mureo"

    def test_written_file_is_0600(self, tmp_path: Path) -> None:
        import stat

        out = tmp_path / "amazon_tools.json"
        asyncio.run(
            generate_manifest(
                _creds(),
                connect=_fake_connect(self._tools(), [], {}),
                out_path=out,
            )
        )
        mode = stat.S_IMODE(out.stat().st_mode)
        assert mode == 0o600
