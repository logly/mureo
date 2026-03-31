"""Landing page (LP) analysis engine.

A pure HTTP + HTML analysis module independent of the Google Ads API.
Fetches an LP by URL and returns structured data: title, headings, features, CTAs,
prices, estimated industry, etc.
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
# Constants
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 500_000  # 500KB
_TIMEOUT_SECONDS = 15
_MAX_MAIN_TEXT_LENGTH = 1500
_USER_AGENT = "Mozilla/5.0 (compatible; MarketingAgent/1.0; +https://example.com/bot)"

# Price pattern (Japanese yen notation)
_PRICE_PATTERN = re.compile(r"[￥¥][\d,]+|[\d,]+円")

# Industry estimation keyword dictionary
_INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "美容": ("エステ", "脱毛", "美容", "化粧品", "スキンケア", "コスメ", "美白"),
    "不動産": ("物件", "賃貸", "マンション", "不動産", "住宅", "リフォーム", "建売"),
    "SaaS": (
        "クラウド",
        "SaaS",
        "ツール",
        "プラン",
        "無料トライアル",
        "API",
        "ダッシュボード",
    ),
    "EC": ("通販", "ショップ", "カート", "送料無料", "お買い物", "購入", "注文"),
    "医療": ("クリニック", "病院", "診療", "治療", "医師", "予約", "健康診断"),
    "教育": ("スクール", "講座", "学習", "資格", "セミナー", "研修", "受講"),
    "金融": ("融資", "ローン", "保険", "投資", "金利", "口座", "クレジット"),
    "人材": ("求人", "転職", "採用", "年収", "キャリア", "エントリー", "応募"),
    "飲食": ("レストラン", "メニュー", "予約", "テイクアウト", "デリバリー", "グルメ"),
    "旅行": ("ツアー", "宿泊", "ホテル", "旅行", "予約", "航空券", "観光"),
}

# HTML elements to exclude
_EXCLUDE_TAGS = frozenset({"script", "style", "nav", "footer", "header", "noscript"})

# SSRF protection: allowed URL schemes
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# SSRF protection: blocked hostnames
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # nosec B104
        "::1",
        "169.254.169.254",  # Cloud metadata service
        "metadata.google.internal",
    }
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LPContent:
    """Immutable data class for LP analysis results."""

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
# Analysis class
# ---------------------------------------------------------------------------


class LPAnalyzer:
    """Class for fetching and analyzing landing pages (LPs)."""

    async def analyze(self, url: str) -> LPContent:
        """Fetch an LP from a URL and return structured data.

        On error, returns an LPContent with the error field set (does not raise).
        """
        try:
            html = await self._fetch_html(url)
        except ValueError as exc:
            # Return validation errors (SSRF protection, etc.) as-is
            logger.warning("LP URL validation failed: url=%s, error=%s", url, exc)
            return LPContent(url=url, error=str(exc))
        except Exception as exc:
            logger.warning("Failed to fetch LP: url=%s, error=%s", url, exc)
            return LPContent(
                url=url,
                error="Failed to fetch LP. Please verify the URL is correct.",
            )

        try:
            return self._parse_html(url, html)
        except Exception as exc:
            logger.warning("HTML parsing failed: url=%s, error=%s", url, exc)
            return LPContent(
                url=url,
                error="Failed to analyze LP. The page format may not be supported.",
            )

    @staticmethod
    def _validate_url(url: str) -> None:
        """SSRF protection: validate a URL.

        Blocks requests to private IPs, localhost, cloud metadata endpoints, etc.
        """
        parsed = urlparse(url)

        # Scheme validation
        if parsed.scheme not in _ALLOWED_SCHEMES:
            raise ValueError(f"URL scheme not allowed: {parsed.scheme}")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL does not contain a hostname")

        # Block known dangerous hosts
        if hostname in _BLOCKED_HOSTS:
            raise ValueError("Internal network URLs are not allowed")

        # Block private/loopback/link-local IP addresses
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError("Internal network URLs are not allowed")
        except ValueError as exc:
            if "Internal network" in str(exc):
                raise
            # If hostname is not an IP address, resolve via DNS and check
            try:
                resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for _, _, _, _, addr in resolved:
                    ip = ipaddress.ip_address(addr[0])
                    if (
                        ip.is_private
                        or ip.is_loopback
                        or ip.is_link_local
                        or ip.is_reserved
                    ):
                        raise ValueError(
                            "URLs that resolve to internal networks are not allowed"
                        )
            except socket.gaierror:
                pass  # DNS resolution failure will error at HTTP request time

    async def _fetch_html(self, url: str) -> str:
        """Fetch HTML via HTTP."""
        self._validate_url(url)
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
            # Validate redirect destination for SSRF
            final_url = str(response.url)
            if final_url != url:
                self._validate_url(final_url)
            response.raise_for_status()
            # Size limit
            if len(response.content) > _MAX_BODY_BYTES:
                return response.content[:_MAX_BODY_BYTES].decode(
                    response.encoding or "utf-8", errors="replace"
                )
            return response.text

    def _parse_html(self, url: str, html: str) -> LPContent:
        """Parse HTML and build an LPContent."""
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

        # Industry estimation
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

    # --- Individual extraction methods ---

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
            h.get_text(strip=True)
            for h in soup.find_all(tag_name)
            if h.get_text(strip=True)
        )

    @staticmethod
    def _extract_main_text(soup: BeautifulSoup) -> str:
        """Extract body text excluding script/style/nav/footer etc.

        Note: Operates on a copy of soup to avoid mutating the original.
        """
        soup_copy = copy.copy(soup)
        for tag in soup_copy.find_all(_EXCLUDE_TAGS):
            tag.decompose()

        text = soup_copy.get_text(separator=" ", strip=True)
        # Normalize consecutive whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:_MAX_MAIN_TEXT_LENGTH]

    @staticmethod
    def _extract_cta_texts(soup: BeautifulSoup) -> tuple[str, ...]:
        """Extract CTA (call-to-action) texts."""
        ctas: list[str] = []

        # button elements
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

        # a.btn* (links with CSS class containing "btn")
        for a_tag in soup.find_all("a", class_=True):
            if isinstance(a_tag, Tag):
                classes = a_tag.get("class", [])  # type: ignore[arg-type]
                if isinstance(classes, list) and any("btn" in c for c in classes):
                    text = a_tag.get_text(strip=True)
                    if text:
                        ctas.append(text)

        # Deduplicate (preserve order)
        seen: set[str] = set()
        unique: list[str] = []
        for c in ctas:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        return tuple(unique)

    @staticmethod
    def _extract_features(soup: BeautifulSoup) -> tuple[str, ...]:
        """Extract features from ul/ol list items."""
        items: list[str] = []
        for list_tag in soup.find_all(["ul", "ol"]):
            for li in list_tag.find_all("li", recursive=False):  # type: ignore[union-attr, unused-ignore]
                text = li.get_text(strip=True)
                if text and len(text) > 3:
                    items.append(text)
        return tuple(items[:30])  # limit 30

    @staticmethod
    def _extract_prices(text: str) -> tuple[str, ...]:
        """Extract price information via regex."""
        matches = _PRICE_PATTERN.findall(text)
        # Deduplicate
        seen: set[str] = set()
        unique: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return tuple(unique[:10])  # limit 10

    @staticmethod
    def _extract_brand_name(soup: BeautifulSoup, url: str) -> str:
        """Estimate brand name (og:site_name -> domain name)."""
        og_site = soup.find("meta", attrs={"property": "og:site_name"})
        if og_site and isinstance(og_site, Tag):
            name = str(og_site.get("content", "")).strip()
            if name:
                return name
        # Fallback: extract domain name from URL
        try:
            parsed = urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return ""

    @staticmethod
    def _extract_og_property(soup: BeautifulSoup, property_name: str) -> str:
        """Get OGP property."""
        tag = soup.find("meta", attrs={"property": property_name})
        if tag and isinstance(tag, Tag):
            return str(tag.get("content", "")).strip()
        return ""

    @staticmethod
    def _extract_structured_data(soup: BeautifulSoup) -> tuple[dict[str, Any], ...]:
        """Extract JSON-LD structured data."""
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
        return tuple(results[:5])  # limit 5

    @staticmethod
    def _estimate_industry(text: str) -> tuple[str, ...]:
        """Estimate industry from text via keyword dictionary matching."""
        text_lower = text.lower()
        matched: list[str] = []
        for industry, keywords in _INDUSTRY_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if count >= 2:
                matched.append(industry)
        return tuple(matched)
