"""Meta Ads Lead Ads operations mixin.

Lead form management and lead data retrieval.
Lead Forms are linked to Pages, so page_id is required.
Lead data contains PII and is not logged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lead form retrieval fields
_LEAD_FORM_FIELDS = (
    "id,name,status,locale,questions,"
    "follow_up_action_url,created_time,expired_leads_count,"
    "leads_count,organic_leads_count"
)

# Lead data retrieval fields
_LEAD_FIELDS = "id,created_time,field_data,ad_id,ad_name,form_id"


class LeadsMixin:
    """Meta Ads Lead Ads operations mixin

    Used via multiple inheritance with MetaAdsApiClient.
    Lead Forms are linked to Facebook Pages, so page_id is required.
    """

    _ad_account_id: str

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def list_lead_forms(
        self,
        page_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List lead forms

        Args:
            page_id: Facebook page ID
            limit: Maximum number of items to retrieve

        Returns:
            List of lead form information.
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FORM_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{page_id}/leadgen_forms", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def get_lead_form(self, form_id: str) -> dict[str, Any]:
        """Get lead form details

        Args:
            form_id: Lead form ID

        Returns:
            Lead form detail information.
        """
        params: dict[str, Any] = {"fields": _LEAD_FORM_FIELDS}
        return await self._get(f"/{form_id}", params)

    async def create_lead_form(
        self,
        page_id: str,
        name: str,
        questions: list[dict[str, Any]],
        privacy_policy_url: str,
        *,
        follow_up_action_url: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        """Create a lead form

        Args:
            page_id: Facebook page ID
            name: Form name
            questions: List of questions (FULL_NAME, EMAIL, PHONE_NUMBER, COMPANY_NAME, CUSTOM, etc.)
            privacy_policy_url: Privacy policy URL
            follow_up_action_url: Redirect URL after form submission
            locale: Locale

        Returns:
            Created lead form information.
        """
        data: dict[str, Any] = {
            "name": name,
            "questions": json.dumps(questions),
            "privacy_policy": json.dumps({"url": privacy_policy_url}),
        }

        if follow_up_action_url is not None:
            data["follow_up_action_url"] = follow_up_action_url
        if locale is not None:
            data["locale"] = locale

        logger.info(
            "Lead form creation: page_id=%s, name=%s",
            page_id,
            name,
        )
        return await self._post(f"/{page_id}/leadgen_forms", data)

    async def get_leads(
        self,
        form_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get lead data submitted to a form

        Lead data contains PII (name, email, phone, etc.) and
        is not logged.

        Args:
            form_id: Lead form ID
            limit: Maximum number of items to retrieve

        Returns:
            List of lead data.
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{form_id}/leads", params)
        # Not logged because it contains PII
        leads = result.get("data", [])
        logger.info("Lead data retrieval: form_id=%s, count=%d", form_id, len(leads))
        return leads  # type: ignore[no-any-return]

    async def get_ad_leads(
        self,
        ad_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get lead data via ads

        Lead data contains PII (name, email, phone, etc.) and
        is not logged.

        Args:
            ad_id: Ad ID
            limit: Maximum number of items to retrieve

        Returns:
            List of lead data.
        """
        params: dict[str, Any] = {
            "fields": _LEAD_FIELDS,
            "limit": limit,
        }
        result = await self._get(f"/{ad_id}/leads", params)
        # Not logged because it contains PII
        leads = result.get("data", [])
        logger.info("Lead data by ad: ad_id=%s, count=%d", ad_id, len(leads))
        return leads  # type: ignore[no-any-return]
