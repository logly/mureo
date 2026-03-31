"""Creative research mixin.

Integrates LP analysis, existing ads, search terms, and keyword suggestions
to return all data needed for ad creative planning.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from mureo.analysis.lp_analyzer import LPAnalyzer

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _CreativeMixin:
    """Mixin providing composite ad creative tools."""

    # Type declarations for attributes provided by parent class (GoogleAdsApiClient)
    _customer_id: str
    _client: GoogleAdsClient

    # Parent class methods (called by mixin)
    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...

    async def list_keywords(  # type: ignore[empty-body]
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]: ...
    async def get_search_terms_report(  # type: ignore[empty-body]
        self,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]: ...
    async def suggest_keywords(  # type: ignore[empty-body]
        self,
        seed_keywords: list[str],
        language_id: str = "1005",
        geo_id: str = "2392",
    ) -> list[dict[str, Any]]: ...

    # =================================================================
    # 1. LP analysis
    # =================================================================

    async def analyze_landing_page(self, url: str) -> dict[str, Any]:
        """Analyze LP and return structured data as dict.

        Returns error dict on failure (does not raise exceptions).
        """
        try:
            analyzer = LPAnalyzer()
            lp_content = await analyzer.analyze(url)
            return asdict(lp_content)
        except Exception as exc:
            logger.warning("LP analysis failed: url=%s, error=%s", url, exc)
            return {
                "url": url,
                "error": "LP analysis failed. Please verify the URL is correct.",
            }

    # =================================================================
    # 2. Creative research (integrated collection)
    # =================================================================

    async def research_creative(
        self,
        campaign_id: str,
        url: str,
        ad_group_id: str | None = None,
    ) -> dict[str, Any]:
        """Macro tool that collects LP analysis + existing ads + search terms + keyword suggestions.

        Each step is isolated with try-except so one failure does not affect the whole.
        """
        self._validate_id(campaign_id, "campaign_id")
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")

        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "url": url,
        }

        # --- 1. LP analysis ---
        lp_data = await self.analyze_landing_page(url)
        result["lp_analysis"] = lp_data

        # --- 2. Existing ad details (top 5) ---
        try:
            result["existing_ads"] = await self._fetch_existing_ads(
                campaign_id, ad_group_id
            )
        except Exception:
            logger.warning("Failed to retrieve existing ads", exc_info=True)
            result["existing_ads"] = "取得失敗"

        # --- 3. Search term insights ---
        try:
            result["search_term_insights"] = await self._extract_search_term_insights(
                campaign_id, ad_group_id
            )
        except Exception:
            logger.warning("Failed to retrieve search term insights", exc_info=True)
            result["search_term_insights"] = "取得失敗"

        # --- 4. Keyword suggestions ---
        try:
            seeds = self._generate_seed_keywords(lp_data)
            if seeds:
                result["keyword_suggestions"] = await self.suggest_keywords(seeds)
            else:
                result["keyword_suggestions"] = []
        except Exception:
            logger.warning("Failed to retrieve keyword suggestions", exc_info=True)
            result["keyword_suggestions"] = "取得失敗"

        # --- 5. Existing keywords ---
        try:
            result["existing_keywords"] = await self.list_keywords(
                campaign_id=campaign_id
            )
        except Exception:
            logger.warning("Failed to retrieve existing keywords", exc_info=True)
            result["existing_keywords"] = "取得失敗"

        # --- 6. Context summary for LLM ---
        result["context_summary"] = self._build_context_summary(result)

        return result

    # =================================================================
    # Helper methods
    # =================================================================

    async def _fetch_existing_ads(
        self,
        campaign_id: str,
        ad_group_id: str | None,
    ) -> list[dict[str, Any]]:
        """Retrieve existing ad headlines/descriptions/performance."""
        # Defensive validation (already validated by caller, but for direct calls)
        self._validate_id(campaign_id, "campaign_id")
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
        query = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.responsive_search_ad.headlines,
                ad_group_ad.ad.responsive_search_ad.descriptions,
                ad_group_ad.ad.final_urls,
                ad_group_ad.status,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.ctr
            FROM ad_group_ad
            WHERE campaign.id = {campaign_id}
                AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
                AND ad_group_ad.status != 'REMOVED'
        """
        if ad_group_id:
            query += f"\n                AND ad_group.id = {ad_group_id}"
        query += "\n            ORDER BY metrics.impressions DESC\n            LIMIT 5"

        response = await self._search(query)  # type: ignore[attr-defined]
        ads: list[dict[str, Any]] = []
        for row in response:
            ad = row.ad_group_ad.ad
            rsa = ad.responsive_search_ad
            headlines = [asset.text for asset in rsa.headlines] if rsa.headlines else []
            descriptions = (
                [asset.text for asset in rsa.descriptions] if rsa.descriptions else []
            )
            ads.append(
                {
                    "ad_id": str(ad.id),
                    "headlines": headlines,
                    "descriptions": descriptions,
                    "final_urls": list(ad.final_urls),
                    "impressions": row.metrics.impressions,
                    "clicks": row.metrics.clicks,
                    "conversions": row.metrics.conversions,
                    "ctr": round(row.metrics.ctr * 100, 2) if row.metrics.ctr else 0,
                }
            )
        return ads

    async def _extract_search_term_insights(
        self,
        campaign_id: str,
        ad_group_id: str | None,
    ) -> dict[str, Any]:
        """Extract high-CV and high-click terms from search terms."""
        kwargs: dict[str, Any] = {"campaign_id": campaign_id}
        if ad_group_id:
            kwargs["ad_group_id"] = ad_group_id
        terms = await self.get_search_terms_report(**kwargs)

        # High-CV terms (CV > 0, sorted by CV desc)
        high_cv = sorted(
            [t for t in terms if t.get("metrics", {}).get("conversions", 0) > 0],
            key=lambda x: x.get("metrics", {}).get("conversions", 0),
            reverse=True,
        )

        # High-click terms (sorted by clicks desc)
        high_click = sorted(
            terms,
            key=lambda x: x.get("metrics", {}).get("clicks", 0),
            reverse=True,
        )

        return {
            "high_cv_terms": high_cv[:10],
            "high_click_terms": high_click[:10],
            "total_terms": len(terms),
        }

    @staticmethod
    def _generate_seed_keywords(lp_data: dict[str, Any]) -> list[str]:
        """Generate seed keywords for suggestions from LP analysis results."""
        seeds: list[str] = []

        # Extract keywords from title
        title = lp_data.get("title", "")
        if title:
            seeds.append(title)

        # h1 text
        for h1 in lp_data.get("h1_texts", []):
            if h1 and h1 not in seeds:
                seeds.append(h1)

        # Meta description
        meta = lp_data.get("meta_description", "")
        if meta and meta not in seeds:
            seeds.append(meta)

        # Limit to 5
        return seeds[:5]

    @staticmethod
    def _build_context_summary(result: dict[str, Any]) -> str:
        """Summarize research results as context string for LLM."""
        parts: list[str] = []

        # LP information
        lp = result.get("lp_analysis", {})
        if isinstance(lp, dict) and not lp.get("error"):
            parts.append("[LP Information]")
            if lp.get("title"):
                parts.append(f"Title: {lp['title']}")
            if lp.get("meta_description"):
                parts.append(f"Description: {lp['meta_description']}")
            if lp.get("h1_texts"):
                parts.append(f"H1 Headings: {', '.join(lp['h1_texts'])}")
            if lp.get("cta_texts"):
                parts.append(f"CTA: {', '.join(lp['cta_texts'])}")
            if lp.get("features"):
                parts.append(f"Features: {', '.join(lp['features'][:5])}")
            if lp.get("prices"):
                parts.append(f"Prices: {', '.join(lp['prices'])}")
            if lp.get("industry_hints"):
                parts.append(f"Industry: {', '.join(lp['industry_hints'])}")

        # High-performance elements from existing ads
        ads = result.get("existing_ads", [])
        if isinstance(ads, list) and ads:
            parts.append("\n[Top Performing Existing Ads]")
            for ad in ads[:3]:
                parts.append(
                    f"- Headlines: {', '.join(ad.get('headlines', [])[:3])} "
                    f"(CTR: {ad.get('ctr', 0)}%, CV: {ad.get('conversions', 0)})"
                )

        # Search term insights
        insights = result.get("search_term_insights", {})
        if isinstance(insights, dict):
            high_cv = insights.get("high_cv_terms", [])
            if high_cv:
                cv_terms = [t.get("search_term", "") for t in high_cv[:5]]
                parts.append(f"\n[Converting Search Terms] {', '.join(cv_terms)}")

        # Target keywords
        keywords = result.get("existing_keywords", [])
        if isinstance(keywords, list) and keywords:
            kw_texts = [kw.get("text", "") for kw in keywords[:10] if kw.get("text")]
            if kw_texts:
                parts.append(f"\n[Target Keywords]\n{', '.join(kw_texts)}")

        return "\n".join(parts) if parts else "No LP analysis data"
