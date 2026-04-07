from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AdSetsMixin:
    """Meta Ads ad set operations mixin

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
    _AD_SET_FIELDS = (
        "id,name,status,campaign_id,daily_budget,lifetime_budget,"
        "billing_event,optimization_goal,targeting,start_time,end_time,"
        "created_time,updated_time,bid_amount,bid_strategy"
    )

    async def list_ad_sets(
        self,
        campaign_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List ad sets.

        Args:
            campaign_id: Campaign ID (when specified, only ad sets under this campaign)
            limit: Maximum number of results

        Returns:
            List of ad set information
        """
        params: dict[str, Any] = {
            "fields": self._AD_SET_FIELDS,
            "limit": limit,
        }

        if campaign_id:
            path = f"/{campaign_id}/adsets"
        else:
            account_id = self._ad_account_id
            path = f"/{account_id}/adsets"

        result = await self._get(path, params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """Get ad set details.

        Args:
            ad_set_id: Ad set ID

        Returns:
            Ad set detail information
        """
        params: dict[str, Any] = {"fields": self._AD_SET_FIELDS}
        return await self._get(f"/{ad_set_id}", params)

    async def create_ad_set(
        self,
        campaign_id: str,
        name: str,
        daily_budget: int = 0,
        billing_event: str = "IMPRESSIONS",
        optimization_goal: str = "REACH",
        targeting: dict[str, Any] | None = None,
        status: str = "PAUSED",
        use_dynamic_creative: bool = False,
        bid_amount: int | None = None,
    ) -> dict[str, Any]:
        """Create an ad set

        Args:
            campaign_id: Parent campaign ID
            name: Ad set name
            daily_budget: Daily budget (in cents). Set to 0 for CBO campaigns.
            billing_event: Billing event (IMPRESSIONS, LINK_CLICKS, etc.)
            optimization_goal: Optimization goal (REACH, LINK_CLICKS, CONVERSIONS, etc.)
            targeting: Targeting settings
            status: Initial status (default: PAUSED)
            use_dynamic_creative: Enable dynamic creative
            bid_amount: Bid amount in cents (required for some optimization goals)

        Returns:
            Created ad set information.
        """
        account_id = self._ad_account_id
        data: dict[str, Any] = {
            "campaign_id": campaign_id,
            "name": name,
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "status": status,
        }
        # Only include daily_budget if > 0 (CBO campaigns manage budget at campaign level)
        if daily_budget > 0:
            data["daily_budget"] = daily_budget
        if bid_amount is not None:
            data["bid_amount"] = bid_amount
        if targeting is not None:
            data["targeting"] = json.dumps(targeting)
        else:
            # Default targeting (all of Japan)
            data["targeting"] = json.dumps({"geo_locations": {"countries": ["JP"]}})
        if use_dynamic_creative:
            data["use_dynamic_creative"] = True

        return await self._post(f"/{account_id}/adsets", data)

    async def update_ad_set(
        self,
        ad_set_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update an ad set

        Args:
            ad_set_id: Ad set ID
            **kwargs: Fields to update (name, status, daily_budget,
                      targeting, optimization_goal, etc.)

        Returns:
            Update result.
        """
        data: dict[str, Any] = {}
        for key, value in kwargs.items():
            if value is not None:
                if key == "targeting" and isinstance(value, dict):
                    data[key] = json.dumps(value)
                else:
                    data[key] = value

        return await self._post(f"/{ad_set_id}", data)

    async def pause_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """Pause an ad set

        Args:
            ad_set_id: Ad set ID

        Returns:
            Update result.
        """
        return await self.update_ad_set(ad_set_id, status="PAUSED")

    async def enable_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """Enable an ad set

        Args:
            ad_set_id: Ad set ID

        Returns:
            Update result.
        """
        return await self.update_ad_set(ad_set_id, status="ACTIVE")
