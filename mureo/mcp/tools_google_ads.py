"""Google Ads MCPツール定義

82ツールのツール定義（MCP Tool）を提供する。
ハンドラー実装は _handlers_google_ads.py / _handlers_google_ads_extensions.py /
_handlers_google_ads_analysis.py に分離。

ツール定義はカテゴリ別サブモジュールに分割:
  _tools_google_ads_campaigns.py  — キャンペーン・広告グループ・広告・予算
  _tools_google_ads_keywords.py   — キーワード・除外キーワード
  _tools_google_ads_extensions.py — サイトリンク・コールアウト・コンバージョン・ターゲティング
  _tools_google_ads_analysis.py   — パフォーマンス分析・検索語句・監視・キャプチャ
  _tools_google_ads_assets.py     — 画像アセット
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

# ハンドラーモジュールを公開（テストからpatch可能にする）
from mureo.mcp._handlers_google_ads import (  # noqa: F401
    HANDLERS as _HANDLERS,
)

# カテゴリ別ツール定義をインポート
from mureo.mcp._tools_google_ads_analysis import TOOLS as _TOOLS_ANALYSIS
from mureo.mcp._tools_google_ads_assets import TOOLS as _TOOLS_ASSETS
from mureo.mcp._tools_google_ads_campaigns import TOOLS as _TOOLS_CAMPAIGNS
from mureo.mcp._tools_google_ads_extensions import TOOLS as _TOOLS_EXTENSIONS
from mureo.mcp._tools_google_ads_keywords import TOOLS as _TOOLS_KEYWORDS

# ---------------------------------------------------------------------------
# ツール定義（82個）— サブモジュールを集約
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = (
    _TOOLS_CAMPAIGNS
    + _TOOLS_KEYWORDS
    + _TOOLS_EXTENSIONS
    + _TOOLS_ANALYSIS
    + _TOOLS_ASSETS
)

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


# ---------------------------------------------------------------------------
# ハンドラーディスパッチ
# ---------------------------------------------------------------------------


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """ツール名に対応するハンドラーを実行する。

    Raises:
        ValueError: 未知のツール名、または必須パラメータの欠損
    """
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]
