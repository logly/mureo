"""Performance Max asset-group text assets (#590).

A Performance Max campaign has no ``ad_group_ad``, so every ad-text query
in this package returns nothing for it: its headlines, long headlines and
descriptions are assets linked to an **asset group** through
``asset_group_asset``. This mixin is the read and the write for those
three field types.

Why the write is a swap and not an update
-----------------------------------------
A text ``Asset`` is immutable — the string cannot be edited in place, and
``AssetGroupAssetService`` only re-points a link. Replacing one headline
is therefore three operations: create the new ``Asset``, create the
``AssetGroupAsset`` link that attaches it, remove the old link.

They are sent as **one** ``GoogleAdsService.mutate`` request, creates
first. An asset group has a per-field-type minimum asset count, so a
removal issued on its own can be refused with
``AssetGroupError.NOT_ENOUGH_HEADLINE_ASSET`` (and the long-headline /
description twins) — and if it were not refused, the split would leave
the asset group short between the two round trips. One request keeps the
net count unchanged and makes the swap atomic: either both halves land or
neither does. ``partial_failure`` is deliberately left off for the same
reason.

References:
https://developers.google.com/google-ads/api/performance-max/asset-groups
https://developers.google.com/google-ads/api/docs/assets/working-with-assets
https://developers.google.com/google-ads/api/performance-max/asset-requirements
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.ads.googleads.errors import GoogleAdsException

from mureo.google_ads._enum_names import (
    ASSET_FIELD_TYPE_MAP,
    ASSET_LINK_STATUS_MAP,
    map_enum_name,
)
from mureo.google_ads._gaql_validator import validate_static_query
from mureo.google_ads._rsa_validator import display_width
from mureo.google_ads.client import _wrap_mutate_error

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

#: The Performance Max text field types this module reads and swaps, mapped
#: to the display-width limit Google enforces on each. Width, not character
#: count: Google counts a full-width character as two, which is what
#: :func:`mureo.google_ads._rsa_validator.display_width` measures.
PMAX_TEXT_FIELD_TYPES: dict[str, int] = {
    "HEADLINE": 30,
    "LONG_HEADLINE": 90,
    "DESCRIPTION": 90,
}

#: ``AssetGroupError`` codes that mean "this would leave the asset group
#: below its minimum". Surfaced as an actionable message rather than a raw
#: API error, since the operator's next step differs from any other failure.
_NOT_ENOUGH_ASSET_ERRORS: tuple[str, ...] = (
    "NOT_ENOUGH_HEADLINE_ASSET",
    "NOT_ENOUGH_LONG_HEADLINE_ASSET",
    "NOT_ENOUGH_DESCRIPTION_ASSET",
)

#: Temporary id for the ``Asset`` created inside the bulk mutate. Negative
#: ids are the Google Ads mechanism for referring to a resource created
#: earlier in the same request.
_TEMP_ASSET_ID = "-1"

# The field-type filter is spelled out so the query stays a pure literal and
# can carry the validate_static_query marker. test_google_ads_asset_groups.py
# pins it against PMAX_TEXT_FIELD_TYPES so the two cannot drift.
_TEXT_ASSET_QUERY = """
            SELECT
                asset_group_asset.resource_name,
                asset_group_asset.field_type,
                asset_group_asset.status,
                asset.id,
                asset.text_asset.text,
                asset_group.id,
                asset_group.name,
                asset_group.campaign
            FROM asset_group_asset
            WHERE asset_group_asset.field_type IN ('HEADLINE', 'LONG_HEADLINE', 'DESCRIPTION')
"""


def _map_text_asset_row(row: Any) -> dict[str, Any]:
    """Map one ``asset_group_asset`` row, verbatim.

    ``campaign_id`` is the trailing segment of the asset group's own
    ``campaign`` resource name; the full resource name is returned beside
    it so the derivation is visible rather than implied.
    """
    link = row.asset_group_asset
    group = row.asset_group
    campaign_resource = str(group.campaign)
    return {
        "resource_name": str(link.resource_name),
        "field_type": map_enum_name(link.field_type, ASSET_FIELD_TYPE_MAP),
        "status": map_enum_name(link.status, ASSET_LINK_STATUS_MAP),
        "asset_id": str(row.asset.id),
        "text": str(row.asset.text_asset.text),
        "asset_group_id": str(group.id),
        "asset_group_name": str(group.name),
        "campaign_id": campaign_resource.rsplit("/", 1)[-1],
        "campaign_resource_name": campaign_resource,
    }


def _validate_field_type(value: Any) -> str:
    """Return ``value`` if it is one of the three P-MAX text field types."""
    if not isinstance(value, str) or value not in PMAX_TEXT_FIELD_TYPES:
        raise ValueError(
            f"Invalid field_type: {value!r}. Supported: "
            f"{', '.join(PMAX_TEXT_FIELD_TYPES)}."
        )
    return value


def _validate_text(value: Any, field_type: str) -> str:
    """Return ``value`` if it fits the field type's display-width limit."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("new_text is required and must be a non-empty string")
    limit = PMAX_TEXT_FIELD_TYPES[field_type]
    width = display_width(value)
    if width > limit:
        raise ValueError(
            f"{field_type} text exceeds the Google Ads limit: display width "
            f"{width} > {limit} (a full-width character counts as two)"
        )
    return value


