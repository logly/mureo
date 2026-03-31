"""クリエイティブリサーチ Mixin

LP解析 + 既存広告 + 検索語句 + キーワード提案を統合収集し、
広告クリエイティブ立案に必要なデータを一括で返す。
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
    """広告クリエイティブ関連の複合ツールを提供する Mixin"""

    # 親クラス (GoogleAdsApiClient) が提供する属性の型宣言
    _customer_id: str
    _client: GoogleAdsClient

    # 親クラスのメソッド（Mixin が呼び出す）
    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...

    async def list_keywords(
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]: ...
    async def get_search_terms_report(
        self,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]: ...
    async def suggest_keywords(
        self,
        seed_keywords: list[str],
        language_id: str = "1005",
        geo_id: str = "2392",
    ) -> list[dict[str, Any]]: ...

    # =================================================================
    # 1. LP解析
    # =================================================================

    async def analyze_landing_page(self, url: str) -> dict[str, Any]:
        """LPを解析し、構造化データをdict形式で返す。

        エラー時もエラー付きdictを返す（例外を投げない）。
        """
        try:
            analyzer = LPAnalyzer()
            lp_content = await analyzer.analyze(url)
            return asdict(lp_content)
        except Exception as exc:
            logger.warning("LP解析に失敗: url=%s, error=%s", url, exc)
            return {
                "url": url,
                "error": "LP解析に失敗しました。URLが正しいか確認してください。",
            }

    # =================================================================
    # 2. クリエイティブリサーチ（統合収集）
    # =================================================================

    async def research_creative(
        self,
        campaign_id: str,
        url: str,
        ad_group_id: str | None = None,
    ) -> dict[str, Any]:
        """LP解析+既存広告+検索語句+KW提案を一括収集するマクロツール。

        各ステップはtry-exceptで隔離し、1箇所の失敗が全体に影響しない。
        """
        self._validate_id(campaign_id, "campaign_id")
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")

        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "url": url,
        }

        # --- 1. LP解析 ---
        lp_data = await self.analyze_landing_page(url)
        result["lp_analysis"] = lp_data

        # --- 2. 既存広告の詳細（上位5件） ---
        try:
            result["existing_ads"] = await self._fetch_existing_ads(
                campaign_id, ad_group_id
            )
        except Exception:
            logger.warning("既存広告の取得に失敗", exc_info=True)
            result["existing_ads"] = "取得失敗"

        # --- 3. 検索語句インサイト ---
        try:
            result["search_term_insights"] = await self._extract_search_term_insights(
                campaign_id, ad_group_id
            )
        except Exception:
            logger.warning("検索語句インサイトの取得に失敗", exc_info=True)
            result["search_term_insights"] = "取得失敗"

        # --- 4. キーワード提案 ---
        try:
            seeds = self._generate_seed_keywords(lp_data)
            if seeds:
                result["keyword_suggestions"] = await self.suggest_keywords(seeds)
            else:
                result["keyword_suggestions"] = []
        except Exception:
            logger.warning("キーワード提案の取得に失敗", exc_info=True)
            result["keyword_suggestions"] = "取得失敗"

        # --- 5. 既存キーワード ---
        try:
            result["existing_keywords"] = await self.list_keywords(
                campaign_id=campaign_id
            )
        except Exception:
            logger.warning("既存キーワードの取得に失敗", exc_info=True)
            result["existing_keywords"] = "取得失敗"

        # --- 6. LLM向けコンテキスト要約 ---
        result["context_summary"] = self._build_context_summary(result)

        return result

    # =================================================================
    # ヘルパーメソッド
    # =================================================================

    async def _fetch_existing_ads(
        self,
        campaign_id: str,
        ad_group_id: str | None,
    ) -> list[dict[str, Any]]:
        """既存広告のheadlines/descriptions/パフォーマンスを取得"""
        # 防御的バリデーション（呼び出し元でも検証済みだが、直接呼び出しに備える）
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

        response = await self._search(query)
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
        """検索語句から高CV語句・高クリック語句を抽出"""
        kwargs: dict[str, Any] = {"campaign_id": campaign_id}
        if ad_group_id:
            kwargs["ad_group_id"] = ad_group_id
        terms = await self.get_search_terms_report(**kwargs)

        # 高CV語句（CV > 0、CV降順）
        high_cv = sorted(
            [t for t in terms if t.get("metrics", {}).get("conversions", 0) > 0],
            key=lambda x: x.get("metrics", {}).get("conversions", 0),
            reverse=True,
        )

        # 高クリック語句（クリック降順）
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
        """LP解析結果からキーワード提案用のシードを生成"""
        seeds: list[str] = []

        # タイトルからキーワード抽出
        title = lp_data.get("title", "")
        if title:
            seeds.append(title)

        # h1テキスト
        for h1 in lp_data.get("h1_texts", []):
            if h1 and h1 not in seeds:
                seeds.append(h1)

        # メタディスクリプション
        meta = lp_data.get("meta_description", "")
        if meta and meta not in seeds:
            seeds.append(meta)

        # 最大5件に制限
        return seeds[:5]

    @staticmethod
    def _build_context_summary(result: dict[str, Any]) -> str:
        """リサーチ結果をLLM向けのコンテキスト文字列にまとめる"""
        parts: list[str] = []

        # LP情報
        lp = result.get("lp_analysis", {})
        if isinstance(lp, dict) and not lp.get("error"):
            parts.append("【LP情報】")
            if lp.get("title"):
                parts.append(f"タイトル: {lp['title']}")
            if lp.get("meta_description"):
                parts.append(f"説明: {lp['meta_description']}")
            if lp.get("h1_texts"):
                parts.append(f"見出し(H1): {', '.join(lp['h1_texts'])}")
            if lp.get("cta_texts"):
                parts.append(f"CTA: {', '.join(lp['cta_texts'])}")
            if lp.get("features"):
                parts.append(f"特徴: {', '.join(lp['features'][:5])}")
            if lp.get("prices"):
                parts.append(f"価格: {', '.join(lp['prices'])}")
            if lp.get("industry_hints"):
                parts.append(f"業界: {', '.join(lp['industry_hints'])}")

        # 既存広告の高パフォーマンス要素
        ads = result.get("existing_ads", [])
        if isinstance(ads, list) and ads:
            parts.append("\n【既存広告のパフォーマンス上位】")
            for ad in ads[:3]:
                parts.append(
                    f"- 見出し: {', '.join(ad.get('headlines', [])[:3])} "
                    f"(CTR: {ad.get('ctr', 0)}%, CV: {ad.get('conversions', 0)})"
                )

        # 検索語句インサイト
        insights = result.get("search_term_insights", {})
        if isinstance(insights, dict):
            high_cv = insights.get("high_cv_terms", [])
            if high_cv:
                cv_terms = [t.get("search_term", "") for t in high_cv[:5]]
                parts.append(f"\n【CV獲得検索語句】{', '.join(cv_terms)}")

        # ターゲットキーワード
        keywords = result.get("existing_keywords", [])
        if isinstance(keywords, list) and keywords:
            kw_texts = [kw.get("text", "") for kw in keywords[:10] if kw.get("text")]
            if kw_texts:
                parts.append(f"\n【ターゲットキーワード】\n{', '.join(kw_texts)}")

        return "\n".join(parts) if parts else "LP解析データなし"
