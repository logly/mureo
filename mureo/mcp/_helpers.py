"""MCPハンドラー共通ヘルパー

Google Ads / Meta Ads ハンドラーで共通利用するユーティリティ関数と
APIエラーハンドリングデコレータを提供する。
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable, Coroutine

from mcp.types import TextContent

logger = logging.getLogger(__name__)


def _require(arguments: dict[str, Any], key: str) -> Any:
    """必須パラメータを取得。欠損時は ValueError を送出する。"""
    value = arguments.get(key)
    if value is None or value == "":
        raise ValueError(f"必須パラメータ {key} が指定されていません")
    return value


def _opt(arguments: dict[str, Any], key: str, default: Any = None) -> Any:
    """オプションパラメータを取得する。"""
    return arguments.get(key, default)


def _json_result(data: Any) -> list[TextContent]:
    """結果をJSON文字列の TextContent リストに変換する。"""
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _no_creds_result(msg: str) -> list[TextContent]:
    """認証情報なしエラーを返す。"""
    return [TextContent(type="text", text=msg)]


def api_error_handler(
    func: Callable[..., Coroutine[Any, Any, list[TextContent]]],
) -> Callable[..., Coroutine[Any, Any, list[TextContent]]]:
    """API呼び出し例外を TextContent エラーメッセージに変換するデコレータ。"""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> list[TextContent]:
        try:
            return await func(*args, **kwargs)
        except ValueError:
            # 必須パラメータ欠損など、呼び出し元で処理すべき例外はそのまま再送出
            raise
        except Exception as exc:
            logger.exception("%s failed", func.__name__)
            return [TextContent(type="text", text=f"APIエラー: {exc}")]

    return wrapper
