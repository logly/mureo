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

    def test_missing_manifest_returns_empty_never_raises(self, tmp_path: Path) -> None:
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
        b = _bridge(tmp_path, connect=_connect(calls, captured, ["RESULT"]))
        out = asyncio.run(
            b.handle_mcp_tool("campaign_management-create_campaign", {"name": "X"})
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


@pytest.mark.unit
class TestTokenRefreshRetry:
    def _connect_seq(self, attempts: list, *, fail_first: int):
        """Connect factory: records Authorization per attempt; raises on
        the first ``fail_first`` attempts, then returns content."""

        class _Sess:
            def __init__(s, n):
                s._n = n

            async def initialize(s):
                pass

            async def call_tool(s, name, arguments):
                if s._n <= fail_first:
                    raise RuntimeError("401 token expired")
                return type("R", (), {"content": [f"ok#{s._n}"]})()

        class _CM:
            def __init__(s, url, headers):
                attempts.append(headers["Authorization"])
                s._n = len(attempts)

            async def __aenter__(s):
                return _Sess(s._n)

            async def __aexit__(s, *e):
                return False

        return lambda url, headers: _CM(url, headers)

    def _creds(self, **kw):
        from mureo.auth import AmazonAdsCredentials

        base = dict(
            client_id="cid",
            access_token="Atza|OLD",
            refresh_token="Atzr|R",
            client_secret="sec",
        )
        base.update(kw)
        return AmazonAdsCredentials(**base)

    def _mk(self, tmp_path: Path, creds, connect, **kw):
        mp = tmp_path / "amazon_tools.json"
        mp.write_text(json.dumps(_MANIFEST))
        return AmazonAdsBridge(
            manifest_path=mp,
            creds_loader=lambda: creds,
            connect=connect,
            refresher=kw.get("refresher"),
            token_saver=kw.get("token_saver"),
        )

    def test_expired_token_refreshes_persists_and_retries(self, tmp_path: Path) -> None:
        from mureo.amazon_ads.lwa import LwaTokens

        attempts: list[str] = []
        saved: list = []
        refreshed: list = []

        def refresher(c):
            refreshed.append(c.access_token)
            return LwaTokens("Atza|NEW", "Atzr|R2", 3600)

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq(attempts, fail_first=1),
            refresher=refresher,
            token_saver=lambda a, r: saved.append((a, r)),
        )
        out = asyncio.run(b.handle_mcp_tool("campaign_management-x", {}))
        assert out == ["ok#2"]
        assert refreshed == ["Atza|OLD"]
        assert saved == [("Atza|NEW", "Atzr|R2")]
        assert attempts[0] == "Bearer Atza|OLD"
        assert attempts[1] == "Bearer Atza|NEW"  # retry used refreshed token

    def test_no_refresh_creds_reraises_original(self, tmp_path: Path) -> None:
        attempts: list[str] = []
        called = []
        b = self._mk(
            tmp_path,
            self._creds(refresh_token=None, client_secret=None),
            self._connect_seq(attempts, fail_first=9),
            refresher=lambda c: called.append(1),
        )
        with pytest.raises(RuntimeError, match="401 token expired"):
            asyncio.run(b.handle_mcp_tool("x", {}))
        assert called == []  # no refresh attempted

    def test_invalid_grant_raises_bridge_error_no_token_leak(
        self, tmp_path: Path
    ) -> None:
        from mureo.amazon_ads.lwa import AmazonAuthError

        def refresher(c):
            raise AmazonAuthError("LwA refresh token is invalid_grant — re-authorize")

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=9),
            refresher=refresher,
            token_saver=lambda a, r: None,
        )
        with pytest.raises(AmazonBridgeError, match="re-authorize"):
            asyncio.run(b.handle_mcp_tool("x", {}))

    def test_unpersistable_token_raises_clear_bridge_error(
        self, tmp_path: Path
    ) -> None:
        """A malformed credentials.json must surface, not blow up raw.

        ``save_amazon_access_token`` refuses to overwrite a corrupt
        credentials.json (``ConfigWriteError``) rather than erasing the
        other providers' sections. The bridge turns that into an
        actionable ``AmazonBridgeError`` carrying the underlying reason,
        with the original call failure still chained and no token text.
        """
        from mureo.amazon_ads.lwa import LwaTokens
        from mureo.providers.config_writer import ConfigWriteError

        def saver(access: str, refresh: str | None) -> None:
            raise ConfigWriteError(
                "existing settings file at /x/credentials.json is malformed "
                "JSON (refusing to overwrite to protect user data)"
            )

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=1),
            refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R", 3600),
            token_saver=saver,
        )
        with pytest.raises(AmazonBridgeError, match="malformed") as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        assert "Atza|" not in str(ei.value)  # no token material in the message
        assert isinstance(ei.value.__cause__, RuntimeError)  # original chained

    def test_retry_after_refresh_still_failing_raises(self, tmp_path: Path) -> None:
        from mureo.amazon_ads.lwa import LwaTokens

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=9),  # every attempt fails
            refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R", 3600),
            token_saver=lambda a, r: None,
        )
        with pytest.raises(RuntimeError, match="401 token expired"):
            asyncio.run(b.handle_mcp_tool("x", {}))

    def test_non_auth_first_failure_also_refreshes_then_retry_succeeds(
        self, tmp_path: Path
    ) -> None:
        """Accepted trade-off: a non-auth first failure still triggers
        exactly one refresh; the retry then succeeds."""
        from mureo.amazon_ads.lwa import LwaTokens

        class _Sess:
            def __init__(s, n):
                s._n = n

            async def initialize(s):
                pass

            async def call_tool(s, name, arguments):
                if s._n == 1:
                    raise RuntimeError("500 internal server error")  # non-auth
                return type("R", (), {"content": [f"ok#{s._n}"]})()

        attempts: list[str] = []

        class _CM:
            def __init__(s, url, headers):
                attempts.append(headers["Authorization"])
                s._n = len(attempts)

            async def __aenter__(s):
                return _Sess(s._n)

            async def __aexit__(s, *e):
                return False

        refreshed: list = []
        b = self._mk(
            tmp_path,
            self._creds(),
            lambda url, headers: _CM(url, headers),
            refresher=lambda c: (
                refreshed.append(1) or LwaTokens("Atza|NEW", "Atzr|R", 3600)
            ),
            token_saver=lambda a, r: None,
        )
        out = asyncio.run(b.handle_mcp_tool("x", {}))
        assert out == ["ok#2"]
        assert refreshed == [1]  # wasted-but-bounded refresh happened

    def test_retry_failure_chains_original_cause(self, tmp_path: Path) -> None:
        from mureo.amazon_ads.lwa import LwaTokens

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=9),
            refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R", 3600),
            token_saver=lambda a, r: None,
        )
        with pytest.raises(RuntimeError) as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        # original first failure preserved as the explicit cause
        assert isinstance(ei.value.__cause__, RuntimeError)
        assert "401 token expired" in str(ei.value.__cause__)