def _result_resource_name(responses: Any, index: int, attribute: str) -> str:
    """Read one mutate result's resource name, or ``""`` when absent.

    The response is only read for reporting, so a shape mureo did not
    expect degrades to an empty string rather than masking a swap that
    the API already applied.
    """
    try:
        return str(getattr(responses[index], attribute).resource_name)
    except (AttributeError, IndexError, TypeError):  # pragma: no cover - defensive
        return ""


def _swap_result(
    responses: Any,
    *,
    asset_group_id: str,
    field_type: str,
    new_text: str,
    old: dict[str, Any],
    removed_link: str,
) -> dict[str, Any]:
    """Report both sides of the swap, as the mutate confirmed them."""
    new_asset_resource = _result_resource_name(responses, 0, "asset_result")
    return {
        "asset_group_id": asset_group_id,
        "field_type": field_type,
        "added": {
            "asset_id": new_asset_resource.rsplit("/", 1)[-1],
            "asset_resource_name": new_asset_resource,
            "text": new_text,
            "asset_group_asset": _result_resource_name(
                responses, 1, "asset_group_asset_result"
            ),
        },
        "removed": {
            "asset_id": old["asset_id"],
            "text": old["text"],
            "asset_group_asset": removed_link,
        },
        "note": (
            "Sent as one atomic GoogleAdsService.mutate (create asset, link "
            "it, unlink the old one), so the asset group never drops below "
            "the Performance Max minimum for this field type. The old asset "
            "itself still exists; only its link to this asset group was "
            "removed."
        ),
    }


