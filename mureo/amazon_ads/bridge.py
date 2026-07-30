"""The Amazon Ads bridge provider (#113 Phase 1, task #24).

Shape matches the #114 ``MCPToolProvider`` Protocol so it can ride the
exact same collect/dispatch + safety layer (audit / throttle /
strategy / rollback) as entry-point plugins:

- ``mcp_tools()`` — PURE: reads ``~/.mureo/amazon_tools.json`` only.
  No credentials, no network, and it NEVER raises (it runs at mureo
  server start; a missing/broken manifest ⇒ no Amazon tools, not a
  crash).
- ``handle_mcp_tool()`` — lazily opens one authenticated MCP session
  to the region endpoint (creds from ``~/.mureo/credentials.json``)
  and forwards the call. Tool names are Amazon's own (no taxonomy
  remap), consistent with how mureo treats other official MCPs.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from mcp.types import Tool

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.amazon_ads.lwa import AmazonAuthError as _LwaAuthError
from mureo.amazon_ads.lwa import LwaTokens, refresh_access_token
from mureo.amazon_ads.manifest import _default_connect, manifest_path
from mureo.auth import (
    AmazonAdsCredentials,
    load_amazon_ads_credentials,
    save_amazon_access_token,
)
from mureo.providers.config_writer import ConfigWriteError

ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]
CredsLoader = Callable[[], AmazonAdsCredentials | None]
Refresher = Callable[[AmazonAdsCredentials], LwaTokens]
TokenSaver = Callable[[str, str | None], None]


class AmazonBridgeError(RuntimeError):
    """Raised by ``handle_mcp_tool`` when the bridge cannot proceed
    (e.g. ``amazon_ads`` credentials are not configured)."""


class AmazonAdsBridge:
    """Internal (non-entry-point) provider bridging to Amazon's MCP."""

    name = "amazon_ads"
    display_name = "Amazon Ads"

    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        creds_loader: CredsLoader | None = None,
        connect: ConnectFactory | None = None,
        refresher: Refresher | None = None,
        token_saver: TokenSaver | None = None,
    ) -> None:
        self._manifest_path = manifest_path or _default_manifest_path()
        self._creds_loader: CredsLoader = creds_loader or load_amazon_ads_credentials
        self._connect: ConnectFactory = connect or _default_connect
        self._refresher: Refresher = refresher or refresh_access_token
        self._token_saver: TokenSaver = token_saver or save_amazon_access_token

    # -- collection-time (pure, never raises) -------------------------------

    def mcp_tools(self) -> tuple[Tool, ...]:
        try:
            raw = json.loads(Path(self._manifest_path).read_text(encoding="utf-8"))
            items = raw.get("tools", []) if isinstance(raw, dict) else []
        except (OSError, ValueError, TypeError):
            return ()  # missing / unreadable / malformed ⇒ no Amazon tools
        tools: list[Tool] = []
        for entry in items if isinstance(items, list) else []:
            try:
                tools.append(Tool.model_validate(entry))
            except Exception:  # noqa: BLE001 — one bad tool ≠ crash start
                continue
        return tuple(tools)

    # -- dispatch-time (authenticated, network) -----------------------------

    async def handle_mcp_tool(self, name: str, arguments: dict[str, Any]) -> list[Any]:
        creds = self._creds_loader()
        if creds is None:
            raise AmazonBridgeError(
                "amazon_ads credentials not configured in "
                "~/.mureo/credentials.json (run the Amazon setup first)"
            )
        try:
            return await self._call(creds, name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as first_exc:
            # The Amazon access token expires after 60 min. We do not
            # observe the MCP transport's exact 401 shape, so on ANY
            # first failure — when refresh creds are present — attempt
            # exactly one LwA refresh + persist + retry. Bounded (one
            # extra POST + one retry). Accepted trade-off: a *non-auth*
            # first failure also triggers one wasted refresh (a token
            # rotation + a credentials.json write) before the same
            # error recurs; this is intentional until the 401 shape is
            # observed and can be narrowed. The original error is always
            # chained (``from first_exc``) so it is never lost.
            if not (creds.refresh_token and creds.client_secret):
                raise
            return await self._refresh_and_retry(creds, name, arguments, first_exc)

    async def _refresh_and_retry(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
        first_exc: BaseException,
    ) -> list[Any]:
        """Refresh the LwA token once, persist it, and retry ``name``.

        Every failure mode is reported as an ``AmazonBridgeError`` with an
        actionable message, always chaining ``first_exc`` so the original
        call failure is never lost.
        """
        try:
            tokens = self._refresher(creds)
        except _LwaAuthError as auth_exc:
            raise AmazonBridgeError(
                f"Amazon access token expired and refresh failed: {auth_exc}"
            ) from first_exc
        try:
            self._token_saver(tokens.access_token, tokens.refresh_token)
        except (ConfigWriteError, OSError) as save_exc:
            # The refreshed token is valid but is not on disk, so every later
            # call would re-refresh from a refresh token Amazon has already
            # rotated against. Surface the underlying reason — typically a
            # malformed credentials.json that mureo deliberately refuses to
            # overwrite — instead of letting a raw traceback out.
            raise AmazonBridgeError(
                f"Amazon access token was refreshed but could not be saved to "
                f"~/.mureo/credentials.json: {save_exc}"
            ) from first_exc
        refreshed = dataclasses.replace(
            creds,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )
        try:
            return await self._call(refreshed, name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as retry_exc:
            raise retry_exc from first_exc

    async def _call(
        self,
        creds: AmazonAdsCredentials,
        name: str,
        arguments: dict[str, Any],
    ) -> list[Any]:
        url = endpoint_url(creds.region)
        headers = request_headers(creds)
        async with self._connect(url, headers) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return list(result.content)


def _default_manifest_path() -> Path:
    return manifest_path()


__all__ = ["AmazonAdsBridge", "AmazonBridgeError"]
