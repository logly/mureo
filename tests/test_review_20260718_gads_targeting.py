"""Regression tests for the 2026-07-18 full-review findings.

Covers:
- C1: GAQL injection guard on ``update_ad_group`` (ad_group_id must be
  validated before it reaches the manual-bid pre-check query or
  ``ad_group_path``).
- H4: ID validation on ``update_location_targeting`` /
  ``update_schedule_targeting`` (campaign_id, geo target constants, and
  criterion_ids), plus the "add or remove is required" contract exposed
  through the tool schema ``anyOf`` and the MCP handler runtime check.
- LOW: the ``_resolve_target_cpa`` type-only stub is no longer a runtime
  attribute of the keyword / search-term analysis mixins (removes the
  implicit MRO-order dependency).

All Google Ads API calls are mocked.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.google_ads._analysis_btob import _BtoBAnalysisMixin
from mureo.google_ads._analysis_keywords import _KeywordsAnalysisMixin
from mureo.google_ads._analysis_search_terms import _SearchTermsAnalysisMixin
from mureo.google_ads._extensions_targeting import _TargetingMixin
from mureo.google_ads._gaql_validator import validate_id
from mureo.google_ads.client import GoogleAdsApiClient

# GAQL payloads that must be rejected by _validate_id.
_INJECTION_IDS = ["1 OR 1=1", "'; DROP TABLE ad_group;--", "123; SELECT", "abc"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> GoogleAdsApiClient:
    """Build a GoogleAdsApiClient whose underlying GoogleAdsClient is mocked."""
    creds = MagicMock()
    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_gads.return_value = MagicMock()
        client = GoogleAdsApiClient(
            credentials=creds,
            customer_id="1234567890",
            developer_token="test-dev-token",
        )
    return client


class _MockTargetingClient(_TargetingMixin):
    """Exercise _TargetingMixin against the real GAQL id validator."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()
        self._search = AsyncMock(return_value=[])
        self._cc_service = MagicMock()

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        return validate_id(value, field_name)

    def _get_service(self, service_name: str) -> MagicMock:
        return self._cc_service

    def _stub_results(self, count: int) -> None:
        resp = MagicMock()
        resp.results = [SimpleNamespace(resource_name=f"rn/{i}") for i in range(count)]
        self._cc_service.mutate_campaign_criteria.return_value = resp


# ---------------------------------------------------------------------------
# C1 - update_ad_group id validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAdGroupIdValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_id", _INJECTION_IDS)
    async def test_malicious_ad_group_id_rejected(self, bad_id: str) -> None:
        client = _make_client()
        # _search would run the injectable pre-check query; assert it is never
        # reached because validation fails first.
        client._search = AsyncMock(side_effect=AssertionError("query ran"))
        with pytest.raises(ValueError, match="ad_group_id"):
            await client.update_ad_group({"ad_group_id": bad_id, "name": "x"})

    @pytest.mark.asyncio
    async def test_valid_ad_group_id_accepted(self) -> None:
        client = _make_client()
        result = MagicMock()
        result.resource_name = "customers/123/adGroups/789"
        response = MagicMock()
        response.results = [result]
        service = MagicMock()
        service.mutate_ad_groups.return_value = response
        client._client.get_service.return_value = service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        out = await client.update_ad_group({"ad_group_id": "789", "name": "n"})
        assert out["resource_name"] == "customers/123/adGroups/789"


# ---------------------------------------------------------------------------
# H4 - location / schedule targeting id validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLocationTargetingIdValidation:
    @pytest.mark.asyncio
    async def test_malicious_campaign_id_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="campaign_id"):
            await client.update_location_targeting(
                {"campaign_id": "1 OR 1=1", "add_locations": ["2392"]}
            )

    @pytest.mark.asyncio
    async def test_malicious_geo_target_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="geo_target_constant"):
            await client.update_location_targeting(
                {"campaign_id": "123", "add_locations": ["2392'; DROP"]}
            )

    @pytest.mark.asyncio
    async def test_malicious_geo_target_with_prefix_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="geo_target_constant"):
            await client.update_location_targeting(
                {
                    "campaign_id": "123",
                    "add_locations": ["geoTargetConstants/2392 OR 1=1"],
                }
            )

    @pytest.mark.asyncio
    async def test_malicious_remove_criterion_id_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="criterion_id"):
            await client.update_location_targeting(
                {"campaign_id": "123", "remove_criterion_ids": ["30002; DROP"]}
            )

    @pytest.mark.asyncio
    async def test_valid_locations_accepted_and_prefix_normalized(self) -> None:
        client = _MockTargetingClient()
        client._stub_results(2)
        out = await client.update_location_targeting(
            {
                "campaign_id": "123",
                "add_locations": ["2392", "geoTargetConstants/2840"],
            }
        )
        assert len(out) == 2


