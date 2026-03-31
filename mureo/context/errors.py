"""コンテキストモジュール用カスタム例外."""

from __future__ import annotations


class ContextFileError(Exception):
    """ファイルI/O関連のエラー（不正JSON、権限エラー等）."""
