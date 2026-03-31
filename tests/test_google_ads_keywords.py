"""Google Ads _keywords.py テスト

_KeywordsMixin の list_keywords, add_keywords, remove_keyword,
pause_keyword, diagnose_keywords, suggest_keywords,
list_negative_keywords, add_negative_keywords, add_negative_keywords_to_ad_group,
remove_negative_keyword, get_search_terms_report のテスト。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.ads.googleads.errors import GoogleAdsException

from mureo.google_ads.client import GoogleAdsApiClient


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_client() -> GoogleAdsApiClient:
    creds = MagicMock()
    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_gads.return_value = MagicMock()
        client = GoogleAdsApiClient(
            credentials=creds,
            customer_id="1234567890",
            developer_token="test-token",
        )
    return client


def _make_google_ads_exception(
    message: str = "error",
    attr_name: str | None = None,
    error_name: str | None = None,
) -> GoogleAdsException:
    error = MagicMock()
    error.message = message
    if attr_name and error_name:
        code_attr = MagicMock()
        code_attr.name = error_name
        error.error_code = MagicMock(**{attr_name: code_attr})
    else:
        error.error_code = MagicMock(spec=[])
    failure = MagicMock()
    failure.errors = [error]
    exc = GoogleAdsException.__new__(GoogleAdsException)
    exc._failure = failure
    exc._call = MagicMock()
    exc._request_id = "req-123"
    type(exc).failure = property(lambda self: self._failure)
    return exc


def _make_keyword_row(
    criterion_id: int = 1,
    text: str = "テストキーワード",
    match_type: int = 4,  # BROAD
    status: int = 2,  # ENABLED
    approval_status: int = 3,  # APPROVED
) -> MagicMock:
    row = MagicMock()
    row.ad_group_criterion.criterion_id = criterion_id
    row.ad_group_criterion.keyword.text = text
    row.ad_group_criterion.keyword.match_type = match_type
    row.ad_group_criterion.status = status
    row.ad_group_criterion.approval_status = approval_status
    row.campaign.id = 100
    row.campaign.name = "テストキャンペーン"
    row.ad_group.id = 200
    row.ad_group.name = "テストグループ"
    return row


def _make_quality_keyword_row(
    criterion_id: int = 1,
    text: str = "テストKW",
    quality_score: int | None = 7,
    system_serving_status: str = "ELIGIBLE",
    approval_status: str = "APPROVED",
    creative_quality_score: str = "ABOVE_AVERAGE",
    post_click_quality_score: str = "ABOVE_AVERAGE",
    search_predicted_ctr: str = "ABOVE_AVERAGE",
) -> MagicMock:
    row = MagicMock()
    c = row.ad_group_criterion
    c.criterion_id = criterion_id
    c.keyword.text = text
    c.keyword.match_type = 4
    c.status = 2
    c.approval_status = approval_status
    c.system_serving_status = system_serving_status
    qi = c.quality_info
    qi.quality_score = quality_score
    qi.creative_quality_score = creative_quality_score
    qi.post_click_quality_score = post_click_quality_score
    qi.search_predicted_ctr = search_predicted_ctr
    row.campaign.id = 100
    row.campaign.name = "テストキャンペーン"
    row.ad_group.id = 200
    row.ad_group.name = "テストグループ"
    return row


# ---------------------------------------------------------------------------
# list_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = _make_keyword_row()
        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_keywords()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_campaign_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_keywords(campaign_id="100")
            query = mock_search.call_args[0][0]
            assert "campaign.id = 100" in query

    @pytest.mark.asyncio
    async def test_ad_group_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_keywords(ad_group_id="200")
            query = mock_search.call_args[0][0]
            assert "adGroups/200" in query

    @pytest.mark.asyncio
    async def test_status_filterフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_keywords(status_filter="ENABLED")
            query = mock_search.call_args[0][0]
            assert "ad_group_criterion.status = 'ENABLED'" in query


# ---------------------------------------------------------------------------
# add_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result1 = MagicMock()
        mock_result1.resource_name = "customers/123/adGroupCriteria/200~1"
        mock_result2 = MagicMock()
        mock_result2.resource_name = "customers/123/adGroupCriteria/200~2"
        mock_response = MagicMock()
        mock_response.results = [mock_result1, mock_result2]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.add_keywords({
            "ad_group_id": "200",
            "keywords": [
                {"text": "キーワード1", "match_type": "BROAD"},
                {"text": "キーワード2", "match_type": "EXACT"},
            ],
        })
        assert len(result) == 2
        assert result[0]["resource_name"] == "customers/123/adGroupCriteria/200~1"

    @pytest.mark.asyncio
    async def test_空リスト_エラー(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="キーワードを1つ以上"):
            await client.add_keywords({
                "ad_group_id": "200",
                "keywords": [],
            })

    @pytest.mark.asyncio
    async def test_80文字超_エラー(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="80文字以内"):
            await client.add_keywords({
                "ad_group_id": "200",
                "keywords": [{"text": "a" * 81}],
            })

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("追加エラー")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_criteria.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="エラーが発生しました"):
            await client.add_keywords({
                "ad_group_id": "200",
                "keywords": [{"text": "テスト"}],
            })


# ---------------------------------------------------------------------------
# remove_keyword
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveKeyword:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupCriteria/200~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.remove_keyword({
            "ad_group_id": "200",
            "criterion_id": "1",
        })
        assert result["resource_name"] == "customers/123/adGroupCriteria/200~1"

    @pytest.mark.asyncio
    async def test_不正なad_group_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なad_group_id"):
            await client.remove_keyword({
                "ad_group_id": "abc",
                "criterion_id": "1",
            })

    @pytest.mark.asyncio
    async def test_不正なcriterion_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なcriterion_id"):
            await client.remove_keyword({
                "ad_group_id": "200",
                "criterion_id": "abc",
            })


# ---------------------------------------------------------------------------
# pause_keyword
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPauseKeyword:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupCriteria/200~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.pause_keyword({
            "ad_group_id": "200",
            "criterion_id": "1",
        })
        assert result["resource_name"] == "customers/123/adGroupCriteria/200~1"


# ---------------------------------------------------------------------------
# diagnose_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDiagnoseKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        rows = [
            _make_quality_keyword_row(criterion_id=1, text="KW1", quality_score=8),
            _make_quality_keyword_row(criterion_id=2, text="KW2", quality_score=3),
            _make_quality_keyword_row(criterion_id=3, text="KW3", quality_score=None),
        ]

        with patch.object(client, "_search", return_value=rows):
            result = await client.diagnose_keywords("100")

        assert result["campaign_id"] == "100"
        assert result["total_keywords"] == 3
        dist = result["quality_score_distribution"]
        assert dist["high_7_10"] >= 1
        assert dist["low_1_4"] >= 1
        assert dist["no_score"] >= 1

    @pytest.mark.asyncio
    async def test_空結果(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            result = await client.diagnose_keywords("100")

        assert result["total_keywords"] == 0
        assert result["campaign_name"] == ""

    @pytest.mark.asyncio
    async def test_問題カテゴリ_low_quality_score(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(quality_score=2)
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["low_quality_score"]) >= 1
        assert result["total_issues"] >= 1
        assert len(result["recommendations"]) >= 1

    @pytest.mark.asyncio
    async def test_問題カテゴリ_rarely_served(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(system_serving_status="RARELY_SERVED")
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["rarely_served"]) >= 1

    @pytest.mark.asyncio
    async def test_問題カテゴリ_disapproved(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(approval_status="DISAPPROVED")
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["disapproved"]) >= 1

    @pytest.mark.asyncio
    async def test_問題カテゴリ_below_average_ctr(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(search_predicted_ctr="BELOW_AVERAGE")
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["below_average_ctr"]) >= 1

    @pytest.mark.asyncio
    async def test_問題カテゴリ_below_average_ad_relevance(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(creative_quality_score="BELOW_AVERAGE")
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["below_average_ad_relevance"]) >= 1

    @pytest.mark.asyncio
    async def test_問題カテゴリ_below_average_landing_page(self) -> None:
        client = _make_client()
        row = _make_quality_keyword_row(post_click_quality_score="BELOW_AVERAGE")
        with patch.object(client, "_search", return_value=[row]):
            result = await client.diagnose_keywords("100")

        assert len(result["issues"]["below_average_landing_page"]) >= 1

    @pytest.mark.asyncio
    async def test_keywords上限50件(self) -> None:
        client = _make_client()
        rows = [_make_quality_keyword_row(criterion_id=i) for i in range(60)]
        with patch.object(client, "_search", return_value=rows):
            result = await client.diagnose_keywords("100")

        assert result["total_keywords"] == 60
        assert len(result["keywords"]) == 50


# ---------------------------------------------------------------------------
# suggest_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSuggestKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        idea1 = MagicMock()
        idea1.text = "提案KW1"
        idea1.keyword_idea_metrics.avg_monthly_searches = 1000
        idea1.keyword_idea_metrics.competition = "MEDIUM"
        idea2 = MagicMock()
        idea2.text = "提案KW2"
        idea2.keyword_idea_metrics.avg_monthly_searches = 500
        idea2.keyword_idea_metrics.competition = "LOW"
        mock_response = MagicMock()
        mock_response.results = [idea1, idea2]
        mock_service = MagicMock()
        mock_service.generate_keyword_ideas.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.suggest_keywords(["テスト"])
        assert len(result) == 2
        assert result[0]["keyword"] == "提案KW1"
        assert result[0]["avg_monthly_searches"] == 1000

    @pytest.mark.asyncio
    async def test_20件上限(self) -> None:
        client = _make_client()
        ideas = []
        for i in range(30):
            idea = MagicMock()
            idea.text = f"KW{i}"
            idea.keyword_idea_metrics.avg_monthly_searches = 100
            idea.keyword_idea_metrics.competition = "LOW"
            ideas.append(idea)
        mock_response = MagicMock()
        mock_response.results = ideas
        mock_service = MagicMock()
        mock_service.generate_keyword_ideas.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.suggest_keywords(["テスト"])
        assert len(result) == 20

    @pytest.mark.asyncio
    async def test_DEVELOPER_TOKEN_NOT_APPROVED(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception(
            attr_name="authorization_error",
            error_name="DEVELOPER_TOKEN_NOT_APPROVED",
        )
        mock_service = MagicMock()
        mock_service.generate_keyword_ideas.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        with pytest.raises(ValueError, match="BasicまたはStandardアクセス"):
            await client.suggest_keywords(["テスト"])

    @pytest.mark.asyncio
    async def test_一般的なGoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("一般エラー")
        mock_service = MagicMock()
        mock_service.generate_keyword_ideas.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="エラーが発生しました"):
            await client.suggest_keywords(["テスト"])


# ---------------------------------------------------------------------------
# list_negative_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListNegativeKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign_criterion.criterion_id = 1
        row.campaign_criterion.keyword.text = "除外KW"
        row.campaign_criterion.keyword.match_type = 4

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_negative_keywords("100")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_不正なcampaign_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なcampaign_id"):
            await client.list_negative_keywords("abc")


# ---------------------------------------------------------------------------
# add_negative_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddNegativeKeywords:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaignCriteria/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaign_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.add_negative_keywords({
            "campaign_id": "100",
            "keywords": [{"text": "除外KW", "match_type": "EXACT"}],
        })
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("追加エラー")
        mock_service = MagicMock()
        mock_service.mutate_campaign_criteria.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="エラーが発生しました"):
            await client.add_negative_keywords({
                "campaign_id": "100",
                "keywords": [{"text": "除外KW"}],
            })


# ---------------------------------------------------------------------------
# add_negative_keywords_to_ad_group
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddNegativeKeywordsToAdGroup:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupCriteria/200~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.add_negative_keywords_to_ad_group({
            "ad_group_id": "200",
            "keywords": [{"text": "除外KW", "match_type": "BROAD"}],
        })
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_不正なad_group_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なad_group_id"):
            await client.add_negative_keywords_to_ad_group({
                "ad_group_id": "abc",
                "keywords": [{"text": "除外KW"}],
            })


# ---------------------------------------------------------------------------
# remove_negative_keyword
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveNegativeKeyword:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaignCriteria/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaign_criteria.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.remove_negative_keyword({
            "campaign_id": "100",
            "criterion_id": "1",
        })
        assert result["resource_name"] == "customers/123/campaignCriteria/100~1"

    @pytest.mark.asyncio
    async def test_不正なcampaign_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なcampaign_id"):
            await client.remove_negative_keyword({
                "campaign_id": "abc",
                "criterion_id": "1",
            })

    @pytest.mark.asyncio
    async def test_不正なcriterion_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="不正なcriterion_id"):
            await client.remove_negative_keyword({
                "campaign_id": "100",
                "criterion_id": "abc",
            })


# ---------------------------------------------------------------------------
# get_search_terms_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSearchTermsReport:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.search_term_view.search_term = "テスト検索語句"
        row.metrics.impressions = 100
        row.metrics.clicks = 10
        row.metrics.cost_micros = 1000_000_000
        row.metrics.conversions = 1
        row.metrics.ctr = 0.1

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_search_terms_report()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_campaign_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.get_search_terms_report(campaign_id="100")
            query = mock_search.call_args[0][0]
            assert "campaign.id = 100" in query

    @pytest.mark.asyncio
    async def test_ad_group_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.get_search_terms_report(ad_group_id="200")
            query = mock_search.call_args[0][0]
            assert "ad_group.id = 200" in query

    @pytest.mark.asyncio
    async def test_period指定(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.get_search_terms_report(period="LAST_7_DAYS")
            query = mock_search.call_args[0][0]
            assert "DURING LAST_7_DAYS" in query
