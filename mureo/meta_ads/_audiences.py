"""Meta Ads audience operations mixin.

Custom audience management and lookalike audience creation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Custom audience retrieval fields
_AUDIENCE_FIELDS = (
    "id,name,subtype,description,approximate_count,"
    "delivery_status,operation_status,retention_days,"
    "rule,lookalike_spec,time_created,time_updated"
)


class AudiencesMixin:
    """Meta Ads audience operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _delete(self, path: str) -> dict[str, Any]: ...  # type: ignore[empty-body]

    async def list_custom_audiences(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List custom audiences.

        Returns:
            List of custom audience information
        """
        params: dict[str, Any] = {
            "fields": _AUDIENCE_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{self._ad_account_id}/customaudiences", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_custom_audience(self, audience_id: str) -> dict[str, Any]:
        """Get custom audience details.

        Args:
            audience_id: Audience ID

        Returns:
            Audience detail information
        """
        params: dict[str, Any] = {"fields": _AUDIENCE_FIELDS}
        return await self._get(f"/{audience_id}", params)

    async def create_custom_audience(
        self,
        name: str,
        subtype: str,
        *,
        description: str | None = None,
        retention_days: int | None = None,
        rule: dict[str, Any] | None = None,
        pixel_id: str | None = None,
        customer_file_source: str | None = None,
    ) -> dict[str, Any]:
        """Create a custom audience.

        Args:
            name: Audience name
            subtype: Subtype (WEBSITE, CUSTOM, APP, ENGAGEMENT, etc.)
            description: Description
            retention_days: Retention period (in days, for WEBSITE)
            rule: Rule definition (for WEBSITE, JSON format)
            pixel_id: Meta Pixel ID (for WEBSITE)
            customer_file_source: Customer file source (for CUSTOM)

        Returns:
            Created audience information
        """
        data: dict[str, Any] = {
            "name": name,
            "subtype": subtype,
        }

        if description:
            data["description"] = description
        if retention_days is not None:
            data["retention_days"] = retention_days
        if rule is not None:
            data["rule"] = json.dumps(rule)
        if pixel_id:
            data["pixel_id"] = pixel_id
        if customer_file_source:
            data["customer_file_source"] = customer_file_source

        return await self._post(f"/{self._ad_account_id}/customaudiences", data)

    async def delete_custom_audience(self, audience_id: str) -> dict[str, Any]:
        """Delete a custom audience.

        Args:
            audience_id: Audience ID

        Returns:
            Deletion result
        """
        return await self._delete(f"/{audience_id}")

    async def create_lookalike_audience(
        self,
        name: str,
        source_audience_id: str,
        country: str | list[str],
        ratio: float,
        *,
        starting_ratio: float = 0.0,
    ) -> dict[str, Any]:
        """Create a lookalike audience.

        Args:
            name: Audience name
            source_audience_id: Source custom audience ID
            country: Target country code (single or list)
            ratio: Similarity ratio (0.01=top 1%, 0.05=top 5%, max 0.20)
            starting_ratio: Starting position of similarity (default 0.0, used for range specification)

        Returns:
            Created lookalike audience information
        """
        lookalike_spec = {
            "origin_audience_id": source_audience_id,
            "starting_ratio": starting_ratio,
            "ratio": ratio,
            "country": country if isinstance(country, list) else country,
        }

        data: dict[str, Any] = {
            "name": name,
            "subtype": "LOOKALIKE",
            "lookalike_spec": json.dumps(lookalike_spec),
        }

        return await self._post(f"/{self._ad_account_id}/customaudiences", data)
