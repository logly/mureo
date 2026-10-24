"""Tests for the RSA validator.

Exercises the pure validation logic in _rsa_validator.py.
Runs without a database or external API.
"""

from __future__ import annotations

import pytest

from mureo.google_ads._rsa_validator import (
    DESCRIPTION_MAX_WIDTH,
    HEADLINE_MAX_WIDTH,
    AdStrengthResult,
    RSAValidationResult,
    _bigram_similarity,
    _check_headline_diversity,
    _check_keyword_relevance,
    _check_prohibited,
    _has_synonym_overlap,
    _sanitize_text,
    _strip_match_type,
    display_width,
    predict_ad_strength,
    validate_rsa_texts,
)

# ---------------------------------------------------------------------------
# display_width
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDisplayWidth:
    def test_ascii_alphanumeric(self) -> None:
        assert display_width("abc") == 3

    def test_full_width_characters(self) -> None:
        assert display_width("テスト") == 6

    def test_mixed_width(self) -> None:
        assert display_width("ABCテスト") == 9

    def test_empty_string(self) -> None:
        assert display_width("") == 0

    def test_headline_max_width(self) -> None:
        assert HEADLINE_MAX_WIDTH == 30

    def test_description_max_width(self) -> None:
        assert DESCRIPTION_MAX_WIDTH == 90


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSanitizeText:
    def test_collapses_repeated_exclamation_marks(self) -> None:
        text, fixes = _sanitize_text("素晴らしい！！！")
        assert text == "素晴らしい！"
        assert any("punctuation" in f.lower() for f in fixes)

    def test_collapses_repeated_question_marks(self) -> None:
        text, fixes = _sanitize_text("本当？？？")
        assert text == "本当？"

    def test_collapses_repeated_decorative_symbols(self) -> None:
        text, fixes = _sanitize_text("★★★限定")
        assert text == "★限定"
        assert any("decorative symbol" in f.lower() for f in fixes)

    def test_normalizes_full_width_spaces(self) -> None:
        text, fixes = _sanitize_text("商品\u3000\u3000紹介")
        assert text == "商品 紹介"
        assert any("full-width space" in f.lower() for f in fixes)

    def test_strips_leading_and_trailing_punctuation(self) -> None:
        text, fixes = _sanitize_text("！見出し。")
        assert text == "見出し"
        assert any("leading" in f.lower() for f in fixes)

    def test_converts_half_width_katakana(self) -> None:
        text, fixes = _sanitize_text("ｷｰﾜｰﾄﾞ")
        assert text == "キーワード"
        assert any("half-width katakana" in f.lower() for f in fixes)

    def test_removes_emoji(self) -> None:
        text, fixes = _sanitize_text("限定セール\U0001f525")
        assert text == "限定セール"
        assert any("emoji" in f.lower() for f in fixes)

    def test_clean_text_has_no_fixes(self) -> None:
        text, fixes = _sanitize_text("正常な広告テキスト")
        assert text == "正常な広告テキスト"
        assert fixes == []

    def test_truncates_overlong_text(self) -> None:
        long_text = "あ" * 300
        text, fixes = _sanitize_text(long_text)
        assert len(text) <= 200
        assert any("truncated" in f.lower() for f in fixes)


# ---------------------------------------------------------------------------
# _check_prohibited
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckProhibited:
    def test_superlative_expression(self) -> None:
        warnings = _check_prohibited("世界一の品質")
        assert any("世界一" in w for w in warnings)

    def test_price_claim_expression(self) -> None:
        warnings = _check_prohibited("最安値で提供")
        assert any("最安値" in w for w in warnings)

    def test_guaranteed_results_expression(self) -> None:
        warnings = _check_prohibited("効果保証付き")
        assert any("効果保証" in w for w in warnings)

    def test_medical_claim_expression(self) -> None:
        warnings = _check_prohibited("これで治る")
        assert any("治る" in w for w in warnings)

    def test_clickbait(self) -> None:
        warnings = _check_prohibited("こちらをクリック")
        assert any("clickbait" in w.lower() for w in warnings)

    def test_clean_text(self) -> None:
        warnings = _check_prohibited("高品質な商品をお届け")
        assert warnings == []


