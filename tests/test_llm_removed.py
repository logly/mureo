"""LLM除去済みモジュールのテスト

_rsa_insights.py, _intent_classifier.py, _message_match.py の
build_prompt / parse_response が正しく動作することを確認する。
"""

from __future__ import annotations

import builtins
import json

import pytest

from mureo.google_ads._intent_classifier import (
    INTENT_COMMERCIAL,
    INTENT_INFORMATIONAL,
    INTENT_NAVIGATIONAL,
    INTENT_TRANSACTIONAL,
    VALID_INTENTS,
    IntentClassifier,
    SearchTermIntent,
)
from mureo.google_ads._message_match import (
    LPScreenshotter,
    MessageMatchEvaluator,
    MessageMatchResult,
)
from mureo.google_ads._rsa_insights import (
    RSAInsight,
    RSAInsightExtractor,
)


# ===========================================================================
# RSAInsightExtractor
# ===========================================================================


@pytest.mark.unit
class TestRSAInsightExtractorBuildPrompt:
    def test_基本プロンプト生成(self) -> None:
        asset_data = {
            "best_headlines": [
                {"text": "高品質商品", "impressions": 1000, "clicks": 50}
            ],
            "worst_headlines": [
                {"text": "一般的な商品", "impressions": 100, "clicks": 2}
            ],
            "best_descriptions": [],
            "worst_descriptions": [],
            "headlines": [],
            "descriptions": [],
        }

        prompt = RSAInsightExtractor.build_prompt(
            asset_data=asset_data,
            keywords=["テスト", "商品"],
        )

        assert "高品質商品" in prompt
        assert "一般的な商品" in prompt
        assert "テスト, 商品" in prompt

    def test_戦略コンテキスト付き(self) -> None:
        asset_data = {"best_headlines": [], "worst_headlines": []}

        prompt = RSAInsightExtractor.build_prompt(
            asset_data=asset_data,
            strategic_context="ターゲット: 30代女性",
        )

        assert "戦略コンテキスト" in prompt
        assert "30代女性" in prompt

    def test_キーワードなし(self) -> None:
        asset_data = {"best_headlines": [], "worst_headlines": []}

        prompt = RSAInsightExtractor.build_prompt(asset_data=asset_data)

        assert "(Not specified)" in prompt

    def test_空データ(self) -> None:
        prompt = RSAInsightExtractor.build_prompt(asset_data={})

        assert "(No data)" in prompt


@pytest.mark.unit
class TestRSAInsightExtractorParseResponse:
    def test_正常なJSONレスポンス(self) -> None:
        response = json.dumps(
            {
                "winning_patterns": ["数字訴求が効果的"],
                "losing_patterns": ["一般的すぎる表現"],
                "recommendations": ["数字入りの見出しを追加"],
                "new_ad_variants": [
                    {
                        "headlines": ["見出し1", "見出し2"],
                        "descriptions": ["説明文1"],
                        "rationale": "勝因を活用",
                    }
                ],
            }
        )

        result = RSAInsightExtractor.parse_response(response)

        assert isinstance(result, RSAInsight)
        assert len(result.winning_patterns) == 1
        assert len(result.losing_patterns) == 1
        assert len(result.recommendations) == 1
        assert len(result.new_ad_variants) == 1
        assert result.error is None

    def test_markdownコードブロック付き(self) -> None:
        response = '```json\n{"winning_patterns": ["テスト"], "losing_patterns": [], "recommendations": [], "new_ad_variants": []}\n```'

        result = RSAInsightExtractor.parse_response(response)

        assert result.winning_patterns == ("テスト",)
        assert result.error is None

    def test_不正JSON(self) -> None:
        result = RSAInsightExtractor.parse_response("これはJSONではありません")

        assert result.error is not None
        assert result.winning_patterns == ()

    def test_空レスポンス(self) -> None:
        result = RSAInsightExtractor.parse_response("")

        assert result.error is not None


# ===========================================================================
# IntentClassifier
# ===========================================================================


@pytest.mark.unit
class TestIntentClassifierBuildPrompt:
    def test_基本プロンプト生成(self) -> None:
        prompt = IntentClassifier.build_prompt(
            search_terms=["テスト 購入", "テスト とは"],
            campaign_name="テストキャンペーン",
            keywords=["テスト"],
        )

        assert "テスト 購入" in prompt
        assert "テスト とは" in prompt
        assert "テストキャンペーン" in prompt

    def test_戦略コンテキスト付き(self) -> None:
        prompt = IntentClassifier.build_prompt(
            search_terms=["テスト"],
            strategic_context="ターゲット: BtoB企業",
        )

        assert "戦略情報" in prompt
        assert "BtoB企業" in prompt

    def test_キャンペーン名なし(self) -> None:
        prompt = IntentClassifier.build_prompt(search_terms=["テスト"])

        assert "（未指定）" in prompt

    def test_キーワードなし(self) -> None:
        prompt = IntentClassifier.build_prompt(search_terms=["テスト"])

        assert "（未指定）" in prompt


