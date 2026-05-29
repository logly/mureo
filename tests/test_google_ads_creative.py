"""Unit tests for Google Ads _creative.py.

Mock-based tests for _CreativeMixin's analyze_landing_page /
research_creative and helper methods.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.google_ads._creative import _CreativeMixin


# ---------------------------------------------------------------------------
# Mock client class for tests
# ---------------------------------------------------------------------------


class _MockCreativeClient(_CreativeMixin):
    """Mock class that makes _CreativeMixin testable."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()
        self._search = AsyncMock(return_value=[])

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value or not value.isdigit():
            raise ValueError(f"{field_name} must be a numeric string: {value}")
        return value

    def _get_service(self, service_name: str):
        return MagicMock()

    async def list_keywords(self, **kwargs):
        return []

    async def get_search_terms_report(self, **kwargs):
        return []

    async def suggest_keywords(self, seed_keywords, **kwargs):
        return []


# ---------------------------------------------------------------------------
# analyze_landing_page tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalyzeLandingPage:
    @pytest.fixture()
    def client(self) -> _MockCreativeClient:
        return _MockCreativeClient()

    @pytest.mark.asyncio
    async def test_success(self, client: _MockCreativeClient) -> None:
        mock_result = MagicMock()
        mock_result.title = "Test Title"
        mock_result.meta_description = "desc"
        mock_result.h1_texts = ["H1"]
        mock_result.cta_texts = []
        mock_result.features = []
        mock_result.prices = []
        mock_result.industry_hints = []
        mock_result.url = "https://example.com"
        mock_result.error = None

        with patch("mureo.google_ads._creative.LPAnalyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.analyze = AsyncMock(return_value=mock_result)
            with patch("mureo.google_ads._creative.asdict") as mock_asdict:
                mock_asdict.return_value = {
                    "title": "Test Title",
                    "url": "https://example.com",
                }
                result = await client.analyze_landing_page("https://example.com")

        assert result["title"] == "Test Title"

    @pytest.mark.asyncio
    async def test_failure_returns_error(self, client: _MockCreativeClient) -> None:
        with patch("mureo.google_ads._creative.LPAnalyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.analyze = AsyncMock(side_effect=RuntimeError("parse error"))
            result = await client.analyze_landing_page("https://bad.com")

        assert "error" in result
        assert result["url"] == "https://bad.com"


# ---------------------------------------------------------------------------
# _generate_seed_keywords tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateSeedKeywords:
    def test_from_title_and_h1(self) -> None:
        lp_data = {
            "title": "格安航空券",
            "h1_texts": ["最安値の航空券を検索"],
            "meta_description": "国内外の格安航空券を比較",
        }
        seeds = _CreativeMixin._generate_seed_keywords(lp_data)
        assert "格安航空券" in seeds
        assert "最安値の航空券を検索" in seeds
        assert len(seeds) <= 5

    def test_empty_lp_data(self) -> None:
        seeds = _CreativeMixin._generate_seed_keywords({})
        assert seeds == []

    def test_dedup(self) -> None:
        lp_data = {
            "title": "Same",
            "h1_texts": ["Same"],
            "meta_description": "Same",
        }
        seeds = _CreativeMixin._generate_seed_keywords(lp_data)
        assert seeds == ["Same"]

    def test_max_5(self) -> None:
        lp_data = {
            "title": "A",
            "h1_texts": ["B", "C", "D", "E", "F", "G"],
            "meta_description": "H",
        }
        seeds = _CreativeMixin._generate_seed_keywords(lp_data)
        assert len(seeds) <= 5


# ---------------------------------------------------------------------------
# _build_context_summary tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildContextSummary:
    def test_with_lp_data(self) -> None:
        result = {
            "lp_analysis": {
                "title": "Test LP",
                "meta_description": "description",
                "h1_texts": ["見出し"],
                "cta_texts": ["申込む"],
                "features": ["特徴1"],
                "prices": ["月額1000円"],
                "industry_hints": ["SaaS"],
            },
            "existing_ads": [],
            "search_term_insights": {},
            "existing_keywords": [],
        }
        summary = _CreativeMixin._build_context_summary(result)
        assert "LP Information" in summary
        assert "Test LP" in summary
        assert "見出し" in summary

    def test_with_existing_ads(self) -> None:
        result = {
            "lp_analysis": {"error": "failed"},
            "existing_ads": [
                {
                    "headlines": ["H1", "H2"],
                    "ctr": 5.0,
                    "conversions": 10,
                }
            ],
            "search_term_insights": {},
            "existing_keywords": [],
        }
        summary = _CreativeMixin._build_context_summary(result)
        assert "Existing Ads" in summary

    def test_with_search_term_insights(self) -> None:
        result = {
            "lp_analysis": {},
            "existing_ads": [],
            "search_term_insights": {
                "high_cv_terms": [
                    {"search_term": "格安航空券"},
                    {"search_term": "航空券 比較"},
                ]
            },
            "existing_keywords": [],
        }
        summary = _CreativeMixin._build_context_summary(result)
        assert "Converting Search Terms" in summary

    def test_with_existing_keywords(self) -> None:
        result = {
            "lp_analysis": {},
            "existing_ads": [],
            "search_term_insights": {},
            "existing_keywords": [
                {"text": "格安航空券"},
                {"text": "LCC 国内"},
            ],
        }
        summary = _CreativeMixin._build_context_summary(result)
        assert "Target Keywords" in summary

    def test_no_data(self) -> None:
        result = {
            "lp_analysis": {"error": "no data"},
            "existing_ads": [],
            "search_term_insights": {},
            "existing_keywords": [],
        }
        summary = _CreativeMixin._build_context_summary(result)
        assert summary == "No LP analysis data"


# ---------------------------------------------------------------------------
# _extract_search_term_insights tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSearchTermInsights:
    @pytest.fixture()
    def client(self) -> _MockCreativeClient:
        return _MockCreativeClient()

    @pytest.mark.asyncio
    async def test_extracts_high_cv_and_high_click(
        self, client: _MockCreativeClient
    ) -> None:
        client.get_search_terms_report = AsyncMock(
            return_value=[
                {"search_term": "a", "metrics": {"conversions": 5, "clicks": 10}},
                {"search_term": "b", "metrics": {"conversions": 0, "clicks": 50}},
                {"search_term": "c", "metrics": {"conversions": 3, "clicks": 5}},
            ]
        )

        result = await client._extract_search_term_insights("123", None)
        assert result["total_terms"] == 3
        assert len(result["high_cv_terms"]) == 2  # a, c
        assert result["high_cv_terms"][0]["search_term"] == "a"  # sorted by CV desc


# ---------------------------------------------------------------------------
# research_creative tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResearchCreative:
    @pytest.fixture()
    def client(self) -> _MockCreativeClient:
        return _MockCreativeClient()

    @pytest.mark.asyncio
    async def test_full_flow(self, client: _MockCreativeClient) -> None:
        """All steps run successfully."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"title": "Test", "h1_texts": ["H1"]}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.return_value = {
                        "high_cv_terms": [],
                        "high_click_terms": [],
                        "total_terms": 0,
                    }

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                    )

        assert result["campaign_id"] == "123"
        assert result["url"] == "https://example.com"
        assert "lp_analysis" in result
        assert "context_summary" in result

    @pytest.mark.asyncio
    async def test_partial_failure_handled(self, client: _MockCreativeClient) -> None:
        """The remaining steps still run when some steps fail."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"error": "failed"}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.side_effect = RuntimeError("API error")

                result = await client.research_creative(
                    campaign_id="123",
                    url="https://example.com",
                )

        assert result["existing_ads"] == "fetch_failed"
        assert "lp_analysis" in result

    @pytest.mark.asyncio
    async def test_with_ad_group_id(self, client: _MockCreativeClient) -> None:
        """When ad_group_id is provided, it is validated (line 85)."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"title": "Test"}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.return_value = {
                        "high_cv_terms": [],
                        "high_click_terms": [],
                        "total_terms": 0,
                    }

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                        ad_group_id="456",
                    )

        assert result["campaign_id"] == "123"

    @pytest.mark.asyncio
    async def test_search_term_insights_failure(
        self, client: _MockCreativeClient
    ) -> None:
        """Fallback when search-term insights fail (lines 110-112)."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"title": "Test"}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.side_effect = RuntimeError("search terms error")

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                    )

        assert result["search_term_insights"] == "fetch_failed"

    @pytest.mark.asyncio
    async def test_keyword_suggestions_failure(
        self, client: _MockCreativeClient
    ) -> None:
        """Fallback when keyword suggestion fails (lines 121-123)."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"title": "Test", "h1_texts": ["H1"]}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.return_value = {
                        "high_cv_terms": [],
                        "high_click_terms": [],
                        "total_terms": 0,
                    }
                    client.suggest_keywords = AsyncMock(
                        side_effect=RuntimeError("suggest error")
                    )

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                    )

        assert result["keyword_suggestions"] == "fetch_failed"

    @pytest.mark.asyncio
    async def test_existing_keywords_failure(self, client: _MockCreativeClient) -> None:
        """Fallback when existing-keyword lookup fails (lines 130-132)."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"title": "Test"}
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.return_value = {
                        "high_cv_terms": [],
                        "high_click_terms": [],
                        "total_terms": 0,
                    }
                    client.list_keywords = AsyncMock(
                        side_effect=RuntimeError("kw error")
                    )

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                    )

        assert result["existing_keywords"] == "fetch_failed"

    @pytest.mark.asyncio
    async def test_empty_seeds_no_suggestions(
        self, client: _MockCreativeClient
    ) -> None:
        """When LP analysis yields empty seeds, keyword suggestions are an empty list."""
        with patch.object(
            client, "analyze_landing_page", new_callable=AsyncMock
        ) as mock_lp:
            mock_lp.return_value = {"error": "no data"}  # no title/h1
            with patch.object(
                client, "_fetch_existing_ads", new_callable=AsyncMock
            ) as mock_ads:
                mock_ads.return_value = []
                with patch.object(
                    client, "_extract_search_term_insights", new_callable=AsyncMock
                ) as mock_st:
                    mock_st.return_value = {
                        "high_cv_terms": [],
                        "high_click_terms": [],
                        "total_terms": 0,
                    }

                    result = await client.research_creative(
                        campaign_id="123",
                        url="https://example.com",
                    )

        assert result["keyword_suggestions"] == []


