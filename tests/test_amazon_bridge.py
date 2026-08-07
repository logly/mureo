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
            def __init__(self, n):
                self._n = n

            async def initialize(self):
                pass

            async def call_tool(self, name, arguments):
                if self._n <= fail_first:
                    raise RuntimeError("401 token expired")
                return type("R", (), {"content": [f"ok#{self._n}"]})()

        class _CM:
            def __init__(self, url, headers):
                attempts.append(headers["Authorization"])
                self._n = len(attempts)

            async def __aenter__(self):
                return _Sess(self._n)

            async def __aexit__(self, *e):
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

    def test_a_save_error_carrying_token_text_is_scrubbed(self, tmp_path: Path) -> None:
        """The nested error's text is not mureo's to trust.

        ``_token_saver`` is injectable and an ``OSError`` carries whatever the
        OS put in it, so the underlying message can contain token material —
        and this string lands in an agent-visible tool result. It goes through
        the same secret-shape redactor the audit trail and the CLI use.
        """
        from mureo.amazon_ads.lwa import LwaTokens

        def saver(access: str, refresh: str | None) -> None:
            raise OSError(
                "failed writing credentials.json: payload was "
                "Atza|LEAKED-access-token-abc123"
            )

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=1),
            refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R", 3600),
            token_saver=saver,
        )
        with pytest.raises(AmazonBridgeError) as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        message = str(ei.value)
        assert "LEAKED" not in message
        assert "Atza|" not in message
        assert "***" in message
        # The actionable part survives the scrub.
        assert "could not be saved" in message

    def test_an_lwa_error_carrying_token_text_is_scrubbed(self, tmp_path: Path) -> None:
        """Same discipline on the mint/refresh failure path."""
        from mureo.amazon_ads.lwa import AmazonAuthError

        def refresher(creds):
            raise AmazonAuthError("invalid_grant for Atzr|LEAKED-refresh-xyz789")

        b = self._mk(
            tmp_path,
            self._creds(),
            self._connect_seq([], fail_first=1),
            refresher=refresher,
            token_saver=lambda a, r: None,
        )
        with pytest.raises(AmazonBridgeError) as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        message = str(ei.value)
        assert "LEAKED" not in message
        assert "Atzr|" not in message
        assert "***" in message

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
            def __init__(self, n):
                self._n = n

            async def initialize(self):
                pass

            async def call_tool(self, name, arguments):
                if self._n == 1:
                    raise RuntimeError("500 internal server error")  # non-auth
                return type("R", (), {"content": [f"ok#{self._n}"]})()

        attempts: list[str] = []

        class _CM:
            def __init__(self, url, headers):
                attempts.append(headers["Authorization"])
                self._n = len(attempts)

            async def __aenter__(self):
                return _Sess(self._n)

            async def __aexit__(self, *e):
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

    def test_a_cancelled_call_is_never_refreshed_or_re_issued(
        self, tmp_path: Path
    ) -> None:
        """A stop is not a refreshable failure — anywhere in the bridge.

        The refresh-and-retry above fires on ANY first failure, which is
        deliberate while the 401 shape is unobserved. A cancellation is not a
        failure though: re-issuing the call would send a second request — for a
        mutating tool, a second WRITE — on behalf of a caller that has already
        disconnected, and returning the retry's result would swallow the
        cancellation whole.
        """
        from mureo.amazon_ads.lwa import LwaTokens

        attempts: list[str] = []
        refreshed: list[int] = []

        class _Sess:
            def __init__(self, n):
                self._n = n

            async def initialize(self):
                pass

            async def call_tool(self, name, arguments):
                if self._n == 1:
                    await asyncio.Event().wait()  # first attempt never returns
                return type("R", (), {"content": [f"ok#{self._n}"]})()

        class _CM:
            def __init__(self, url, headers):
                attempts.append(headers["Authorization"])
                self._n = len(attempts)

            async def __aenter__(self):
                return _Sess(self._n)

            async def __aexit__(self, *e):
                return False

        b = self._mk(
            tmp_path,
            self._creds(),
            lambda url, headers: _CM(url, headers),
            refresher=lambda c: (
                refreshed.append(1) or LwaTokens("Atza|NEW", "Atzr|R", 3600)
            ),
            token_saver=lambda a, r: None,
        )

        async def _drive() -> None:
            task = asyncio.ensure_future(b.handle_mcp_tool("x", {}))
            while not attempts:  # the call is in flight
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_drive())
        assert attempts == ["Bearer Atza|OLD"]  # NOT re-issued
        assert refreshed == []  # and no LwA exchange spent on it

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


