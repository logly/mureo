"""Sitelink operations mixin.

Provides list_sitelinks / create_sitelink / remove_sitelink.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_sitelink

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

# Sitelink limit per campaign
_MAX_SITELINKS_PER_CAMPAIGN = 20


class _SitelinksMixin:
    """Mixin providing sitelink operations."""

    # Type declarations for attributes provided by parent class (GoogleAdsApiClient)
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    def _get_service(self, service_name: str) -> Any: ...

    # Expose limit value as class variable
    _MAX_SITELINKS_PER_CAMPAIGN = _MAX_SITELINKS_PER_CAMPAIGN

    async def list_sitelinks(self, campaign_id: str) -> list[dict[str, Any]]:
        """List sitelinks applied to campaign (campaign + account level).

        In Google Ads, sitelinks can be set at 3 levels:
        - Account level (customer_asset): Applied to all campaigns
        - Campaign level (campaign_asset): Specified campaign only
        - Ad group level (ad_group_asset): Specified ad group only

        This method returns both campaign-level and account-level sitelinks.
        """
        self._validate_id(campaign_id, "campaign_id")

        # Campaign level
        campaign_query = f"""
            SELECT
                campaign.id,
                asset.id, asset.resource_name,
                asset.sitelink_asset.link_text,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.final_urls
            FROM campaign_asset
            WHERE campaign_asset.field_type = 'SITELINK'
                AND campaign.id = {campaign_id}
        """

        # Account level (applied to all campaigns)
        account_query = """
            SELECT
                asset.id, asset.resource_name,
                asset.sitelink_asset.link_text,
                asset.sitelink_asset.description1,
                asset.sitelink_asset.description2,
                asset.final_urls
            FROM customer_asset
            WHERE customer_asset.field_type = 'SITELINK'
        """

        campaign_response = await self._search(campaign_query)  # type: ignore[attr-defined]
        results = [
            {**map_sitelink(row), "level": "campaign"} for row in campaign_response
        ]

        # Record existing asset IDs to avoid duplicates
        seen_ids: set[str | None] = {r.get("id") for r in results}

        try:
            account_response = await self._search(account_query)  # type: ignore[attr-defined]
            for row in account_response:
                mapped = map_sitelink(row)
                if mapped.get("id") not in seen_ids:
                    mapped["level"] = "account"
                    results.append(mapped)
                    seen_ids.add(mapped.get("id"))
        except Exception:
            logger.debug("Failed to retrieve account-level sitelinks", exc_info=True)

        return results

    @_wrap_mutate_error("sitelink creation")
    async def create_sitelink(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create sitelink and link to campaign."""
        # Limit check
        campaign_id = params["campaign_id"]
        existing = await self.list_sitelinks(campaign_id)
        campaign_count = sum(1 for s in existing if s.get("level") == "campaign")
        if campaign_count >= self._MAX_SITELINKS_PER_CAMPAIGN:
            return {
                "error": True,
                "error_type": "validation_error",
                "message": f"Maximum {self._MAX_SITELINKS_PER_CAMPAIGN} sitelinks per campaign. "
                f"Currently {campaign_count} registered; please delete unnecessary sitelinks before adding.",
            }

        # 1. Create asset
        asset_service = self._get_service("AssetService")
        asset_op = self._client.get_type("AssetOperation")
        asset = asset_op.create
        asset.sitelink_asset.link_text = params["link_text"]
        asset.final_urls.append(params["final_url"])
        if "description1" in params:
            asset.sitelink_asset.description1 = params["description1"]
        if "description2" in params:
            asset.sitelink_asset.description2 = params["description2"]
        asset_response = asset_service.mutate_assets(
            customer_id=self._customer_id,
            operations=[asset_op],
        )
        asset_resource_name = asset_response.results[0].resource_name

        # 2. Link to campaign
        campaign_asset_service = self._get_service("CampaignAssetService")
        ca_op = self._client.get_type("CampaignAssetOperation")
        campaign_asset = ca_op.create
        campaign_asset.campaign = self._client.get_service(
            "CampaignService"
        ).campaign_path(self._customer_id, params["campaign_id"])
        campaign_asset.asset = asset_resource_name
        campaign_asset.field_type = self._client.enums.AssetFieldTypeEnum.SITELINK
        campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[ca_op],
        )
        return {"resource_name": asset_resource_name}

    @_wrap_mutate_error("sitelink removal")
    async def remove_sitelink(self, params: dict[str, Any]) -> dict[str, Any]:
        """Remove sitelink."""
        self._validate_id(params["campaign_id"], "campaign_id")
        self._validate_id(params["asset_id"], "asset_id")
        campaign_asset_service = self._get_service("CampaignAssetService")
        op = self._client.get_type("CampaignAssetOperation")
        op.remove = self._client.get_service(
            "CampaignAssetService"
        ).campaign_asset_path(
            self._customer_id,
            params["campaign_id"],
            params["asset_id"],
            "SITELINK",
        )
        response = campaign_asset_service.mutate_campaign_assets(
            customer_id=self._customer_id,
            operations=[op],
        )
        return {"resource_name": response.results[0].resource_name}
