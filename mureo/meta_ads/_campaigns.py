from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CampaignsMixin:
    """Meta Ads campaign operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    # Common field definitions
    _CAMPAIGN_FIELDS = (
        "id,name,status,objective,daily_budget,lifetime_budget,"
        "created_time,updated_time,start_time,stop_time,"
        "special_ad_categories,bid_strategy,budget_remaining"
    )

    async def list_campaigns(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List campaigns.

        Args:
            status_filter: Status filter (ACTIVE, PAUSED, ARCHIVED, DELETED)
            limit: Maximum number of results

        Returns:
            List of campaign information
        """
        account_id = self._ad_account_id
        params: dict[str, Any] = {
            "fields": self._CAMPAIGN_FIELDS,
            "limit": limit,
        }
        if status_filter:
            params["filtering"] = json.dumps(
                [{"field": "status", "operator": "IN", "value": [status_filter]}]
            )

        result = await self._get(f"/{account_id}/campaigns", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Get campaign details.

        Args:
            campaign_id: Campaign ID

        Returns:
            Campaign detail information
        """
        params: dict[str, Any] = {"fields": self._CAMPAIGN_FIELDS}
        return await self._get(f"/{campaign_id}", params)

    async def create_campaign(
        self,
        name: str,
        objective: str,
        status: str = "PAUSED",
        *,
        daily_budget: int | None = None,
        lifetime_budget: int | None = None,
        special_ad_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a campaign.

        Args:
            name: Campaign name
            objective: Campaign objective (CONVERSIONS, LINK_CLICKS, REACH, etc.)
            status: Initial status (default: PAUSED)
            daily_budget: Daily budget (in cents)
            lifetime_budget: Lifetime budget (in cents)
            special_ad_categories: Special ad categories (HOUSING, CREDIT, etc.)

        Returns:
            Created campaign information
        """
        account_id = self._ad_account_id
        data: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "status": status,
        }
        if daily_budget is not None:
            data["daily_budget"] = daily_budget
        if lifetime_budget is not None:
            data["lifetime_budget"] = lifetime_budget
        if special_ad_categories is not None:
            data["special_ad_categories"] = json.dumps(special_ad_categories)
        else:
            # Meta API requires special_ad_categories (empty array is acceptable)
            data["special_ad_categories"] = json.dumps([])

        return await self._post(f"/{account_id}/campaigns", data)

    async def update_campaign(
        self,
        campaign_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update a campaign.

        Args:
            campaign_id: Campaign ID
            **kwargs: Fields to update (name, status, daily_budget, lifetime_budget, etc.)

        Returns:
            Update result
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value

        return await self._post(f"/{campaign_id}", data)

    async def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Pause a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Update result
        """
        return await self.update_campaign(campaign_id, status="PAUSED")

    async def enable_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Enable a campaign.

        Args:
            campaign_id: Campaign ID

        Returns:
            Update result
        """
        return await self.update_campaign(campaign_id, status="ACTIVE")
