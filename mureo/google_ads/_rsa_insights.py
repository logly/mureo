"""RSAインサイト抽出

RSA広告のアセット別パフォーマンスを分析し、
「なぜ勝ち広告が勝ったのか」を構造化して説明する。
さらに勝因に基づく新規広告バリエーションを生成する。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RSAInsight:
    """RSAインサイト抽出結果"""

    winning_patterns: tuple[str, ...]
    losing_patterns: tuple[str, ...]
    recommendations: tuple[str, ...]
    new_ad_variants: tuple[dict[str, Any], ...]
    error: str | None = None


# Managed側（src/plugins/google_ads）でLLM呼び出しに使うプロンプトテンプレート
_INSIGHT_PROMPT = """\
あなたはリスティング広告のRSA（レスポンシブ検索広告）の専門家です。

以下のアセット別パフォーマンスデータを分析し、
「なぜ勝ちアセットが勝ったのか」を構造的に説明してください。
その後、勝因を活かした新しい広告バリエーション3案を生成してください。
{strategic_context_section}
## アセットパフォーマンスデータ

### 高パフォーマンス見出し
{best_headlines}

### 低パフォーマンス見出し
{worst_headlines}

### 高パフォーマンス説明文
{best_descriptions}

### 低パフォーマンス説明文
{worst_descriptions}

### 全見出し一覧（インプレッション順）
{all_headlines}

### 全説明文一覧（インプレッション順）
{all_descriptions}

## ターゲットキーワード
{keywords}

## 出力フォーマット（JSON）
```json
{{
    "winning_patterns": [
        "具体的な数字（価格・実績）を含む見出しのCTRが高い",
        "ユーザーの悩みに直接言及する説明文のCVRが高い"
    ],
    "losing_patterns": [
        "一般的すぎる表現の見出しはインプレッションが低い",
        "長すぎる説明文は表示が切れてCTRが低下"
    ],
    "recommendations": [
        "数字訴求を含む見出しを増やす",
        "低パフォーマンスの見出しXXを差し替える"
    ],
    "new_ad_variants": [
        {{
            "headlines": ["見出し1", "見出し2", "見出し3", "見出し4", "見出し5"],
            "descriptions": ["説明文1", "説明文2"],
            "rationale": "勝因Xを活かし、YYを強化した案"
        }},
        {{
            "headlines": ["見出し1", "見出し2", "見出し3", "見出し4", "見出し5"],
            "descriptions": ["説明文1", "説明文2"],
            "rationale": "勝因Zに基づき、ABテスト向けの差分を作成"
        }},
        {{
            "headlines": ["見出し1", "見出し2", "見出し3", "見出し4", "見出し5"],
            "descriptions": ["説明文1", "説明文2"],
            "rationale": "新しい訴求軸を追加しつつ勝ちパターンを維持"
        }}
    ]
}}
```

見出しは全角15文字（半角30文字）以内、説明文は全角45文字（半角90文字）以内で作成してください。
JSON のみを出力してください。"""


def _format_assets(assets: list[dict[str, Any]]) -> str:
    """アセットリストを文字列フォーマット"""
    if not assets:
        return "（データなし）"
    lines: list[str] = []
    for a in assets:
        lines.append(
            f"- 「{a.get('text', '')}」"
            f" imp={a.get('impressions', 0):,}"
            f" click={a.get('clicks', 0):,}"
            f" CV={a.get('conversions', 0)}"
            f" CTR={a.get('ctr', 0)}%"
            f" label={a.get('performance_label', 'N/A')}"
        )
    return "\n".join(lines)


class RSAInsightExtractor:
    """RSAアセットパフォーマンスデータを構造化するクラス。

    mureo-coreではLLM依存を除去しているため、勝因分析・新広告案生成は行わない。
    アセットデータの構造化とプロンプト生成までを担当する。
    LLMによる分析はManaged側で実施すること。
    """

    @staticmethod
    def build_prompt(
        asset_data: dict[str, Any],
        keywords: list[str] | None = None,
        strategic_context: str | None = None,
    ) -> str:
        """LLM分析用のプロンプトを生成する。

        LLM呼び出し自体はManaged側で実施する。
        """
        ctx_section = ""
        if strategic_context:
            ctx_section = (
                "\n## 戦略コンテキスト\n"
                "以下のペルソナ・USP・ターゲット情報を踏まえて、"
                "新広告バリエーションの訴求軸を決定してください。\n\n"
                f"{strategic_context}\n"
            )

        return _INSIGHT_PROMPT.format(
            best_headlines=_format_assets(asset_data.get("best_headlines", [])),
            worst_headlines=_format_assets(asset_data.get("worst_headlines", [])),
            best_descriptions=_format_assets(asset_data.get("best_descriptions", [])),
            worst_descriptions=_format_assets(asset_data.get("worst_descriptions", [])),
            all_headlines=_format_assets(asset_data.get("headlines", [])),
            all_descriptions=_format_assets(asset_data.get("descriptions", [])),
            keywords=", ".join(keywords) if keywords else "（未指定）",
            strategic_context_section=ctx_section,
        )

    @staticmethod
    def parse_response(content: str) -> RSAInsight:
        """LLMレスポンスをパースする。

        Managed側でLLM呼び出し後にこのメソッドで結果をパースする。
        """
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("RSAインサイトのJSONパースに失敗: %s", exc)
            return RSAInsight(
                winning_patterns=(),
                losing_patterns=(),
                recommendations=(),
                new_ad_variants=(),
                error=f"結果のパースに失敗しました: {exc}",
            )

        return RSAInsight(
            winning_patterns=tuple(data.get("winning_patterns", [])),
            losing_patterns=tuple(data.get("losing_patterns", [])),
            recommendations=tuple(data.get("recommendations", [])),
            new_ad_variants=tuple(data.get("new_ad_variants", [])),
        )
