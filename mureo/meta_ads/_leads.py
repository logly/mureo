"""Meta Ads Lead Ads operations mixin.

Lead form management and lead data retrieval.
Lead Forms are linked to Pages, so page_id is required.
Lead data contains PII and is not logged.
"""

from __future__ import annotations

import csv
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from pathlib import Path

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

# Characters that turn a CSV cell into a live formula in
# Excel / Sheets / Numbers. Prepending a single-quote disarms the
# injection without breaking the visible value for spreadsheet users.
_CSV_INJECTION_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: str) -> str:
    """Escape leading characters that would otherwise be interpreted
    as a spreadsheet formula. Idempotent — re-escaping the result is
    a no-op because the leading single quote is itself benign.
    """
    if value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


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
        context_card: dict[str, Any] | None = None,
        thank_you_page: dict[str, Any] | None = None,
        is_higher_intent: bool = False,
        conditional_questions_choices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a lead form.

        Args:
            page_id: Facebook page ID.
            name: Form name shown in Ads Manager and Lead Center.
            questions: Ordered list of question dicts. Standard
                types (``FULL_NAME``, ``EMAIL``, ``PHONE_NUMBER``,
                ``COMPANY_NAME``, ``JOB_TITLE``, ``CITY``, ``STATE``,
                ``ZIP_CODE``, ``COUNTRY``, ``DATE_OF_BIRTH``) only
                need ``type``; ``CUSTOM`` questions require ``key``,
                ``label``, and (for dropdowns) ``options``.
            privacy_policy_url: HTTPS URL of the advertiser's
                privacy policy. Required by Meta policy.
            follow_up_action_url: Optional redirect URL shown after
                submission. Omit for Meta's default confirmation.
            locale: Optional form locale (e.g. ``"ja_JP"``).
            context_card: Optional intro / welcome screen shown
                before the form. Expected shape:
                ``{"title": "...", "content": "...",
                "style": "PARAGRAPH_STYLE" | "LIST_STYLE",
                "cover_photo_id": "..."}``. Meta lifts conversion
                rates measurably when an intro is supplied.
            thank_you_page: Optional custom completion screen with
                a CTA. Expected shape (subset):
                ``{"title": "...", "body": "...",
                "button_type": "VIEW_WEBSITE" | "CALL_BUSINESS" |
                "MESSAGE_BUSINESS" | "DOWNLOAD" | "DOWNLOAD_APP",
                "website_url": "...", "button_text": "..."}``.
                Replaces ``follow_up_action_url``'s simple redirect.
            is_higher_intent: When ``True``, Meta renders a 3-step
                form (input → review → submit) which trims junk
                submissions at the cost of total leads volume.
                Default ``False`` (single-step standard form).
            conditional_questions_choices: Branching logic — list of
                entries that, given a prior question's value, choose
                which question to ask next. Each entry's expected
                shape: ``{"question": "<key>", "value": "<choice>",
                "next_question_key": "<key>"}``. Mureo passes the
                value through unchanged; Meta validates the keys
                refer to real questions.

        Returns:
            Created lead form info dict.
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
        if context_card is not None:
            data["context_card"] = json.dumps(context_card)
        if thank_you_page is not None:
            data["thank_you_page"] = json.dumps(thank_you_page)
        if is_higher_intent:
            data["is_higher_intent"] = True
        if conditional_questions_choices is not None:
            data["conditional_questions_choices"] = json.dumps(
                conditional_questions_choices
            )

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

    async def export_leads_to_csv(
        self,
        form_id: str,
        output_path: Path,
        *,
        limit: int = 1000,
        field_order: list[str] | None = None,
    ) -> int:
        """Fetch all leads for a form and write them to a CSV file.

        The header row is ``["id", "created_time", *field_keys]``.
        ``field_keys`` is derived from the form's declared questions
        in declared order — for standard questions without an
        explicit ``key`` (the common case) Meta's wire format uses
        the lowercased ``type`` (``"EMAIL"`` → ``"email"``), so the
        helper aligns column names with ``field_data[].name``. Pass
        ``field_order`` to lock a different column order — useful
        when the operator wants a stable CRM-import schema
        regardless of future form edits.

        Pagination is followed automatically: the helper calls
        ``/{form_id}/leads?fields=…&limit=<limit>`` and keeps
        traversing ``paging.next`` cursors until no more pages
        remain, so a form with arbitrarily many leads completes in
        one call.

        CSV-injection defense: values starting with ``= + - @ \\t
        \\r`` are prefixed with a single quote before they reach the
        ``csv.writer``. Lead values are operator-controlled
        downstream (the operator opens the export in Excel /
        Sheets / Numbers), so the prefix prevents user-supplied
        text becoming a live formula. Multi-value answers are
        joined with ``" | "`` so a comma inside one value does not
        get confused with a value separator (``csv.writer`` quotes
        the whole cell, but the prior format collapsed multi-values
        into a single comma-joined string which was ambiguous).

        Lead values are sensitive (PII): nothing from the lead's
        ``field_data`` is ever surfaced in mureo's log output. Only
        the row count, form_id, and path make it to the info log.

        Args:
            form_id: Lead form ID.
            output_path: File path for the CSV. Parent directory is
                auto-created. UTF-8 encoded; existing files are
                overwritten.
            limit: Max leads to fetch per Graph API call. Default
                1000 (Meta's per-call ceiling). The helper still
                fetches every lead via pagination — this only
                controls page size.
            field_order: Optional explicit list of question keys to
                drive the column order. Overrides the form's
                declared question order.

        Returns:
            Number of lead rows written (excluding the header).
        """
        form = await self.get_lead_form(form_id)
        if field_order is None:
            field_order = []
            for q in form.get("questions", []):
                # Meta's wire format for ``field_data[].name`` uses
                # the lowercased standard type (e.g. ``"EMAIL"`` →
                # ``"email"``) when the form question has no explicit
                # ``key``. CUSTOM questions always have a ``key``.
                key = q.get("key") or q.get("type", "").lower()
                if key:
                    field_order.append(key)

        # Page through /{form_id}/leads until paging.next is absent.
        # Meta returns a fully-qualified ``paging.next`` URL, but
        # ``_get`` always prepends ``BASE_URL`` so an absolute URL
        # would double-prefix. Extract the ``after`` cursor instead
        # and re-issue with the same relative path.
        all_leads: list[dict[str, Any]] = []
        path: str = f"/{form_id}/leads"
        params: dict[str, Any] = {"fields": _LEAD_FIELDS, "limit": limit}
        while True:
            result = await self._get(path, params)
            all_leads.extend(result.get("data", []) or [])
            next_url = (result.get("paging", {}) or {}).get("next")
            if not next_url:
                break
            after_values = parse_qs(urlparse(next_url).query).get("after")
            if not after_values:
                # Paging cursor missing in a non-standard ``next`` —
                # bail out rather than loop forever.
                break
            params = {**params, "after": after_values[0]}

        header = ["id", "created_time", *field_order]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for lead in all_leads:
                field_lookup = {
                    fd.get("name", ""): _csv_safe(
                        " | ".join(fd.get("values", []) or [])
                    )
                    for fd in lead.get("field_data", [])
                }
                row = [
                    _csv_safe(lead.get("id", "")),
                    _csv_safe(lead.get("created_time", "")),
                    *[field_lookup.get(key, "") for key in field_order],
                ]
                writer.writerow(row)

        # PII intentionally not logged — only the count.
        logger.info(
            "Lead CSV export: form_id=%s, rows=%d, path=%s",
            form_id,
            len(all_leads),
            output_path,
        )
        return len(all_leads)
