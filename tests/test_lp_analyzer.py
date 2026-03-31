"""LP analyzer テスト

HTML解析ロジックのテスト。外部HTTPなしでテスト可能（HTMLをモックデータで渡す）。
"""

from __future__ import annotations

import pytest

from mureo.analysis.lp_analyzer import (
    LPAnalyzer,
    LPContent,
    _BLOCKED_HOSTS,
    _INDUSTRY_KEYWORDS,
)


# ---------------------------------------------------------------------------
# テスト用HTML
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head>
    <title>テスト商品 | テストブランド</title>
    <meta name="description" content="テスト商品の説明文です。高品質な商品をお届けします。">
    <meta property="og:title" content="OGテスト商品">
    <meta property="og:description" content="OG説明文です">
    <meta property="og:site_name" content="テストブランド">
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "テスト商品"
    }
    </script>
</head>
<body>
    <header>ヘッダー</header>
    <h1>メイン見出し</h1>
    <h2>サブ見出し1</h2>
    <h2>サブ見出し2</h2>
    <p>本文テキストです。商品の特徴を説明します。価格は￥10,000です。</p>
    <ul>
        <li>特徴1: 高品質な素材</li>
        <li>特徴2: 送料無料</li>
        <li>特徴3: 30日間返品保証</li>
        <li>短い</li>
    </ul>
    <button>今すぐ購入</button>
    <input type="submit" value="申し込み">
    <a class="btn-primary" href="/order">注文する</a>
    <footer>フッター</footer>
    <script>console.log('除外対象');</script>
    <style>.excluded { display: none; }</style>
</body>
</html>
"""

_MINIMAL_HTML = """\
<!DOCTYPE html>
<html><head><title>最小ページ</title></head>
<body><p>コンテンツ</p></body></html>
"""


@pytest.fixture
def analyzer() -> LPAnalyzer:
    return LPAnalyzer()


# ---------------------------------------------------------------------------
# _parse_html テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseHtml:
    def test_タイトル抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert result.title == "テスト商品 | テストブランド"

    def test_メタディスクリプション抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert "テスト商品の説明文" in result.meta_description

    def test_h1抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert result.h1_texts == ("メイン見出し",)

    def test_h2抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert result.h2_texts == ("サブ見出し1", "サブ見出し2")

    def test_CTA抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert "今すぐ購入" in result.cta_texts
        assert "申し込み" in result.cta_texts
        assert "注文する" in result.cta_texts

    def test_特徴抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        # 3文字以下のliは除外される
        assert any("高品質" in f for f in result.features)
        assert not any(f == "短い" for f in result.features)

    def test_価格抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert "￥10,000" in result.prices

    def test_ブランド名抽出_og_site_name(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert result.brand_name == "テストブランド"

    def test_ブランド名_フォールバック(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://www.example.com", _MINIMAL_HTML)

        assert result.brand_name == "example.com"

    def test_OGP抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert result.og_title == "OGテスト商品"
        assert result.og_description == "OG説明文です"

    def test_構造化データ抽出(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert len(result.structured_data) == 1
        assert result.structured_data[0]["@type"] == "Product"

    def test_本文テキスト_script_style除外(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com", _SAMPLE_HTML)

        assert "console.log" not in result.main_text
        assert ".excluded" not in result.main_text

    def test_URLの保持(self, analyzer: LPAnalyzer) -> None:
        result = analyzer._parse_html("https://example.com/test", _SAMPLE_HTML)

        assert result.url == "https://example.com/test"


# ---------------------------------------------------------------------------
# 業界推定テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEstimateIndustry:
    def test_SaaS業界推定(self, analyzer: LPAnalyzer) -> None:
        text = "クラウドSaaSツールの無料トライアルをお試しください"
        hints = analyzer._estimate_industry(text)

        assert "SaaS" in hints

    def test_美容業界推定(self, analyzer: LPAnalyzer) -> None:
        text = "エステサロンの脱毛メニュー。美容のプロが対応"
        hints = analyzer._estimate_industry(text)

        assert "美容" in hints

    def test_該当なし(self, analyzer: LPAnalyzer) -> None:
        text = "一般的なテキストです"
        hints = analyzer._estimate_industry(text)

        assert hints == ()

    def test_2キーワード未満では判定しない(self, analyzer: LPAnalyzer) -> None:
        text = "クラウドの活用"  # SaaSキーワード1個のみ
        hints = analyzer._estimate_industry(text)

        assert "SaaS" not in hints


# ---------------------------------------------------------------------------
# SSRF対策テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateUrl:
    def test_正常なURL(self, analyzer: LPAnalyzer) -> None:
        # 例外が発生しなければOK
        analyzer._validate_url("https://example.com")

    def test_localhostブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="(?i)internal network"):
            analyzer._validate_url("http://localhost/test")

    def test_127_0_0_1ブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="(?i)internal network"):
            analyzer._validate_url("http://127.0.0.1/test")

    def test_メタデータサービスブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="(?i)internal network"):
            analyzer._validate_url("http://169.254.169.254/latest/meta-data")

    def test_ftpスキームブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            analyzer._validate_url("ftp://example.com/file")

    def test_ホスト名なしブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="hostname"):
            analyzer._validate_url("https://")

    def test_プライベートIPブロック(self, analyzer: LPAnalyzer) -> None:
        with pytest.raises(ValueError, match="(?i)internal network"):
            analyzer._validate_url("http://10.0.0.1/test")

    def test_ipv6_loopbackブロック(self, analyzer: LPAnalyzer) -> None:
        # ::1はurlparseでhostnameがNoneになるため「ホスト名」エラー
        # ブラケット付き[::1]の場合は「内部ネットワーク」エラー
        with pytest.raises(ValueError):
            analyzer._validate_url("http://[::1]/test")


# ---------------------------------------------------------------------------
# LPContent データクラステスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLPContent:
    def test_イミュータブル(self) -> None:
        content = LPContent(url="https://example.com")
        with pytest.raises(AttributeError):
            content.url = "https://other.com"  # type: ignore[misc]

    def test_デフォルト値(self) -> None:
        content = LPContent(url="https://example.com")

        assert content.title == ""
        assert content.h1_texts == ()
        assert content.error is None

    def test_エラー付き(self) -> None:
        content = LPContent(url="https://example.com", error="取得失敗")

        assert content.error == "取得失敗"