@pytest.mark.unit
class TestScheduleTargetingIdValidation:
    @pytest.mark.asyncio
    async def test_malicious_campaign_id_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="campaign_id"):
            await client.update_schedule_targeting(
                {
                    "campaign_id": "1 OR 1=1",
                    "add_schedules": [{"day": "MONDAY"}],
                }
            )

    @pytest.mark.asyncio
    async def test_malicious_remove_criterion_id_rejected(self) -> None:
        client = _MockTargetingClient()
        with pytest.raises(ValueError, match="criterion_id"):
            await client.update_schedule_targeting(
                {"campaign_id": "123", "remove_criterion_ids": ["30002 OR 1=1"]}
            )

    @pytest.mark.asyncio
    async def test_valid_remove_accepted(self) -> None:
        client = _MockTargetingClient()
        client._stub_results(1)
        out = await client.update_schedule_targeting(
            {"campaign_id": "123", "remove_criterion_ids": ["30002"]}
        )
        assert len(out) == 1


# ---------------------------------------------------------------------------
# H4 - tool schema anyOf + handler runtime check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTargetingToolContracts:
    def test_location_and_schedule_tools_declare_anyof(self) -> None:
        from mureo.mcp._tools_google_ads_extensions import TOOLS

        by_name = {t.name: t for t in TOOLS}
        for name, first_key in (
            ("google_ads_location_targeting_update", "add_locations"),
            ("google_ads_schedule_targeting_update", "add_schedules"),
        ):
            schema = by_name[name].inputSchema
            required_sets = [set(o["required"]) for o in schema["anyOf"]]
            assert {first_key} in required_sets
            assert {"remove_criterion_ids"} in required_sets

    @pytest.mark.asyncio
    async def test_location_handler_requires_add_or_remove(self) -> None:
        from mureo.mcp import _handlers_google_ads_extensions as mod

        with (
            patch.object(mod, "_get_client", return_value=MagicMock()),
            pytest.raises(ValueError, match="add_locations"),
        ):
            await mod.handle_location_targeting_update({"campaign_id": "123"})

    @pytest.mark.asyncio
    async def test_schedule_handler_requires_add_or_remove(self) -> None:
        from mureo.mcp import _handlers_google_ads_extensions as mod

        with (
            patch.object(mod, "_get_client", return_value=MagicMock()),
            pytest.raises(ValueError, match="add_schedules"),
        ):
            await mod.handle_schedule_targeting_update({"campaign_id": "123"})


# ---------------------------------------------------------------------------
# LOW - _resolve_target_cpa stub is type-only (no runtime shadowing)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveTargetCpaStubTypeOnly:
    def test_keywords_mixin_has_no_runtime_stub(self) -> None:
        assert "_resolve_target_cpa" not in _KeywordsAnalysisMixin.__dict__

    def test_search_terms_mixin_has_no_runtime_stub(self) -> None:
        assert "_resolve_target_cpa" not in _SearchTermsAnalysisMixin.__dict__

    def test_composed_client_resolves_real_impl(self) -> None:
        from mureo.google_ads._analysis_performance import (
            _PerformanceAnalysisMixin,
        )

        assert (
            GoogleAdsApiClient._resolve_target_cpa
            is _PerformanceAnalysisMixin._resolve_target_cpa
        )


# ---------------------------------------------------------------------------
# LOW - B2B advisory failures are logged (not silently swallowed)
# ---------------------------------------------------------------------------


class _MockBtoBClient(_BtoBAnalysisMixin):
    """Minimal B2B mixin host with a failing schedule read."""

    def __init__(self) -> None:
        self._customer_id = "1234567890"
        self._client = MagicMock()

    async def list_schedule_targeting(self, campaign_id: str) -> list:
        raise RuntimeError("boom")


@pytest.mark.unit
class TestBtoBAdvisoryLogging:
    @pytest.mark.asyncio
    async def test_schedule_check_failure_is_logged_and_tolerated(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _MockBtoBClient()
        suggestions: list = []
        with caplog.at_level("WARNING", logger="mureo.google_ads._analysis_btob"):
            await client._check_schedule_for_btob("123", suggestions)
        # Advisory check degrades gracefully (no suggestion emitted) ...
        assert suggestions == []
        # ... but the failure is now surfaced in the logs.
        assert any("B2B schedule check failed" in rec.message for rec in caplog.records)
