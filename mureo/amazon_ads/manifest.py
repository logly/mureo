"""Generate the Amazon MCP tool manifest.

Credentialed/network in production (one authenticated MCP session to
the region endpoint). The result is written to
``~/.mureo/amazon_tools.json`` so the bridge's ``mcp_tools()`` can be a
pure, credential-free, network-free read at mureo server start.

The MCP client session is dependency-injected (``connect``) so the
core is unit-testable without a real Amazon connection or the mcp SDK
transport.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.amazon_ads.endpoints import endpoint_url, request_headers

if TYPE_CHECKING:
    from mureo.auth import AmazonAdsCredentials

# (url, headers) -> async context manager yielding an object with
# ``await initialize()`` and ``await list_tools()`` (mcp ClientSession).
ConnectFactory = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]


def manifest_path() -> Path:
    """Default manifest location: ``~/.mureo/amazon_tools.json``."""
    return Path.home() / ".mureo" / "amazon_tools.json"


def _default_connect(
    url: str, headers: dict[str, str]
) -> AbstractAsyncContextManager[Any]:
    @asynccontextmanager
    async def _cm() -> AsyncIterator[Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(url, headers=headers) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            yield session

    return _cm()


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    # mcp.types.Tool is pydantic v2; keep only the wire-relevant,
    # secret-free fields the bridge will rebuild a Tool from.
    dumped: dict[str, Any] = tool.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    keep = ("name", "description", "inputSchema", "annotations", "_meta")
    return {k: dumped[k] for k in keep if k in dumped}


async def generate_manifest(
    creds: AmazonAdsCredentials,
    *,
    connect: ConnectFactory | None = None,
    out_path: Path | None = None,
) -> Path:
    """Connect once, list Amazon's tools, write the manifest. Returns path.

    Never writes a partial file: the manifest is only written after a
    successful tool listing (a connection failure propagates and leaves
    no file behind).
    """
    connect = connect or _default_connect
    out = out_path or manifest_path()
    url = endpoint_url(creds.region)
    headers = request_headers(creds)

    async with connect(url, headers) as session:
        await session.initialize()
        result = await session.list_tools()
        tools = list(result.tools)

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": creds.region,
        "endpoint": url,
        "account_mode": creds.account_mode,
        "tools": [_tool_to_dict(t) for t in tools],
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic + 0600: write a temp sibling, then replace, so a reader
    # never sees a half-written manifest and the file is not world-read.
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix=".amazon_tools.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, out)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return out


def generate_manifest_sync(
    creds: AmazonAdsCredentials,
    *,
    connect: ConnectFactory | None = None,
    out_path: Path | None = None,
) -> Path:
    """Blocking wrapper for the CLI command path."""
    return asyncio.run(generate_manifest(creds, connect=connect, out_path=out_path))
