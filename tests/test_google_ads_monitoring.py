"""Google Ads _monitoring.py ユニットテスト

_MonitoringMixin の evaluate_delivery_goal / evaluate_cpa_goal /
evaluate_cv_goal / diagnose_zero_conversions をモックベースでテストする。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mureo.google_ads._monitoring import _MonitoringMixin


# ---------------------------------------------------------------------------
# テスト用のモッククライアントクラス
# ---------------------------------------------------------------------------


class _MockMonitoringClient(_MonitoringMixin):
    """_MonitoringMixin をテスト可能にするモッククラス"""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value or not value.isdigit():
            raise ValueError(f"{field_name} は数値文字列である必要があります: {value}")
        return value

    async def get_campaign(self, campaign_id: str):
        return None

    async def get_performance_report(self, **kwargs):
        return []

    async def diagnose_campaign_delivery(self, campaign_id: str):
        return {}

    async def analyze_performance(self, campaign_id: str, period: str = "LAST_7_DAYS"):
        return {}

    async def investigate_cost_increase(self, campaign_id: str):
        return {}

    async def get_search_terms_report(self, **kwargs):
        return []

    async def list_conversion_actions(self):
        return []


# ---------------------------------------------------------------------------
# evaluate_delivery_goal テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateDeliveryGoal:
    @pytest.fixture()
    def client(self) -> _MockMonitoringClient:
        return _MockMonitoringClient()

    @pytest.mark.asyncio
    async def test_healthy_campaign(self, client: _MockMonitoringClient) -> None:
        """正常な配信状態 → healthy"""
        client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [],
            "warnings": [],
        })
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 100, "clicks": 10}}
        ])

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] == "healthy"
        assert "normally" in result["summary"]

    @pytest.mark.asyncio
    async def test_critical_no_impressions(self, client: _MockMonitoringClient) -> None:
        """インプレッション0 → critical"""
        client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [],
            "warnings": [],
        })
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 0, "clicks": 0}}
        ])

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] == "critical"
        assert result.get("suggested_workflow") == "delivery_fix"

    @pytest.mark.asyncio
    async def test_critical_with_issues(self, client: _MockMonitoringClient) -> None:
        """診断で issues 検出 → critical"""
        client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": ["有効な広告がありません"],
            "warnings": [],
        })
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 50, "clicks": 5}}
        ])

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_warning_with_warnings_only(self, client: _MockMonitoringClient) -> None:
        """診断で warnings のみ → warning"""
        client.get_campaign = AsyncMock(return_value={"status": "ENABLED"})
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [],
            "warnings": ["地域ターゲティングが未設定"],
        })
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 50, "clicks": 5}}
        ])

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_paused_campaign_critical(self, client: _MockMonitoringClient) -> None:
        """一時停止中 → critical"""
        client.get_campaign = AsyncMock(return_value={"status": "PAUSED"})
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [],
            "warnings": [],
        })
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 0, "clicks": 0}}
        ])

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] == "critical"

    @pytest.mark.asyncio
    async def test_exception_handling(self, client: _MockMonitoringClient) -> None:
        """各メソッドの例外は吸収される"""
        client.get_campaign = AsyncMock(side_effect=RuntimeError("fail"))
        client.diagnose_campaign_delivery = AsyncMock(side_effect=RuntimeError("fail"))
        client.get_performance_report = AsyncMock(side_effect=RuntimeError("fail"))

        result = await client.evaluate_delivery_goal("123")
        assert result["status"] in ("critical", "warning")


# ---------------------------------------------------------------------------
# evaluate_cpa_goal テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateCpaGoal:
    @pytest.fixture()
    def client(self) -> _MockMonitoringClient:
        return _MockMonitoringClient()

    @pytest.mark.asyncio
    async def test_healthy_cpa(self, client: _MockMonitoringClient) -> None:
        """CPA目標内 → healthy"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"cost": 10000, "conversions": 10}}
        ])
        client.investigate_cost_increase = AsyncMock(return_value={})

        result = await client.evaluate_cpa_goal("123", 2000.0)
        assert result["status"] == "healthy"
        assert result["current_cpa"] == 1000.0

    @pytest.mark.asyncio
    async def test_warning_cpa(self, client: _MockMonitoringClient) -> None:
        """CPA目標の1.2倍以内 → warning"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"cost": 11000, "conversions": 10}}  # CPA=1100
        ])
        client.investigate_cost_increase = AsyncMock(return_value={})

        result = await client.evaluate_cpa_goal("123", 1000.0)
        assert result["status"] == "warning"
        assert result["deviation_pct"] > 0

    @pytest.mark.asyncio
    async def test_critical_cpa(self, client: _MockMonitoringClient) -> None:
        """CPA目標の1.2倍超 → critical"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"cost": 15000, "conversions": 10}}  # CPA=1500
        ])
        client.investigate_cost_increase = AsyncMock(return_value={})

        result = await client.evaluate_cpa_goal("123", 1000.0)
        assert result["status"] == "critical"
        assert result.get("suggested_workflow") == "cpa_optimization"

    @pytest.mark.asyncio
    async def test_zero_conversions(self, client: _MockMonitoringClient) -> None:
        """CV0 → warning, current_cpa=None"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"cost": 5000, "conversions": 0}}
        ])
        client.investigate_cost_increase = AsyncMock(return_value={})

        result = await client.evaluate_cpa_goal("123", 1000.0)
        assert result["status"] == "warning"
        assert result["current_cpa"] is None

    @pytest.mark.asyncio
    async def test_wasteful_terms_extraction(self, client: _MockMonitoringClient) -> None:
        """wasteful_search_termsが正しく抽出される"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"cost": 5000, "conversions": 5}}
        ])
        client.investigate_cost_increase = AsyncMock(return_value={
            "wasteful_search_terms": [{"term": f"t{i}"} for i in range(10)]
        })

        result = await client.evaluate_cpa_goal("123", 2000.0)
        assert len(result["wasteful_terms"]) == 5  # 上位5件


