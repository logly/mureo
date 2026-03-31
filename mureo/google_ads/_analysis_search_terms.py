"""検索語句分析 Mixin。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import (
    _INFORMATIONAL_PATTERNS,
    _extract_ngrams,
    _get_comparison_date_ranges,
)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


def _is_informational_term(term_text: str) -> bool:
    """情報収集パターンにマッチするかを判定する。"""
    return any(p in term_text for p in _INFORMATIONAL_PATTERNS)


def _build_add_candidate(
    term_text: str,
    conversions: float,
    clicks: int,
    cost: float,
    ctr: float,
    match_type: str,
    score: int,
    reason: str,
) -> dict[str, Any]:
    """追加候補エントリを構築する。"""
    return {
        "search_term": term_text,
        "action": "add",
        "match_type": match_type,
        "score": score,
        "reason": reason,
        "metrics": {
            "conversions": conversions,
            "clicks": clicks,
            "cost": cost,
            "ctr": round(ctr, 4),
        },
    }


def _build_exclude_candidate(
    term_text: str,
    conversions: float,
    clicks: int,
    cost: float,
    ctr: float,
    match_type: str,
    score: int,
    reason: str,
) -> dict[str, Any]:
    """除外候補エントリを構築する。"""
    return {
        "search_term": term_text,
        "action": "exclude",
        "match_type": match_type,
        "score": score,
        "reason": reason,
        "metrics": {
            "conversions": conversions,
            "clicks": clicks,
            "cost": cost,
            "ctr": round(ctr, 4),
        },
    }


class _SearchTermsAnalysisMixin:
    """検索語句分析系メソッドを提供する Mixin。"""

    # 親クラスが提供する属性・メソッドの型宣言
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    async def get_search_terms_report(
        self, **kwargs: Any
    ) -> list[dict[str, Any]]: ...
    async def list_keywords(
        self, ad_group_id: str | None = None, campaign_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_negative_keywords(self, campaign_id: str) -> list[dict[str, Any]]: ...

    # PerformanceAnalysisMixin のメソッド
    async def _resolve_target_cpa(
        self, campaign_id: str, explicit: float | None = None
    ) -> tuple[float | None, str]: ...

    # =================================================================
    # 共通: 前期比較付き検索語句取得 / 新規語句ルーティング
    # =================================================================

    async def _fetch_terms_with_prev(
        self,
        campaign_id: str,
        period: str,
        ad_group_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """当期の検索語句リストと前期の語句テキストセットを返す。"""
        current_range, prev_range = _get_comparison_date_ranges(period)
        search_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, ad_group_id=ad_group_id, period=current_range
        )
        prev_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, ad_group_id=ad_group_id, period=prev_range
        )
        prev_term_set = {t.get("search_term", "").lower() for t in prev_terms}
        return search_terms, prev_term_set

    @staticmethod
    def _route_by_newness(
        entry: dict[str, Any],
        term_text: str,
        is_new: bool,
        main_list: list[dict[str, Any]],
        watch_list: list[dict[str, Any]],
    ) -> None:
        """新規語句を経過観察リストへ、既存語句をメインリストへ振り分ける。"""
        if is_new:
            entry["reason"] = f"新規語句（経過観察）: {entry['reason']}"
            if "action" in entry:
                entry["action"] = "watch"
            watch_list.append(entry)
        else:
            main_list.append(entry)

    # =================================================================
    # 検索語句オーバーラップ分析
    # =================================================================

    async def analyze_search_terms(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """検索語句とキーワードのオーバーラップ・N-gram分布・候補を分析する。"""
        self._validate_id(campaign_id, "campaign_id")

        # キーワードと検索語句を取得
        keywords = await self.list_keywords(campaign_id=campaign_id)
        search_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=period
        )

        # キーワードテキストの集合（小文字）
        keyword_texts: set[str] = {
            kw.get("text", "").lower() for kw in keywords
        }

        # オーバーラップ率
        overlap_count = sum(
            1 for t in search_terms
            if t.get("search_term", "").lower() in keyword_texts
        )
        overlap_rate = (
            overlap_count / len(search_terms) if search_terms else 0.0
        )

        # N-gram分布（1-3gram）
        ngram_agg: dict[int, dict[str, dict[str, float]]] = {
            1: {}, 2: {}, 3: {},
        }
        for t in search_terms:
            text = t.get("search_term", "")
            m = t.get("metrics", {})
            cost = float(m.get("cost", 0))
            convs = float(m.get("conversions", 0))
            for n in (1, 2, 3):
                for gram in _extract_ngrams(text, n):
                    agg = ngram_agg[n].setdefault(
                        gram, {"count": 0, "cost": 0.0, "conversions": 0.0}
                    )
                    agg["count"] += 1
                    agg["cost"] += cost
                    agg["conversions"] += convs

        ngram_distribution: dict[str, list[dict[str, Any]]] = {}
        label_map = {1: "unigrams", 2: "bigrams", 3: "trigrams"}
        for n, label in label_map.items():
            sorted_grams = sorted(
                ngram_agg[n].items(),
                key=lambda x: x[1]["count"],
                reverse=True,
            )[:10]
            ngram_distribution[label] = [
                {
                    "text": g,
                    "count": int(v["count"]),
                    "cost": round(v["cost"], 0),
                    "conversions": round(v["conversions"], 1),
                }
                for g, v in sorted_grams
            ]

        # キーワード候補: CV > 0 かつ未登録
        keyword_candidates = [
            {
                "search_term": t.get("search_term", ""),
                "conversions": float(t.get("metrics", {}).get("conversions", 0)),
                "cost": float(t.get("metrics", {}).get("cost", 0)),
                "clicks": int(t.get("metrics", {}).get("clicks", 0)),
            }
            for t in search_terms
            if float(t.get("metrics", {}).get("conversions", 0)) > 0
            and t.get("search_term", "").lower() not in keyword_texts
        ]

        # 除外候補: コストあり・CV0（コスト降順、上位20件）
        negative_candidates = sorted(
            [
                {
                    "search_term": t.get("search_term", ""),
                    "cost": float(t.get("metrics", {}).get("cost", 0)),
                    "clicks": int(t.get("metrics", {}).get("clicks", 0)),
                    "impressions": int(t.get("metrics", {}).get("impressions", 0)),
                }
                for t in search_terms
                if float(t.get("metrics", {}).get("cost", 0)) > 0
                and float(t.get("metrics", {}).get("conversions", 0)) == 0
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )[:20]

        # インサイト生成
        insights: list[str] = []
        if overlap_rate < 0.3:
            insights.append(
                f"オーバーラップ率が{overlap_rate:.0%}と低く、"
                "検索語句の多くがキーワードとして登録されていません。"
                "キーワード追加を検討してください"
            )
        if negative_candidates:
            total_waste = sum(c["cost"] for c in negative_candidates)
            insights.append(
                f"CVなしでコストが発生している検索語句が{len(negative_candidates)}件あり、"
                f"合計 ¥{total_waste:,.0f} の無駄コストが発生しています"
            )
        if keyword_candidates:
            insights.append(
                f"CVが発生しているが未登録の検索語句が{len(keyword_candidates)}件あります。"
                "キーワードとして追加することを推奨します"
            )

        return {
            "campaign_id": campaign_id,
            "period": period,
            "registered_keywords_count": len(keywords),
            "search_terms_count": len(search_terms),
            "overlap_rate": round(overlap_rate, 3),
            "ngram_distribution": ngram_distribution,
            "keyword_candidates": keyword_candidates,
            "negative_candidates": negative_candidates,
            "insights": insights,
        }

    # =================================================================
    # 除外キーワード自動提案
    # =================================================================

    async def suggest_negative_keywords(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
        target_cpa: float | None = None,
        use_intent_analysis: bool = True,
        ad_group_id: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """除外キーワード候補を自動提案する。"""
        self._validate_id(campaign_id, "campaign_id")

        effective_target = target_cpa

        # 目標CPAベースの閾値解決（常にCPA×1.5を使用）
        resolved_cpa, cpa_source = await self._resolve_target_cpa(
            campaign_id, explicit=effective_target
        )
        effective_threshold: float | None = None
        if resolved_cpa is not None:
            effective_threshold = resolved_cpa * 1.5

        # 検索語句を当期・前期で取得（新規語句保護用）
        search_terms, prev_term_set = await self._fetch_terms_with_prev(
            campaign_id, period, ad_group_id=ad_group_id
        )

        existing_negatives = await self.list_negative_keywords(campaign_id)

        # 既存除外KWテキスト（小文字）
        existing_neg_texts: set[str] = {
            n.get("keyword_text", "").lower() for n in existing_negatives
        }

        # フィルタ: 目標CPA×1.5以上・CV0・既存除外と重複なし
        suggestions: list[dict[str, Any]] = []
        watch_terms: list[dict[str, Any]] = []
        total_wasteful_cost: float = 0.0
        for t in search_terms:
            m = t.get("metrics", {})
            cost = float(m.get("cost", 0))
            convs = float(m.get("conversions", 0))
            term_text = t.get("search_term", "")

            if convs > 0:
                continue

            is_new = term_text.lower() not in prev_term_set
            is_informational = _is_informational_term(term_text)

            if not is_informational:
                if effective_threshold is not None and cost < effective_threshold:
                    if cost > 0:
                        total_wasteful_cost += cost
                    continue
                if effective_threshold is None:
                    if cost > 0:
                        total_wasteful_cost += cost
                    continue

            if cost > 0:
                total_wasteful_cost += cost

            if term_text.lower() in existing_neg_texts:
                continue

            # マッチタイプ推奨
            if is_informational:
                match_type = "PHRASE"
                reason = f"情報収集意図（CV0、コスト ¥{cost:,.0f}）"
            else:
                if resolved_cpa is None:
                    raise RuntimeError("resolved_cpa should not be None here")
                word_count = len(term_text.strip().split())
                match_type = "EXACT" if word_count <= 2 else "PHRASE"
                reason = f"¥{cost:,.0f}のコストでCV0件（目標CPA ¥{resolved_cpa:,.0f} ×1.5超過）"

            entry = {
                "search_term": term_text,
                "cost": cost,
                "clicks": int(m.get("clicks", 0)),
                "impressions": int(m.get("impressions", 0)),
                "ctr": float(m.get("ctr", 0)),
                "recommended_match_type": match_type,
                "reason": reason,
            }
            self._route_by_newness(entry, term_text, is_new, suggestions, watch_terms)

        # コスト降順でソート
        suggestions.sort(key=lambda x: x["cost"], reverse=True)
        watch_terms.sort(key=lambda x: x["cost"], reverse=True)
        potential_savings = sum(s["cost"] for s in suggestions)

        # インサイト生成
        insights: list[str] = []
        if resolved_cpa is not None:
            insights.append(
                f"目標CPA ¥{resolved_cpa:,.0f}（{cpa_source}）× 1.5 = "
                f"¥{effective_threshold:,.0f} を除外判定閾値として使用"
            )
        else:
            insights.append(
                "目標CPAを取得できなかったため、"
                "情報収集パターン以外の閾値判定はスキップしました"
            )
        if suggestions:
            insights.append(
                f"{len(suggestions)}件の除外キーワード候補があります。"
                f"追加により最大 ¥{potential_savings:,.0f} のコスト削減が見込まれます"
            )
        if watch_terms:
            insights.append(
                f"{len(watch_terms)}件の新規語句があります。"
                "前期に出現していないため経過観察を推奨します"
            )
        if not suggestions and not watch_terms and total_wasteful_cost == 0:
            insights.append(
                "除外判定閾値を超えるCVなし検索語句は見つかりませんでした"
            )

        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "ad_group_id": ad_group_id,
            "period": period,
            "target_cpa": resolved_cpa,
            "target_cpa_source": cpa_source,
            "existing_negative_count": len(existing_negatives),
            "suggestions": suggestions,
            "watch_terms": watch_terms,
            "total_wasteful_cost": round(total_wasteful_cost, 0),
            "potential_savings": round(potential_savings, 0),
            "insights": insights,
        }

        # 意図分析（オプション）
        if use_intent_analysis:
            logger.info("suggest_negative_keywords: 意図分析開始 campaign_id=%s", campaign_id)
            intent_additions = await self._suggest_by_intent(
                campaign_id=campaign_id,
                search_terms=search_terms,
                existing_suggestions=suggestions,
                existing_neg_texts=existing_neg_texts,
            )
            logger.info("suggest_negative_keywords: 意図分析完了 campaign_id=%s", campaign_id)
            if intent_additions:
                result["intent_based_suggestions"] = intent_additions
                insights.append(
                    f"意図分析により追加で{len(intent_additions)}件の"
                    "除外候補を検出しました"
                )

        return result

    # =================================================================
    # 検索語句レビュー（多段階判定）
    # =================================================================

    async def review_search_terms(
        self,
        campaign_id: str,
        period: str = "LAST_7_DAYS",
        target_cpa: float | None = None,
        use_intent_analysis: bool = True,
        ad_group_id: str | None = None,
    ) -> dict[str, Any]:
        """検索語句を多段階ルールでレビューし、追加・除外候補を提案する。"""
        self._validate_id(campaign_id, "campaign_id")

        effective_target = target_cpa

        # 目標CPA解決
        resolved_cpa, cpa_source = await self._resolve_target_cpa(
            campaign_id, explicit=effective_target
        )

        # 検索語句を当期・前期で取得
        search_terms, prev_term_set = await self._fetch_terms_with_prev(
            campaign_id, period, ad_group_id=ad_group_id
        )

        keywords = await self.list_keywords(
            campaign_id=campaign_id, ad_group_id=ad_group_id
        )
        keyword_texts: set[str] = {kw.get("text", "").lower() for kw in keywords}
        existing_negatives = await self.list_negative_keywords(campaign_id=campaign_id)
        existing_neg_texts: set[str] = {
            n.get("keyword_text", "").lower() for n in existing_negatives
        }

        add_candidates: list[dict[str, Any]] = []
        exclude_candidates: list[dict[str, Any]] = []
        watch_candidates: list[dict[str, Any]] = []

        for t in search_terms:
            self._classify_search_term(
                t,
                keyword_texts=keyword_texts,
                existing_neg_texts=existing_neg_texts,
                prev_term_set=prev_term_set,
                resolved_cpa=resolved_cpa,
                add_candidates=add_candidates,
                exclude_candidates=exclude_candidates,
                watch_candidates=watch_candidates,
            )

        # スコア降順ソート
        add_candidates.sort(key=lambda x: x["score"], reverse=True)
        exclude_candidates.sort(key=lambda x: x["score"], reverse=True)
        watch_candidates.sort(key=lambda x: x["score"], reverse=True)

        # 意図分析（オプション）
        intent_summary: dict[str, Any] | None = None
        if use_intent_analysis:
            logger.info("review_search_terms: 意図分析開始 campaign_id=%s", campaign_id)
            intent_summary = await self._apply_intent_analysis(
                campaign_id=campaign_id,
                add_candidates=add_candidates,
                exclude_candidates=exclude_candidates,
                watch_candidates=watch_candidates,
                keyword_texts=keyword_texts,
            )
            logger.info("review_search_terms: 意図分析完了 campaign_id=%s", campaign_id)

        result: dict[str, Any] = {
            "campaign_id": campaign_id,
            "ad_group_id": ad_group_id,
            "period": period,
            "target_cpa": resolved_cpa,
            "target_cpa_source": cpa_source,
            "add_candidates": add_candidates,
            "exclude_candidates": exclude_candidates,
            "watch_candidates": watch_candidates,
            "summary": {
                "total_search_terms": len(search_terms),
                "add_count": len(add_candidates),
                "exclude_count": len(exclude_candidates),
                "watch_count": len(watch_candidates),
            },
        }
        if intent_summary is not None:
            result["intent_analysis"] = intent_summary
        return result

    def _classify_search_term(
        self,
        t: dict[str, Any],
        *,
        keyword_texts: set[str],
        existing_neg_texts: set[str],
        prev_term_set: set[str],
        resolved_cpa: float | None,
        add_candidates: list[dict[str, Any]],
        exclude_candidates: list[dict[str, Any]],
        watch_candidates: list[dict[str, Any]],
    ) -> None:
        """検索語句1件を判定ルールで分類し、適切なリストに追加する。"""
        term_text = t.get("search_term", "")
        m = t.get("metrics", {})
        conversions = float(m.get("conversions", 0))
        clicks = int(m.get("clicks", 0))
        cost = float(m.get("cost", 0))
        impressions = int(m.get("impressions", 0))
        ctr = clicks / impressions if impressions > 0 else 0.0

        is_registered = term_text.lower() in keyword_texts
        is_new = term_text.lower() not in prev_term_set

        # Rule 1: CV>=2 & 未登録 → add EXACT (score=90)
        if conversions >= 2 and not is_registered:
            add_candidates.append(_build_add_candidate(
                term_text, conversions, clicks, cost, ctr,
                "EXACT", 90, f"CV{conversions:.0f}件、キーワード未登録",
            ))
            return

        # Rule 2: CV=1 & CPA<=目標CPA & 未登録 → add EXACT (score=70)
        if conversions == 1 and not is_registered and resolved_cpa is not None:
            cpa = cost
            if cpa <= resolved_cpa:
                add_candidates.append(_build_add_candidate(
                    term_text, conversions, clicks, cost, ctr,
                    "EXACT", 70,
                    f"CV1件、CPA ¥{cpa:,.0f} ≤ 目標CPA ¥{resolved_cpa:,.0f}",
                ))
                return

        # Rule 3: CV=0 & Click>=20 & CTR>=3% & 未登録 → add PHRASE (score=50)
        if conversions == 0 and clicks >= 20 and ctr >= 0.03 and not is_registered:
            add_candidates.append(_build_add_candidate(
                term_text, conversions, clicks, cost, ctr,
                "PHRASE", 50,
                f"CTR {ctr:.1%}（高CTR）、クリック{clicks}回",
            ))
            return

        # 除外候補: 既に除外キーワードとして登録済みならスキップ
        is_already_excluded = term_text.lower() in existing_neg_texts

        # Rule 4: CV=0 & コスト>=目標CPA×2 → exclude EXACT (score=80)
        if conversions == 0 and resolved_cpa is not None and cost >= resolved_cpa * 2 and not is_already_excluded:
            entry = _build_exclude_candidate(
                term_text, conversions, clicks, cost, ctr,
                "EXACT", 80,
                f"CV0、コスト ¥{cost:,.0f} ≥ 目標CPA×2 (¥{resolved_cpa * 2:,.0f})",
            )
            self._route_by_newness(entry, term_text, is_new, exclude_candidates, watch_candidates)
            return

        # Rule 5: CV=0 & Click>=30 & CTR<1% → exclude EXACT (score=60)
        if conversions == 0 and clicks >= 30 and ctr < 0.01 and not is_already_excluded:
            entry = _build_exclude_candidate(
                term_text, conversions, clicks, cost, ctr,
                "EXACT", 60,
                f"CV0、クリック{clicks}回でCTR {ctr:.2%}（低CTR）",
            )
            self._route_by_newness(entry, term_text, is_new, exclude_candidates, watch_candidates)
            return

        # Rule 6: 情報収集パターン & CV=0 → exclude PHRASE (score=40)
        if conversions == 0 and _is_informational_term(term_text) and not is_already_excluded:
            entry = _build_exclude_candidate(
                term_text, conversions, clicks, cost, ctr,
                "PHRASE", 40,
                "情報収集意図の検索語句（CV0）",
            )
            self._route_by_newness(entry, term_text, is_new, exclude_candidates, watch_candidates)

    # =================================================================
    # 意図ベース検索語句分析（LLMヘルパー/スタブ）
    # =================================================================

    async def _apply_intent_analysis(
        self,
        campaign_id: str,
        add_candidates: list[dict[str, Any]],
        exclude_candidates: list[dict[str, Any]],
        watch_candidates: list[dict[str, Any]],
        keyword_texts: set[str],
    ) -> dict[str, Any]:
        """LLM意図分析のスタブ。mureo-coreではLLM依存を除去。"""
        return {"classified_count": 0, "adjustments": [], "note": "LLM意図分析はManaged側で実施"}

    async def _suggest_by_intent(
        self,
        campaign_id: str,
        search_terms: list[dict[str, Any]],
        existing_suggestions: list[dict[str, Any]],
        existing_neg_texts: set[str],
    ) -> list[dict[str, Any]]:
        """LLM意図分析による追加提案のスタブ。"""
        return []

    async def _get_strategic_context_for_intent(
        self, campaign_id: str
    ) -> str | None:
        """戦略コンテキスト取得のスタブ。"""
        return None