# ---------------------------------------------------------------------------
# validate_rsa_texts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateRsaTexts:
    def test_valid_rsa_texts(self) -> None:
        result = validate_rsa_texts(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1です", "説明文2です"],
            final_url="https://example.com",
        )

        assert isinstance(result, RSAValidationResult)
        assert len(result.headlines) == 3
        assert len(result.descriptions) == 2

    def test_missing_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="final_url"):
            validate_rsa_texts(
                headlines=["見出し"],
                descriptions=["説明文"],
                final_url="",
            )

    def test_invalid_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid URL"):
            validate_rsa_texts(
                headlines=["見出し"],
                descriptions=["説明文"],
                final_url="invalid-url",
            )

    def test_removes_duplicate_headlines(self) -> None:
        result = validate_rsa_texts(
            headlines=["同じ見出し", "同じ見出し", "別の見出し"],
            descriptions=["説明文"],
            final_url="https://example.com",
        )

        assert len(result.headlines) == 2
        assert any("duplicate" in w for w in result.warnings)

    def test_width_over_limit_raises_value_error(self) -> None:
        long_headline = "あ" * 20  # 20 full-width chars = width 40 > 30
        with pytest.raises(ValueError, match="character limit"):
            validate_rsa_texts(
                headlines=[long_headline],
                descriptions=["説明文"],
                final_url="https://example.com",
            )

    def test_prohibited_expression_warns(self) -> None:
        result = validate_rsa_texts(
            headlines=["世界一の品質"],
            descriptions=["説明文です"],
            final_url="https://example.com",
        )

        assert any("世界一" in w for w in result.warnings)

    def test_applies_sanitization(self) -> None:
        result = validate_rsa_texts(
            headlines=["素晴らしい！！！"],
            descriptions=["説明文です"],
            final_url="https://example.com",
        )

        assert result.headlines[0] == "素晴らしい！"


# ---------------------------------------------------------------------------
# _bigram_similarity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBigramSimilarity:
    def test_identical_strings(self) -> None:
        assert _bigram_similarity("テスト", "テスト") == 1.0

    def test_completely_different_strings(self) -> None:
        sim = _bigram_similarity("あいう", "かきく")
        assert sim == 0.0

    def test_short_strings(self) -> None:
        assert _bigram_similarity("a", "a") == 1.0
        assert _bigram_similarity("a", "b") == 0.0


# ---------------------------------------------------------------------------
# _has_synonym_overlap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasSynonymOverlap:
    def test_detects_synonym_pair(self) -> None:
        assert _has_synonym_overlap("安い商品", "格安セール") is True

    def test_no_synonyms(self) -> None:
        assert _has_synonym_overlap("高品質", "高速配送") is False


# ---------------------------------------------------------------------------
# _check_headline_diversity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckHeadlineDiversity:
    def test_diverse_headlines(self) -> None:
        score, msgs = _check_headline_diversity(["商品紹介", "お客様の声", "無料体験"])
        assert score > 0.5
        assert msgs == []

    def test_single_headline(self) -> None:
        score, msgs = _check_headline_diversity(["テスト"])
        assert score == 1.0

    def test_headlines_with_synonyms(self) -> None:
        score, msgs = _check_headline_diversity(["安い商品", "格安セール"])
        assert score < 1.0
        assert len(msgs) > 0


# ---------------------------------------------------------------------------
# _check_keyword_relevance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckKeywordRelevance:
    def test_all_keywords_present(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト商品の紹介"],
            ["テストの説明文"],
            ["テスト", "商品"],
        )
        assert score == 1.0
        assert missing == []

    def test_some_keywords_missing(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト"],
            ["説明文"],
            ["テスト", "未知のKW"],
        )
        assert score == 0.5
        assert "未知のKW" in missing

    def test_no_keywords(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト"],
            ["説明文"],
            [],
        )
        assert score == 0.5


# ---------------------------------------------------------------------------
# _strip_match_type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStripMatchType:
    def test_phrase_match(self) -> None:
        assert _strip_match_type('"テスト"') == "テスト"

    def test_exact_match(self) -> None:
        assert _strip_match_type("[テスト]") == "テスト"

    def test_broad_match_modifier(self) -> None:
        assert _strip_match_type("+テスト") == "テスト"

    def test_plain_keyword(self) -> None:
        assert _strip_match_type("テスト") == "テスト"


# ---------------------------------------------------------------------------
# predict_ad_strength
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPredictAdStrength:
    def test_minimum_configuration(self) -> None:
        result = predict_ad_strength(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1", "説明文2"],
        )

        assert isinstance(result, AdStrengthResult)
        assert result.level in ("POOR", "AVERAGE", "GOOD", "EXCELLENT")
        assert 0.0 <= result.score <= 1.0
        assert len(result.factors) == 6

    def test_maximum_configuration_is_excellent(self) -> None:
        result = predict_ad_strength(
            headlines=[f"見出し{i}" for i in range(15)],
            descriptions=[f"説明文{i}" for i in range(4)],
            keywords=["見出し0", "見出し1"],
            has_sitelinks=True,
            pinned_count=0,
        )

        assert result.level in ("GOOD", "EXCELLENT")
        assert result.score >= 0.65

    def test_pinning_is_penalized(self) -> None:
        base = predict_ad_strength(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1", "説明文2"],
            pinned_count=0,
        )
        pinned = predict_ad_strength(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1", "説明文2"],
            pinned_count=3,
        )

        assert pinned.score < base.score

    def test_generates_suggestions(self) -> None:
        result = predict_ad_strength(
            headlines=["見出し1"],
            descriptions=["説明文1"],
        )

        assert len(result.suggestions) > 0
