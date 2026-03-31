"""LP（ランディングページ）解析エンジン

Google Ads APIに依存しない純粋なHTTP + HTML解析モジュール。
LPのURLからタイトル・見出し・特徴・CTA・価格・業界推定等を構造化して返す。
"""

from __future__ import annotations

import copy
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 500_000  # 500KB
_TIMEOUT_SECONDS = 15
_MAX_MAIN_TEXT_LENGTH = 1500
_USER_AGENT = (
    "Mozilla/5.0 (compatible; MarketingAgent/1.0; +https://example.com/bot)"
)

# 価格パターン（日本円）
_PRICE_PATTERN = re.compile(r"[￥¥][\d,]+|[\d,]+円")

# 業界推定キーワード辞書
_INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "美容": ("エステ", "脱毛", "美容", "化粧品", "スキンケア", "コスメ", "美白"),
    "不動産": ("物件", "賃貸", "マンション", "不動産", "住宅", "リフォーム", "建売"),
    "SaaS": ("クラウド", "SaaS", "ツール", "プラン", "無料トライアル", "API", "ダッシュボード"),
    "EC": ("通販", "ショップ", "カート", "送料無料", "お買い物", "購入", "注文"),
    "医療": ("クリニック", "病院", "診療", "治療", "医師", "予約", "健康診断"),
    "教育": ("スクール", "講座", "学習", "資格", "セミナー", "研修", "受講"),
    "金融": ("融資", "ローン", "保険", "投資", "金利", "口座", "クレジット"),
    "人材": ("求人", "転職", "採用", "年収", "キャリア", "エントリー", "応募"),
    "飲食": ("レストラン", "メニュー", "予約", "テイクアウト", "デリバリー", "グルメ"),
    "旅行": ("ツアー", "宿泊", "ホテル", "旅行", "予約", "航空券", "観光"),
}

# 除外するHTML要素
_EXCLUDE_TAGS = frozenset({"script", "style", "nav", "footer", "header", "noscript"})

# SSRF対策: 許可するURLスキーム
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# SSRF対策: ブロックするホスト名
_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # nosec B104
    "::1",
    "169.254.169.254",  # クラウドメタデータサービス
    "metadata.google.internal",
})


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LPContent:
    """LP解析結果を格納するイミュータブルデータクラス"""

    url: str
    title: str = ""
    meta_description: str = ""
    h1_texts: tuple[str, ...] = ()
    h2_texts: tuple[str, ...] = ()
    main_text: str = ""
    cta_texts: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    prices: tuple[str, ...] = ()
    brand_name: str = ""
    industry_hints: tuple[str, ...] = ()
    og_title: str = ""
    og_description: str = ""
    structured_data: tuple[dict[str, Any], ...] = ()
    error: str | None = None


# ---------------------------------------------------------------------------
# 解析クラス
# ---------------------------------------------------------------------------


