"""Negative placement (delivery-surface exclusion) operations mixin (#544).

Google Ads models "do not deliver here" as **negative criteria** on a
campaign or an ad group. Three criterion types make up the surface an
operator touches during Display / Demand-Gen placement hygiene:

- ``PLACEMENT`` — an excluded website / placement URL,
- ``MOBILE_APPLICATION`` — an excluded app,
- ``MOBILE_APP_CATEGORY`` — an excluded app category.

They are exposed here under one tool-facing vocabulary (``website`` /
``mobile_application`` / ``mobile_app_category``) so a batch can mix
types in a single call, which is how the work is actually done — and, in
turn, how the whole batch becomes one ``action_log`` entry and one
reversal.

Removal deliberately verifies before it mutates: the criterion ids it is
given must resolve to *negative placement criteria at the named level*.
An id that does not is skipped, never removed. Without that check the
reversal of an add would be a general "delete criterion by id" primitive
— which would also delete keywords.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import map_negative_placement

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

#: Tool-facing exclusion kind → (Google Ads criterion type, criterion
#: sub-message, field on that sub-message carrying the value). The criterion
#: types double as the GAQL type filter below; they are whitelisted literals,
#: never caller input.
EXCLUSION_KINDS: dict[str, tuple[str, str, str]] = {
    "website": ("PLACEMENT", "placement", "url"),
    "mobile_application": ("MOBILE_APPLICATION", "mobile_application", "app_id"),
    "mobile_app_category": (
        "MOBILE_APP_CATEGORY",
        "mobile_app_category",
        "mobile_app_category_constant",
    ),
}

#: Google Ads criterion type → tool-facing exclusion kind (the reverse map,
#: used when shaping read rows).
CRITERION_TYPE_TO_KIND: dict[str, str] = {
    spec[0]: kind for kind, spec in EXCLUSION_KINDS.items()
}

_TYPE_FILTER = ", ".join(f"'{spec[0]}'" for spec in EXCLUSION_KINDS.values())

#: Resource-name prefix for a mobile app category constant. A bare numeric id
#: is normalized onto it so operators can paste the id straight out of a
#: report without having to know the resource-name spelling.
_APP_CATEGORY_PREFIX = "mobileAppCategoryConstants/"

#: Row cap for the reads below — they allow account-wide, unscoped queries, so
#: an explicit LIMIT keeps a huge account from materializing without bound.
#: Matches ``_extensions_targeting._CRITERIA_READ_LIMIT``.
_PLACEMENT_READ_LIMIT = 1000


class _PlacementsMixin:
    """Campaign / ad-group negative placement criteria: list, add, remove."""

    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _resolve_level(params: dict[str, Any]) -> tuple[str, str]:
        """Return ``(level, scope_id)`` for a mutation, or raise.

        Exactly one of ``campaign_id`` / ``ad_group_id`` must be supplied.
        Accepting both would leave the level — and therefore the reversal's
        target — ambiguous; accepting neither would silently widen the write.
        """
        campaign_id = params.get("campaign_id")
        ad_group_id = params.get("ad_group_id")
        if bool(campaign_id) == bool(ad_group_id):
            raise ValueError(
                "Specify exactly one of campaign_id or ad_group_id "
                "(campaign-level and ad group-level exclusions are separate "
                "criteria)."
            )
        if campaign_id:
            return "campaign", str(campaign_id)
        return "ad_group", str(ad_group_id)

    @staticmethod
    def _criterion_id_of(resource_name: str) -> str:
        """``customers/1/campaignCriteria/100~555`` → ``'555'``."""
        return resource_name.rsplit("~", 1)[-1]

    @classmethod
    def _normalize_value(cls, kind: str, value: Any) -> str:
        """Validate one exclusion entry and return the API-shaped value."""
        if kind not in EXCLUSION_KINDS:
            raise ValueError(
                f"Unsupported exclusion type {kind!r}. Supported types: "
                f"{', '.join(sorted(EXCLUSION_KINDS))}."
            )
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"Exclusion of type {kind!r} has an empty value.")
        if kind != "mobile_app_category":
            return text
        if text.startswith(_APP_CATEGORY_PREFIX):
            return text
        if not text.isdigit():
            raise ValueError(
                f"mobile_app_category value {text!r} must be a numeric category "
                f"id or a '{_APP_CATEGORY_PREFIX}<id>' resource name."
            )
        return f"{_APP_CATEGORY_PREFIX}{text}"

    # -- reads -------------------------------------------------------------

    async def list_negative_placements(
        self,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List excluded websites / mobile apps / app categories.

        Covers both levels by default. Supplying ``ad_group_id`` narrows to
        that ad group (campaign-level negatives are a different resource and
        are not returned); supplying only ``campaign_id`` returns the
        campaign's own negatives plus those of its ad groups.
        """
        rows: list[dict[str, Any]] = []
        if not ad_group_id:
            rows.extend(await self._list_campaign_level(campaign_id))
        rows.extend(await self._list_ad_group_level(campaign_id, ad_group_id))
        return rows

    async def _list_campaign_level(
        self, campaign_id: str | None
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign_criterion.criterion_id,
                campaign_criterion.type,
                campaign_criterion.negative,
                campaign_criterion.placement.url,
                campaign_criterion.mobile_application.app_id,
                campaign_criterion.mobile_application.name,
                campaign_criterion.mobile_app_category.mobile_app_category_constant
            FROM campaign_criterion
            WHERE campaign_criterion.negative = true
                AND campaign_criterion.type IN ({_TYPE_FILTER})"""
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n                AND campaign.id = {campaign_id}"
        query += f"\n            LIMIT {_PLACEMENT_READ_LIMIT}"
        response = await self._search(query)  # type: ignore[attr-defined]
        return [
            map_negative_placement(
                row.campaign_criterion, "campaign", row.campaign, None
            )
            for row in response
        ]

    async def _list_ad_group_level(
        self, campaign_id: str | None, ad_group_id: str | None
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                ad_group.id,
                ad_group.name,
                ad_group_criterion.criterion_id,
                ad_group_criterion.type,
                ad_group_criterion.negative,
                ad_group_criterion.placement.url,
                ad_group_criterion.mobile_application.app_id,
                ad_group_criterion.mobile_application.name,
                ad_group_criterion.mobile_app_category.mobile_app_category_constant
            FROM ad_group_criterion
            WHERE ad_group_criterion.negative = true
                AND ad_group_criterion.type IN ({_TYPE_FILTER})"""
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n                AND campaign.id = {campaign_id}"
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
            query += f"\n                AND ad_group.id = {ad_group_id}"
        query += f"\n            LIMIT {_PLACEMENT_READ_LIMIT}"
        response = await self._search(query)  # type: ignore[attr-defined]
        return [
            map_negative_placement(
                row.ad_group_criterion, "ad_group", row.campaign, row.ad_group
            )
            for row in response
        ]

    # -- writes ------------------------------------------------------------

    @_wrap_mutate_error("negative placement addition")
    async def add_negative_placements(self, params: dict[str, Any]) -> dict[str, Any]:
        """Exclude websites / mobile apps / app categories in one batch.

        Returns the created ``criterion_id`` per input entry, which is what
        makes the whole batch reversible as a single unit.
        """
        level, scope_id = self._resolve_level(params)
        placements = params.get("placements") or []
        if not placements:
            raise ValueError("At least one placement exclusion must be specified")
        entries = [
            (
                str(item.get("type", "")),
                self._normalize_value(str(item.get("type", "")), item.get("value")),
            )
            for item in placements
        ]
        self._validate_id(
            scope_id, "campaign_id" if level == "campaign" else "ad_group_id"
        )
        results = (
            self._add_campaign_level(scope_id, entries)
            if level == "campaign"
            else self._add_ad_group_level(scope_id, entries)
        )
        created = [
            {
                "criterion_id": self._criterion_id_of(result.resource_name),
                "resource_name": result.resource_name,
                "type": kind,
                "value": value,
            }
            for result, (kind, value) in zip(results, entries, strict=False)
        ]
        key = "campaign_id" if level == "campaign" else "ad_group_id"
        return {
            "level": level,
            key: scope_id,
            "count": len(created),
            "created": created,
        }

    def _add_campaign_level(
        self, campaign_id: str, entries: list[tuple[str, str]]
    ) -> list[Any]:
        service = self._get_service("CampaignCriterionService")
        campaign = self._client.get_service("CampaignService").campaign_path(
            self._customer_id, campaign_id
        )
        operations = []
        for kind, value in entries:
            op = self._client.get_type("CampaignCriterionOperation")
            criterion = op.create
            criterion.campaign = campaign
            criterion.negative = True
            _, message, field = EXCLUSION_KINDS[kind]
            setattr(getattr(criterion, message), field, value)
            operations.append(op)
        response = service.mutate_campaign_criteria(
            customer_id=self._customer_id, operations=operations
        )
        return list(response.results)

    def _add_ad_group_level(
        self, ad_group_id: str, entries: list[tuple[str, str]]
    ) -> list[Any]:
        service = self._get_service("AdGroupCriterionService")
        ad_group = self._client.get_service("AdGroupService").ad_group_path(
            self._customer_id, ad_group_id
        )
        operations = []
        for kind, value in entries:
            op = self._client.get_type("AdGroupCriterionOperation")
            criterion = op.create
            criterion.ad_group = ad_group
            criterion.negative = True
            _, message, field = EXCLUSION_KINDS[kind]
            setattr(getattr(criterion, message), field, value)
            operations.append(op)
        response = service.mutate_ad_group_criteria(
            customer_id=self._customer_id, operations=operations
        )
        return list(response.results)

    async def _verify_removable(
        self, level: str, scope_id: str, requested: list[str]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Split ``requested`` into ids that ARE removable here, and the rest.

        This is the guard that keeps "remove by criterion_id" from being a
        general delete primitive: a criterion id is only removable if the
        live read reports it as a negative placement criterion at the same
        level. Everything else is returned as a skip reason.
        """
        existing = await self.list_negative_placements(
            campaign_id=scope_id if level == "campaign" else None,
            ad_group_id=scope_id if level == "ad_group" else None,
        )
        removable = {row["criterion_id"] for row in existing if row["level"] == level}
        verified = [cid for cid in requested if cid in removable]
        skipped = [
            {
                "criterion_id": cid,
                "reason": "not a negative placement criterion at this level",
            }
            for cid in requested
            if cid not in removable
        ]
        return verified, skipped

    @_wrap_mutate_error("negative placement removal")
    async def remove_negative_placements(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Lift exclusions by ``criterion_id``, in one batch.

        Every id is verified against the live criteria at the named level
        first; ids that are not negative placement criteria there are
        reported under ``skipped`` and never mutated.
        """
        level, scope_id = self._resolve_level(params)
        requested = [str(cid) for cid in (params.get("criterion_ids") or [])]
        if not requested:
            raise ValueError("At least one criterion_id must be specified")
        for criterion_id in requested:
            self._validate_id(criterion_id, "criterion_id")
        self._validate_id(
            scope_id, "campaign_id" if level == "campaign" else "ad_group_id"
        )
        verified, skipped = await self._verify_removable(level, scope_id, requested)
        removed: list[dict[str, Any]] = []
        if verified:
            results = (
                self._remove_campaign_level(scope_id, verified)
                if level == "campaign"
                else self._remove_ad_group_level(scope_id, verified)
            )
            removed = [
                {
                    "criterion_id": self._criterion_id_of(result.resource_name),
                    "resource_name": result.resource_name,
                }
                for result in results
            ]
        key = "campaign_id" if level == "campaign" else "ad_group_id"
        return {
            "level": level,
            key: scope_id,
            "removed": removed,
            "removed_count": len(removed),
            "skipped": skipped,
        }

    def _remove_campaign_level(
        self, campaign_id: str, criterion_ids: list[str]
    ) -> list[Any]:
        service = self._get_service("CampaignCriterionService")
        path = self._client.get_service("CampaignCriterionService")
        operations = []
        for criterion_id in criterion_ids:
            op = self._client.get_type("CampaignCriterionOperation")
            op.remove = path.campaign_criterion_path(
                self._customer_id, campaign_id, criterion_id
            )
            operations.append(op)
        response = service.mutate_campaign_criteria(
            customer_id=self._customer_id, operations=operations
        )
        return list(response.results)

    def _remove_ad_group_level(
        self, ad_group_id: str, criterion_ids: list[str]
    ) -> list[Any]:
        service = self._get_service("AdGroupCriterionService")
        path = self._client.get_service("AdGroupCriterionService")
        operations = []
        for criterion_id in criterion_ids:
            op = self._client.get_type("AdGroupCriterionOperation")
            op.remove = path.ad_group_criterion_path(
                self._customer_id, ad_group_id, criterion_id
            )
            operations.append(op)
        response = service.mutate_ad_group_criteria(
            customer_id=self._customer_id, operations=operations
        )
        return list(response.results)