# ---------------------------------------------------------------------------
# evaluate_cv_goal テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvaluateCvGoal:
    @pytest.fixture()
    def client(self) -> _MockMonitoringClient:
        return _MockMonitoringClient()

    @pytest.mark.asyncio
    async def test_healthy_cv(self, client: _MockMonitoringClient) -> None:
        """CV目標達成 → healthy"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 1000, "clicks": 100, "conversions": 70}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["status"] == "healthy"
        assert result["current_cv_daily"] == 10.0  # 70/7

    @pytest.mark.asyncio
    async def test_warning_cv(self, client: _MockMonitoringClient) -> None:
        """CV目標の80%以上 → warning"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 1000, "clicks": 100, "conversions": 63}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_critical_cv(self, client: _MockMonitoringClient) -> None:
        """CV目標の80%未満 → critical"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 1000, "clicks": 100, "conversions": 35}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["status"] == "critical"
        assert result.get("suggested_workflow") == "cv_increase"

    @pytest.mark.asyncio
    async def test_bottleneck_impression(self, client: _MockMonitoringClient) -> None:
        """インプレッション系インサイト → impression ボトルネック"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 10, "clicks": 5, "conversions": 0}}
        ])
        client.analyze_performance = AsyncMock(return_value={
            "insights": ["インプレッションが不足しています"]
        })

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["bottleneck"] == "impression"

    @pytest.mark.asyncio
    async def test_bottleneck_ctr(self, client: _MockMonitoringClient) -> None:
        """低CTR → ctr ボトルネック"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 10000, "clicks": 10, "conversions": 0}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["bottleneck"] == "ctr"

    @pytest.mark.asyncio
    async def test_bottleneck_cvr(self, client: _MockMonitoringClient) -> None:
        """低CVR → cvr ボトルネック"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 10000, "clicks": 500, "conversions": 1}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 10.0)
        assert result["bottleneck"] == "cvr"

    @pytest.mark.asyncio
    async def test_zero_target(self, client: _MockMonitoringClient) -> None:
        """target_cv_daily=0 → deviation_pct=0"""
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 100, "clicks": 10, "conversions": 0}}
        ])
        client.analyze_performance = AsyncMock(return_value={"insights": []})

        result = await client.evaluate_cv_goal("123", 0.0)
        assert result["deviation_pct"] == 0.0


