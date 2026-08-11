"""Tests for Google Ads negative placement criteria (#544).

Covers ``_PlacementsMixin`` (list / add / remove of excluded websites,
mobile applications and mobile app categories at campaign and ad group
level), the ``map_negative_placement`` mapper, the MCP tool schemas and
the handler wiring.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo.google_ads.client import GoogleAdsApiClient

PLACEMENT = 3  # CriterionTypeEnum.PLACEMENT
MOBILE_APP_CATEGORY = 4
MOBILE_APPLICATION = 5


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


def _campaign_row(
    criterion_id: int = 555,
    ctype: int = PLACEMENT,
    url: str = "example.com",
    app_id: str = "",
    app_name: str = "",
    category: str = "",
) -> MagicMock:
    row = MagicMock()
    crit = row.campaign_criterion
    crit.criterion_id = criterion_id
    crit.type_ = ctype
    crit.negative = True
    crit.placement.url = url
    crit.mobile_application.app_id = app_id
    crit.mobile_application.name = app_name
    crit.mobile_app_category.mobile_app_category_constant = category
    row.campaign.id = 100
    row.campaign.name = "Display JP"
    return row


def _ad_group_row(
    criterion_id: int = 777,
    ctype: int = MOBILE_APPLICATION,
    url: str = "",
    app_id: str = "2-com.example.app",
    app_name: str = "Example App",
    category: str = "",
) -> MagicMock:
    row = MagicMock()
    crit = row.ad_group_criterion
    crit.criterion_id = criterion_id
    crit.type_ = ctype
    crit.negative = True
    crit.placement.url = url
    crit.mobile_application.app_id = app_id
    crit.mobile_application.name = app_name
    crit.mobile_app_category.mobile_app_category_constant = category
    row.campaign.id = 100
    row.campaign.name = "Display JP"
    row.ad_group.id = 200
    row.ad_group.name = "App exclusions"
    return row


def _mutate_response(resource_names: list[str]) -> MagicMock:
    response = MagicMock()
    response.results = []
    for name in resource_names:
        result = MagicMock()
        result.resource_name = name
        response.results.append(result)
    return response


# ---------------------------------------------------------------------------
# list_negative_placements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListNegativePlacements:
    @pytest.mark.asyncio
    async def test_reads_both_levels_by_default(self) -> None:
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return (
                [_campaign_row()]
                if "FROM campaign_criterion" in query
                else [_ad_group_row()]
            )

        client._search = _search  # type: ignore[method-assign]
        rows = await client.list_negative_placements()

        assert len(queries) == 2
        assert len(rows) == 2
        campaign_entry = next(r for r in rows if r["level"] == "campaign")
        assert campaign_entry["criterion_id"] == "555"
        assert campaign_entry["type"] == "website"
        assert campaign_entry["value"] == "example.com"
        assert campaign_entry["campaign_id"] == "100"
        ad_group_entry = next(r for r in rows if r["level"] == "ad_group")
        assert ad_group_entry["type"] == "mobile_application"
        assert ad_group_entry["value"] == "2-com.example.app"
        assert ad_group_entry["ad_group_id"] == "200"

    @pytest.mark.asyncio
    async def test_ad_group_scope_skips_the_campaign_level_query(self) -> None:
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return [_ad_group_row()]

        client._search = _search  # type: ignore[method-assign]
        rows = await client.list_negative_placements(ad_group_id="200")
        assert len(queries) == 1
        assert "FROM ad_group_criterion" in queries[0]
        assert "ad_group.id = 200" in queries[0]
        assert all(r["level"] == "ad_group" for r in rows)

    @pytest.mark.asyncio
    async def test_campaign_scope_filters_both_queries(self) -> None:
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return []

        client._search = _search  # type: ignore[method-assign]
        await client.list_negative_placements(campaign_id="100")
        assert len(queries) == 2
        assert all("campaign.id = 100" in q for q in queries)

    @pytest.mark.asyncio
    async def test_app_category_value_is_the_constant_resource_name(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            if "FROM campaign_criterion" not in query:
                return []
            return [
                _campaign_row(
                    criterion_id=9,
                    ctype=MOBILE_APP_CATEGORY,
                    url="",
                    category="mobileAppCategoryConstants/60000",
                )
            ]

        client._search = _search  # type: ignore[method-assign]
        rows = await client.list_negative_placements()
        assert rows[0]["type"] == "mobile_app_category"
        assert rows[0]["value"] == "mobileAppCategoryConstants/60000"

    @pytest.mark.asyncio
    async def test_rejects_non_numeric_ids(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="campaign_id"):
            await client.list_negative_placements(campaign_id="1; DROP TABLE")


# ---------------------------------------------------------------------------
# add_negative_placements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddNegativePlacements:
    @pytest.mark.asyncio
    async def test_campaign_level_add_returns_criterion_ids(self) -> None:
        client = _make_client()
        service = MagicMock()
        service.mutate_campaign_criteria.return_value = _mutate_response(
            [
                "customers/1234567890/campaignCriteria/100~555",
                "customers/1234567890/campaignCriteria/100~556",
            ]
        )
        client._client.get_service.return_value = service
        client._client.get_type.return_value = MagicMock()

        result = await client.add_negative_placements(
            {
                "campaign_id": "100",
                "placements": [
                    {"type": "website", "value": "example0.com"},
                    {"type": "mobile_application", "value": "2-com.example.app"},
                ],
            }
        )
        assert result["level"] == "campaign"
        assert result["campaign_id"] == "100"
        assert result["count"] == 2
        assert [c["criterion_id"] for c in result["created"]] == ["555", "556"]
        assert result["created"][0]["type"] == "website"
        assert result["created"][1]["value"] == "2-com.example.app"

    @pytest.mark.asyncio
    async def test_ad_group_level_add_uses_ad_group_criteria(self) -> None:
        client = _make_client()
        service = MagicMock()
        service.mutate_ad_group_criteria.return_value = _mutate_response(
            ["customers/1234567890/adGroupCriteria/200~777"]
        )
        client._client.get_service.return_value = service
        client._client.get_type.return_value = MagicMock()

        result = await client.add_negative_placements(
            {
                "ad_group_id": "200",
                "placements": [{"type": "website", "value": "bad.example"}],
            }
        )
        assert result["level"] == "ad_group"
        assert result["ad_group_id"] == "200"
        service.mutate_ad_group_criteria.assert_called_once()

    @pytest.mark.asyncio
    async def test_bare_app_category_id_is_normalized_to_a_resource_name(self) -> None:
        client = _make_client()
        service = MagicMock()
        service.mutate_campaign_criteria.return_value = _mutate_response(
            ["customers/1234567890/campaignCriteria/100~1"]
        )
        client._client.get_service.return_value = service
        criterion_op = MagicMock()
        client._client.get_type.return_value = criterion_op

        await client.add_negative_placements(
            {
                "campaign_id": "100",
                "placements": [{"type": "mobile_app_category", "value": "60000"}],
            }
        )
        assert (
            criterion_op.create.mobile_app_category.mobile_app_category_constant
            == "mobileAppCategoryConstants/60000"
        )

    @pytest.mark.asyncio
    async def test_requires_exactly_one_level(self) -> None:
        client = _make_client()
        placements = [{"type": "website", "value": "x.example"}]
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_negative_placements({"placements": placements})
        with pytest.raises(ValueError, match="exactly one"):
            await client.add_negative_placements(
                {"campaign_id": "1", "ad_group_id": "2", "placements": placements}
            )

    @pytest.mark.asyncio
    async def test_rejects_unknown_exclusion_type(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="youtube_channel"):
            await client.add_negative_placements(
                {
                    "campaign_id": "100",
                    "placements": [{"type": "youtube_channel", "value": "abc"}],
                }
            )

    @pytest.mark.asyncio
    async def test_rejects_empty_placement_list(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="At least one"):
            await client.add_negative_placements(
                {"campaign_id": "100", "placements": []}
            )


# ---------------------------------------------------------------------------
# remove_negative_placements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemoveNegativePlacements:
    @pytest.mark.asyncio
    async def test_removes_verified_exclusion_criteria(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_campaign_row(criterion_id=555), _campaign_row(criterion_id=556)]

        client._search = _search  # type: ignore[method-assign]
        service = MagicMock()
        service.mutate_campaign_criteria.return_value = _mutate_response(
            [
                "customers/1234567890/campaignCriteria/100~555",
                "customers/1234567890/campaignCriteria/100~556",
            ]
        )
        client._client.get_service.return_value = service
        client._client.get_type.return_value = MagicMock()

        result = await client.remove_negative_placements(
            {"campaign_id": "100", "criterion_ids": ["555", "556"]}
        )
        assert result["removed_count"] == 2
        assert [r["criterion_id"] for r in result["removed"]] == ["555", "556"]
        assert result["skipped"] == []

    @pytest.mark.asyncio
    async def test_refuses_ids_that_are_not_negative_placements(self) -> None:
        """The reversal of an add must not be usable to delete a keyword."""
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return [_campaign_row(criterion_id=555)]

        client._search = _search  # type: ignore[method-assign]
        service = MagicMock()
        service.mutate_campaign_criteria.return_value = _mutate_response(
            ["customers/1234567890/campaignCriteria/100~555"]
        )
        client._client.get_service.return_value = service
        criterion_path = client._client.get_service.return_value
        criterion_path.campaign_criterion_path.side_effect = (
            lambda cust, camp, crit: f"customers/{cust}/campaignCriteria/{camp}~{crit}"
        )
        client._client.get_type.side_effect = lambda _name: MagicMock()

        result = await client.remove_negative_placements(
            {"campaign_id": "100", "criterion_ids": ["555", "999"]}
        )
        assert [r["criterion_id"] for r in result["removed"]] == ["555"]
        assert result["skipped"] == [
            {
                "criterion_id": "999",
                "reason": "not a negative placement criterion at this level",
            }
        ]
        # The unverified id never became a remove operation: exactly one
        # operation was submitted, and it names the verified criterion.
        assert service.mutate_campaign_criteria.call_count == 1
        operations = service.mutate_campaign_criteria.call_args.kwargs["operations"]
        assert len(operations) == 1
        assert operations[0].remove.endswith("~555")

    @pytest.mark.asyncio
    async def test_no_verified_ids_means_no_mutate_call(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return []

        client._search = _search  # type: ignore[method-assign]
        service = MagicMock()
        client._client.get_service.return_value = service
        client._client.get_type.return_value = MagicMock()

        result = await client.remove_negative_placements(
            {"campaign_id": "100", "criterion_ids": ["999"]}
        )
        assert result["removed"] == []
        assert result["removed_count"] == 0
        service.mutate_campaign_criteria.assert_not_called()

    @pytest.mark.asyncio
    async def test_requires_exactly_one_level(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="exactly one"):
            await client.remove_negative_placements({"criterion_ids": ["1"]})

    @pytest.mark.asyncio
    async def test_rejects_non_numeric_criterion_ids(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="criterion_id"):
            await client.remove_negative_placements(
                {"campaign_id": "100", "criterion_ids": ["1 OR 1=1"]}
            )


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolSchemas:
    def test_add_schema_declares_the_three_exclusion_types(self) -> None:
        from mureo.mcp.tools_google_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "google_ads_negative_placements_add")
        item = tool.inputSchema["properties"]["placements"]["items"]
        assert set(item["properties"]["type"]["enum"]) == {
            "website",
            "mobile_application",
            "mobile_app_category",
        }
        assert item["required"] == ["type", "value"]

    def test_remove_schema_takes_a_list_so_a_bad_batch_reverts_in_one_call(
        self,
    ) -> None:
        from mureo.mcp.tools_google_ads import TOOLS

        tool = next(
            t for t in TOOLS if t.name == "google_ads_negative_placements_remove"
        )
        criterion_ids = tool.inputSchema["properties"]["criterion_ids"]
        assert criterion_ids["type"] == "array"
        assert criterion_ids["minItems"] == 1


@pytest.mark.unit
class TestHandlers:
    @pytest.mark.asyncio
    async def test_add_handler_passes_params_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import _handlers_google_ads as h

        captured: dict[str, Any] = {}

        class _Client:
            async def add_negative_placements(
                self, params: dict[str, Any]
            ) -> dict[str, Any]:
                captured.update(params)
                return {"level": "campaign", "campaign_id": "100", "created": []}

        monkeypatch.setattr(h, "_get_client", lambda _args: _Client())
        result = await h.HANDLERS["google_ads_negative_placements_add"](
            {
                "campaign_id": "100",
                "placements": [{"type": "website", "value": "x.example"}],
            }
        )
        assert captured == {
            "campaign_id": "100",
            "ad_group_id": None,
            "placements": [{"type": "website", "value": "x.example"}],
        }
        assert json.loads(result[0].text)["level"] == "campaign"

    @pytest.mark.asyncio
    async def test_list_handler_returns_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import _handlers_google_ads as h

        class _Client:
            async def list_negative_placements(self, **kwargs: Any) -> list[Any]:
                return [{"criterion_id": "1"}]

        monkeypatch.setattr(h, "_get_client", lambda _args: _Client())
        result = await h.HANDLERS["google_ads_negative_placements_list"]({})
        assert json.loads(result[0].text) == [{"criterion_id": "1"}]

    @pytest.mark.asyncio
    async def test_remove_handler_requires_criterion_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import _handlers_google_ads as h

        monkeypatch.setattr(h, "_get_client", lambda _args: MagicMock())
        with pytest.raises(ValueError, match="criterion_ids"):
            await h.HANDLERS["google_ads_negative_placements_remove"](
                {"campaign_id": "100"}
            )


# ---------------------------------------------------------------------------
# Placement performance — the denominator for the #547 impact preview
# ---------------------------------------------------------------------------


def _placement_perf_row(
    placement: str = "example.com",
    placement_type: str = "PlacementType.WEBSITE",
    impressions: int = 1000,
) -> MagicMock:
    row = MagicMock()
    view = row.group_placement_view
    view.placement = placement
    view.display_name = "Example"
    view.target_url = f"https://{placement}"
    view.placement_type = placement_type
    row.metrics.impressions = impressions
    row.metrics.clicks = 10
    row.metrics.cost_micros = 5_000_000
    row.metrics.conversions = 2.0
    return row


@pytest.mark.unit
class TestPlacementPerformance:
    @pytest.mark.asyncio
    async def test_reads_group_placement_view_scoped_to_the_campaign(self) -> None:
        client = _make_client()
        queries: list[str] = []

        async def _search(query: str) -> list[Any]:
            queries.append(query)
            return [
                _placement_perf_row(),
                _placement_perf_row(
                    "mobileapp::1-com.example.app",
                    "PlacementType.MOBILE_APPLICATION",
                    400,
                ),
            ]

        client._search = _search  # type: ignore[method-assign]
        rows = await client.get_placement_performance(
            campaign_id="100", period="LAST_30_DAYS"
        )

        assert "FROM group_placement_view" in queries[0]
        assert "AND campaign.id = 100" in queries[0]
        assert "DURING LAST_30_DAYS" in queries[0]
        assert rows[0]["placement"] == "example.com"
        assert rows[0]["type"] == "website"
        assert rows[0]["impressions"] == 1000
        assert rows[0]["cost"] == 5.0
        assert rows[1]["type"] == "mobile_application"

    @pytest.mark.asyncio
    async def test_a_between_window_is_validated_not_interpolated_raw(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return []

        client._search = _search  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await client.get_placement_performance(
                campaign_id="100", period="BETWEEN '2026-01-01' AND '; DROP'"
            )

    @pytest.mark.asyncio
    async def test_a_non_numeric_scope_id_is_refused(self) -> None:
        client = _make_client()

        async def _search(query: str) -> list[Any]:
            return []

        client._search = _search  # type: ignore[method-assign]
        with pytest.raises(ValueError):
            await client.get_placement_performance(campaign_id="100 OR 1=1")
