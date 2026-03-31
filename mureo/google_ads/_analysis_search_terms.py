"""Search term analysis mixin."""

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
    """Determine if a search term matches informational patterns."""
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
    """Build candidate entry for keyword addition."""
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
    """Build exclusion candidate entry."""
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
    """Mixin providing search term analysis methods."""

    # Type declarations for attributes/methods provided by parent class
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    async def get_search_terms_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_keywords(  # type: ignore[empty-body]
        self, ad_group_id: str | None = None, campaign_id: str | None = None
    ) -> list[dict[str, Any]]: ...
    async def list_negative_keywords(  # type: ignore[empty-body]
        self, campaign_id: str
    ) -> list[dict[str, Any]]: ...

    # Method from PerformanceAnalysisMixin
    async def _resolve_target_cpa(  # type: ignore[empty-body]
        self, campaign_id: str, explicit: float | None = None
    ) -> tuple[float | None, str]: ...

    # =================================================================
    # Common: Search terms retrieval with previous period / new term routing
    # =================================================================

    async def _fetch_terms_with_prev(
        self,
        campaign_id: str,
        period: str,
        ad_group_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        """Return current period search terms list and previous period term text set."""
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
        """Route new terms to watch list and existing terms to main list."""
        if is_new:
            entry["reason"] = f"New term (under observation): {entry['reason']}"
            if "action" in entry:
                entry["action"] = "watch"
            watch_list.append(entry)
        else:
            main_list.append(entry)

    # =================================================================
    # Search term overlap analysis
    # =================================================================

    async def analyze_search_terms(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Analyze search term/keyword overlap, N-gram distribution, and candidates."""
        self._validate_id(campaign_id, "campaign_id")

        # Retrieve keywords and search terms
        keywords = await self.list_keywords(campaign_id=campaign_id)
        search_terms = await self.get_search_terms_report(
            campaign_id=campaign_id, period=period
        )

        # Set of keyword texts (lowercase)
        keyword_texts: set[str] = {kw.get("text", "").lower() for kw in keywords}

        # Overlap rate
        overlap_count = sum(
            1 for t in search_terms if t.get("search_term", "").lower() in keyword_texts
        )
        overlap_rate = overlap_count / len(search_terms) if search_terms else 0.0

        # N-gram distribution (1-3gram)
        ngram_agg: dict[int, dict[str, dict[str, float]]] = {
            1: {},
            2: {},
            3: {},
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

        # Keyword candidates: CV > 0 and not registered
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

        # Exclusion candidates: has cost, CV=0 (sorted by cost desc, top 20)
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

        # Insight generation
        insights: list[str] = []
        if overlap_rate < 0.3:
            insights.append(
                f"Overlap rate is {overlap_rate:.0%}, which is low. "
                "Many search terms are not registered as keywords. "
                "Consider adding keywords"
            )
        if negative_candidates:
            total_waste = sum(c["cost"] for c in negative_candidates)
            insights.append(
                f"There are {len(negative_candidates)} search terms with cost but no conversions, "
                f"resulting in ¥{total_waste:,.0f} of wasted cost"
            )
        if keyword_candidates:
            insights.append(
                f"There are {len(keyword_candidates)} search terms with conversions that are not registered. "
                "We recommend adding them as keywords"
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
    # Automatic negative keyword suggestions
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
        """Automatically suggest negative keyword candidates."""
        self._validate_id(campaign_id, "campaign_id")

        effective_target = target_cpa

        # CPA-based threshold resolution (always use CPA x 1.5)
        resolved_cpa, cpa_source = await self._resolve_target_cpa(
            campaign_id, explicit=effective_target
        )
        effective_threshold: float | None = None
        if resolved_cpa is not None:
            effective_threshold = resolved_cpa * 1.5

        # Retrieve search terms for current/previous periods (for new term protection)
        search_terms, prev_term_set = await self._fetch_terms_with_prev(
            campaign_id, period, ad_group_id=ad_group_id
        )

        existing_negatives = await self.list_negative_keywords(campaign_id)

        # Existing negative keyword texts (lowercase)
        existing_neg_texts: set[str] = {
            n.get("keyword_text", "").lower() for n in existing_negatives
        }

        # Filter: >= target CPA x 1.5, CV=0, no overlap with existing negatives
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

            # Recommended match type
            if is_informational:
                match_type = "PHRASE"
                reason = f"Informational intent (0 CV, cost ¥{cost:,.0f})"
            else:
                if resolved_cpa is None:
                    raise RuntimeError("resolved_cpa should not be None here")
                word_count = len(term_text.strip().split())
                match_type = "EXACT" if word_count <= 2 else "PHRASE"
                reason = f"¥{cost:,.0f} cost with 0 CV (exceeds target CPA ¥{resolved_cpa:,.0f} x 1.5)"

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

        # Sort by cost descending
        suggestions.sort(key=lambda x: x["cost"], reverse=True)
        watch_terms.sort(key=lambda x: x["cost"], reverse=True)
        potential_savings = sum(s["cost"] for s in suggestions)

        # Insight generation
        insights: list[str] = []
        if resolved_cpa is not None:
            insights.append(
                f"Using target CPA ¥{resolved_cpa:,.0f} ({cpa_source}) x 1.5 = "
                f"¥{effective_threshold:,.0f} as exclusion threshold"
            )
        else:
            insights.append(
                "Could not retrieve target CPA; "
                "threshold-based exclusion was skipped except for informational patterns"
            )
        if suggestions:
            insights.append(
                f"There are {len(suggestions)} negative keyword candidates. "
                f"Adding them could save up to ¥{potential_savings:,.0f}"
            )
        if watch_terms:
            insights.append(
                f"There are {len(watch_terms)} new terms. "
                "They were not present in the previous period; observation is recommended"
            )
        if not suggestions and not watch_terms and total_wasteful_cost == 0:
            insights.append(
                "No zero-CV search terms exceeding the exclusion threshold were found"
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

        # Intent analysis (optional)
        if use_intent_analysis:
            logger.info(
                "suggest_negative_keywords: intent analysis start campaign_id=%s",
                campaign_id,
            )
            intent_additions = await self._suggest_by_intent(
                campaign_id=campaign_id,
                search_terms=search_terms,
                existing_suggestions=suggestions,
                existing_neg_texts=existing_neg_texts,
            )
            logger.info(
                "suggest_negative_keywords: intent analysis done campaign_id=%s",
                campaign_id,
            )
            if intent_additions:
                result["intent_based_suggestions"] = intent_additions
                insights.append(
                    f"Intent analysis detected {len(intent_additions)} additional "
                    "exclusion candidates"
                )

        return result

    # =================================================================
    # Search term review (multi-stage evaluation)
    # =================================================================

    async def review_search_terms(
        self,
        campaign_id: str,
        period: str = "LAST_7_DAYS",
        target_cpa: float | None = None,
        use_intent_analysis: bool = True,
        ad_group_id: str | None = None,
    ) -> dict[str, Any]:
        """Review search terms with multi-stage rules and suggest add/exclude candidates."""
        self._validate_id(campaign_id, "campaign_id")

        effective_target = target_cpa

        # Resolve target CPA
        resolved_cpa, cpa_source = await self._resolve_target_cpa(
            campaign_id, explicit=effective_target
        )

        # Retrieve search terms for current/previous periods
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

        # Sort by score descending
        add_candidates.sort(key=lambda x: x["score"], reverse=True)
        exclude_candidates.sort(key=lambda x: x["score"], reverse=True)
        watch_candidates.sort(key=lambda x: x["score"], reverse=True)

        # Intent analysis (optional)
        intent_summary: dict[str, Any] | None = None
        if use_intent_analysis:
            logger.info(
                "review_search_terms: intent analysis start campaign_id=%s", campaign_id
            )
            intent_summary = await self._apply_intent_analysis(
                campaign_id=campaign_id,
                add_candidates=add_candidates,
                exclude_candidates=exclude_candidates,
                watch_candidates=watch_candidates,
                keyword_texts=keyword_texts,
            )
            logger.info(
                "review_search_terms: intent analysis done campaign_id=%s", campaign_id
            )

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
        """Classify a single search term using evaluation rules and add to the appropriate list."""
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
            add_candidates.append(
                _build_add_candidate(
                    term_text,
                    conversions,
                    clicks,
                    cost,
                    ctr,
                    "EXACT",
                    90,
                    f"{conversions:.0f} conversions, keyword not registered",
                )
            )
            return

        # Rule 2: CV=1 & CPA<=目標CPA & 未登録 → add EXACT (score=70)
        if conversions == 1 and not is_registered and resolved_cpa is not None:
            cpa = cost
            if cpa <= resolved_cpa:
                add_candidates.append(
                    _build_add_candidate(
                        term_text,
                        conversions,
                        clicks,
                        cost,
                        ctr,
                        "EXACT",
                        70,
                        f"CV1件、CPA ¥{cpa:,.0f} ≤ 目標CPA ¥{resolved_cpa:,.0f}",
                    )
                )
                return

        # Rule 3: CV=0 & Click>=20 & CTR>=3% & 未登録 → add PHRASE (score=50)
        if conversions == 0 and clicks >= 20 and ctr >= 0.03 and not is_registered:
            add_candidates.append(
                _build_add_candidate(
                    term_text,
                    conversions,
                    clicks,
                    cost,
                    ctr,
                    "PHRASE",
                    50,
                    f"CTR {ctr:.1%} (high CTR), {clicks} clicks",
                )
            )
            return

        # Exclusion candidates: skip if already registered as negative keyword
        is_already_excluded = term_text.lower() in existing_neg_texts

        # Rule 4: CV=0 & cost >= target CPA × 2 → exclude EXACT (score=80)
        if (
            conversions == 0
            and resolved_cpa is not None
            and cost >= resolved_cpa * 2
            and not is_already_excluded
        ):
            entry = _build_exclude_candidate(
                term_text,
                conversions,
                clicks,
                cost,
                ctr,
                "EXACT",
                80,
                f"0 conversions, cost ¥{cost:,.0f} >= target CPA x2 (¥{resolved_cpa * 2:,.0f})",
            )
            self._route_by_newness(
                entry, term_text, is_new, exclude_candidates, watch_candidates
            )
            return

        # Rule 5: CV=0 & Click>=30 & CTR<1% → exclude EXACT (score=60)
        if conversions == 0 and clicks >= 30 and ctr < 0.01 and not is_already_excluded:
            entry = _build_exclude_candidate(
                term_text,
                conversions,
                clicks,
                cost,
                ctr,
                "EXACT",
                60,
                f"0 conversions, {clicks} clicks with CTR {ctr:.2%} (low CTR)",
            )
            self._route_by_newness(
                entry, term_text, is_new, exclude_candidates, watch_candidates
            )
            return

        # Rule 6: Informational pattern & CV=0 -> exclude PHRASE (score=40)
        if (
            conversions == 0
            and _is_informational_term(term_text)
            and not is_already_excluded
        ):
            entry = _build_exclude_candidate(
                term_text,
                conversions,
                clicks,
                cost,
                ctr,
                "PHRASE",
                40,
                "Informational intent search term (0 CV)",
            )
            self._route_by_newness(
                entry, term_text, is_new, exclude_candidates, watch_candidates
            )

    # =================================================================
    # Intent-based search term analysis (LLM helper/stub)
    # =================================================================

    async def _apply_intent_analysis(
        self,
        campaign_id: str,
        add_candidates: list[dict[str, Any]],
        exclude_candidates: list[dict[str, Any]],
        watch_candidates: list[dict[str, Any]],
        keyword_texts: set[str],
    ) -> dict[str, Any]:
        """Stub for LLM intent analysis. LLM dependency removed in mureo-core."""
        return {
            "classified_count": 0,
            "adjustments": [],
            "note": "LLM intent analysis is performed on the Managed side",
        }

    async def _suggest_by_intent(
        self,
        campaign_id: str,
        search_terms: list[dict[str, Any]],
        existing_suggestions: list[dict[str, Any]],
        existing_neg_texts: set[str],
    ) -> list[dict[str, Any]]:
        """Stub for additional suggestions via LLM intent analysis."""
        return []

    async def _get_strategic_context_for_intent(self, campaign_id: str) -> str | None:
        """Stub for strategic context retrieval."""
        return None
