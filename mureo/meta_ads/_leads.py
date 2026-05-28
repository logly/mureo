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
    "id,name,status,locale,questions,privacy_policy,"
    "follow_up_action_url,created_time,expired_leads_count,"
    "leads_count,organic_leads_count"
)

# Lead data retrieval fields
_LEAD_FIELDS = "id,created_time,field_data,ad_id,ad_name,form_id"

# Lead form ``status`` values Meta accepts on update. The full
# lifecycle is just two states — ``ACTIVE`` and ``ARCHIVED``. Other
# values (``DRAFT``, ``DELETED``, ``DELETION_PENDING``) appear in
# read paths but cannot be set by an operator.
_VALID_FORM_STATUSES: frozenset[str] = frozenset({"ACTIVE", "ARCHIVED"})


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

    async def _get_as_page(  # type: ignore[empty-body]
        self, page_id: str, path: str, params: dict[str, Any] | None = None
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
        result = await self._get_as_page(page_id, f"/{page_id}/leadgen_forms", params)
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

    async def update_lead_form(
        self,
        form_id: str,
        *,
        status: str,
    ) -> dict[str, Any]:
        """Change a lead form's lifecycle status.

        This helper updates **only** ``status``; other lead-form
        fields are intentionally out of scope. (Meta's API surface
        for post-creation form mutation has shifted between
        versions — ``follow_up_action_url`` in particular has gone
        in and out of being mutable — so the helper stays
        conservative.) Pass ``"ARCHIVED"`` to retire a form (existing
        leads stay queryable; the form just stops accepting new
        submissions). Pass ``"ACTIVE"`` to undo an archive.

        Args:
            form_id: Lead form ID.
            status: One of ``"ACTIVE"`` / ``"ARCHIVED"``. Other values
                are rejected at the helper level rather than after a
                Meta 400 round-trip.

        Raises:
            ValueError: ``status`` is not in
                :data:`_VALID_FORM_STATUSES`.
        """
        if status not in _VALID_FORM_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_FORM_STATUSES)}; "
                f"got {status!r}"
            )
        logger.info("Lead form status update: form_id=%s, status=%s", form_id, status)
        return await self._post(f"/{form_id}", {"status": status})

    async def duplicate_lead_form(
        self,
        form_id: str,
        *,
        page_id: str,
        new_name: str,
    ) -> dict[str, Any]:
        """Duplicate a lead form under the same (or another) Page.

        Meta has no native "copy" endpoint, so the helper fetches the
        source form's core configuration (questions, privacy policy,
        optional follow-up URL, locale) and creates a fresh form
        with the supplied ``new_name``. The returned dict carries
        the new form's ID; the source form is untouched.

        **Lossy duplication.** Only the four fields above round-trip.
        Advanced features that may exist on the source —
        ``legal_content_id``, ``gdpr_required`` /
        ``custom_disclaimer``, ``question_page_custom_headline``,
        intro / thank-you screens, conditional question branches —
        are **not** copied. If you need those, re-create them on the
        new form manually after duplication. PR 3 (advanced form
        features) will widen the copied surface.

        Args:
            form_id: Source lead form ID to copy from.
            page_id: Facebook Page that will own the new form (often
                the same Page that owns the source form, but the
                helper does not assume so).
            new_name: Name for the new form. Pick something distinct
                from the source so audit trails stay readable.

        Raises:
            ValueError: The source form has no ``privacy_policy.url``
                nor ``privacy_policy_url`` field (Meta requires one
                at creation time, so the duplicate would fail
                server-side anyway). Also raised when
                ``privacy_policy`` is present but its ``url`` is
                empty / missing — falls through to the same fail
                path so the operator gets one clear error rather
                than a Meta 400 later.
        """
        source = await self.get_lead_form(form_id)
        policy = source.get("privacy_policy")
        if isinstance(policy, dict) and policy.get("url"):
            privacy_url = policy["url"]
        elif source.get("privacy_policy_url"):
            privacy_url = source["privacy_policy_url"]
        else:
            raise ValueError(
                f"source form {form_id!r} has no privacy_policy.url; "
                "Meta requires one for lead form creation"
            )

        data: dict[str, Any] = {
            "name": new_name,
            "questions": json.dumps(source.get("questions", [])),
            "privacy_policy": json.dumps({"url": privacy_url}),
        }
        if source.get("follow_up_action_url"):
            data["follow_up_action_url"] = source["follow_up_action_url"]
        if source.get("locale"):
            data["locale"] = source["locale"]

        logger.info(
            "Lead form duplicate: source=%s, page_id=%s, new_name=%s",
            form_id,
            page_id,
            new_name,
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
