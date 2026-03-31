"""分析モジュール共通の定数・ヘルパー関数。"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 期間名 → 日数マッピング（非重複の前期比較用）
# ---------------------------------------------------------------------------

_PERIOD_DAYS: dict[str, int] = {
    "LAST_7_DAYS": 7,
    "LAST_14_DAYS": 14,
    "LAST_30_DAYS": 30,
}

# ---------------------------------------------------------------------------
# 共通マッピング定数（重複定義を排除）
# ---------------------------------------------------------------------------

_MATCH_TYPE_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "EXACT",
    3: "PHRASE",
    4: "BROAD",
}

_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "ENABLED",
    3: "PAUSED",
    4: "REMOVED",
}

# ---------------------------------------------------------------------------
# 情報収集パターン
# ---------------------------------------------------------------------------

_INFORMATIONAL_PATTERNS: tuple[str, ...] = (
    "とは", "比較", "方法", "無料", "やり方", "仕組み",
    "口コミ", "評判", "ランキング", "おすすめ", "違い",
)


# ---------------------------------------------------------------------------
# 共通ヘルパー関数
# ---------------------------------------------------------------------------


def _get_comparison_date_ranges(period: str) -> tuple[str, str]:
    """指定期間に対する非重複の当期・前期を BETWEEN 形式で返す。

    例: LAST_7_DAYS →
      当期: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (直近7日)
      前期: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (その前の7日)
    """
    days = _PERIOD_DAYS.get(period.upper(), 7)
    today = date.today()
    current_end = today - timedelta(days=1)
    current_start = today - timedelta(days=days)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    fmt = "%Y-%m-%d"
    current = f"BETWEEN '{current_start.strftime(fmt)}' AND '{current_end.strftime(fmt)}'"
    previous = f"BETWEEN '{prev_start.strftime(fmt)}' AND '{prev_end.strftime(fmt)}'"
    return current, previous


def _calc_change_rate(current: float, previous: float) -> float | None:
    """変化率を計算する（%）。前期が0の場合はNoneを返す。"""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _safe_metrics(perf: list[dict[str, Any]]) -> dict[str, Any]:
    """パフォーマンスレポートから最初のメトリクスを安全に取り出す。"""
    if perf:
        return perf[0].get("metrics", {})
    return {"impressions": 0, "clicks": 0, "cost": 0}


def _extract_ngrams(text: str, n: int) -> list[str]:
    """テキストからN-gramを抽出（スペース分割）"""
    words = text.strip().split()
    if len(words) < n:
        return [text.strip()] if text.strip() else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def _resolve_enum(raw_value: int | Any, mapping: dict[int, str]) -> str:
    """protobuf enum int を文字列に変換。enum型の場合は.nameを使う。"""
    if isinstance(raw_value, int):
        return mapping.get(raw_value, str(raw_value))
    return raw_value.name if hasattr(raw_value, "name") else str(raw_value)
