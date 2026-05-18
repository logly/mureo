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

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from mcp.types import Tool

from mureo.amazon_ads.endpoints import endpoint_url, request_headers
from mureo.amazon_ads.manifest import _default_connect, manifest_path
from mureo.auth import AmazonAdsCredentials, load_amazon_ads_credentials

ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]
CredsLoader = Callable[[], AmazonAdsCredentials | None]


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
    ) -> None:
        self._manifest_path = manifest_path or _default_manifest_path()
        self._creds_loader: CredsLoader = creds_loader or load_amazon_ads_credentials
        self._connect: ConnectFactory = connect or _default_connect

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
        url = endpoint_url(creds.region)
        headers = request_headers(creds)
        async with self._connect(url, headers) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            return list(result.content)


def _default_manifest_path() -> Path:
    return manifest_path()


__all__ = ["AmazonAdsBridge", "AmazonBridgeError"]
