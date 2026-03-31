"""mureo MCP サーバー本体

MCPプロトコルで Google Ads / Meta Ads ツールを公開する。
stdio ベースで Claude Code / Cursor 等の MCP クライアントから呼び出される。

ツール定義・ハンドラーは tools_google_ads.py / tools_meta_ads.py に分離。
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_google_ads import handle_tool as handle_google_ads_tool
from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS
from mureo.mcp.tools_meta_ads import handle_tool as handle_meta_ads_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 統合ツール一覧
# ---------------------------------------------------------------------------

_ALL_TOOLS: list[Tool] = [*GOOGLE_ADS_TOOLS, *META_ADS_TOOLS]
_GOOGLE_ADS_NAMES: frozenset[str] = frozenset(t.name for t in GOOGLE_ADS_TOOLS)
_META_ADS_NAMES: frozenset[str] = frozenset(t.name for t in META_ADS_TOOLS)


# ---------------------------------------------------------------------------
# ハンドラー（テストから直接呼べるようにモジュールレベル関数として定義）
# ---------------------------------------------------------------------------


async def handle_list_tools() -> list[Any]:
    """登録済みツール一覧を返す"""
    return list(_ALL_TOOLS)


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """ツールを実行して結果を返す

    Raises:
        ValueError: 未知のツール名、または必須パラメータの欠損
    """
    if name in _GOOGLE_ADS_NAMES:
        return await handle_google_ads_tool(name, arguments)
    if name in _META_ADS_NAMES:
        return await handle_meta_ads_tool(name, arguments)
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# MCP サーバーセットアップ & エントリポイント
# ---------------------------------------------------------------------------


def _create_server() -> Server:
    """MCP Server インスタンスを作成し、ハンドラーを登録する"""
    server = Server("mureo")

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return await handle_list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        return await handle_call_tool(name, arguments)

    return server


async def main() -> None:
    """stdio ベースで MCP サーバーを起動する"""
    server = _create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