@pytest.mark.unit
class TestProactiveTokenMint:
    """#121 — an empty ``access_token`` is minted BEFORE the first call.

    The configure-UI / env-var setup path stores only the durable LwA
    material (``client_id`` + ``refresh_token`` + ``client_secret``).
    Spending a guaranteed-to-fail forwarded call just to discover that
    would be wasteful and confusing, so the bridge mints first. The
    one-refresh bound still holds: minting counts as the single LwA
    exchange, so a failure afterwards is NOT retried.
    """

    def _creds(self, **kw):
        base = dict(
            client_id="cid",
            access_token="",
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

    def test_empty_access_token_is_minted_persisted_and_used(
        self, tmp_path: Path
    ) -> None:
        from mureo.amazon_ads.lwa import LwaTokens

        calls: list = []
        captured: dict = {}
        saved: list = []
        b = self._mk(
            tmp_path,
            self._creds(),
            _connect(calls, captured, ["RESULT"]),
            refresher=lambda c: LwaTokens("Atza|MINTED", "Atzr|R2", 3600),
            token_saver=lambda a, r: saved.append((a, r)),
        )
        out = asyncio.run(b.handle_mcp_tool("campaign_management-x", {}))

        assert out == ["RESULT"]
        assert saved == [("Atza|MINTED", "Atzr|R2")]
        assert captured["headers"]["Authorization"] == "Bearer Atza|MINTED"
        # Exactly one forwarded call — no wasted first attempt.
        assert calls == [("initialize",), ("call_tool", "campaign_management-x", {})]

    def test_stored_access_token_is_used_as_is_without_minting(
        self, tmp_path: Path
    ) -> None:
        refreshed: list = []
        captured: dict = {}
        b = self._mk(
            tmp_path,
            self._creds(access_token="Atza|STORED"),
            _connect([], captured, ["RESULT"]),
            refresher=lambda c: refreshed.append(1),
            token_saver=lambda a, r: None,
        )
        asyncio.run(b.handle_mcp_tool("x", {}))
        assert refreshed == []
        assert captured["headers"]["Authorization"] == "Bearer Atza|STORED"

    def test_mint_failure_surfaces_an_actionable_error_without_token_text(
        self, tmp_path: Path
    ) -> None:
        from mureo.amazon_ads.lwa import AmazonAuthError

        def refresher(c):
            raise AmazonAuthError(
                "LwA refresh token is invalid_grant — the advertiser must "
                "re-authorize (see docs/amazon-ads.md)"
            )

        b = self._mk(
            tmp_path,
            self._creds(),
            _connect([], {}, ["RESULT"]),
            refresher=refresher,
            token_saver=lambda a, r: None,
        )
        with pytest.raises(AmazonBridgeError, match="re-authorize") as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        assert "Atzr|" not in str(ei.value)

    def test_unpersistable_minted_token_raises_a_clear_error(
        self, tmp_path: Path
    ) -> None:
        from mureo.amazon_ads.lwa import LwaTokens
        from mureo.providers.config_writer import ConfigWriteError

        def saver(access: str, refresh: str | None) -> None:
            raise ConfigWriteError("credentials.json is malformed")

        b = self._mk(
            tmp_path,
            self._creds(),
            _connect([], {}, ["RESULT"]),
            refresher=lambda c: LwaTokens("Atza|MINTED", "Atzr|R", 3600),
            token_saver=saver,
        )
        with pytest.raises(AmazonBridgeError, match="malformed") as ei:
            asyncio.run(b.handle_mcp_tool("x", {}))
        assert "Atza|" not in str(ei.value)

    def test_call_failure_after_a_mint_is_not_retried(self, tmp_path: Path) -> None:
        """One LwA exchange per dispatch — minting consumes the budget."""
        from mureo.amazon_ads.lwa import LwaTokens

        attempts: list[str] = []
        refreshed: list = []

        class _Sess:
            async def initialize(self):
                pass

            async def call_tool(self, name, arguments):
                raise RuntimeError("401 token expired")

        class _CM:
            def __init__(self, url, headers):
                attempts.append(headers["Authorization"])

            async def __aenter__(self):
                return _Sess()

            async def __aexit__(self, *e):
                return False

        def refresher(c):
            refreshed.append(1)
            return LwaTokens("Atza|MINTED", "Atzr|R", 3600)

        b = self._mk(
            tmp_path,
            self._creds(),
            lambda url, headers: _CM(url, headers),
            refresher=refresher,
            token_saver=lambda a, r: None,
        )
        with pytest.raises(RuntimeError, match="401 token expired"):
            asyncio.run(b.handle_mcp_tool("x", {}))
        assert refreshed == [1]  # minted once, never refreshed again
        assert attempts == ["Bearer Atza|MINTED"]  # exactly one forwarded call


def _connect_result(content, *, is_error: bool = False, attempts: list | None = None):
    """Connect factory whose session answers with ``content`` + ``isError``.

    Mirrors the real ``CallToolResult``: a failure is DECLARED by the server
    through ``isError``, not inferred from the body.
    """

    class _Sess:
        async def initialize(self) -> None: ...

        async def call_tool(self, name, arguments):
            if attempts is not None:
                attempts.append(name)
            return type("R", (), {"content": content, "isError": is_error})()

    class _CM:
        def __init__(self, url, headers):
            pass

        async def __aenter__(self):
            return _Sess()

        async def __aexit__(self, *e):
            return False

    return lambda url, headers: _CM(url, headers)


@pytest.mark.unit
class TestFailureEnvelopeNormalization:
    """#528 — an Amazon-declared failure becomes the canonical ``API error:``.

    Amazon returns a platform-side failure as ordinary content, so
    ``mureo.mcp._helpers.is_error_result`` — which knows only mureo's own
    ``API error:`` prefix — said False and a mutation that never happened was
    promoted into ``STATE.json``'s ``action_log``.

    The discriminator is ``CallToolResult.isError``, MCP's own field, which is
    LIVE-VERIFIED (region ``fe``, 2026-08-05) as ``True`` on both #528
    failures and ``False`` on a successful query. The payload is NOT
    inspected: every body-shape heuristic tried before this misread plausible
    mutation acks (``{"code": "CREATED", …}``) as failures, which would DROP
    the ``action_log`` entry for a change that really happened.
    """

    def _text(self, s: str):
        from mcp.types import TextContent

        return [TextContent(type="text", text=s)]

    def _call(self, tmp_path: Path, content, *, is_error: bool = False):
        b = _bridge(tmp_path, connect=_connect_result(content, is_error=is_error))
        return asyncio.run(
            b.handle_mcp_tool("campaign_management-create_campaign", {"name": "X"})
        )

    def _is_error(self, out) -> bool:
        from mureo.mcp._helpers import is_error_result

        return is_error_result(out)

    def test_live_json_failure_becomes_an_api_error(self, tmp_path: Path) -> None:
        """Live-observed shape #1, with the live-observed ``isError=True``."""
        out = self._call(
            tmp_path,
            self._text(
                '{"code":"FIELD_VALUE_IS_INVALID","message":"Multi marketplace '
                'query requests only support query by primary resource id"}'
            ),
            is_error=True,
        )
        assert self._is_error(out)
        text = out[0].text
        # The MESSAGE — the actionable half — survives verbatim.
        assert "Multi marketplace query requests" in text
        assert "Traceback" not in text
        # The CODE does not: the shared redactor masks the value of a quoted
        # ``"code"`` key (it cannot tell an Amazon error code from an OAuth
        # authorization code, and must not guess — see
        # ``test_a_token_shaped_code_never_reaches_the_agent``).
        assert "FIELD_VALUE_IS_INVALID" not in text
        assert "***" in text

    def test_a_token_shaped_code_never_reaches_the_agent(self, tmp_path: Path) -> None:
        """A credential-shaped ``code`` must stay masked end to end.

        The redactor masks the value of a quoted ``"code"`` key precisely
        because an LwA authorization code leaks in that shape. Rendering the
        payload for display must therefore happen AFTER scrubbing — flattening
        first would strip the ``"code":`` anchor the rule keys on and hand the
        agent (and the audit trail) the credential in cleartext.
        """
        secret = "AQABAAgAAAAmoFfGtYxfTKd1RVy5Z1oL8vXeqR7uKQzTOKENVALUE1234"
        out = self._call(
            tmp_path,
            self._text(
                f'{{"code": "{secret}", "message": "authorization code rejected"}}'
            ),
            is_error=True,
        )
        assert self._is_error(out)
        assert secret not in out[0].text
        assert "***" in out[0].text
        assert "authorization code rejected" in out[0].text

    def test_a_deeply_nested_body_does_not_escape_as_an_exception(
        self, tmp_path: Path
    ) -> None:
        """``RecursionError`` is a ``RuntimeError``, so ``except ValueError``
        misses it: the display helper must catch it and hand back the text.

        Letting it escape would replace the graceful envelope with a raw
        exception AND — with refresh credentials present — burn the one-shot
        refresh-and-retry on a problem that is not authentication.
        """
        out = self._call(tmp_path, self._text("[" * 3000 + "]" * 3000), is_error=True)
        assert self._is_error(out)

    @pytest.mark.parametrize(
        "body",
        [
            '{"code":"FIELD_VALUE_IS_INVALID"}',  # message absent
            '{"code":"FIELD_VALUE_IS_INVALID","message":""}',  # empty
            '{"code":"FIELD_VALUE_IS_INVALID","message":"   "}',  # whitespace
            '{"code":"FIELD_VALUE_IS_INVALID","message":null}',  # null
            '{"code":"FIELD_VALUE_IS_INVALID","message":{"nested":1}}',  # not a str
        ],
    )
    def test_a_failure_with_no_usable_message_says_so(
        self, tmp_path: Path, body: str
    ) -> None:
        """A masked code AND no message must not hand back an opaque blob.

        The redactor masks the code, so without a message there is nothing
        left to read. The envelope has to SAY that, otherwise the agent is
        handed ``API error: {"code":"***"}`` and can only guess.
        """
        out = self._call(tmp_path, self._text(body), is_error=True)
        assert self._is_error(out)
        assert "no error message" in out[0].text

    def test_a_message_without_a_code_is_still_rendered(self, tmp_path: Path) -> None:
        """The message alone is a perfectly good diagnosis."""
        out = self._call(
            tmp_path, self._text('{"message":"campaign not found"}'), is_error=True
        )
        assert out[0].text == "API error: campaign not found"

    def test_a_token_shaped_value_under_a_code_suffixed_key_is_masked(
        self, tmp_path: Path
    ) -> None:
        """Appending extra keys made this reachable, so it must be covered.

        The redactor's ``code`` rule required the key to BE ``code``; a field
        named ``authorizationCode`` carrying the same material slipped through
        and now lands in the agent-visible text verbatim.
        """
        secret = "AQABAAABBBCCCDDDauthcode123456"
        out = self._call(
            tmp_path,
            self._text(
                '{"code":"BAD","message":"rejected",'
                f'"authorizationCode":"{secret}"}}'
            ),
            is_error=True,
        )
        assert secret not in out[0].text
        assert "rejected" in out[0].text

    def test_a_bearer_token_in_a_message_keeps_the_body_parseable(
        self, tmp_path: Path
    ) -> None:
        """A redaction that eats the closing quote breaks the flattening."""
        out = self._call(
            tmp_path,
            self._text(
                '{"code":"BAD","message":"bad header Bearer sometoken.jwt.here"}'
            ),
            is_error=True,
        )
        assert out[0].text == "API error: BAD: bad header ***"

    def test_the_agent_visible_text_is_bounded(self, tmp_path: Path) -> None:
        """An unbounded body must not dump megabytes into the agent's context.

        The audit line has always been capped; the agent-facing text was not.
        """
        from mureo.amazon_ads.bridge import _MAX_FAILURE_TEXT

        huge_message = self._call(
            tmp_path,
            self._text('{"code":"BAD","message":"%s"}' % ("x" * 2_000_000)),
            is_error=True,
        )
        assert len(huge_message[0].text) < _MAX_FAILURE_TEXT + 100
        assert "truncated" in huge_message[0].text

        extras = ",".join(f'"k{i}":"v{i}"' for i in range(50_000))
        huge_extras = self._call(
            tmp_path,
            self._text('{"code":"BAD","message":"m",%s}' % extras),
            is_error=True,
        )
        assert len(huge_extras[0].text) < _MAX_FAILURE_TEXT + 100
        assert "truncated" in huge_extras[0].text

    def test_unrecognised_keys_are_kept_in_the_display_text(
        self, tmp_path: Path
    ) -> None:
        """Flattening must not silently discard the rest of the payload."""
        out = self._call(
            tmp_path,
            self._text(
                '{"code":"BAD","message":"bad id",'
                '"details":[{"field":"campaignId"}],"requestId":"r-1"}'
            ),
            is_error=True,
        )
        text = out[0].text
        assert "bad id" in text
        assert "campaignId" in text  # details survived
        assert "r-1" in text  # requestId survived

    def test_live_validation_failure_becomes_an_api_error(self, tmp_path: Path) -> None:
        """Live-observed shape #2 — plain text, also flagged ``isError=True``."""
        out = self._call(
            tmp_path,
            self._text(
                "Validation failed: provided input does not match tool input "
                "schema. Validation errors: [/body: required property "
                "'adProductFilter' not found]"
            ),
            is_error=True,
        )
        assert self._is_error(out)
        assert "adProductFilter" in out[0].text
        assert "Traceback" not in out[0].text

    def test_is_error_normalises_a_success_looking_payload(
        self, tmp_path: Path
    ) -> None:
        """The case ONLY ``isError`` can catch.

        A body that reads exactly like a successful query envelope, declared
        a failure by the server. No payload heuristic could ever see this;
        the protocol field settles it.
        """
        out = self._call(
            tmp_path,
            self._text('{"campaigns":[{"campaignId":"C1","state":"ENABLED"}]}'),
            is_error=True,
        )
        assert self._is_error(out)
        assert "campaigns" in out[0].text  # Amazon's own body still surfaced

    def test_validation_prefix_without_is_error_is_belt_and_braces(
        self, tmp_path: Path
    ) -> None:
        """Second signal: no success message plausibly opens this way."""
        out = self._call(
            tmp_path,
            self._text("Validation failed: provided input does not match schema."),
            is_error=False,
        )
        assert self._is_error(out)

    def test_is_error_with_no_text_still_yields_the_envelope(
        self, tmp_path: Path
    ) -> None:
        """A declared failure with an empty body is still a failure."""
        out = self._call(tmp_path, [], is_error=True)
        assert self._is_error(out)
        assert "no message" in out[0].text

    def test_success_envelope_is_returned_unchanged(self, tmp_path: Path) -> None:
        payload = '{"campaigns":[{"campaignId":"C1","state":"ENABLED"}]}'
        out = self._call(tmp_path, self._text(payload))
        assert not self._is_error(out)
        assert out[0].text == payload

    @pytest.mark.parametrize(
        "payload",
        [
            '{"code":"CREATED","message":"Campaign 123 created successfully"}',
            '{"code":"ACCEPTED","message":"request accepted"}',
            '{"code":"UPDATED","message":"campaign updated"}',
            '{"code":"DELETED","message":"campaign deleted"}',
            '{"code":"ENABLED","message":"campaign enabled"}',
            '{"code":"IN_PROGRESS","message":"update in progress"}',
            '{"code":"SUCCESS","message":"OK","campaignId":"C1"}',
            '{"code": 200, "message": "Campaign updated successfully"}',
            '{"code": 0, "message": "Campaign updated successfully"}',
            '{"code":"PARTIAL","message":"one item failed",'
            '"campaigns":[{"campaignId":"C1"}]}',
        ],
    )
    def test_a_mutation_ack_is_never_a_failure(
        self, tmp_path: Path, payload: str
    ) -> None:
        """Every ack shape the reviews produced, none of them ``isError``.

        These are exactly the payloads the previous vocabulary heuristics
        misclassified. Without ``isError`` the body cannot make the bridge
        call something a failure, so the whole class of bug is gone by
        construction rather than by a longer word list.
        """
        out = self._call(tmp_path, self._text(payload))
        assert not self._is_error(out)
        assert out[0].text == payload

    def test_unrecognised_payload_without_is_error_is_a_success(
        self, tmp_path: Path
    ) -> None:
        for payload in (
            "Something entirely unexpected happened",
            '{"foo":1}',
            '{"message":"no code here"}',
            '{"code":"NO_MESSAGE_HERE"}',
            "[1, 2, 3]",
        ):
            out = self._call(tmp_path, self._text(payload))
            assert not self._is_error(out), payload
            assert out[0].text == payload

    def test_non_text_content_is_returned_unchanged(self, tmp_path: Path) -> None:
        out = self._call(tmp_path, ["RESULT"])
        assert out == ["RESULT"]

    def test_a_session_without_the_field_is_treated_as_a_success(
        self, tmp_path: Path
    ) -> None:
        """The injection seam: a stand-in result need not carry ``isError``."""
        out = self._call(tmp_path, self._text('{"code":"X_IS_INVALID","message":"m"}'))
        assert not self._is_error(out)

    def test_error_detail_goes_through_the_token_scrubbing(
        self, tmp_path: Path
    ) -> None:
        out = self._call(
            tmp_path,
            self._text(
                '{"code":"UNAUTHORIZED","message":"bad header '
                'Bearer Atza|LEAKED-TOKEN for client_secret=hunter2"}'
            ),
            is_error=True,
        )
        assert self._is_error(out)
        text = out[0].text
        assert "Atza|LEAKED-TOKEN" not in text
        assert "hunter2" not in text
        # The message keeps the non-secret context; the quoted code value is
        # masked like every other one (see the live-shape test).
        assert "bad header" in text

    def test_normalization_also_applies_to_the_post_refresh_retry(
        self, tmp_path: Path
    ) -> None:
        """The retry leg returns through the same normalisation."""
        from mcp.types import TextContent

        from mureo.amazon_ads.lwa import LwaTokens

        attempts: list[int] = []

        class _Sess:
            def __init__(self, n):
                self._n = n

            async def initialize(self):
                pass

            async def call_tool(self, name, arguments):
                if self._n == 1:
                    raise RuntimeError("401 token expired")
                return type(
                    "R",
                    (),
                    {
                        "content": [
                            TextContent(
                                type="text",
                                text='{"code":"BAD_REQUEST","message":"nope"}',
                            )
                        ],
                        "isError": True,
                    },
                )()

        class _CM:
            def __init__(self, url, headers):
                attempts.append(1)
                self._n = len(attempts)

            async def __aenter__(self):
                return _Sess(self._n)

            async def __aexit__(self, *e):
                return False

        mp = tmp_path / "amazon_tools.json"
        mp.write_text(json.dumps(_MANIFEST))
        b = AmazonAdsBridge(
            manifest_path=mp,
            creds_loader=lambda: AmazonAdsCredentials(
                client_id="cid",
                access_token="Atza|OLD",
                refresh_token="Atzr|R",
                client_secret="sec",
            ),
            connect=lambda url, headers: _CM(url, headers),
            refresher=lambda c: LwaTokens("Atza|NEW", "Atzr|R2", 3600),
            token_saver=lambda a, r: None,
        )
        out = asyncio.run(b.handle_mcp_tool("campaign_management-x", {}))
        assert self._is_error(out)
        assert "nope" in out[0].text  # message survives; quoted code is masked


@pytest.mark.unit
def test_importing_the_bridge_first_does_not_break_plugin_discovery() -> None:
    """Regression: the bridge must not import ``mureo.mcp`` at module level.

    ``mureo.mcp.__init__`` imports the server, which builds its plugin tool
    list AT IMPORT TIME by reaching this bridge through
    ``mureo.amazon_ads.provider``. Any module-level ``mureo.mcp.*`` import here
    re-enters a partially-initialized bridge, and the failure is quiet: plugin
    discovery degrades to a warning and mureo starts with ZERO plugin tools —
    including every Amazon tool. Run in a subprocess so the import order is the
    real one rather than whatever the test session already cached.
    """
    import subprocess
    import sys

    source = (
        "import warnings\n"
        "warnings.simplefilter('error')\n"
        # ...but NOT a dependency's deprecation noise. Since #516 the bridge
        # resolves its manifest through the active RuntimeContext, so on a
        # host with a ``mureo.runtime_context_factory`` installed the
        # factory's own imports (google-ads emits two FutureWarnings on
        # Python 3.10) run inside collection. Escalating those would fail
        # this test for a third party's release calendar; the canary that
        # matters — PluginToolWarning, i.e. discovery actually degraded —
        # stays an error.
        "warnings.simplefilter('default', FutureWarning)\n"
        "import mureo.amazon_ads.bridge\n"  # bridge FIRST — the risky order
        "import mureo.mcp.server as s\n"
        "assert s._PLUGIN_DISPATCH is not None\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert "circular import" not in result.stderr