@pytest.mark.unit
class TestIntentClassifierParseResponse:
    def test_正常なJSONレスポンス(self) -> None:
        response = json.dumps(
            [
                {
                    "search_term": "テスト 購入",
                    "intent": "transactional",
                    "relevance_score": 90,
                    "reasoning": "購入意図が明確",
                    "exclude_recommendation": False,
                },
                {
                    "search_term": "テスト とは",
                    "intent": "informational",
                    "relevance_score": 30,
                    "reasoning": "情報収集目的",
                    "exclude_recommendation": True,
                },
            ]
        )

        results = IntentClassifier.parse_response(
            response, ["テスト 購入", "テスト とは"]
        )

        assert len(results) == 2
        assert results[0].intent == INTENT_TRANSACTIONAL
        assert results[0].relevance_score == 90
        assert results[0].exclude_recommendation is False
        assert results[1].intent == INTENT_INFORMATIONAL
        assert results[1].exclude_recommendation is True

    def test_markdownコードブロック付き(self) -> None:
        response = '```json\n[{"search_term": "テスト", "intent": "navigational", "relevance_score": 80, "reasoning": "test", "exclude_recommendation": false}]\n```'

        results = IntentClassifier.parse_response(response, ["テスト"])

        assert len(results) == 1
        assert results[0].intent == INTENT_NAVIGATIONAL

    def test_不正JSON_デフォルト分類(self) -> None:
        results = IntentClassifier.parse_response("invalid json", ["語句1", "語句2"])

        assert len(results) == 2
        for r in results:
            assert r.intent == INTENT_INFORMATIONAL
            assert r.relevance_score == 50
            assert "parse failure" in r.reasoning

    def test_不正intent値のフォールバック(self) -> None:
        response = json.dumps(
            [
                {
                    "search_term": "テスト",
                    "intent": "invalid_intent",
                    "relevance_score": 50,
                    "reasoning": "テスト",
                    "exclude_recommendation": False,
                }
            ]
        )

        results = IntentClassifier.parse_response(response, ["テスト"])

        assert results[0].intent == INTENT_INFORMATIONAL

    def test_relevance_scoreのクランプ(self) -> None:
        response = json.dumps(
            [
                {
                    "search_term": "テスト",
                    "intent": "transactional",
                    "relevance_score": 150,
                    "reasoning": "テスト",
                    "exclude_recommendation": False,
                }
            ]
        )

        results = IntentClassifier.parse_response(response, ["テスト"])

        assert results[0].relevance_score == 100

    def test_LLM出力と元語句のマッチング(self) -> None:
        """LLM出力の語句順序が異なっても正しくマッチする"""
        response = json.dumps(
            [
                {
                    "search_term": "語句B",
                    "intent": "commercial_investigation",
                    "relevance_score": 70,
                    "reasoning": "B",
                    "exclude_recommendation": False,
                },
                {
                    "search_term": "語句A",
                    "intent": "transactional",
                    "relevance_score": 90,
                    "reasoning": "A",
                    "exclude_recommendation": False,
                },
            ]
        )

        results = IntentClassifier.parse_response(response, ["語句A", "語句B"])

        assert results[0].search_term == "語句A"
        assert results[0].intent == INTENT_TRANSACTIONAL
        assert results[1].search_term == "語句B"
        assert results[1].intent == INTENT_COMMERCIAL


@pytest.mark.unit
class TestIntentConstants:
    def test_定数値(self) -> None:
        assert INTENT_TRANSACTIONAL == "transactional"
        assert INTENT_COMMERCIAL == "commercial_investigation"
        assert INTENT_INFORMATIONAL == "informational"
        assert INTENT_NAVIGATIONAL == "navigational"

    def test_valid_intents(self) -> None:
        assert len(VALID_INTENTS) == 4


@pytest.mark.unit
class TestSearchTermIntent:
    def test_イミュータブル(self) -> None:
        intent = SearchTermIntent(
            search_term="テスト",
            intent="transactional",
            relevance_score=90,
            reasoning="購入意図",
            exclude_recommendation=False,
        )
        with pytest.raises(AttributeError):
            intent.intent = "informational"  # type: ignore[misc]


# ===========================================================================
# MessageMatchEvaluator
# ===========================================================================


@pytest.mark.unit
class TestMessageMatchEvaluatorBuildPrompt:
    def test_基本プロンプト生成(self) -> None:
        evaluator = MessageMatchEvaluator()

        prompt = evaluator.build_prompt(
            headlines=["見出し1", "見出し2"],
            descriptions=["説明文1"],
        )

        assert "見出し1" in prompt
        assert "見出し2" in prompt
        assert "説明文1" in prompt
        assert "メッセージマッチ" in prompt

    def test_戦略コンテキスト付き(self) -> None:
        evaluator = MessageMatchEvaluator()

        prompt = evaluator.build_prompt(
            headlines=["見出し"],
            descriptions=["説明文"],
            strategic_context="ターゲット: 20代男性",
        )

        assert "戦略コンテキスト" in prompt
        assert "20代男性" in prompt


