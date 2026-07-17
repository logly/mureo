"""Landing page (LP) analysis engine.

A pure HTTP + HTML analysis module independent of the Google Ads API.
Fetches an LP by URL and returns structured data: title, headings, features, CTAs,
prices, estimated industry, etc.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from mureo.core.url_guard import validate_public_url

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

# Industry estimation keyword dictionary. Keys are Japanese industry
# labels surfaced to callers via ``industry_hints``; values are Japanese
# keywords detected in LP body text. Intentionally left in Japanese:
# mureo's LP analyzer is designed to classify Japanese landing pages.
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

# SSRF protection: max redirect hops. Each hop is validated BEFORE it is
# followed (we do not let httpx auto-follow), so a public URL cannot bounce the
# fetch to an internal host.
_MAX_REDIRECTS = 5


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
        """SSRF protection: delegate to the canonical URL guard.

        Uses :func:`mureo.core.url_guard.validate_public_url`, the single
        source of truth for outbound-fetch SSRF checks. It blocks non-http(s)
        schemes, cloud-metadata hosts, and private/loopback/link-local/
        reserved/multicast/unspecified addresses for both literal IPs and DNS
        names — closing the ``is_multicast``/``is_unspecified`` gap the previous
        in-module reimplementation had. Kept as a thin static wrapper so
        existing callers — including
        :class:`mureo.google_ads._message_match.LPScreenshotter` — keep working.

        Raises:
            ValueError: (an ``UnsafeUrlError`` subclass) if the URL is unsafe.
        """
        validate_public_url(url)

    async def _fetch_html(self, url: str) -> str:
        """Fetch HTML via HTTP, validating every redirect hop for SSRF.

        Redirects are followed MANUALLY (``follow_redirects=False``) so each
        ``Location`` is run through :meth:`_validate_url` *before* the next
        request is issued. Letting httpx auto-follow would fetch an
        intermediate hop pointing at an internal host (e.g. 169.254.169.254)
        before the destination could be re-validated — a blind-SSRF gap. A
        residual DNS-rebinding TOCTOU remains (httpx re-resolves the validated
        hostname), acceptable for this read-only analyzer.

        The body is read as a stream and truncated at ``_MAX_BODY_BYTES`` (see
        :meth:`_read_capped_body`) so an oversized response cannot balloon
        memory. Validation runs in a worker thread to keep its blocking DNS
        lookup off the event loop.
        """
        await asyncio.to_thread(self._validate_url, url)
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            current_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                async with client.stream("GET", current_url) as response:
                    # has_redirect_location (not is_redirect) is True only for a
                    # 3xx that actually carries a Location — so a 304/300 without
                    # one is a terminal response rather than a phantom redirect.
                    if response.has_redirect_location:
                        location = response.headers["location"]
                        # Resolve a possibly-relative Location against the
                        # current URL, then validate BEFORE following it.
                        next_url = str(httpx.URL(current_url).join(location))
                        await asyncio.to_thread(self._validate_url, next_url)
                        current_url = next_url
                        continue
                    response.raise_for_status()
                    return await self._read_capped_body(response)
            raise ValueError(f"Too many redirects (>{_MAX_REDIRECTS}) fetching {url}")

    @staticmethod
    async def _read_capped_body(response: httpx.Response) -> str:
        """Read a streamed response body, stopping once the size cap is hit.

        Accumulates chunks until ``_MAX_BODY_BYTES`` is reached, then stops
        pulling from the stream (the ``async with`` in :meth:`_fetch_html`
        closes it on exit) instead of materialising an unbounded body via
        ``response.content``. Decoding mirrors the previous truncation path:
        header charset if present, else UTF-8, with undecodable bytes replaced.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total >= _MAX_BODY_BYTES:
                break
        body = b"".join(chunks)[:_MAX_BODY_BYTES]
        return body.decode(response.encoding or "utf-8", errors="replace")

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
