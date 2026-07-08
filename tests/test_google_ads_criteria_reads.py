"""Unit tests for the read-only Google Ads criteria / asset retrievals (#366).

Covers _TargetingMixin.list_demographic_criteria /
list_audience_criteria and _MediaMixin.list_image_assets with
``_search`` mocked — no external API calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mureo.google_ads._extensions_targeting import _TargetingMixin
from mureo.google_ads._media import _MediaMixin


class _MockTargetingClient(_TargetingMixin):
    """Mock class that makes _TargetingMixin testable."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._search = AsyncMock(return_value=[])

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        if not value or not value.isdigit():
            raise ValueError(f"Invalid {field_name}: {value}")
        return value

    @staticmethod
    def _validate_date(value: str, field_name: str) -> str:
        return value

    @staticmethod
    def _validate_recommendation_type(rec_type: str) -> str:
        return rec_type

    @staticmethod
    def _validate_resource_name(value: str, pattern: Any, field_name: str) -> str:
        return value

    def _get_service(self, service_name: str) -> Any:
        return None


class _MockMediaClient(_MediaMixin):
    """Mock class that makes _MediaMixin testable."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = None
        self._search = AsyncMock(return_value=[])


def _demographic_row(
    *,
    criterion_type: Any = 10,  # CriterionType.AGE_RANGE (raw proto int)
    age_range: Any = 503002,  # AgeRangeType.AGE_RANGE_25_34
    gender: Any = 0,
    status: Any = 2,  # AdGroupCriterionStatus.ENABLED
    negative: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        campaign=SimpleNamespace(id=111),
        ad_group=SimpleNamespace(id=222, name="AG"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=333,
            type_=criterion_type,
            status=status,
            negative=negative,
            age_range=SimpleNamespace(type_=age_range),
            gender=SimpleNamespace(type_=gender),
            parental_status=SimpleNamespace(type_=0),
            income_range=SimpleNamespace(type_=0),
        ),
    )


@pytest.mark.unit
class TestListDemographicCriteria:
    @pytest.fixture()
    def client(self) -> _MockTargetingClient:
        return _MockTargetingClient()

    async def test_maps_age_range_row_from_raw_proto_ints(
        self, client: _MockTargetingClient
    ) -> None:
        """The real API (use_proto_plus=False) yields int enums — map to names."""
        client._search.return_value = [_demographic_row()]
        result = await client.list_demographic_criteria()
        assert result == [
            {
                "criterion_id": "333",
                "type": "AGE_RANGE",
                "value": "AGE_RANGE_25_34",
                "status": "ENABLED",
                "negative": False,
                "campaign_id": "111",
                "ad_group_id": "222",
                "ad_group_name": "AG",
            }
        ]

    async def test_maps_gender_row_from_raw_proto_ints(
        self, client: _MockTargetingClient
    ) -> None:
        client._search.return_value = [
            _demographic_row(
                criterion_type=11,  # CriterionType.GENDER
                gender=11,  # GenderType.FEMALE
                negative=True,
            )
        ]
        result = await client.list_demographic_criteria()
        assert result[0]["type"] == "GENDER"
        assert result[0]["value"] == "FEMALE"
        assert result[0]["negative"] is True

    async def test_maps_proto_plus_string_enums(
        self, client: _MockTargetingClient
    ) -> None:
        """proto-plus members stringify as 'Enum.NAME' (py3.10) — same result."""
        client._search.return_value = [
            _demographic_row(
                criterion_type="CriterionType.AGE_RANGE",
                age_range="AgeRangeType.AGE_RANGE_25_34",
                status="AdGroupCriterionStatus.ENABLED",
            )
        ]
        result = await client.list_demographic_criteria()
        assert result[0]["type"] == "AGE_RANGE"
        assert result[0]["value"] == "AGE_RANGE_25_34"
        assert result[0]["status"] == "ENABLED"

    async def test_maps_numeric_string_enums(
        self, client: _MockTargetingClient
    ) -> None:
        """py3.11+ IntEnum stringifies as the number — still mapped to names."""
        client._search.return_value = [
            _demographic_row(criterion_type="10", age_range="503002", status="2")
        ]
        result = await client.list_demographic_criteria()
        assert result[0]["type"] == "AGE_RANGE"
        assert result[0]["value"] == "AGE_RANGE_25_34"
        assert result[0]["status"] == "ENABLED"

    async def test_filters_by_ad_group_and_campaign(
        self, client: _MockTargetingClient
    ) -> None:
        await client.list_demographic_criteria(ad_group_id="222", campaign_id="111")
        query = client._search.await_args.args[0]
        assert "ad_group.id = 222" in query
        assert "campaign.id = 111" in query
        assert "FROM ad_group_criterion" in query

    async def test_unscoped_query_is_capped(self, client: _MockTargetingClient) -> None:
        """Account-wide reads carry an internal LIMIT (unbounded-read guard)."""
        await client.list_demographic_criteria()
        assert "LIMIT 1000" in client._search.await_args.args[0]
        await client.list_audience_criteria()
        assert "LIMIT 1000" in client._search.await_args.args[0]

    async def test_invalid_ad_group_id_raises(
        self, client: _MockTargetingClient
    ) -> None:
        with pytest.raises(ValueError, match="ad_group_id"):
            await client.list_demographic_criteria(ad_group_id="1 OR 1=1")

    async def test_invalid_campaign_id_raises(
        self, client: _MockTargetingClient
    ) -> None:
        with pytest.raises(ValueError, match="campaign_id"):
            await client.list_demographic_criteria(campaign_id="abc")


def _audience_row(
    *,
    criterion_type: Any = 16,  # CriterionType.USER_LIST (raw proto int)
    user_list: str = "customers/1/userLists/42",
) -> SimpleNamespace:
    return SimpleNamespace(
        campaign=SimpleNamespace(id=111),
        ad_group=SimpleNamespace(id=222, name="AG"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=444,
            type_=criterion_type,
            status=2,  # AdGroupCriterionStatus.ENABLED
            negative=False,
            user_list=SimpleNamespace(user_list=user_list),
            user_interest=SimpleNamespace(
                user_interest_category="customers/1/userInterests/99"
            ),
            audience=SimpleNamespace(audience="customers/1/audiences/7"),
            custom_affinity=SimpleNamespace(
                custom_affinity="customers/1/customAffinities/5"
            ),
            custom_audience=SimpleNamespace(
                custom_audience="customers/1/customAudiences/6"
            ),
            combined_audience=SimpleNamespace(
                combined_audience="customers/1/combinedAudiences/8"
            ),
        ),
    )


@pytest.mark.unit
class TestListAudienceCriteria:
    @pytest.fixture()
    def client(self) -> _MockTargetingClient:
        return _MockTargetingClient()

    async def test_maps_user_list_row_from_raw_proto_ints(
        self, client: _MockTargetingClient
    ) -> None:
        client._search.return_value = [_audience_row()]
        result = await client.list_audience_criteria()
        assert result[0]["type"] == "USER_LIST"
        assert result[0]["value"] == "customers/1/userLists/42"
        assert result[0]["status"] == "ENABLED"
        assert result[0]["criterion_id"] == "444"
        assert result[0]["ad_group_id"] == "222"

    async def test_maps_user_interest_row_from_raw_proto_ints(
        self, client: _MockTargetingClient
    ) -> None:
        client._search.return_value = [
            _audience_row(criterion_type=24)  # CriterionType.USER_INTEREST
        ]
        result = await client.list_audience_criteria()
        assert result[0]["type"] == "USER_INTEREST"
        assert result[0]["value"] == "customers/1/userInterests/99"

    async def test_maps_proto_plus_string_enum(
        self, client: _MockTargetingClient
    ) -> None:
        client._search.return_value = [
            _audience_row(criterion_type="CriterionType.COMBINED_AUDIENCE")
        ]
        result = await client.list_audience_criteria()
        assert result[0]["type"] == "COMBINED_AUDIENCE"
        assert result[0]["value"] == "customers/1/combinedAudiences/8"

    async def test_filters_by_ad_group(self, client: _MockTargetingClient) -> None:
        await client.list_audience_criteria(ad_group_id="222")
        query = client._search.await_args.args[0]
        assert "ad_group.id = 222" in query
        assert "USER_LIST" in query and "COMBINED_AUDIENCE" in query

    async def test_invalid_campaign_id_raises(
        self, client: _MockTargetingClient
    ) -> None:
        with pytest.raises(ValueError, match="campaign_id"):
            await client.list_audience_criteria(campaign_id="x'; DROP")


def _image_asset_row(
    *,
    asset_type: Any = 4,  # AssetType.IMAGE (raw proto int)
    mime_type: Any = 4,  # MimeType.IMAGE_PNG
) -> SimpleNamespace:
    return SimpleNamespace(
        asset=SimpleNamespace(
            id=555,
            name="hero_banner",
            type_=asset_type,
            image_asset=SimpleNamespace(
                file_size=204800,
                mime_type=mime_type,
                full_size=SimpleNamespace(
                    width_pixels=1200,
                    height_pixels=628,
                    url="https://example.com/hero.png",
                ),
            ),
        ),
    )


@pytest.mark.unit
class TestListImageAssets:
    @pytest.fixture()
    def client(self) -> _MockMediaClient:
        return _MockMediaClient()

    async def test_maps_image_asset_row_from_raw_proto_ints(
        self, client: _MockMediaClient
    ) -> None:
        """The real API (use_proto_plus=False) yields int enums — map to names."""
        client._search.return_value = [_image_asset_row()]
        result = await client.list_image_assets()
        assert result == [
            {
                "id": "555",
                "name": "hero_banner",
                "type": "IMAGE",
                "file_size": 204800,
                "mime_type": "IMAGE_PNG",
                "width_pixels": 1200,
                "height_pixels": 628,
                "url": "https://example.com/hero.png",
            }
        ]

    async def test_maps_proto_plus_string_enums(self, client: _MockMediaClient) -> None:
        client._search.return_value = [
            _image_asset_row(
                asset_type="AssetType.IMAGE", mime_type="MimeType.IMAGE_PNG"
            )
        ]
        result = await client.list_image_assets()
        assert result[0]["type"] == "IMAGE"
        assert result[0]["mime_type"] == "IMAGE_PNG"

    async def test_query_selects_asset_name(self, client: _MockMediaClient) -> None:
        await client.list_image_assets(limit=25)
        query = client._search.await_args.args[0]
        assert "asset.name" in query
        assert "FROM asset" in query
        assert "asset.type = 'IMAGE'" in query
        assert "LIMIT 25" in query

    @pytest.mark.parametrize("bad_limit", [0, -5, 1001, True, "50", 2.5])
    async def test_invalid_limit_raises(
        self, client: _MockMediaClient, bad_limit: Any
    ) -> None:
        with pytest.raises(ValueError, match="limit"):
            await client.list_image_assets(limit=bad_limit)