@pytest.mark.unit
class TestMessageMatchEvaluatorParseResponse:
    def test_正常なJSONレスポンス(self) -> None:
        response = json.dumps(
            {
                "overall_score": 8,
                "headline_match": 9,
                "description_match": 7,
                "cta_match": 8,
                "strengths": ["見出しとLPが一致"],
                "weaknesses": ["価格情報が不足"],
                "suggestions": ["価格訴求を追加"],
            }
        )

        result = MessageMatchEvaluator.parse_response(response)

        assert isinstance(result, MessageMatchResult)
        assert result.overall_score == 8
        assert result.headline_match == 9
        assert result.description_match == 7
        assert result.cta_match == 8
        assert result.strengths == ("見出しとLPが一致",)
        assert result.weaknesses == ("価格情報が不足",)
        assert result.suggestions == ("価格訴求を追加",)
        assert result.error is None

    def test_markdownコードブロック付き(self) -> None:
        response = '```json\n{"overall_score": 5, "headline_match": 5, "description_match": 5, "cta_match": 5, "strengths": [], "weaknesses": [], "suggestions": []}\n```'

        result = MessageMatchEvaluator.parse_response(response)

        assert result.overall_score == 5
        assert result.error is None

    def test_不正JSON(self) -> None:
        result = MessageMatchEvaluator.parse_response("不正なJSON")

        assert result.error is not None
        assert result.overall_score == 0

    def test_空レスポンス(self) -> None:
        result = MessageMatchEvaluator.parse_response("")

        assert result.error is not None


@pytest.mark.unit
class TestMessageMatchResult:
    def test_イミュータブル(self) -> None:
        result = MessageMatchResult(
            url="https://example.com",
            overall_score=8,
            headline_match=9,
            description_match=7,
            cta_match=8,
            strengths=("テスト",),
            weaknesses=(),
            suggestions=(),
        )
        with pytest.raises(AttributeError):
            result.overall_score = 5  # type: ignore[misc]

    def test_エラー付き(self) -> None:
        result = MessageMatchResult(
            url="",
            overall_score=0,
            headline_match=0,
            description_match=0,
            cta_match=0,
            strengths=(),
            weaknesses=(),
            suggestions=(),
            error="Failed to parse",
        )

        assert result.error == "Failed to parse"


@pytest.mark.unit
class TestRSAInsight:
    def test_イミュータブル(self) -> None:
        insight = RSAInsight(
            winning_patterns=("テスト",),
            losing_patterns=(),
            recommendations=(),
            new_ad_variants=(),
        )
        with pytest.raises(AttributeError):
            insight.error = "テスト"  # type: ignore[misc]


# ===========================================================================
# LPScreenshotter (SSRF検証・import失敗パス)
# ===========================================================================


@pytest.mark.unit
class TestLPScreenshotterCapture:
    @pytest.mark.asyncio
    async def test_ssrf対策でプライベートIPを拒否(self) -> None:
        """SSRF対策: LPAnalyzer._validate_url経由でプライベートIPを拒否"""
        from unittest.mock import patch

        screenshotter = LPScreenshotter()

        with patch(
            "mureo.analysis.lp_analyzer.LPAnalyzer._validate_url",
            side_effect=ValueError("Invalid URL"),
        ):
            with pytest.raises(ValueError, match="Invalid URL"):
                await screenshotter.capture("http://127.0.0.1/internal")

    @pytest.mark.asyncio
    async def test_playwrightが未インストールの場合(self) -> None:
        """playwright未インストール時にRuntimeErrorを送出"""
        import sys
        from unittest.mock import patch

        screenshotter = LPScreenshotter()

        # _validate_urlは通過させ、playwright importで失敗させる
        with patch(
            "mureo.analysis.lp_analyzer.LPAnalyzer._validate_url",
        ):
            # playwrightモジュールを一時的にブロック
            import importlib

            _real_import = builtins.__import__

            def _mock_import(name: str, *args: object, **kwargs: object) -> object:
                if "playwright" in name:
                    raise ImportError("No module named 'playwright'")
                return _real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=_mock_import):
                with pytest.raises(RuntimeError, match="Playwright"):
                    await screenshotter.capture("https://example.com")


@pytest.mark.unit
class TestMessageMatchEvaluatorParseResponseEdgeCases:
    def test_コードブロックのみ_jsonラベルなし(self) -> None:
        """```だけでjsonラベルがないコードブロックをパースする（行145カバー）"""
        response = '```\n{"overall_score": 6, "headline_match": 7, "description_match": 5, "cta_match": 6, "strengths": ["OK"], "weaknesses": [], "suggestions": []}\n```'

        result = MessageMatchEvaluator.parse_response(response)

        assert result.overall_score == 6
        assert result.headline_match == 7
        assert result.error is None

    def test_戦略コンテキストなしのプロンプト(self) -> None:
        """strategic_context=Noneの場合、戦略コンテキストセクションが含まれない"""
        evaluator = MessageMatchEvaluator()

        prompt = evaluator.build_prompt(
            headlines=["テスト見出し"],
            descriptions=["テスト説明文"],
            strategic_context=None,
        )

        assert "戦略コンテキスト" not in prompt
        assert "テスト見出し" in prompt
