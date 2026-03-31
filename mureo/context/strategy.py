"""STRATEGY.md の読み書き."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from mureo.context.errors import ContextFileError
from mureo.context.models import StrategyEntry
from mureo.context.state import _atomic_write

logger = logging.getLogger(__name__)

# セクション見出し → context_type のマッピング
_SECTION_MAP: dict[str, str] = {
    "Persona": "persona",
    "USP": "usp",
    "Target Audience": "target_audience",
    "Brand Voice": "brand_voice",
    "Market Context": "market_context",
    "Operation Mode": "operation_mode",
}

# context_type から見出し名への逆マッピング（Custom/Deep Research/Sales Material以外）
_TYPE_TO_HEADING: dict[str, str] = {v: k for k, v in _SECTION_MAP.items()}

# コロン付きプレフィックス → context_type
_PREFIX_TYPES: dict[str, str] = {
    "Custom": "custom",
    "Deep Research": "deep_research",
    "Sales Material": "sales_material",
}

# context_type → プレフィックス名（SUGGESTION-1: モジュールレベル定数化）
_TYPE_TO_PREFIX: dict[str, str] = {v: k for k, v in _PREFIX_TYPES.items()}

# h2見出しのパターン
_H2_PATTERN = re.compile(r"^##\s+(.+)$")


def parse_strategy(text: str) -> list[StrategyEntry]:
    """Markdown文字列をパースしてStrategyEntryのリストを返す."""
    if not text.strip():
        return []

    entries: list[StrategyEntry] = []
    current_type: str | None = None
    current_title: str = ""
    content_lines: list[str] = []

    def _flush() -> None:
        if current_type is not None:
            content = "\n".join(content_lines).strip()
            entries.append(
                StrategyEntry(
                    context_type=current_type,
                    title=current_title,
                    content=content,
                )
            )

    for line in text.split("\n"):
        m = _H2_PATTERN.match(line)
        if m:
            _flush()
            heading = m.group(1).strip()
            current_type, current_title = _resolve_heading(heading)
            content_lines = []
        elif current_type is not None:
            content_lines.append(line)

    _flush()
    return entries


def _resolve_heading(heading: str) -> tuple[str | None, str]:
    """見出し文字列から (context_type, title) を解決する.

    未知の見出しの場合は (None, heading) を返し、warningをログ出力する。
    """
    # 完全一致チェック
    if heading in _SECTION_MAP:
        return _SECTION_MAP[heading], heading

    # プレフィックス型チェック（"Custom: タイトル" 等）
    for prefix, ctx_type in _PREFIX_TYPES.items():
        if heading.startswith(f"{prefix}:"):
            title = heading[len(prefix) + 1 :].strip()
            return ctx_type, title

    # WARNING-3: 未知セクションのlogging.warning
    logger.warning("未知のセクション見出しをスキップしました: '%s'", heading)
    return None, heading


def render_strategy(entries: list[StrategyEntry]) -> str:
    """StrategyEntryのリストからMarkdown文字列を生成する."""
    lines: list[str] = ["# Strategy", ""]

    for entry in entries:
        heading = _make_heading(entry)
        lines.append(f"## {heading}")
        lines.append(entry.content)
        lines.append("")

    return "\n".join(lines)


def _make_heading(entry: StrategyEntry) -> str:
    """StrategyEntryから見出し文字列を生成する."""
    if entry.context_type in _TYPE_TO_HEADING:
        return _TYPE_TO_HEADING[entry.context_type]

    # SUGGESTION-1: モジュールレベル定数を使用
    if entry.context_type in _TYPE_TO_PREFIX:
        return f"{_TYPE_TO_PREFIX[entry.context_type]}: {entry.title}"

    return entry.title


def read_strategy_file(path: Path) -> list[StrategyEntry]:
    """STRATEGY.md ファイルを読み取ってStrategyEntryのリストを返す.

    ファイルが存在しない場合は空リストを返す。
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(
            f"STRATEGY.md の読み取り権限がありません: {path}"
        ) from exc
    return parse_strategy(text)


def write_strategy_file(path: Path, entries: list[StrategyEntry]) -> None:
    """StrategyEntryのリストをSTRATEGY.md ファイルにアトミックに書き込む."""
    text = render_strategy(entries)
    _atomic_write(path, text)


def add_strategy_entry(path: Path, entry: StrategyEntry) -> list[StrategyEntry]:
    """既存ファイルにエントリを追加する.

    Returns:
        更新後のエントリリスト
    """
    entries = read_strategy_file(path)
    entries = [*entries, entry]
    write_strategy_file(path, entries)
    return entries


def remove_strategy_entry(
    path: Path,
    context_type: str,
    *,
    title: str | None = None,
) -> list[StrategyEntry]:
    """特定のcontext_type（およびtitle）のエントリを削除する.

    titleが指定された場合はcontext_typeとtitleの両方が一致するエントリのみ削除。
    titleが未指定の場合はcontext_typeが一致する全エントリを削除。

    Returns:
        更新後のエントリリスト
    """
    entries = read_strategy_file(path)

    def _should_keep(e: StrategyEntry) -> bool:
        if e.context_type != context_type:
            return True
        return bool(title is not None and e.title != title)

    filtered = [e for e in entries if _should_keep(e)]
    write_strategy_file(path, filtered)
    return filtered