# ---------------------------------------------------------------------------
# diagnose_zero_conversions テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiagnoseZeroConversions:
    @pytest.fixture()
    def client(self) -> _MockMonitoringClient:
        return _MockMonitoringClient()

    @pytest.mark.asyncio
    async def test_no_cv_tracking_critical(self, client: _MockMonitoringClient) -> None:
        """CV計測未設定 → critical"""
        client.get_campaign = AsyncMock(return_value={
            "bidding_strategy": "MAXIMIZE_CONVERSIONS"
        })
        client.list_conversion_actions = AsyncMock(return_value=[])
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 100, "clicks": 10, "conversions": 0, "cost": 5000}}
        ])
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [], "warnings": [], "recommendations": [],
        })

        result = await client.diagnose_zero_conversions("123")
        assert result["status"] == "critical"
        assert result["conversion_tracking"]["has_issue"] is True

    @pytest.mark.asyncio
    async def test_no_delivery_bottleneck(self, client: _MockMonitoringClient) -> None:
        """インプレッション0 → no_delivery ボトルネック"""
        client.get_campaign = AsyncMock(return_value={"bidding_strategy": "MAXIMIZE_CLICKS"})
        client.list_conversion_actions = AsyncMock(return_value=[
            {"status": "ENABLED"}
        ])
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 0, "clicks": 0, "conversions": 0, "cost": 0}}
        ])
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [], "warnings": [], "recommendations": [],
        })

        result = await client.diagnose_zero_conversions("123")
        assert result["funnel"]["bottleneck"] == "no_delivery"

    @pytest.mark.asyncio
    async def test_no_clicks_bottleneck(self, client: _MockMonitoringClient) -> None:
        """クリック0 → no_clicks ボトルネック"""
        client.get_campaign = AsyncMock(return_value={"bidding_strategy": "MAXIMIZE_CLICKS"})
        client.list_conversion_actions = AsyncMock(return_value=[
            {"status": "ENABLED"}
        ])
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 100, "clicks": 0, "conversions": 0, "cost": 0}}
        ])
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [], "warnings": [], "recommendations": [],
        })

        result = await client.diagnose_zero_conversions("123")
        assert result["funnel"]["bottleneck"] == "no_clicks"

    @pytest.mark.asyncio
    async def test_healthy_with_conversions(self, client: _MockMonitoringClient) -> None:
        """CVあり → healthy"""
        client.get_campaign = AsyncMock(return_value={"bidding_strategy": "MAXIMIZE_CLICKS"})
        client.list_conversion_actions = AsyncMock(return_value=[
            {"status": "ENABLED"}
        ])
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 1000, "clicks": 100, "conversions": 10, "cost": 50000}}
        ])
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [], "warnings": [], "recommendations": [],
        })

        result = await client.diagnose_zero_conversions("123")
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_search_term_quality_high_waste(self, client: _MockMonitoringClient) -> None:
        """CVなし検索語句のコストが50%超の場合はissueに含まれる"""
        client.get_campaign = AsyncMock(return_value={"bidding_strategy": "MAXIMIZE_CLICKS"})
        client.list_conversion_actions = AsyncMock(return_value=[
            {"status": "ENABLED"}
        ])
        client.get_performance_report = AsyncMock(return_value=[
            {"metrics": {"impressions": 1000, "clicks": 100, "conversions": 0, "cost": 10000}}
        ])
        client.diagnose_campaign_delivery = AsyncMock(return_value={
            "issues": [], "warnings": [], "recommendations": [],
        })
        client.get_search_terms_report = AsyncMock(return_value=[
            {"search_term": "bad1", "metrics": {"conversions": 0, "cost": 6000}},
            {"search_term": "bad2", "metrics": {"conversions": 0, "cost": 2000}},
        ])

        result = await client.diagnose_zero_conversions("123")
        assert result["search_term_quality"] is not None
        assert result["search_term_quality"]["zero_cv_cost"] == 8000


# ---------------------------------------------------------------------------
# _build_cv_recommendations テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildCvRecommendations:
    def test_all_issues(self) -> None:
        """全問題が存在する場合の推奨アクション"""
        actions = _MonitoringMixin._build_cv_recommendations(
            has_cv_issue=True,
            bidding_issue="入札戦略不整合",
            bottleneck="no_delivery",
            search_term_quality={"zero_cv_terms": 5},
            cost=5000.0,
        )
        action_types = [a["action"] for a in actions]
        assert "fix_cv_tracking" in action_types
        assert "fix_bidding_strategy" in action_types
        assert "add_negative_keywords" in action_types
        assert "fix_delivery" in action_types
        # 優先順位が昇順
        priorities = [a["priority"] for a in actions]
        assert priorities == sorted(priorities)

    def test_no_issues(self) -> None:
        """問題がない場合でも基本的な提案は含まれる"""
        actions = _MonitoringMixin._build_cv_recommendations(
            has_cv_issue=False,
            bidding_issue=None,
            bottleneck=None,
            search_term_quality=None,
            cost=0.0,
        )
        action_types = [a["action"] for a in actions]
        assert "improve_ads_and_keywords" in action_types
        assert "review_landing_page" in action_types
