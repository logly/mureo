"""Search term intent classification.

Provides data models, prompts, and parsers for search term intent classification.
LLM dependency is removed in mureo-core; no LLM calls are made here.
Batch classification via LLM should be done on the Managed side.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Intent category constants
INTENT_TRANSACTIONAL = "transactional"
INTENT_COMMERCIAL = "commercial_investigation"
INTENT_INFORMATIONAL = "informational"
INTENT_NAVIGATIONAL = "navigational"

VALID_INTENTS: frozenset[str] = frozenset(
    {
        INTENT_TRANSACTIONAL,
        INTENT_COMMERCIAL,
        INTENT_INFORMATIONAL,
        INTENT_NAVIGATIONAL,
    }
)


@dataclass(frozen=True)
class SearchTermIntent:
    """Search term intent classification result."""

    search_term: str
    intent: (
        str  # transactional / commercial_investigation / informational / navigational
    )
    relevance_score: int  # 0-100: Relevance to advertiser business
    reasoning: str
    exclude_recommendation: bool  # Whether exclusion is recommended


_CLASSIFY_PROMPT = """\
あなたはリスティング広告の検索語句分析の専門家です。

## タスク
以下の検索語句それぞれについて、検索意図とビジネス関連度を分析してください。
ビジネスコンテキスト（特にペルソナとUSP）を参照し、
ターゲットユーザーの検索意図に合致するかどうかを判断してください。

## ビジネスコンテキスト
- キャンペーン名: {campaign_name}
- 登録キーワード: {keywords}
{strategic_context}

## 検索語句リスト
{search_terms}

## 分類ルール

### 検索意図（intent）
- **transactional**: 購入・申込・問合せなど行動意図がある（例: 「〇〇 申し込み」「〇〇 購入」）
- **commercial_investigation**: 購入前の比較検討段階（例: 「〇〇 おすすめ」「〇〇 口コミ」）
- **informational**: 情報収集が目的（例: 「〇〇 とは」「〇〇 仕組み」「〇〇 やり方」）
- **navigational**: 特定サイト・ブランドへの直接アクセス意図（例: 「〇〇 公式」「〇〇 ログイン」）

### ビジネス関連度（relevance_score: 0-100）
- 90-100: 直接的に商品・サービスに関連し、CVにつながる可能性が高い
- 60-89: 関連はあるがCV意図は弱い
- 30-59: 間接的に関連、CV可能性は低い
- 0-29: 無関係または競合ブランドへの遷移意図

### 除外推奨（exclude_recommendation）
以下の条件で true:
- informational かつ relevance_score < 40
- navigational かつ 自社ブランドでない
- relevance_score < 20（意図に関わらず無関係）

**重要:** ペルソナのニーズやUSPに関連する語句は、短期的なCPA悪化だけで除外推奨にしないこと。
ターゲットの検索意図に合致する語句は relevance_score を高く評価すること。

## 出力フォーマット（JSON配列）
```json
[
    {{
        "search_term": "検索語句",
        "intent": "transactional",
        "relevance_score": 85,
        "reasoning": "商品名を含み購入意図が明確",
        "exclude_recommendation": false
    }}
]
```

JSON配列のみを出力してください。"""


class IntentClassifier:
    """Search term intent classifier.

    LLM dependency is removed in mureo-core; no LLM calls are made here.
    Handles prompt generation and response parsing only.
    Classification via LLM should be done on the Managed side.
    """

    @staticmethod
    def build_prompt(
        search_terms: list[str],
        campaign_name: str = "",
        keywords: list[str] | None = None,
        strategic_context: str | None = None,
    ) -> str:
        """Generate a prompt for LLM classification.

        The actual LLM call is performed on the Managed side.
        """
        terms_text = "\n".join(
            f"{idx + 1}. {term}" for idx, term in enumerate(search_terms)
        )

        context_section = ""
        if strategic_context:
            context_section = f"\n### 戦略情報（ペルソナ・USP）\n{strategic_context}"

        return _CLASSIFY_PROMPT.format(
            campaign_name=campaign_name or "（未指定）",
            keywords=", ".join(keywords[:20]) if keywords else "（未指定）",
            search_terms=terms_text,
            strategic_context=context_section,
        )

    @staticmethod
    def parse_response(
        content: str, original_terms: list[str]
    ) -> list[SearchTermIntent]:
        """Parse an LLM response."""
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse intent classification JSON: %s", exc)
            return [
                SearchTermIntent(
                    search_term=t,
                    intent=INTENT_INFORMATIONAL,
                    relevance_score=50,
                    reasoning=f"Default classification due to parse failure: {exc}",
                    exclude_recommendation=False,
                )
                for t in original_terms
            ]

        if not isinstance(data, list):
            data = [data]

        # Match LLM output against original term list
        result_map: dict[str, dict[str, Any]] = {}
        for item in data:
            if isinstance(item, dict):
                key = item.get("search_term", "").strip().lower()
                result_map[key] = item

        results: list[SearchTermIntent] = []
        for term in original_terms:
            item = result_map.get(term.strip().lower(), {})
            intent_raw = str(item.get("intent", INTENT_INFORMATIONAL)).lower()
            intent = intent_raw if intent_raw in VALID_INTENTS else INTENT_INFORMATIONAL

            relevance = item.get("relevance_score", 50)
            if not isinstance(relevance, (int, float)):
                relevance = 50
            relevance = max(0, min(100, int(relevance)))

            results.append(
                SearchTermIntent(
                    search_term=term,
                    intent=intent,
                    relevance_score=relevance,
                    reasoning=str(item.get("reasoning", "No classification info")),
                    exclude_recommendation=bool(
                        item.get("exclude_recommendation", False)
                    ),
                )
            )

        return results