# ---------------------------------------------------------------------------
# _fetch_existing_ads tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchExistingAds:
    @pytest.fixture()
    def client(self) -> _MockCreativeClient:
        return _MockCreativeClient()

    @pytest.mark.asyncio
    async def test_with_ad_group_id(self, client: _MockCreativeClient) -> None:
        """When ad_group_id is provided, it is included in the query (lines 169-170)."""
        row = MagicMock()
        rsa = row.ad_group_ad.ad.responsive_search_ad
        h = MagicMock()
        h.text = "見出し"
        d = MagicMock()
        d.text = "説明"
        rsa.headlines = [h]
        rsa.descriptions = [d]
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.ad.final_urls = ["https://example.com"]
        row.metrics.impressions = 100
        row.metrics.clicks = 10
        row.metrics.conversions = 1
        row.metrics.ctr = 0.1

        client._search = AsyncMock(return_value=[row])

        ads = await client._fetch_existing_ads("123", "456")
        assert len(ads) == 1
        assert ads[0]["headlines"] == ["見出し"]

    @pytest.mark.asyncio
    async def test_without_ad_group_id(self, client: _MockCreativeClient) -> None:
        """Without ad_group_id (lines 150-190)."""
        client._search = AsyncMock(return_value=[])

        ads = await client._fetch_existing_ads("123", None)
        assert ads == []

    @pytest.mark.asyncio
    async def test_rsa_no_headlines(self, client: _MockCreativeClient) -> None:
        """When the RSA ad has no headlines."""
        row = MagicMock()
        rsa = row.ad_group_ad.ad.responsive_search_ad
        rsa.headlines = None
        rsa.descriptions = None
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.ad.final_urls = []
        row.metrics.impressions = 0
        row.metrics.clicks = 0
        row.metrics.conversions = 0
        row.metrics.ctr = None

        client._search = AsyncMock(return_value=[row])

        ads = await client._fetch_existing_ads("123", None)
        assert len(ads) == 1
        assert ads[0]["headlines"] == []
        assert ads[0]["ctr"] == 0


# ---------------------------------------------------------------------------
# _extract_search_term_insights with ad_group_id tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSearchTermInsightsAdditional:
    @pytest.fixture()
    def client(self) -> _MockCreativeClient:
        return _MockCreativeClient()

    @pytest.mark.asyncio
    async def test_with_ad_group_id(self, client: _MockCreativeClient) -> None:
        """When ad_group_id is provided, it is included in kwargs (line 200)."""
        client.get_search_terms_report = AsyncMock(return_value=[])

        result = await client._extract_search_term_insights("123", "456")
        client.get_search_terms_report.assert_called_once_with(
            campaign_id="123", ad_group_id="456"
        )
        assert result["total_terms"] == 0
