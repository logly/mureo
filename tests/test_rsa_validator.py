"""RSA validator テスト

_rsa_validator.pyの純粋な検証ロジックをテストする。
DB/API不要でテスト可能。
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
    def test_半角英数(self) -> None:
        assert display_width("abc") == 3

    def test_全角文字(self) -> None:
        assert display_width("テスト") == 6

    def test_混在(self) -> None:
        assert display_width("ABCテスト") == 9

    def test_空文字(self) -> None:
        assert display_width("") == 0

    def test_見出し上限(self) -> None:
        assert HEADLINE_MAX_WIDTH == 30

    def test_説明文上限(self) -> None:
        assert DESCRIPTION_MAX_WIDTH == 90


# ---------------------------------------------------------------------------
# _sanitize_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSanitizeText:
    def test_連続感嘆符の縮約(self) -> None:
        text, fixes = _sanitize_text("素晴らしい！！！")
        assert text == "素晴らしい！"
        assert any("句読点" in f for f in fixes)

    def test_連続疑問符の縮約(self) -> None:
        text, fixes = _sanitize_text("本当？？？")
        assert text == "本当？"

    def test_装飾記号の縮約(self) -> None:
        text, fixes = _sanitize_text("★★★限定")
        assert text == "★限定"
        assert any("装飾記号" in f for f in fixes)

    def test_全角スペースの正規化(self) -> None:
        text, fixes = _sanitize_text("商品\u3000\u3000紹介")
        assert text == "商品 紹介"
        assert any("全角スペース" in f for f in fixes)

    def test_先頭末尾記号の除去(self) -> None:
        text, fixes = _sanitize_text("！見出し。")
        assert text == "見出し"
        assert any("先頭・末尾" in f for f in fixes)

    def test_半角カタカナの変換(self) -> None:
        text, fixes = _sanitize_text("ｷｰﾜｰﾄﾞ")
        assert text == "キーワード"
        assert any("半角カタカナ" in f for f in fixes)

    def test_絵文字の除去(self) -> None:
        text, fixes = _sanitize_text("限定セール\U0001f525")
        assert text == "限定セール"
        assert any("絵文字" in f for f in fixes)

    def test_正常テキストは修正なし(self) -> None:
        text, fixes = _sanitize_text("正常な広告テキスト")
        assert text == "正常な広告テキスト"
        assert fixes == []

    def test_超長テキストの切り詰め(self) -> None:
        long_text = "あ" * 300
        text, fixes = _sanitize_text(long_text)
        assert len(text) <= 200
        assert any("切り詰め" in f for f in fixes)


# ---------------------------------------------------------------------------
# _check_prohibited
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckProhibited:
    def test_最上級表現(self) -> None:
        warnings = _check_prohibited("世界一の品質")
        assert any("世界一" in w for w in warnings)

    def test_価格系表現(self) -> None:
        warnings = _check_prohibited("最安値で提供")
        assert any("最安値" in w for w in warnings)

    def test_効果保証表現(self) -> None:
        warnings = _check_prohibited("効果保証付き")
        assert any("効果保証" in w for w in warnings)

    def test_医療系表現(self) -> None:
        warnings = _check_prohibited("これで治る")
        assert any("治る" in w for w in warnings)

    def test_クリックベイト(self) -> None:
        warnings = _check_prohibited("こちらをクリック")
        assert any("クリックベイト" in w for w in warnings)

    def test_正常テキスト(self) -> None:
        warnings = _check_prohibited("高品質な商品をお届け")
        assert warnings == []


# ---------------------------------------------------------------------------
# validate_rsa_texts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateRsaTexts:
    def test_正常なRSAテキスト(self) -> None:
        result = validate_rsa_texts(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1です", "説明文2です"],
            final_url="https://example.com",
        )

        assert isinstance(result, RSAValidationResult)
        assert len(result.headlines) == 3
        assert len(result.descriptions) == 2

    def test_URLなしでValueError(self) -> None:
        with pytest.raises(ValueError, match="final_url"):
            validate_rsa_texts(
                headlines=["見出し"],
                descriptions=["説明文"],
                final_url="",
            )

    def test_不正URLでValueError(self) -> None:
        with pytest.raises(ValueError, match="不正なURL"):
            validate_rsa_texts(
                headlines=["見出し"],
                descriptions=["説明文"],
                final_url="invalid-url",
            )

    def test_重複見出しの除去(self) -> None:
        result = validate_rsa_texts(
            headlines=["同じ見出し", "同じ見出し", "別の見出し"],
            descriptions=["説明文"],
            final_url="https://example.com",
        )

        assert len(result.headlines) == 2
        assert any("重複" in w for w in result.warnings)

    def test_文字幅超過でValueError(self) -> None:
        long_headline = "あ" * 20  # 全角20文字 = 幅40 > 30
        with pytest.raises(ValueError, match="文字数制限"):
            validate_rsa_texts(
                headlines=[long_headline],
                descriptions=["説明文"],
                final_url="https://example.com",
            )

    def test_禁止表現で警告(self) -> None:
        result = validate_rsa_texts(
            headlines=["世界一の品質"],
            descriptions=["説明文です"],
            final_url="https://example.com",
        )

        assert any("世界一" in w for w in result.warnings)

    def test_サニタイズ適用(self) -> None:
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
    def test_同一文字列(self) -> None:
        assert _bigram_similarity("テスト", "テスト") == 1.0

    def test_完全に異なる文字列(self) -> None:
        sim = _bigram_similarity("あいう", "かきく")
        assert sim == 0.0

    def test_短い文字列(self) -> None:
        assert _bigram_similarity("a", "a") == 1.0
        assert _bigram_similarity("a", "b") == 0.0


# ---------------------------------------------------------------------------
# _has_synonym_overlap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasSynonymOverlap:
    def test_同義語ペア検出(self) -> None:
        assert _has_synonym_overlap("安い商品", "格安セール") is True

    def test_同義語なし(self) -> None:
        assert _has_synonym_overlap("高品質", "高速配送") is False


# ---------------------------------------------------------------------------
# _check_headline_diversity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckHeadlineDiversity:
    def test_多様な見出し(self) -> None:
        score, msgs = _check_headline_diversity(["商品紹介", "お客様の声", "無料体験"])
        assert score > 0.5
        assert msgs == []

    def test_単一見出し(self) -> None:
        score, msgs = _check_headline_diversity(["テスト"])
        assert score == 1.0

    def test_同義語含む見出し(self) -> None:
        score, msgs = _check_headline_diversity(["安い商品", "格安セール"])
        assert score < 1.0
        assert len(msgs) > 0


# ---------------------------------------------------------------------------
# _check_keyword_relevance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckKeywordRelevance:
    def test_全キーワード含有(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト商品の紹介"],
            ["テストの説明文"],
            ["テスト", "商品"],
        )
        assert score == 1.0
        assert missing == []

    def test_一部未含有(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト"],
            ["説明文"],
            ["テスト", "未知のKW"],
        )
        assert score == 0.5
        assert "未知のKW" in missing

    def test_キーワードなし(self) -> None:
        score, missing = _check_keyword_relevance(
            ["テスト"], ["説明文"], [],
        )
        assert score == 0.5


# ---------------------------------------------------------------------------
# _strip_match_type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStripMatchType:
    def test_フレーズマッチ(self) -> None:
        assert _strip_match_type('"テスト"') == "テスト"

    def test_完全一致(self) -> None:
        assert _strip_match_type("[テスト]") == "テスト"

    def test_絞り込み部分一致(self) -> None:
        assert _strip_match_type("+テスト") == "テスト"

    def test_通常キーワード(self) -> None:
        assert _strip_match_type("テスト") == "テスト"


# ---------------------------------------------------------------------------
# predict_ad_strength
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPredictAdStrength:
    def test_最小構成(self) -> None:
        result = predict_ad_strength(
            headlines=["見出し1", "見出し2", "見出し3"],
            descriptions=["説明文1", "説明文2"],
        )

        assert isinstance(result, AdStrengthResult)
        assert result.level in ("POOR", "AVERAGE", "GOOD", "EXCELLENT")
        assert 0.0 <= result.score <= 1.0
        assert len(result.factors) == 6

    def test_最大構成でEXCELLENT(self) -> None:
        result = predict_ad_strength(
            headlines=[f"見出し{i}" for i in range(15)],
            descriptions=[f"説明文{i}" for i in range(4)],
            keywords=["見出し0", "見出し1"],
            has_sitelinks=True,
            pinned_count=0,
        )

        assert result.level in ("GOOD", "EXCELLENT")
        assert result.score >= 0.65

    def test_ピン留めでペナルティ(self) -> None:
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

    def test_サジェスチョン生成(self) -> None:
        result = predict_ad_strength(
            headlines=["見出し1"],
            descriptions=["説明文1"],
        )

        assert len(result.suggestions) > 0