class _AssetGroupsMixin:
    """Performance Max asset-group text reads and swaps."""

    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    async def _search(self, query: str) -> Any: ...
    @staticmethod
    def _has_error_code(  # type: ignore[empty-body]
        exc: GoogleAdsException, attr_name: str, error_name: str
    ) -> bool: ...

    async def list_asset_group_text_assets(
        self,
        asset_group_id: str | None = None,
        campaign_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List the text assets linked to Performance Max asset groups.

        Returns one entry per ``asset_group_asset`` link whose ``field_type``
        is HEADLINE, LONG_HEADLINE or DESCRIPTION — in the order the API
        returned them, with nothing summed, deduplicated or reordered. Two
        links carrying the same text are two entries, because that is what
        the asset group has.

        Args:
            asset_group_id: Restrict to one asset group.
            campaign_id: Restrict to the asset groups of one campaign.
        """
        query = validate_static_query(_TEXT_ASSET_QUERY)
        if asset_group_id:
            self._validate_id(asset_group_id, "asset_group_id")
            query += f"                AND asset_group.id = {asset_group_id}\n"
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += (
                "                AND asset_group.campaign = "
                f"'customers/{self._customer_id}/campaigns/{campaign_id}'\n"
            )
        rows = await self._search(query)
        return [_map_text_asset_row(row) for row in rows]

    @_wrap_mutate_error("Performance Max asset-group text replacement")
    async def replace_asset_group_text_asset(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Swap one headline / long headline / description of an asset group.

        Creates the replacement ``Asset``, links it, and unlinks the old
        asset — as a single atomic mutate, so the asset group's per-field-type
        asset count never dips below the Performance Max minimum. The old
        ``Asset`` itself is not deleted; only its link to this asset group is.

        Supported ``params`` keys (all required): ``asset_group_id``,
        ``field_type`` (HEADLINE / LONG_HEADLINE / DESCRIPTION),
        ``old_asset_id`` (the ``asset_id`` reported by
        :meth:`list_asset_group_text_assets`), ``new_text``.
        """
        asset_group_id = self._validate_id(
            str(params.get("asset_group_id", "")), "asset_group_id"
        )
        old_asset_id = self._validate_id(
            str(params.get("old_asset_id", "")), "old_asset_id"
        )
        field_type = _validate_field_type(params.get("field_type"))
        new_text = _validate_text(params.get("new_text"), field_type)

        old = await self._find_linked_text_asset(
            asset_group_id, field_type, old_asset_id, new_text
        )
        operations, removed_link = self._build_swap_operations(
            asset_group_id=asset_group_id,
            old_asset_id=old_asset_id,
            field_type=field_type,
            new_text=new_text,
        )
        responses = self._send_swap(operations, field_type)
        return _swap_result(
            responses,
            asset_group_id=asset_group_id,
            field_type=field_type,
            new_text=new_text,
            old=old,
            removed_link=removed_link,
        )

    async def _find_linked_text_asset(
        self,
        asset_group_id: str,
        field_type: str,
        old_asset_id: str,
        new_text: str,
    ) -> dict[str, Any]:
        """Return the link being replaced, or raise with what IS linked.

        Also refuses text that is already linked under the same field type:
        Google rejects a duplicate link, and saying so here costs one read
        instead of a failed mutate the agent has to decode.
        """
        linked = [
            row
            for row in await self.list_asset_group_text_assets(
                asset_group_id=asset_group_id
            )
            if row["field_type"] == field_type
        ]
        if any(row["text"] == new_text for row in linked):
            raise ValueError(
                f"{new_text!r} is already linked to asset group "
                f"{asset_group_id} as a {field_type}. Google Ads rejects a "
                f"duplicate link; supply different text."
            )
        for row in linked:
            if row["asset_id"] == old_asset_id:
                return row
        available = ", ".join(f"{row['asset_id']} ({row['text']!r})" for row in linked)
        raise ValueError(
            f"Asset {old_asset_id} is not linked to asset group "
            f"{asset_group_id} as a {field_type}. Linked {field_type} assets: "
            f"{available or 'none'}."
        )

    def _build_swap_operations(
        self,
        *,
        asset_group_id: str,
        old_asset_id: str,
        field_type: str,
        new_text: str,
    ) -> tuple[list[Any], str]:
        """Build the three operations, creates before the removal.

        Returns them with the resource name of the link being removed, which
        the response cannot be relied on to echo back.
        """
        temp_asset = self._client.get_service("AssetService").asset_path(
            self._customer_id, _TEMP_ASSET_ID
        )
        create_asset = self._client.get_type("MutateOperation")
        create_asset.asset_operation.create.resource_name = temp_asset
        create_asset.asset_operation.create.text_asset.text = new_text

        link_new = self._client.get_type("MutateOperation")
        link = link_new.asset_group_asset_operation.create
        link.asset_group = self._client.get_service(
            "AssetGroupService"
        ).asset_group_path(self._customer_id, asset_group_id)
        link.asset = temp_asset
        link.field_type = getattr(self._client.enums.AssetFieldTypeEnum, field_type)

        removed_link = self._client.get_service(
            "AssetGroupAssetService"
        ).asset_group_asset_path(
            self._customer_id, asset_group_id, old_asset_id, field_type
        )
        unlink_old = self._client.get_type("MutateOperation")
        unlink_old.asset_group_asset_operation.remove = removed_link
        return [create_asset, link_new, unlink_old], removed_link

    def _send_swap(self, operations: list[Any], field_type: str) -> Any:
        """Issue the bulk mutate; translate the asset-count refusal."""
        service = self._get_service("GoogleAdsService")
        try:
            response = service.mutate(
                customer_id=self._customer_id,
                mutate_operations=operations,
            )
        except GoogleAdsException as exc:
            shortfall = next(
                (
                    code
                    for code in _NOT_ENOUGH_ASSET_ERRORS
                    if self._has_error_code(exc, "asset_group_error", code)
                ),
                None,
            )
            if shortfall is None:
                raise
            # Class name / curated detail only, never the exception: its repr
            # carries the request metadata (developer token, authorization
            # header) — see mureo/google_ads/accounts.py (#603).
            logger.warning(
                "Performance Max %s swap refused for asset-count reasons (%s)",
                field_type,
                shortfall,
            )
            raise RuntimeError(
                f"Google Ads refused the swap: the asset group would be left "
                f"with too few {field_type} assets ({shortfall}). The new "
                f"asset, its link and the removal were sent as one atomic "
                f"request, so the count does not dip mid-flight — the asset "
                f"group is already at or below the Performance Max minimum "
                f"for {field_type}. Add {field_type} copy to the asset group "
                f"first, then retry the swap."
            ) from exc
        return list(response.mutate_operation_responses)