class LPAnalyzer:
    """LP（ランディングページ）を取得・解析するクラス"""

    async def analyze(self, url: str) -> LPContent:
        """URLからLPを取得し、構造化データを返す。

        エラー時はerrorフィールドにメッセージを設定したLPContentを返す（例外を投げない）。
        """
        try:
            html = await self._fetch_html(url)
        except ValueError as exc:
            # バリデーションエラー（SSRF対策等）はそのまま返す
            logger.warning("LP URL検証に失敗: url=%s, error=%s", url, exc)
            return LPContent(url=url, error=str(exc))
        except Exception as exc:
            logger.warning("LP取得に失敗: url=%s, error=%s", url, exc)
            return LPContent(
                url=url,
                error="LP取得に失敗しました。URLが正しいか確認してください。",
            )

        try:
            return self._parse_html(url, html)
        except Exception as exc:
            logger.warning("HTMLパースに失敗: url=%s, error=%s", url, exc)
            return LPContent(
                url=url,
                error="LPの解析に失敗しました。ページの形式が対応していない可能性があります。",
            )

    @staticmethod
    def _validate_url(url: str) -> None:
        """SSRF対策: URLを検証する。

        プライベートIP・ローカルホスト・クラウドメタデータ等への
        リクエストをブロックする。
        """
        parsed = urlparse(url)

        # スキーム検証
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"許可されていないURLスキームです: {parsed.scheme}")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URLにホスト名が含まれていません")

        # 既知の危険ホストをブロック
        if hostname in _BLOCKED_HOSTS:
            raise ValueError("内部ネットワークのURLは許可されていません")

        # IPアドレスの場合、プライベート/ローカル/リンクローカルをブロック
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("内部ネットワークのURLは許可されていません")
        except ValueError as exc:
            if "内部ネットワーク" in str(exc):
                raise
            # ホスト名がIPアドレスでない場合 → DNS解決してチェック
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for _, _, _, _, addr in resolved:
                    ip = ipaddress.ip_address(addr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        raise ValueError("内部ネットワークに解決されるURLは許可されていません")
            except socket.gaierror:
                pass  # DNS解決失敗はHTTPリクエスト時にエラーになる

    async def _fetch_html(self, url: str) -> str:
        """HTTPでHTMLを取得する"""
        self._validate_url(url)
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
            # リダイレクト先もSSRF検証
            final_url = str(response.url)
            if final_url != url:
                self._validate_url(final_url)
            response.raise_for_status()
            # サイズ制限
            if len(response.content) > _MAX_BODY_BYTES:
                return response.content[:_MAX_BODY_BYTES].decode(
                    response.encoding or "utf-8", errors="replace"
                )
            return response.text

    def _parse_html(self, url: str, html: str) -> LPContent:
        """HTMLを解析してLPContentを構築する"""
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        meta_description = self._extract_meta_description(soup)
        h1_texts = self._extract_headings(soup, "h1")
        h2_texts = self._extract_headings(soup, "h2")
        main_text = self._extract_main_text(soup)
        cta_texts = self._extract_cta_texts(soup)
        features = self._extract_features(soup)
        prices = self._extract_prices(main_text)
        brand_name = self._extract_brand_name(soup, url)
        og_title = self._extract_og_property(soup, "og:title")
        og_description = self._extract_og_property(soup, "og:description")
        structured_data = self._extract_structured_data(soup)

        # 業界推定
        all_text = " ".join([title, meta_description, main_text])
        industry_hints = self._estimate_industry(all_text)

        return LPContent(
            url=url,
            title=title,
            meta_description=meta_description,
            h1_texts=h1_texts,
            h2_texts=h2_texts,
            main_text=main_text,
            cta_texts=cta_texts,
            features=features,
            prices=prices,
            brand_name=brand_name,
            industry_hints=industry_hints,
            og_title=og_title,
            og_description=og_description,
            structured_data=structured_data,
        )

    # --- 個別抽出メソッド ---

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _extract_meta_description(soup: BeautifulSoup) -> str:
        tag = soup.find("meta", attrs={"name": "description"})
        if tag and isinstance(tag, Tag):
            return str(tag.get("content", "")).strip()
        return ""

    @staticmethod
    def _extract_headings(soup: BeautifulSoup, tag_name: str) -> tuple[str, ...]:
        return tuple(
            h.get_text(strip=True) for h in soup.find_all(tag_name) if h.get_text(strip=True)
        )

    @staticmethod
    def _extract_main_text(soup: BeautifulSoup) -> str:
        """script/style/nav/footer等を除外した本文テキストを取得

        注意: soupのコピーに対して操作し、元のsoupを破壊しない。
        """
        soup_copy = copy.copy(soup)
        for tag in soup_copy.find_all(_EXCLUDE_TAGS):
            tag.decompose()

        text = soup_copy.get_text(separator=" ", strip=True)
        # 連続空白を正規化
        text = re.sub(r"\s+", " ", text).strip()
        return text[:_MAX_MAIN_TEXT_LENGTH]

    @staticmethod
    def _extract_cta_texts(soup: BeautifulSoup) -> tuple[str, ...]:
        """CTA（行動喚起）テキストを抽出"""
        ctas: list[str] = []

        # button要素
        for btn in soup.find_all("button"):
            text = btn.get_text(strip=True)
            if text:
                ctas.append(text)

        # input[type=submit]
        for inp in soup.find_all("input", attrs={"type": "submit"}):
            if isinstance(inp, Tag):
                val = str(inp.get("value", "")).strip()
                if val:
                    ctas.append(val)

        # a.btn* (CSSクラス名にbtnを含むリンク)
        for a_tag in soup.find_all("a", class_=True):
            if isinstance(a_tag, Tag):
                classes = a_tag.get("class", [])
                if isinstance(classes, list) and any("btn" in c for c in classes):
                    text = a_tag.get_text(strip=True)
                    if text:
                        ctas.append(text)

        # 重複除去（順序保持）
        seen: set[str] = set()
        unique: list[str] = []
        for c in ctas:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return tuple(unique)

    @staticmethod
    def _extract_features(soup: BeautifulSoup) -> tuple[str, ...]:
        """ul/olリスト項目から特徴を抽出"""
        items: list[str] = []
        for list_tag in soup.find_all(["ul", "ol"]):
            for li in list_tag.find_all("li", recursive=False):
                text = li.get_text(strip=True)
                if text and len(text) > 3:
                    items.append(text)
        return tuple(items[:30])  # 上限30件

    @staticmethod
    def _extract_prices(text: str) -> tuple[str, ...]:
        """価格情報を正規表現で抽出"""
        matches = _PRICE_PATTERN.findall(text)
        # 重複除去
        seen: set[str] = set()
        unique: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return tuple(unique[:10])  # 上限10件

    @staticmethod
    def _extract_brand_name(soup: BeautifulSoup, url: str) -> str:
        """ブランド名を推定（og:site_name → ドメイン名）"""
        og_site = soup.find("meta", attrs={"property": "og:site_name"})
        if og_site and isinstance(og_site, Tag):
            name = str(og_site.get("content", "")).strip()
            if name:
                return name
        # フォールバック: URLからドメイン名を抽出
        try:
            parsed = urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return ""

    @staticmethod
    def _extract_og_property(soup: BeautifulSoup, property_name: str) -> str:
        """OGP プロパティを取得"""
        tag = soup.find("meta", attrs={"property": property_name})
        if tag and isinstance(tag, Tag):
            return str(tag.get("content", "")).strip()
        return ""

    @staticmethod
    def _extract_structured_data(soup: BeautifulSoup) -> tuple[dict[str, Any], ...]:
        """JSON-LD構造化データを抽出"""
        results: list[dict[str, Any]] = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            text = script.get_text(strip=True)
            if not text:
                continue
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    results.append(data)
                elif isinstance(data, list):
                    results.extend(d for d in data if isinstance(d, dict))
            except (json.JSONDecodeError, ValueError):
                continue
        return tuple(results[:5])  # 上限5件

    @staticmethod
    def _estimate_industry(text: str) -> tuple[str, ...]:
        """テキストからキーワード辞書マッチで業界を推定"""
        text_lower = text.lower()
        matched: list[str] = []
        for industry, keywords in _INDUSTRY_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if count >= 2:
                matched.append(industry)
        return tuple(matched)
