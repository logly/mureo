"""Amazon bridge provider (TDD, #113 Phase 1, task #24).

``mcp_tools()`` MUST be pure / credential-free / network-free and
NEVER raise (it runs at mureo server start) — it just reads the
manifest. ``handle_mcp_tool()`` lazily opens an authenticated MCP
session and forwards. The session is dependency-injected.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mureo.amazon_ads.bridge import AmazonAdsBridge, AmazonBridgeError
from mureo.auth import AmazonAdsCredentials

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
        },
        {
            "name": "campaign_management-create_campaign",
            "description": "Create an SP campaign.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ],
}


class _FakeSession:
    def __init__(self, calls: list, content) -> None:
        self._calls = calls
        self._content = content

    async def initialize(self) -> None:
        self._calls.append(("initialize",))

    async def call_tool(self, name, arguments):
        self._calls.append(("call_tool", name, arguments))
        return type("R", (), {"content": self._content})()


def _connect(calls, captured, content):
    class _CM:
        def __init__(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers

        async def __aenter__(self):
            return _FakeSession(calls, content)

        async def __aexit__(self, *e):
            return False

    return lambda url, headers: _CM(url, headers)


def _bridge(tmp_path: Path, *, manifest=_MANIFEST, creds=True, **kw):
    mp = tmp_path / "amazon_tools.json"
    if manifest is not None:
        mp.write_text(json.dumps(manifest))
    c = (
        AmazonAdsCredentials(client_id="cid", access_token="Atza|SECRET")
        if creds
        else None
    )
    return AmazonAdsBridge(
        manifest_path=mp, creds_loader=lambda: c, connect=kw.get("connect")
    )


@pytest.mark.unit
class TestMcpTools:
    def test_reads_manifest_into_tools(self, tmp_path: Path) -> None:
        tools = _bridge(tmp_path).mcp_tools()
        names = sorted(t.name for t in tools)
        assert names == [
            "account_management-query_advertiser_account",
            "campaign_management-create_campaign",
        ]
        assert tools[0].inputSchema == {"type": "object", "properties": {}}

    def test_missing_manifest_returns_empty_never_raises(
        self, tmp_path: Path
    ) -> None:
        b = _bridge(tmp_path, manifest=None)
        assert b.mcp_tools() == ()

    def test_malformed_manifest_returns_empty_never_raises(
        self, tmp_path: Path
    ) -> None:
        mp = tmp_path / "amazon_tools.json"
        mp.write_text("{ not json")
        b = AmazonAdsBridge(manifest_path=mp, creds_loader=lambda: None)
        assert b.mcp_tools() == ()

    def test_mcp_tools_is_credential_free(self, tmp_path: Path) -> None:
        # creds_loader raising must NOT break collection-time mcp_tools()
        def _boom():
            raise RuntimeError("must not be called at collection time")

        mp = tmp_path / "amazon_tools.json"
        mp.write_text(json.dumps(_MANIFEST))
        b = AmazonAdsBridge(manifest_path=mp, creds_loader=_boom)
        assert len(b.mcp_tools()) == 2  # no creds access


@pytest.mark.unit
class TestHandleMcpTool:
    def test_forwards_and_returns_content(self, tmp_path: Path) -> None:
        calls: list = []
        captured: dict = {}
        b = _bridge(
            tmp_path, connect=_connect(calls, captured, ["RESULT"])
        )
        out = asyncio.run(
            b.handle_mcp_tool(
                "campaign_management-create_campaign", {"name": "X"}
            )
        )
        assert out == ["RESULT"]
        assert calls == [
            ("initialize",),
            ("call_tool", "campaign_management-create_campaign", {"name": "X"}),
        ]
        assert captured["url"] == "https://advertising-ai.amazon.com/mcp"
        assert captured["headers"]["Authorization"] == "Bearer Atza|SECRET"

    def test_no_credentials_raises_clear_error(self, tmp_path: Path) -> None:
        b = _bridge(tmp_path, creds=False, connect=_connect([], {}, []))
        with pytest.raises(AmazonBridgeError, match="credential"):
            asyncio.run(b.handle_mcp_tool("x", {}))

    def test_satisfies_mcp_tool_provider_shape(self, tmp_path: Path) -> None:
        b = _bridge(tmp_path)
        assert callable(b.mcp_tools)
        assert asyncio.iscoroutinefunction(b.handle_mcp_tool)
