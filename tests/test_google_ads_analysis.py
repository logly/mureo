"""Google Ads 分析 Mixin 群のユニットテスト。

対象モジュール:
- _analysis_constants.py
- _analysis_performance.py
- _analysis_search_terms.py
- _analysis_keywords.py
- _analysis_budget.py
- _analysis_rsa.py
- _analysis_auction.py
- _analysis_btob.py

DB/外部API/LLM呼び出しは一切行わず、
_run_query / _run_report / _search 等をモックして検証する。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.google_ads._analysis_auction import _AuctionAnalysisMixin
from mureo.google_ads._analysis_btob import _BtoBAnalysisMixin
from mureo.google_ads._analysis_budget import _BudgetAnalysisMixin
from mureo.google_ads._analysis_constants import (
    _INFORMATIONAL_PATTERNS,
    _MATCH_TYPE_MAP,
    _STATUS_MAP,
    _calc_change_rate,
    _extract_ngrams,
    _get_comparison_date_ranges,
    _resolve_enum,
    _safe_metrics,
)
from mureo.google_ads._analysis_keywords import _KeywordsAnalysisMixin
from mureo.google_ads._analysis_performance import _PerformanceAnalysisMixin
from mureo.google_ads._analysis_rsa import _RsaAnalysisMixin
from mureo.google_ads._analysis_search_terms import (
    _SearchTermsAnalysisMixin,
    _build_add_candidate,
    _build_exclude_candidate,
    _is_informational_term,
)


# =====================================================================
# モッククライアント
# =====================================================================


class MockAnalysisClient(
    _PerformanceAnalysisMixin,
    _SearchTermsAnalysisMixin,
    _KeywordsAnalysisMixin,
    _BudgetAnalysisMixin,
    _RsaAnalysisMixin,
    _AuctionAnalysisMixin,
    _BtoBAnalysisMixin,
):
    """テスト用に全Mixinを統合し、親クラスメソッドをモックするクラス。"""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = None  # type: ignore[assignment]

        # モック可能な関数群
        self.get_campaign = AsyncMock(return_value=None)
        self.list_campaigns = AsyncMock(return_value=[])
        self.get_performance_report = AsyncMock(return_value=[])
        self.get_search_terms_report = AsyncMock(return_value=[])
        self.list_recommendations = AsyncMock(return_value=[])
        self.list_change_history = AsyncMock(return_value=[])
        self.list_negative_keywords = AsyncMock(return_value=[])
        self.list_keywords = AsyncMock(return_value=[])
        self.get_ad_performance_report = AsyncMock(return_value=[])
        self.get_budget = AsyncMock(return_value=None)
        self.list_schedule_targeting = AsyncMock(return_value=[])
        self.diagnose_campaign_delivery = AsyncMock(return_value={})
        self._search = AsyncMock(return_value=[])

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value:
            raise ValueError(f"{field_name} は必須です")
        return value

    def _period_to_date_clause(self, period: str) -> str:
        return f"DURING {period}"

    def _get_service(self, service_name: str) -> Any:
        return None


# =====================================================================
# _analysis_constants テスト
# =====================================================================


class TestAnalysisConstants:
    """_analysis_constants.py の関数テスト。"""

    @pytest.mark.unit
    def test_calc_change_rate_normal(self) -> None:
        assert _calc_change_rate(120, 100) == 20.0

    @pytest.mark.unit
    def test_calc_change_rate_decrease(self) -> None:
        assert _calc_change_rate(80, 100) == -20.0

    @pytest.mark.unit
    def test_calc_change_rate_previous_zero(self) -> None:
        assert _calc_change_rate(100, 0) is None

    @pytest.mark.unit
    def test_calc_change_rate_both_zero(self) -> None:
        assert _calc_change_rate(0, 0) is None

    @pytest.mark.unit
    def test_safe_metrics_with_data(self) -> None:
        perf = [{"metrics": {"impressions": 100, "clicks": 10}}]
        result = _safe_metrics(perf)
        assert result["impressions"] == 100

    @pytest.mark.unit
    def test_safe_metrics_empty(self) -> None:
        result = _safe_metrics([])
        assert result["impressions"] == 0
        assert result["clicks"] == 0
        assert result["cost"] == 0

    @pytest.mark.unit
    def test_safe_metrics_no_metrics_key(self) -> None:
        result = _safe_metrics([{"other": "data"}])
        assert result == {}

    @pytest.mark.unit
    def test_extract_ngrams_unigram(self) -> None:
        assert _extract_ngrams("hello world", 1) == ["hello", "world"]

    @pytest.mark.unit
    def test_extract_ngrams_bigram(self) -> None:
        assert _extract_ngrams("a b c", 2) == ["a b", "b c"]

    @pytest.mark.unit
    def test_extract_ngrams_trigram(self) -> None:
        assert _extract_ngrams("a b c d", 3) == ["a b c", "b c d"]

    @pytest.mark.unit
    def test_extract_ngrams_short_text(self) -> None:
        result = _extract_ngrams("hello", 2)
        assert result == ["hello"]

    @pytest.mark.unit
    def test_extract_ngrams_empty(self) -> None:
        result = _extract_ngrams("", 1)
        assert result == []

    @pytest.mark.unit
    def test_get_comparison_date_ranges_last_7_days(self) -> None:
        current, previous = _get_comparison_date_ranges("LAST_7_DAYS")
        assert "BETWEEN" in current
        assert "BETWEEN" in previous

    @pytest.mark.unit
    def test_get_comparison_date_ranges_last_30_days(self) -> None:
        current, previous = _get_comparison_date_ranges("LAST_30_DAYS")
        assert "BETWEEN" in current
        assert "BETWEEN" in previous

    @pytest.mark.unit
    def test_get_comparison_date_ranges_unknown_period(self) -> None:
        """不明な期間はデフォルト7日で処理される。"""
        current, previous = _get_comparison_date_ranges("UNKNOWN_PERIOD")
        assert "BETWEEN" in current

    @pytest.mark.unit
    def test_get_comparison_date_ranges_no_overlap(self) -> None:
        """当期と前期が重複しないことを検証。"""
        current, previous = _get_comparison_date_ranges("LAST_7_DAYS")
        # BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' からdateを抽出
        import re
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", current + previous)
        cur_start, cur_end, prev_start, prev_end = [
            date.fromisoformat(d) for d in dates
        ]
        # 前期の終了日 < 当期の開始日
        assert prev_end < cur_start

    @pytest.mark.unit
    def test_resolve_enum_int(self) -> None:
        assert _resolve_enum(2, _MATCH_TYPE_MAP) == "EXACT"
        assert _resolve_enum(4, _MATCH_TYPE_MAP) == "BROAD"

    @pytest.mark.unit
    def test_resolve_enum_unknown_int(self) -> None:
        assert _resolve_enum(99, _MATCH_TYPE_MAP) == "99"

    @pytest.mark.unit
    def test_resolve_enum_with_name_attr(self) -> None:
        class FakeEnum:
            name = "PHRASE"
        assert _resolve_enum(FakeEnum(), _MATCH_TYPE_MAP) == "PHRASE"

    @pytest.mark.unit
    def test_resolve_enum_str_fallback(self) -> None:
        assert _resolve_enum("EXACT", _MATCH_TYPE_MAP) == "EXACT"

    @pytest.mark.unit
    def test_status_map_values(self) -> None:
        assert _STATUS_MAP[2] == "ENABLED"
        assert _STATUS_MAP[3] == "PAUSED"

    @pytest.mark.unit
    def test_informational_patterns(self) -> None:
        assert "とは" in _INFORMATIONAL_PATTERNS
        assert "比較" in _INFORMATIONAL_PATTERNS


# =====================================================================
# _analysis_performance テスト
# =====================================================================


class TestPerformanceAnalysisMixin:
    """_PerformanceAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    @pytest.mark.unit
    async def test_resolve_target_cpa_explicit(self) -> None:
        client = self._make_client()
        cpa, source = await client._resolve_target_cpa("123", explicit=5000.0)
        assert cpa == 5000.0
        assert source == "explicit"

    @pytest.mark.unit
    async def test_resolve_target_cpa_from_bidding(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {
            "bidding_details": {"target_cpa": 3000}
        }
        cpa, source = await client._resolve_target_cpa("123")
        assert cpa == 3000.0
        assert source == "bidding_strategy"

    @pytest.mark.unit
    async def test_resolve_target_cpa_from_actual(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"bidding_details": {}}
        client.get_performance_report.return_value = [
            {"metrics": {"cost": 10000, "conversions": 5}}
        ]
        cpa, source = await client._resolve_target_cpa("123")
        assert cpa == 2000.0
        assert source == "actual"

    @pytest.mark.unit
    async def test_resolve_target_cpa_none(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"bidding_details": {}}
        client.get_performance_report.return_value = [
            {"metrics": {"cost": 0, "conversions": 0}}
        ]
        cpa, source = await client._resolve_target_cpa("123")
        assert cpa is None
        assert source == "none"

    @pytest.mark.unit
    async def test_resolve_target_cpa_exception_fallback(self) -> None:
        client = self._make_client()
        client.get_campaign.side_effect = Exception("API error")
        client.get_performance_report.return_value = [
            {"metrics": {"cost": 6000, "conversions": 3}}
        ]
        cpa, source = await client._resolve_target_cpa("123")
        assert cpa == 2000.0
        assert source == "actual"

    @pytest.mark.unit
    async def test_analyze_performance_campaign_not_found(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = None
        result = await client.analyze_performance("999")
        assert "error" in result

    @pytest.mark.unit
    async def test_analyze_performance_basic(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {
            "id": "123",
            "name": "Test Campaign",
            "status": "ENABLED",
        }
        client.get_performance_report.return_value = [
            {"metrics": {"impressions": 1000, "clicks": 100, "cost": 5000, "conversions": 10}}
        ]
        client.get_search_terms_report.return_value = []
        client.list_recommendations.return_value = []
        client.list_change_history.return_value = []

        result = await client.analyze_performance("123")
        assert result["campaign_id"] == "123"
        assert "campaign" in result
        assert "issues" in result
        assert "insights" in result

    @pytest.mark.unit
    async def test_analyze_performance_paused_campaign(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {
            "id": "123",
            "name": "Paused",
            "status": "PAUSED",
        }
        client.get_performance_report.return_value = [
            {"metrics": {"impressions": 0, "clicks": 0, "cost": 0, "conversions": 0}}
        ]
        result = await client.analyze_performance("123")
        assert any("PAUSED" in i for i in result["issues"])

    @pytest.mark.unit
    def test_generate_performance_insights_cost_increase(self) -> None:
        changes = {
            "impressions_change_pct": -25.0,
            "clicks_change_pct": -25.0,
            "cost_change_pct": 35.0,
            "conversions_change_pct": -30.0,
        }
        current_m = {"cost": 10000, "conversions": 5}
        previous_m = {"cost": 8000, "conversions": 8}
        insights, cpa_info = _PerformanceAnalysisMixin._generate_performance_insights(
            changes, current_m, previous_m
        )
        assert len(insights) >= 3
        assert "cpa_current" in cpa_info
        assert "cpa_previous" in cpa_info

    @pytest.mark.unit
    def test_generate_performance_insights_no_issues(self) -> None:
        changes = {
            "impressions_change_pct": 5.0,
            "clicks_change_pct": 5.0,
            "cost_change_pct": 5.0,
            "conversions_change_pct": 5.0,
        }
        current_m = {"cost": 10000, "conversions": 10}
        previous_m = {"cost": 9500, "conversions": 10}
        insights, cpa_info = _PerformanceAnalysisMixin._generate_performance_insights(
            changes, current_m, previous_m
        )
        assert len(insights) == 0

    @pytest.mark.unit
    def test_generate_performance_insights_zero_conversions(self) -> None:
        changes = {"impressions_change_pct": 0, "clicks_change_pct": 0,
                   "cost_change_pct": 0, "conversions_change_pct": 0}
        current_m = {"cost": 1000, "conversions": 0}
        previous_m = {"cost": 1000, "conversions": 0}
        _, cpa_info = _PerformanceAnalysisMixin._generate_performance_insights(
            changes, current_m, previous_m
        )
        assert "cpa_current" not in cpa_info
        assert "cpa_previous" not in cpa_info

    @pytest.mark.unit
    def test_build_cost_breakdown_cpc_increase(self) -> None:
        current_m = {"average_cpc": 150, "clicks": 100}
        previous_m = {"average_cpc": 100, "clicks": 100}
        breakdown, findings, cpc_change, clicks_change = (
            _PerformanceAnalysisMixin._build_cost_breakdown(current_m, previous_m)
        )
        assert breakdown["cpc_current"] == 150
        assert cpc_change is not None and cpc_change > 10
        assert any("CPC" in f for f in findings)

    @pytest.mark.unit
    def test_build_cost_breakdown_clicks_increase(self) -> None:
        current_m = {"average_cpc": 100, "clicks": 150}
        previous_m = {"average_cpc": 100, "clicks": 100}
        breakdown, findings, _, clicks_change = (
            _PerformanceAnalysisMixin._build_cost_breakdown(current_m, previous_m)
        )
        assert clicks_change is not None and clicks_change > 20
        assert any("クリック" in f for f in findings)

    @pytest.mark.unit
    async def test_investigate_cost_increase_basic(self) -> None:
        client = self._make_client()
        client.get_performance_report.return_value = [
            {"metrics": {"impressions": 1000, "clicks": 100, "cost": 5000,
                         "conversions": 5, "average_cpc": 50}}
        ]
        client.get_search_terms_report.return_value = []
        client.list_change_history.return_value = []
        client.list_negative_keywords.return_value = []
        result = await client.investigate_cost_increase("123")
        assert result["campaign_id"] == "123"
        assert "findings" in result
        assert "recommended_actions" in result

    @pytest.mark.unit
    async def test_health_check_all_campaigns(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = [
            {"id": "1", "name": "Camp A", "status": "ENABLED", "primary_status": "ELIGIBLE"},
            {"id": "2", "name": "Camp B", "status": "ENABLED", "primary_status": "NOT_ELIGIBLE"},
            {"id": "3", "name": "Camp C", "status": "PAUSED"},
        ]
        client.diagnose_campaign_delivery.return_value = {
            "issues": ["test issue"],
            "warnings": [],
            "recommendations": [],
        }

        result = await client.health_check_all_campaigns()
        assert result["total_campaigns"] == 3
        assert result["enabled_count"] == 2
        assert result["paused_count"] == 1
        assert len(result["healthy_campaigns"]) == 1
        assert len(result["problem_campaigns"]) == 1
        assert "message" in result["summary"]

    @pytest.mark.unit
    async def test_health_check_all_healthy(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = [
            {"id": "1", "name": "Good", "status": "ENABLED", "primary_status": "ELIGIBLE"},
        ]
        result = await client.health_check_all_campaigns()
        assert "正常" in result["summary"]["message"]

    @pytest.mark.unit
    async def test_compare_ad_performance_basic(self) -> None:
        client = self._make_client()
        client.get_ad_performance_report.return_value = [
            {
                "ad_id": "ad1",
                "status": "ENABLED",
                "metrics": {"impressions": 500, "clicks": 50, "conversions": 5, "cost": 1000},
            },
            {
                "ad_id": "ad2",
                "status": "ENABLED",
                "metrics": {"impressions": 500, "clicks": 30, "conversions": 2, "cost": 800},
            },
        ]
        result = await client.compare_ad_performance("ag1")
        assert len(result["ads"]) == 2
        assert result["ads"][0]["rank"] == 1
        assert result["winner"] is not None

    @pytest.mark.unit
    async def test_compare_ad_performance_insufficient_data(self) -> None:
        client = self._make_client()
        client.get_ad_performance_report.return_value = [
            {
                "ad_id": "ad1",
                "status": "ENABLED",
                "metrics": {"impressions": 50, "clicks": 5, "conversions": 0, "cost": 100},
            },
        ]
        result = await client.compare_ad_performance("ag1")
        assert result["ads"][0]["verdict"] == "INSUFFICIENT_DATA"
        assert "比較対象" in result["recommendation"]

    @pytest.mark.unit
    async def test_compare_ad_performance_empty(self) -> None:
        client = self._make_client()
        client.get_ad_performance_report.return_value = []
        result = await client.compare_ad_performance("ag1")
        assert len(result["ads"]) == 0

    @pytest.mark.unit
    async def test_analyze_search_term_changes(self) -> None:
        client = self._make_client()
        client.get_search_terms_report.side_effect = [
            # 当期
            [
                {"search_term": "new term", "metrics": {"cost": 500, "conversions": 0}},
                {"search_term": "old term", "metrics": {"cost": 300, "conversions": 1}},
            ],
            # 前期
            [
                {"search_term": "old term", "metrics": {"cost": 200, "conversions": 1}},
            ],
        ]
        result = await client._analyze_search_term_changes("123")
        assert len(result["new_search_terms"]) == 1
        assert result["new_search_terms"][0]["search_term"] == "new term"
        assert result["finding"] is not None


# =====================================================================
# _analysis_search_terms テスト
# =====================================================================


class TestSearchTermsAnalysisMixin:
    """_SearchTermsAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    @pytest.mark.unit
    def test_is_informational_term_true(self) -> None:
        assert _is_informational_term("SEOとは何か") is True
        assert _is_informational_term("ツール比較サイト") is True

    @pytest.mark.unit
    def test_is_informational_term_false(self) -> None:
        assert _is_informational_term("広告代理店") is False

    @pytest.mark.unit
    def test_build_add_candidate(self) -> None:
        result = _build_add_candidate("keyword", 2.0, 30, 1000, 0.05, "EXACT", 90, "test")
        assert result["action"] == "add"
        assert result["match_type"] == "EXACT"
        assert result["score"] == 90

    @pytest.mark.unit
    def test_build_exclude_candidate(self) -> None:
        result = _build_exclude_candidate("keyword", 0.0, 50, 2000, 0.01, "PHRASE", 80, "test")
        assert result["action"] == "exclude"
        assert result["match_type"] == "PHRASE"

    @pytest.mark.unit
    def test_route_by_newness_new(self) -> None:
        client = self._make_client()
        entry = {"action": "exclude", "reason": "test"}
        main: list[dict[str, Any]] = []
        watch: list[dict[str, Any]] = []
        client._route_by_newness(entry, "term", True, main, watch)
        assert len(watch) == 1
        assert entry["action"] == "watch"
        assert "新規語句" in entry["reason"]

    @pytest.mark.unit
    def test_route_by_newness_existing(self) -> None:
        client = self._make_client()
        entry = {"action": "exclude", "reason": "test"}
        main: list[dict[str, Any]] = []
        watch: list[dict[str, Any]] = []
        client._route_by_newness(entry, "term", False, main, watch)
        assert len(main) == 1
        assert len(watch) == 0

    @pytest.mark.unit
    async def test_analyze_search_terms_basic(self) -> None:
        client = self._make_client()
        client.list_keywords.return_value = [
            {"text": "広告 運用"}
        ]
        client.get_search_terms_report.return_value = [
            {
                "search_term": "広告 運用",
                "metrics": {"cost": 500, "conversions": 2, "clicks": 10, "impressions": 100},
            },
            {
                "search_term": "広告 代理店",
                "metrics": {"cost": 300, "conversions": 1, "clicks": 5, "impressions": 80},
            },
            {
                "search_term": "無駄語句",
                "metrics": {"cost": 200, "conversions": 0, "clicks": 8, "impressions": 50},
            },
        ]
        result = await client.analyze_search_terms("123")
        assert result["campaign_id"] == "123"
        assert result["registered_keywords_count"] == 1
        assert result["search_terms_count"] == 3
        assert 0 <= result["overlap_rate"] <= 1
        assert "ngram_distribution" in result
        assert len(result["keyword_candidates"]) >= 1
        assert len(result["negative_candidates"]) >= 1

    @pytest.mark.unit
    async def test_analyze_search_terms_empty(self) -> None:
        client = self._make_client()
        client.list_keywords.return_value = []
        client.get_search_terms_report.return_value = []
        result = await client.analyze_search_terms("123")
        assert result["search_terms_count"] == 0
        assert result["overlap_rate"] == 0.0

    @pytest.mark.unit
    async def test_suggest_negative_keywords_basic(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {
            "bidding_details": {"target_cpa": 3000}
        }
        # 当期
        terms_current = [
            {"search_term": "expensive term", "metrics": {"cost": 5000, "conversions": 0, "clicks": 20, "impressions": 500, "ctr": 0.04}},
            {"search_term": "cheap term", "metrics": {"cost": 100, "conversions": 0, "clicks": 2, "impressions": 50, "ctr": 0.04}},
            {"search_term": "good term", "metrics": {"cost": 2000, "conversions": 3, "clicks": 10, "impressions": 200, "ctr": 0.05}},
        ]
        # 前期
        terms_prev = [
            {"search_term": "expensive term", "metrics": {}},
            {"search_term": "cheap term", "metrics": {}},
            {"search_term": "good term", "metrics": {}},
        ]
        client.get_search_terms_report.side_effect = [terms_current, terms_prev]
        client.list_negative_keywords.return_value = []

        result = await client.suggest_negative_keywords("123", use_intent_analysis=False)
        assert result["target_cpa"] == 3000.0
        assert result["target_cpa_source"] == "bidding_strategy"
        # expensive term: cost 5000 > 3000*1.5=4500 → 除外候補
        assert len(result["suggestions"]) >= 1
        assert result["suggestions"][0]["search_term"] == "expensive term"

    @pytest.mark.unit
    async def test_suggest_negative_keywords_informational(self) -> None:
        """情報収集パターンはCPA閾値に関わらず除外候補になる。"""
        client = self._make_client()
        client.get_campaign.return_value = {"bidding_details": {"target_cpa": 10000}}
        terms = [
            {"search_term": "SEOとは", "metrics": {"cost": 100, "conversions": 0, "clicks": 5, "impressions": 200, "ctr": 0.025}},
        ]
        client.get_search_terms_report.side_effect = [
            terms,  # 当期
            terms,  # 前期（同じ→既存語句扱い）
        ]
        client.list_negative_keywords.return_value = []
        result = await client.suggest_negative_keywords("123", use_intent_analysis=False)
        assert len(result["suggestions"]) >= 1
        assert "PHRASE" == result["suggestions"][0]["recommended_match_type"]

    @pytest.mark.unit
    async def test_review_search_terms_classification(self) -> None:
        """多段階ルールによる分類テスト。"""
        client = self._make_client()
        client.get_campaign.return_value = {
            "bidding_details": {"target_cpa": 3000}
        }
        terms = [
            # Rule 1: CV>=2 & 未登録 → add
            {"search_term": "high cv term", "metrics": {"conversions": 3, "clicks": 20, "cost": 2000, "impressions": 500}},
            # Rule 4: CV=0 & cost >= CPA*2 → exclude
            {"search_term": "waste term", "metrics": {"conversions": 0, "clicks": 40, "cost": 7000, "impressions": 1000}},
            # Rule 6: 情報収集 & CV=0 → exclude
            {"search_term": "SEOとは", "metrics": {"conversions": 0, "clicks": 5, "cost": 200, "impressions": 100}},
        ]
        client.get_search_terms_report.side_effect = [
            terms,  # 当期
            terms,  # 前期
        ]
        client.list_keywords.return_value = []
        client.list_negative_keywords.return_value = []

        result = await client.review_search_terms(
            "123", use_intent_analysis=False
        )
        assert result["summary"]["add_count"] >= 1
        assert result["summary"]["exclude_count"] >= 1

    @pytest.mark.unit
    def test_classify_search_term_rule1_add(self) -> None:
        """Rule 1: CV>=2 & 未登録 → add EXACT (score=90)。"""
        client = self._make_client()
        add: list[dict[str, Any]] = []
        exclude: list[dict[str, Any]] = []
        watch: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "good kw", "metrics": {"conversions": 3, "clicks": 20, "cost": 1000, "impressions": 500}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set=set(),
            resolved_cpa=3000.0,
            add_candidates=add,
            exclude_candidates=exclude,
            watch_candidates=watch,
        )
        assert len(add) == 1
        assert add[0]["score"] == 90
        assert add[0]["match_type"] == "EXACT"

    @pytest.mark.unit
    def test_classify_search_term_rule2_add(self) -> None:
        """Rule 2: CV=1 & CPA<=目標CPA → add EXACT (score=70)。"""
        client = self._make_client()
        add: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "decent kw", "metrics": {"conversions": 1, "clicks": 10, "cost": 2000, "impressions": 200}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set=set(),
            resolved_cpa=3000.0,
            add_candidates=add,
            exclude_candidates=[],
            watch_candidates=[],
        )
        assert len(add) == 1
        assert add[0]["score"] == 70

    @pytest.mark.unit
    def test_classify_search_term_rule3_add_high_ctr(self) -> None:
        """Rule 3: CV=0 & Click>=20 & CTR>=3% → add PHRASE (score=50)。"""
        client = self._make_client()
        add: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "high ctr", "metrics": {"conversions": 0, "clicks": 25, "cost": 500, "impressions": 500}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set=set(),
            resolved_cpa=3000.0,
            add_candidates=add,
            exclude_candidates=[],
            watch_candidates=[],
        )
        assert len(add) == 1
        assert add[0]["score"] == 50
        assert add[0]["match_type"] == "PHRASE"

    @pytest.mark.unit
    def test_classify_search_term_rule4_exclude(self) -> None:
        """Rule 4: CV=0 & cost>=CPA*2 → exclude EXACT (score=80)。"""
        client = self._make_client()
        exclude: list[dict[str, Any]] = []
        # clicks=10, impressions=1000 → CTR=1% でRule3にマッチしない
        client._classify_search_term(
            {"search_term": "waste", "metrics": {"conversions": 0, "clicks": 10, "cost": 7000, "impressions": 1000}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set={"waste"},  # 既存語句
            resolved_cpa=3000.0,
            add_candidates=[],
            exclude_candidates=exclude,
            watch_candidates=[],
        )
        assert len(exclude) == 1
        assert exclude[0]["score"] == 80

    @pytest.mark.unit
    def test_classify_search_term_rule5_low_ctr(self) -> None:
        """Rule 5: CV=0 & Click>=30 & CTR<1% → exclude EXACT (score=60)。"""
        client = self._make_client()
        exclude: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "low ctr", "metrics": {"conversions": 0, "clicks": 40, "cost": 500, "impressions": 5000}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set={"low ctr"},
            resolved_cpa=None,
            add_candidates=[],
            exclude_candidates=exclude,
            watch_candidates=[],
        )
        assert len(exclude) == 1
        assert exclude[0]["score"] == 60

    @pytest.mark.unit
    def test_classify_search_term_already_excluded(self) -> None:
        """既に除外登録済みの語句はスキップされる。"""
        client = self._make_client()
        exclude: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "waste", "metrics": {"conversions": 0, "clicks": 30, "cost": 7000, "impressions": 1000}},
            keyword_texts=set(),
            existing_neg_texts={"waste"},
            prev_term_set={"waste"},
            resolved_cpa=3000.0,
            add_candidates=[],
            exclude_candidates=exclude,
            watch_candidates=[],
        )
        assert len(exclude) == 0

    @pytest.mark.unit
    def test_classify_search_term_no_match(self) -> None:
        """どのルールにもマッチしない場合はどのリストにも追加されない。"""
        client = self._make_client()
        add: list[dict[str, Any]] = []
        exclude: list[dict[str, Any]] = []
        watch: list[dict[str, Any]] = []
        client._classify_search_term(
            {"search_term": "neutral", "metrics": {"conversions": 0, "clicks": 5, "cost": 100, "impressions": 200}},
            keyword_texts=set(),
            existing_neg_texts=set(),
            prev_term_set={"neutral"},
            resolved_cpa=3000.0,
            add_candidates=add,
            exclude_candidates=exclude,
            watch_candidates=watch,
        )
        assert len(add) == 0
        assert len(exclude) == 0
        assert len(watch) == 0


# =====================================================================
# _analysis_keywords テスト
# =====================================================================


class TestKeywordsAnalysisMixin:
    """_KeywordsAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    def _make_gaql_row(
        self,
        criterion_id: int = 1,
        text: str = "test kw",
        match_type: int = 2,
        status: int = 2,
        ad_group_id: int = 100,
        ad_group_name: str = "AdGroup1",
        impressions: int = 100,
        clicks: int = 10,
        cost_micros: int = 5_000_000,
        conversions: float = 1.0,
    ) -> SimpleNamespace:
        """GAQL レスポンス行をSimpleNamespaceで模倣する。"""
        return SimpleNamespace(
            ad_group_criterion=SimpleNamespace(
                criterion_id=criterion_id,
                keyword=SimpleNamespace(text=text, match_type=match_type),
                status=status,
            ),
            ad_group=SimpleNamespace(id=ad_group_id, name=ad_group_name),
            metrics=SimpleNamespace(
                impressions=impressions,
                clicks=clicks,
                cost_micros=cost_micros,
                conversions=conversions,
            ),
        )

    @pytest.mark.unit
    async def test_get_keyword_performance(self) -> None:
        client = self._make_client()
        client._search.return_value = [
            self._make_gaql_row(criterion_id=1, text="kw1", match_type=2, cost_micros=3_000_000, conversions=2.0),
        ]
        results = await client._get_keyword_performance("123")
        assert len(results) == 1
        assert results[0]["text"] == "kw1"
        assert results[0]["match_type"] == "EXACT"
        assert results[0]["metrics"]["cost"] == 3.0

    @pytest.mark.unit
    async def test_get_keyword_performance_exception(self) -> None:
        client = self._make_client()
        client._search.side_effect = Exception("API error")
        results = await client._get_keyword_performance("123")
        assert results == []

    @pytest.mark.unit
    def test_evaluate_keyword_rule1_broad_no_cv(self) -> None:
        """Rule 1: BROAD & CV=0 & コスト>目標CPA → narrow_to_phrase。"""
        kw = {
            "text": "broad kw", "criterion_id": "1", "ad_group_id": "100",
            "match_type": "BROAD",
            "metrics": {"conversions": 0, "clicks": 20, "cost": 5000, "impressions": 300},
        }
        rec = _KeywordsAnalysisMixin._evaluate_keyword(kw, 3000.0, 0.02)
        assert rec is not None
        assert rec["action"] == "narrow_to_phrase"
        assert rec["priority"] == "HIGH"

    @pytest.mark.unit
    def test_evaluate_keyword_rule2_no_cv_many_clicks(self) -> None:
        """Rule 2: CV=0 & Click>50 → pause。"""
        kw = {
            "text": "kw", "criterion_id": "1", "ad_group_id": "100",
            "match_type": "EXACT",
            "metrics": {"conversions": 0, "clicks": 60, "cost": 3000, "impressions": 1000},
        }
        rec = _KeywordsAnalysisMixin._evaluate_keyword(kw, 3000.0, 0.02)
        assert rec is not None
        assert rec["action"] == "pause"
        assert rec["priority"] == "HIGH"

    @pytest.mark.unit
    def test_evaluate_keyword_rule3_phrase_high_cvr(self) -> None:
        """Rule 3: PHRASE & CVR>avg*1.5 → add_exact。"""
        kw = {
            "text": "kw", "criterion_id": "1", "ad_group_id": "100",
            "match_type": "PHRASE",
            "metrics": {"conversions": 5, "clicks": 20, "cost": 3000, "impressions": 500},
        }
        # CVR = 5/20 = 0.25, avg_cvr = 0.05, avg*1.5 = 0.075
        rec = _KeywordsAnalysisMixin._evaluate_keyword(kw, 3000.0, 0.05)
        assert rec is not None
        assert rec["action"] == "add_exact"
        assert rec["priority"] == "MEDIUM"

    @pytest.mark.unit
    def test_evaluate_keyword_rule4_exact_low_imp(self) -> None:
        """Rule 4: EXACT & Imp<50 → expand_to_phrase。"""
        kw = {
            "text": "kw", "criterion_id": "1", "ad_group_id": "100",
            "match_type": "EXACT",
            "metrics": {"conversions": 1, "clicks": 3, "cost": 500, "impressions": 30},
        }
        rec = _KeywordsAnalysisMixin._evaluate_keyword(kw, 3000.0, 0.02)
        assert rec is not None
        assert rec["action"] == "expand_to_phrase"
        assert rec["priority"] == "LOW"

    @pytest.mark.unit
    def test_evaluate_keyword_no_action(self) -> None:
        """どのルールにもマッチしない → None。"""
        kw = {
            "text": "kw", "criterion_id": "1", "ad_group_id": "100",
            "match_type": "EXACT",
            "metrics": {"conversions": 2, "clicks": 20, "cost": 2000, "impressions": 500},
        }
        rec = _KeywordsAnalysisMixin._evaluate_keyword(kw, 3000.0, 0.02)
        assert rec is None

    @pytest.mark.unit
    async def test_audit_keywords(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"bidding_details": {"target_cpa": 3000}}
        client._search.return_value = [
            self._make_gaql_row(text="broad kw", match_type=4, cost_micros=5_000_000, conversions=0, clicks=10),
            self._make_gaql_row(criterion_id=2, text="good kw", match_type=2, cost_micros=2_000_000, conversions=3, clicks=20),
        ]
        result = await client.audit_keywords("123")
        assert result["total_keywords"] == 2
        assert "recommendations" in result
        assert "summary" in result

    @pytest.mark.unit
    async def test_find_cross_adgroup_duplicates(self) -> None:
        client = self._make_client()
        # 同じキーワード・マッチタイプが2つの広告グループに存在
        client._search.return_value = [
            self._make_gaql_row(criterion_id=1, text="dup kw", match_type=2, ad_group_id=100, ad_group_name="AG1", conversions=3),
            self._make_gaql_row(criterion_id=2, text="dup kw", match_type=2, ad_group_id=200, ad_group_name="AG2", conversions=0),
        ]
        result = await client.find_cross_adgroup_duplicates("123")
        assert result["duplicate_groups_count"] == 1
        assert result["total_removable_keywords"] == 1
        group = result["duplicate_groups"][0]
        assert group["keep"]["ad_group_id"] == "100"  # better performance
        assert len(group["remove"]) == 1

    @pytest.mark.unit
    async def test_find_cross_adgroup_duplicates_no_duplicates(self) -> None:
        client = self._make_client()
        client._search.return_value = [
            self._make_gaql_row(criterion_id=1, text="kw1", match_type=2, ad_group_id=100),
            self._make_gaql_row(criterion_id=2, text="kw2", match_type=2, ad_group_id=100),
        ]
        result = await client.find_cross_adgroup_duplicates("123")
        assert result["duplicate_groups_count"] == 0

    @pytest.mark.unit
    async def test_find_cross_adgroup_duplicates_error(self) -> None:
        client = self._make_client()
        client._search.side_effect = Exception("API error")
        result = await client.find_cross_adgroup_duplicates("123")
        assert "error" in result

    @pytest.mark.unit
    def test_extract_duplicate_groups(self) -> None:
        groups = {
            "kw1|EXACT": [
                {"ad_group_id": "100", "ad_group_name": "AG1", "criterion_id": "1",
                 "text": "kw1", "match_type": "EXACT", "status": "ENABLED",
                 "metrics": {"conversions": 5, "clicks": 30, "impressions": 500, "cost": 3000}},
                {"ad_group_id": "200", "ad_group_name": "AG2", "criterion_id": "2",
                 "text": "kw1", "match_type": "EXACT", "status": "ENABLED",
                 "metrics": {"conversions": 0, "clicks": 5, "impressions": 100, "cost": 500}},
            ],
            "kw2|PHRASE": [
                {"ad_group_id": "100", "ad_group_name": "AG1", "criterion_id": "3",
                 "text": "kw2", "match_type": "PHRASE", "status": "ENABLED",
                 "metrics": {"conversions": 1, "clicks": 10, "impressions": 200, "cost": 1000}},
            ],
        }
        dups, removable, waste = _KeywordsAnalysisMixin._extract_duplicate_groups(groups)
        assert len(dups) == 1
        assert removable == 1
        assert waste == 500  # CV=0のremovableのcost


# =====================================================================
# _analysis_budget テスト
# =====================================================================


class TestBudgetAnalysisMixin:
    """_BudgetAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    @pytest.mark.unit
    async def test_analyze_budget_efficiency(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = [
            {"id": "1", "name": "Efficient", "status": "ENABLED"},
            {"id": "2", "name": "Inefficient", "status": "ENABLED"},
        ]
        client.get_performance_report.side_effect = [
            [{"metrics": {"cost": 3000, "conversions": 10}}],  # Camp 1
            [{"metrics": {"cost": 7000, "conversions": 2}}],   # Camp 2
        ]
        result = await client.analyze_budget_efficiency()
        assert result["total_cost"] == 10000
        assert result["total_conversions"] == 12.0
        assert len(result["campaigns"]) == 2
        # Camp 1 は効率的（cv_share/cost_share > 1.2）
        camp1 = next(c for c in result["campaigns"] if c["campaign_id"] == "1")
        assert camp1["verdict"] == "EFFICIENT"

    @pytest.mark.unit
    async def test_analyze_budget_efficiency_no_campaigns(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = []
        result = await client.analyze_budget_efficiency()
        assert result["total_cost"] == 0
        assert result["campaigns"] == []

    @pytest.mark.unit
    async def test_analyze_budget_efficiency_zero_cost(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = [
            {"id": "1", "name": "No Cost", "status": "ENABLED"},
        ]
        client.get_performance_report.return_value = [
            {"metrics": {"cost": 0, "conversions": 0}}
        ]
        result = await client.analyze_budget_efficiency()
        camp = result["campaigns"][0]
        assert camp["verdict"] == "NO_COST"

    @pytest.mark.unit
    async def test_suggest_budget_reallocation(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = [
            {"id": "1", "name": "Efficient", "status": "ENABLED"},
            {"id": "2", "name": "Inefficient", "status": "ENABLED"},
        ]
        client.get_performance_report.side_effect = [
            [{"metrics": {"cost": 3000, "conversions": 10}}],
            [{"metrics": {"cost": 7000, "conversions": 2}}],
        ]
        client.get_budget.side_effect = [
            {"daily_budget": 5000, "id": "b1"},
            {"daily_budget": 10000, "id": "b2"},
        ]
        result = await client.suggest_budget_reallocation()
        assert "reallocation_plan" in result
        plan = result["reallocation_plan"]
        # 非効率キャンペーンから削減 → 効率キャンペーンへ増額
        decreases = [p for p in plan if p["action"] == "DECREASE"]
        increases = [p for p in plan if p["action"] == "INCREASE"]
        assert len(decreases) >= 1
        assert len(increases) >= 1

    @pytest.mark.unit
    async def test_suggest_budget_reallocation_no_data(self) -> None:
        client = self._make_client()
        client.list_campaigns.return_value = []
        result = await client.suggest_budget_reallocation()
        assert result["reallocation_plan"] == []
        assert "データ不足" in result["summary"]


# =====================================================================
# _analysis_rsa テスト
# =====================================================================


class TestRsaAnalysisMixin:
    """_RsaAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    def _make_asset_row(
        self,
        text: str = "見出しテスト",
        field_type: str = "HEADLINE",
        perf_label: str = "BEST",
        impressions: int = 1000,
        clicks: int = 100,
        conversions: float = 5.0,
        cost_micros: int = 3_000_000,
    ) -> SimpleNamespace:
        class _FieldType:
            def __str__(self) -> str:
                return f"FieldType.{field_type}"
        class _PerfLabel:
            def __str__(self) -> str:
                return f"PerfLabel.{perf_label}"
        return SimpleNamespace(
            ad_group_ad_asset_view=SimpleNamespace(
                ad_group_ad="ad1",
                asset="asset1",
                field_type=_FieldType(),
                performance_label=_PerfLabel(),
                enabled=True,
            ),
            asset=SimpleNamespace(text_asset=SimpleNamespace(text=text)),
            metrics=SimpleNamespace(
                impressions=impressions,
                clicks=clicks,
                conversions=conversions,
                cost_micros=cost_micros,
            ),
        )

    @pytest.mark.unit
    async def test_analyze_rsa_assets_basic(self) -> None:
        client = self._make_client()
        client._search.return_value = [
            self._make_asset_row("Best Headline", "HEADLINE", "BEST", 1000, 100, 5.0),
            self._make_asset_row("Low Headline", "HEADLINE", "LOW", 500, 20, 0.0),
            self._make_asset_row("Best Desc", "DESCRIPTION", "BEST", 800, 80, 4.0),
        ]
        result = await client.analyze_rsa_assets("123")
        assert len(result["headlines"]) == 2
        assert len(result["descriptions"]) == 1
        assert len(result["best_headlines"]) == 1
        assert len(result["worst_headlines"]) == 1
        assert result["best_headlines"][0]["text"] == "Best Headline"

    @pytest.mark.unit
    async def test_analyze_rsa_assets_empty(self) -> None:
        client = self._make_client()
        client._search.return_value = []
        result = await client.analyze_rsa_assets("123")
        assert result["headlines"] == []
        assert result["descriptions"] == []
        assert any("まだ蓄積されていません" in i for i in result["insights"])

    @pytest.mark.unit
    async def test_audit_rsa_assets_few_headlines(self) -> None:
        client = self._make_client()
        client._search.return_value = [
            self._make_asset_row("H1", "HEADLINE", "BEST"),
            self._make_asset_row("H2", "HEADLINE", "GOOD"),
        ]
        result = await client.audit_rsa_assets("123")
        # 2本しかないので add_headlines 推奨
        rec_types = [r["type"] for r in result["recommendations"]]
        assert "add_headlines" in rec_types

    @pytest.mark.unit
    async def test_audit_rsa_assets_no_data(self) -> None:
        client = self._make_client()
        client._search.return_value = []
        result = await client.audit_rsa_assets("123")
        assert result["message"] == "RSAアセットデータがありません"

    @pytest.mark.unit
    async def test_audit_rsa_assets_error(self) -> None:
        client = self._make_client()
        client._search.side_effect = Exception("API Error")
        result = await client.audit_rsa_assets("123")
        assert "error" in result

    @pytest.mark.unit
    def test_count_label_distribution(self) -> None:
        headlines = [
            {"performance_label": "BEST"},
            {"performance_label": "BEST"},
            {"performance_label": "LOW"},
        ]
        descriptions = [
            {"performance_label": "GOOD"},
        ]
        dist = _RsaAnalysisMixin._count_label_distribution(headlines, descriptions)
        assert dist["BEST"] == 2
        assert dist["LOW"] == 1
        assert dist["GOOD"] == 1

    @pytest.mark.unit
    def test_check_asset_counts_below_threshold(self) -> None:
        recs: list[dict[str, Any]] = []
        _RsaAnalysisMixin._check_asset_counts(5, 2, recs)
        types = [r["type"] for r in recs]
        assert "add_headlines" in types
        assert "add_descriptions" in types

    @pytest.mark.unit
    def test_check_asset_counts_above_threshold(self) -> None:
        recs: list[dict[str, Any]] = []
        _RsaAnalysisMixin._check_asset_counts(10, 4, recs)
        assert len(recs) == 0

    @pytest.mark.unit
    def test_recommend_asset_replacements(self) -> None:
        recs: list[dict[str, Any]] = []
        worst_h = [{"text": "bad headline", "performance_label": "LOW"}]
        worst_d = [{"text": "bad desc", "performance_label": "POOR"}]
        _RsaAnalysisMixin._recommend_asset_replacements(worst_h, worst_d, recs)
        assert len(recs) == 2
        assert recs[0]["type"] == "replace_headline"
        assert recs[1]["type"] == "replace_description"


# =====================================================================
# _analysis_auction テスト
# =====================================================================


class TestAuctionAnalysisMixin:
    """_AuctionAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    # --- デバイス分析 ---

    def _make_device_row(
        self,
        device: str = "DESKTOP",
        impressions: int = 1000,
        clicks: int = 100,
        cost_micros: int = 5_000_000,
        conversions: float = 5.0,
        ctr: float = 0.10,
        average_cpc: int = 50_000,
    ) -> SimpleNamespace:
        class _Device:
            def __str__(self) -> str:
                return f"Device.{device}"
        return SimpleNamespace(
            segments=SimpleNamespace(device=_Device()),
            metrics=SimpleNamespace(
                impressions=impressions,
                clicks=clicks,
                cost_micros=cost_micros,
                conversions=conversions,
                ctr=ctr,
                average_cpc=average_cpc,
            ),
        )

    @pytest.mark.unit
    async def test_analyze_device_performance_basic(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test Campaign"}
        client._search.return_value = [
            self._make_device_row("DESKTOP", 1000, 100, 5_000_000, 5.0, 0.10, 50_000),
            self._make_device_row("MOBILE", 800, 60, 4_000_000, 2.0, 0.075, 66_667),
        ]
        result = await client.analyze_device_performance("123")
        assert len(result["devices"]) == 2
        assert result["devices"][0]["cost"] >= result["devices"][1]["cost"]

    @pytest.mark.unit
    async def test_analyze_device_performance_not_found(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = None
        result = await client.analyze_device_performance("999")
        assert "error" in result

    @pytest.mark.unit
    async def test_analyze_device_performance_no_data(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        client._search.return_value = []
        result = await client.analyze_device_performance("123")
        assert result["devices"] == []
        assert "データがありません" in result["message"]

    @pytest.mark.unit
    def test_generate_device_insights_cv0_cost(self) -> None:
        devices = [
            {"device_type": "TABLET", "conversions": 0, "cost": 1000, "cpa": None, "ctr": 5.0},
        ]
        insights = _AuctionAnalysisMixin._generate_device_insights(devices)
        assert any("TABLET" in i and "CV0" in i for i in insights)

    @pytest.mark.unit
    def test_generate_device_insights_cpa_gap(self) -> None:
        devices = [
            {"device_type": "DESKTOP", "conversions": 5, "cost": 5000, "cpa": 1000, "ctr": 10.0},
            {"device_type": "MOBILE", "conversions": 2, "cost": 4000, "cpa": 2000, "ctr": 5.0},
        ]
        insights = _AuctionAnalysisMixin._generate_device_insights(devices)
        assert any("倍" in i for i in insights)

    @pytest.mark.unit
    def test_generate_device_insights_mobile_low_ctr(self) -> None:
        devices = [
            {"device_type": "DESKTOP", "conversions": 5, "cost": 5000, "cpa": 1000, "ctr": 10.0},
            {"device_type": "MOBILE", "conversions": 2, "cost": 2000, "cpa": 1000, "ctr": 3.0},
        ]
        insights = _AuctionAnalysisMixin._generate_device_insights(devices)
        assert any("モバイルのCTR" in i for i in insights)

    # --- CPC トレンド ---

    @pytest.mark.unit
    def test_calculate_cpc_trend_rising(self) -> None:
        values = [100, 110, 120, 130, 140, 150, 160]
        trend = _AuctionAnalysisMixin._calculate_cpc_trend(values)
        assert trend["direction"] == "rising"
        assert trend["slope_per_day"] > 0

    @pytest.mark.unit
    def test_calculate_cpc_trend_stable(self) -> None:
        values = [100, 101, 99, 100, 101, 99, 100]
        trend = _AuctionAnalysisMixin._calculate_cpc_trend(values)
        assert trend["direction"] == "stable"

    @pytest.mark.unit
    def test_calculate_cpc_trend_falling(self) -> None:
        values = [160, 150, 140, 130, 120, 110, 100]
        trend = _AuctionAnalysisMixin._calculate_cpc_trend(values)
        assert trend["direction"] == "falling"

    @pytest.mark.unit
    def test_calculate_cpc_trend_insufficient(self) -> None:
        trend = _AuctionAnalysisMixin._calculate_cpc_trend([100])
        assert trend["direction"] == "insufficient_data"

    @pytest.mark.unit
    def test_calculate_cpc_trend_empty(self) -> None:
        trend = _AuctionAnalysisMixin._calculate_cpc_trend([])
        assert trend["direction"] == "insufficient_data"
        assert trend["avg_cpc"] == 0.0

    @pytest.mark.unit
    def test_generate_cpc_insights_rising(self) -> None:
        trend = {"direction": "rising", "change_rate_per_day_pct": 2.5, "avg_cpc": 100}
        insights = _AuctionAnalysisMixin._generate_cpc_insights([100], trend, [])
        assert any("上昇トレンド" in i for i in insights)

    @pytest.mark.unit
    def test_generate_cpc_insights_falling(self) -> None:
        trend = {"direction": "falling", "change_rate_per_day_pct": -2.5, "avg_cpc": 100}
        insights = _AuctionAnalysisMixin._generate_cpc_insights([100], trend, [])
        assert any("下降トレンド" in i for i in insights)

    @pytest.mark.unit
    def test_generate_cpc_insights_weekly_spike(self) -> None:
        # 14日分のデータ: 前7日=100, 直近7日=130 → 30%急騰
        values = [100] * 7 + [130] * 7
        trend = {"direction": "rising", "change_rate_per_day_pct": 1.5, "avg_cpc": 115}
        insights = _AuctionAnalysisMixin._generate_cpc_insights(values, trend, [])
        assert any("急騰" in i for i in insights)

    @pytest.mark.unit
    def test_generate_cpc_insights_spike_detection(self) -> None:
        daily_data = [
            {"date": "2026-03-01", "average_cpc": 100},
            {"date": "2026-03-02", "average_cpc": 300},  # spike: > 100*2
        ]
        trend = {"direction": "stable", "change_rate_per_day_pct": 0, "avg_cpc": 100}
        insights = _AuctionAnalysisMixin._generate_cpc_insights([100, 300], trend, daily_data)
        assert any("異常値" in i for i in insights)

    @pytest.mark.unit
    async def test_detect_cpc_trend_not_found(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = None
        result = await client.detect_cpc_trend("999")
        assert "error" in result

    @pytest.mark.unit
    async def test_detect_cpc_trend_no_data(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        client._search.return_value = []
        result = await client.detect_cpc_trend("123")
        assert result["daily_data"] == []
        assert result["trend"] is None

    @pytest.mark.unit
    async def test_detect_cpc_trend_with_data(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        rows = []
        for i in range(7):
            rows.append(SimpleNamespace(
                segments=SimpleNamespace(date=f"2026-03-{20+i:02d}"),
                metrics=SimpleNamespace(
                    average_cpc=(100 + i * 10) * 1_000_000,
                    clicks=50,
                    impressions=500,
                    cost_micros=5000 * 1_000_000,
                ),
            ))
        client._search.return_value = rows
        result = await client.detect_cpc_trend("123")
        assert result["data_points"] == 7
        assert result["trend"]["direction"] in ("rising", "stable", "falling")

    # --- オークション分析 ---

    def _make_auction_row(
        self, domain: str = "", is_pct: float = 0.5,
        overlap: float = 0.3, position_above: float = 0.2,
        top_imp: float = 0.4, abs_top: float = 0.1, outranking: float = 0.25,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            auction_insight=SimpleNamespace(display_domain=domain),
            metrics=SimpleNamespace(
                auction_insight_search_impression_share=is_pct,
                auction_insight_search_overlap_rate=overlap,
                auction_insight_search_position_above_rate=position_above,
                auction_insight_search_top_impression_percentage=top_imp,
                auction_insight_search_absolute_top_impression_percentage=abs_top,
                auction_insight_search_outranking_share=outranking,
            ),
        )

    @pytest.mark.unit
    async def test_get_auction_insights_basic(self) -> None:
        client = self._make_client()
        client._search.return_value = [
            self._make_auction_row("", 0.6),
            self._make_auction_row("competitor.com", 0.4),
        ]
        result = await client.get_auction_insights("123")
        assert len(result) == 2
        # IS降順ソート
        assert result[0]["impression_share"] >= result[1]["impression_share"]

    @pytest.mark.unit
    async def test_get_auction_insights_error(self) -> None:
        client = self._make_client()
        client._search.side_effect = Exception("API error")
        result = await client.get_auction_insights("123")
        assert result == []

    @pytest.mark.unit
    async def test_analyze_auction_insights_not_found(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = None
        result = await client.analyze_auction_insights("999")
        assert "error" in result

    @pytest.mark.unit
    async def test_analyze_auction_insights_no_data(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        client._search.return_value = []
        result = await client.analyze_auction_insights("123")
        assert result["competitors"] == []
        assert "データがありません" in result["message"]

    @pytest.mark.unit
    async def test_analyze_auction_insights_low_is(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        client._search.return_value = [
            self._make_auction_row("", 0.3, abs_top=0.1),  # IS 30% < 50%
            self._make_auction_row("competitor.com", 0.5, outranking=0.6),
        ]
        result = await client.analyze_auction_insights("123")
        assert any("表示機会" in i for i in result["insights"])
        assert any("上回られ" in i for i in result["insights"])

    @pytest.mark.unit
    async def test_analyze_auction_insights_low_abs_top(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "Test"}
        client._search.return_value = [
            self._make_auction_row("", 0.6, abs_top=0.1),  # abs_top 10% < 20%
        ]
        result = await client.analyze_auction_insights("123")
        assert any("最上位表示率" in i for i in result["insights"])


# =====================================================================
# _analysis_btob テスト
# =====================================================================


class TestBtoBAnalysisMixin:
    """_BtoBAnalysisMixin のテスト。"""

    def _make_client(self) -> MockAnalysisClient:
        return MockAnalysisClient()

    @pytest.mark.unit
    async def test_suggest_btob_optimizations_not_found(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = None
        result = await client.suggest_btob_optimizations("999")
        assert "error" in result

    @pytest.mark.unit
    async def test_check_schedule_no_schedule(self) -> None:
        client = self._make_client()
        client.list_schedule_targeting.return_value = []
        suggestions: list[dict[str, Any]] = []
        await client._check_schedule_for_btob("123", suggestions)
        assert len(suggestions) == 1
        assert suggestions[0]["category"] == "schedule"
        assert suggestions[0]["priority"] == "HIGH"

    @pytest.mark.unit
    async def test_check_schedule_weekend(self) -> None:
        client = self._make_client()
        client.list_schedule_targeting.return_value = [
            {"day_of_week": "MONDAY"},
            {"day_of_week": "SATURDAY"},
        ]
        suggestions: list[dict[str, Any]] = []
        await client._check_schedule_for_btob("123", suggestions)
        assert len(suggestions) == 1
        assert suggestions[0]["priority"] == "MEDIUM"
        assert "土日" in suggestions[0]["message"]

    @pytest.mark.unit
    async def test_check_schedule_weekday_only(self) -> None:
        client = self._make_client()
        client.list_schedule_targeting.return_value = [
            {"day_of_week": "MONDAY"},
            {"day_of_week": "TUESDAY"},
        ]
        suggestions: list[dict[str, Any]] = []
        await client._check_schedule_for_btob("123", suggestions)
        assert len(suggestions) == 0

    @pytest.mark.unit
    async def test_check_schedule_exception(self) -> None:
        client = self._make_client()
        client.list_schedule_targeting.side_effect = Exception("error")
        suggestions: list[dict[str, Any]] = []
        await client._check_schedule_for_btob("123", suggestions)
        assert len(suggestions) == 0

    @pytest.mark.unit
    async def test_check_device_mobile_higher_cpa(self) -> None:
        client = self._make_client()
        # analyze_device_performance をモック
        client.analyze_device_performance = AsyncMock(return_value={
            "devices": [
                {"device_type": "DESKTOP", "cpa": 3000, "conversions": 5, "cost": 15000},
                {"device_type": "MOBILE", "cpa": 5000, "conversions": 2, "cost": 10000},
            ]
        })
        suggestions: list[dict[str, Any]] = []
        await client._check_device_for_btob("123", "LAST_30_DAYS", suggestions)
        assert len(suggestions) >= 1
        assert suggestions[0]["category"] == "device"

    @pytest.mark.unit
    async def test_check_device_tablet_cv0(self) -> None:
        client = self._make_client()
        client.analyze_device_performance = AsyncMock(return_value={
            "devices": [
                {"device_type": "DESKTOP", "cpa": 3000, "conversions": 5, "cost": 15000},
                {"device_type": "MOBILE", "cpa": 3000, "conversions": 3, "cost": 9000},
                {"device_type": "TABLET", "cpa": None, "conversions": 0, "cost": 2000},
            ]
        })
        suggestions: list[dict[str, Any]] = []
        await client._check_device_for_btob("123", "LAST_30_DAYS", suggestions)
        assert any(s["category"] == "device" and "タブレット" in s["message"] for s in suggestions)

    @pytest.mark.unit
    async def test_check_search_terms_high_info_ratio(self) -> None:
        client = self._make_client()
        # 30%が情報収集系
        terms = [
            {"search_term": "SEOとは"},
            {"search_term": "ツール比較"},
            {"search_term": "無料ツール"},
            {"search_term": "広告代理店"},
            {"search_term": "マーケティング会社"},
            {"search_term": "SaaS導入"},
            {"search_term": "営業支援"},
            {"search_term": "CRM選定"},
            {"search_term": "MA導入"},
            {"search_term": "業務効率化"},
        ]
        client.get_search_terms_report.return_value = terms
        suggestions: list[dict[str, Any]] = []
        await client._check_search_terms_for_btob("123", "LAST_30_DAYS", suggestions)
        assert len(suggestions) >= 1
        assert suggestions[0]["category"] == "search_terms"

    @pytest.mark.unit
    async def test_check_search_terms_low_info_ratio(self) -> None:
        client = self._make_client()
        terms = [
            {"search_term": "広告代理店"},
            {"search_term": "マーケティング会社"},
            {"search_term": "SaaS導入"},
            {"search_term": "CRM選定"},
            {"search_term": "MA導入"},
        ]
        client.get_search_terms_report.return_value = terms
        suggestions: list[dict[str, Any]] = []
        await client._check_search_terms_for_btob("123", "LAST_30_DAYS", suggestions)
        assert len(suggestions) == 0

    @pytest.mark.unit
    async def test_check_search_terms_empty(self) -> None:
        client = self._make_client()
        client.get_search_terms_report.return_value = []
        suggestions: list[dict[str, Any]] = []
        await client._check_search_terms_for_btob("123", "LAST_30_DAYS", suggestions)
        assert len(suggestions) == 0

    @pytest.mark.unit
    async def test_check_search_terms_exception(self) -> None:
        client = self._make_client()
        client.get_search_terms_report.side_effect = Exception("error")
        suggestions: list[dict[str, Any]] = []
        await client._check_search_terms_for_btob("123", "LAST_30_DAYS", suggestions)
        assert len(suggestions) == 0

    @pytest.mark.unit
    async def test_suggest_btob_optimizations_full(self) -> None:
        client = self._make_client()
        client.get_campaign.return_value = {"name": "BtoB Campaign"}
        client.list_schedule_targeting.return_value = []
        client.analyze_device_performance = AsyncMock(return_value={
            "devices": [
                {"device_type": "DESKTOP", "cpa": 3000, "conversions": 5, "cost": 15000},
                {"device_type": "MOBILE", "cpa": 5000, "conversions": 2, "cost": 10000},
            ]
        })
        client.get_search_terms_report.return_value = [
            {"search_term": "SEOとは"},
            {"search_term": "広告代理店"},
        ]
        result = await client.suggest_btob_optimizations("123")
        assert result["campaign_name"] == "BtoB Campaign"
        assert result["suggestion_count"] >= 1
