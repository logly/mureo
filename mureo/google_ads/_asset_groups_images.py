"""Performance Max asset-group image swap (#626).

The write half of the image surface whose read lives in
:mod:`mureo.google_ads._asset_groups`. Swapping one image of an asset
group is the same 1:1 exchange #590 shipped for text — one image out, one
image in, the per-field-type asset count unchanged.

Two situations, one tool
------------------------
The replacement is either an image the account already holds (an asset
id) or one that is still a file on the operator's disk. Which of the two
they are in is mureo's problem, not theirs: both arrive at
:meth:`_AssetGroupImagesMixin.replace_asset_group_image_asset`, which
resolves ``new_image_path`` into an asset id by uploading it and then
runs the identical swap. There is exactly one write path below the
resolution step.

Why the swap is only two operations
-----------------------------------
Unlike a text swap, nothing has to be *created* inside the mutate: an
image asset exists before the asset group can point at it, either because
it already did or because the upload just made it. So the atomic request
is create-link then remove-link — creates first, for the same reason #590
gives. An asset group has a per-field-type minimum
(``AssetGroupError.NOT_ENOUGH_MARKETING_IMAGE_ASSET`` and its square and
logo twins), so a removal issued on its own can be refused, and if it were
not refused the split would leave the asset group short between the two
round trips. ``partial_failure`` is deliberately left off.

The upload is a separate request by necessity — it reuses the validated
``upload_image_asset`` path rather than restating its guards — so
everything that can be checked is checked *before* it runs: the link
being replaced, the duplicate-link rule, and the field type's dimension
rule. What remains after a successful upload is the mutate itself; if
that is refused, the account is left holding an unlinked (and therefore
non-serving) image asset, and the error says so.

References:
https://developers.google.com/google-ads/api/performance-max/asset-requirements
https://developers.google.com/google-ads/api/docs/assets/working-with-assets
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from google.ads.googleads.errors import GoogleAdsException

from mureo._image_validation import read_image_dimensions, validate_image_file
from mureo.google_ads._asset_groups import (
    PMAX_IMAGE_FIELD_TYPES,
    _result_resource_name,
    _validate_image_dimensions,
    _validate_image_field_type,
)
from mureo.google_ads._enum_names import map_enum_name
from mureo.google_ads._gaql_validator import validate_static_query
from mureo.google_ads._media import (
    _GOOGLE_ALLOWED_IMAGE_EXTENSIONS,
    _GOOGLE_MAX_IMAGE_SIZE_BYTES,
)
from mureo.google_ads.client import _wrap_mutate_error
from mureo.google_ads.mappers import ASSET_TYPE_MAP

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)

#: ``AssetGroupError`` codes that mean "this would leave the asset group
#: below its image minimum". Only three of the five field types have one:
#: ``AssetGroupErrorEnum`` defines no floor for PORTRAIT_MARKETING_IMAGE or
#: LANDSCAPE_LOGO, because Performance Max does not require either.
_NOT_ENOUGH_IMAGE_ASSET_ERRORS: tuple[str, ...] = (
    "NOT_ENOUGH_MARKETING_IMAGE_ASSET",
    "NOT_ENOUGH_SQUARE_MARKETING_IMAGE_ASSET",
    "NOT_ENOUGH_LOGO_ASSET",
)

#: ``ImageError`` codes that mean "this picture is the wrong shape or size
#: for the slot". mureo checks that itself whenever it can read the
#: dimensions, so these only arrive for a format it cannot probe (a GIF).
#: Translated rather than passed through, because the operator's next step
#: is a different image and the raw code does not say which one.
_IMAGE_CONSTRAINT_ERRORS: tuple[str, ...] = (
    "ASPECT_RATIO_NOT_ALLOWED",
    "IMAGE_TOO_SMALL",
    "IMAGE_CONSTRAINTS_VIOLATED",
    "UNEXPECTED_SIZE",
)

_ASSET_LOOKUP_QUERY = """
            SELECT
                asset.id,
                asset.name,
                asset.type,
                asset.image_asset.full_size.url,
                asset.image_asset.full_size.width_pixels,
                asset.image_asset.full_size.height_pixels
            FROM asset
"""


def _validate_image_source(params: dict[str, Any]) -> tuple[str, str]:
    """Return ``("asset_id" | "path", value)`` for the replacement image.

    Exactly one of the two must be given. Refusing both together is not
    pedantry: with both accepted, one of them would be silently ignored
    and the asset group would end up carrying an image the operator did
    not choose.
    """
    asset_id = params.get("new_asset_id")
    path = params.get("new_image_path")
    given = [
        (kind, str(value))
        for kind, value in (("asset_id", asset_id), ("path", path))
        if isinstance(value, str) and value.strip()
    ]
    if len(given) != 1:
        raise ValueError(
            "Supply exactly one of new_asset_id (an image the account "
            "already holds — see google_ads_image_assets_list) or "
            "new_image_path (a local file to upload). "
            f"Got {len(given)}."
        )
    return given[0]


def _image_swap_result(
    responses: Any,
    *,
    asset_group_id: str,
    field_type: str,
    new: dict[str, Any],
    old: dict[str, Any],
    removed_link: str,
) -> dict[str, Any]:
    """Report both sides of the swap, as the mutate confirmed them."""
    return {
        "asset_group_id": asset_group_id,
        "field_type": field_type,
        "added": {
            "asset_id": new["asset_id"],
            "asset_name": new["asset_name"],
            "width_pixels": new["width_pixels"],
            "height_pixels": new["height_pixels"],
            "source": new["source"],
            "asset_group_asset": _result_resource_name(
                responses, 0, "asset_group_asset_result"
            ),
        },
        "removed": {
            "asset_id": old["asset_id"],
            "asset_name": old["asset_name"],
            "url": old["url"],
            "asset_group_asset": removed_link,
        },
        "note": (
            "Sent as one atomic GoogleAdsService.mutate (link the new image, "
            "unlink the old one), so the asset group never drops below the "
            "Performance Max minimum for this field type. Neither Asset was "
            "deleted; only the old link to this asset group was removed."
        ),
    }


class _AssetGroupImagesMixin:
    """Performance Max asset-group image swaps."""

    _customer_id: str
    _client: GoogleAdsClient

    # Stubs satisfied by the GoogleAdsApiClient base class.
    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]
    def _get_service(self, service_name: str) -> Any: ...
    async def _search(self, query: str) -> Any: ...
    @staticmethod
    def _has_error_code(  # type: ignore[empty-body]
        exc: GoogleAdsException, attr_name: str, error_name: str
    ) -> bool: ...

    if TYPE_CHECKING:
        # Provided at runtime by sibling mixins on GoogleAdsApiClient —
        # list_asset_group_assets by _AssetGroupsMixin, upload_image_asset
        # by _MediaMixin. Declared inside TYPE_CHECKING so mypy sees them
        # without a real body shadowing theirs in the MRO: _MediaMixin is
        # composed AFTER this mixin, so a plain stub here would win the
        # lookup and every image upload would silently return None.
        async def list_asset_group_assets(
            self,
            asset_group_id: str | None = None,
            campaign_id: str | None = None,
        ) -> list[dict[str, Any]]: ...

        async def upload_image_asset(
            self, file_path: str, name: str | None = None
        ) -> dict[str, Any]: ...

    @_wrap_mutate_error("Performance Max asset-group image replacement")
    async def replace_asset_group_image_asset(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Swap one image or logo of a Performance Max asset group.

        Links the replacement image under the same ``field_type`` and
        unlinks the old one, as a single atomic mutate, so the asset
        group's asset count for that field type never dips below the
        Performance Max minimum. Neither ``Asset`` is deleted.

        Required ``params`` keys: ``asset_group_id``, ``field_type`` (one
        of the five P-MAX image field types), ``old_asset_id`` (the
        ``asset_id`` reported by :meth:`list_asset_group_assets`), and
        **exactly one** of ``new_asset_id`` (an image the account already
        holds) or ``new_image_path`` (a local file, uploaded first).
        Optional: ``new_image_name``, the asset name for that upload.
        """
        asset_group_id = self._validate_id(
            str(params.get("asset_group_id", "")), "asset_group_id"
        )
        old_asset_id = self._validate_id(
            str(params.get("old_asset_id", "")), "old_asset_id"
        )
        field_type = _validate_image_field_type(params.get("field_type"))
        kind, value = _validate_image_source(params)
        if kind == "asset_id":
            # Validated here rather than at the lookup, so the duplicate-link
            # check below compares the same normalised id the lookup will use.
            value = self._validate_id(value, "new_asset_id")

        old = await self._find_linked_image_asset(
            asset_group_id,
            field_type,
            old_asset_id,
            value if kind == "asset_id" else "",
        )
        new = await self._resolve_new_image(kind, value, field_type, params)
        operations, removed_link = self._build_image_swap_operations(
            asset_group_id=asset_group_id,
            old_asset_id=old_asset_id,
            new_asset_id=new["asset_id"],
            field_type=field_type,
        )
        responses = self._send_image_swap(operations, field_type, new["source"])
        return _image_swap_result(
            responses,
            asset_group_id=asset_group_id,
            field_type=field_type,
            new=new,
            old=old,
            removed_link=removed_link,
        )

    async def _find_linked_image_asset(
        self,
        asset_group_id: str,
        field_type: str,
        old_asset_id: str,
        new_asset_id: str,
    ) -> dict[str, Any]:
        """Return the link being replaced, or raise with what IS linked.

        Also refuses an asset that is already linked under the same field
        type: Google rejects a duplicate link, and saying so here costs
        one read instead of a failed mutate the agent has to decode. A
        freshly uploaded asset cannot be linked yet, so ``new_asset_id``
        is empty on that path.
        """
        linked = [
            row
            for row in await self.list_asset_group_assets(asset_group_id=asset_group_id)
            if row["field_type"] == field_type
        ]
        if new_asset_id and any(row["asset_id"] == new_asset_id for row in linked):
            raise ValueError(
                f"Asset {new_asset_id} is already linked to asset group "
                f"{asset_group_id} as a {field_type}. Google Ads rejects a "
                f"duplicate link; supply a different image."
            )
        for row in linked:
            if row["asset_id"] == old_asset_id:
                return row
        available = ", ".join(
            f"{row['asset_id']} ({row['asset_name']!r})" for row in linked
        )
        raise ValueError(
            f"Asset {old_asset_id} is not linked to asset group "
            f"{asset_group_id} as a {field_type}. Linked {field_type} assets: "
            f"{available or 'none'}."
        )

    async def _resolve_new_image(
        self,
        kind: str,
        value: str,
        field_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Turn either entry point into one asset id, dimensions checked."""
        if kind == "asset_id":
            return await self._existing_image_asset(value, field_type)
        return await self._uploaded_image_asset(value, field_type, params)

    async def _existing_image_asset(
        self, new_asset_id: str, field_type: str
    ) -> dict[str, Any]:
        """Read an asset the account already holds, and vet it for the slot."""
        asset_id = self._validate_id(str(new_asset_id), "new_asset_id")
        query = validate_static_query(_ASSET_LOOKUP_QUERY)
        query += f"            WHERE asset.id = {asset_id}\n"
        rows = list(await self._search(query))
        if not rows:
            raise ValueError(
                f"Asset {asset_id} was not found in this account. Use "
                f"google_ads_image_assets_list to find an image asset id."
            )
        asset = rows[0].asset
        asset_type = map_enum_name(asset.type_, ASSET_TYPE_MAP)
        if asset_type != "IMAGE":
            raise ValueError(
                f"Asset {asset_id} is a {asset_type} asset, not an image. "
                f"{field_type} takes an image asset."
            )
        full_size = asset.image_asset.full_size
        width = int(full_size.width_pixels)
        height = int(full_size.height_pixels)
        _validate_image_dimensions(field_type, width, height)
        return {
            "asset_id": asset_id,
            "asset_name": str(asset.name),
            "width_pixels": width,
            "height_pixels": height,
            "source": "existing_asset",
        }

    async def _uploaded_image_asset(
        self, file_path: str, field_type: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate a local file, then upload it as a new image asset.

        The dimension check runs against the bytes on disk, before the
        upload, so a wrongly proportioned file costs no API call and
        leaves no unlinked asset in the account.
        """
        path = validate_image_file(
            file_path,
            max_size_bytes=_GOOGLE_MAX_IMAGE_SIZE_BYTES,
            max_size_label="5MB",
            allowed_extensions=_GOOGLE_ALLOWED_IMAGE_EXTENSIONS,
        )
        width, height = read_image_dimensions(path)
        _validate_image_dimensions(field_type, width, height)
        name = params.get("new_image_name")
        uploaded = await self.upload_image_asset(
            str(path), str(name) if isinstance(name, str) and name.strip() else None
        )
        return {
            "asset_id": str(uploaded["id"]),
            "asset_name": str(uploaded["name"]),
            "width_pixels": width or 0,
            "height_pixels": height or 0,
            "source": "uploaded",
        }

    def _build_image_swap_operations(
        self,
        *,
        asset_group_id: str,
        old_asset_id: str,
        new_asset_id: str,
        field_type: str,
    ) -> tuple[list[Any], str]:
        """Build the two operations, the link before the unlink.

        Returns them with the resource name of the link being removed,
        which the response cannot be relied on to echo back.
        """
        link_new = self._client.get_type("MutateOperation")
        link = link_new.asset_group_asset_operation.create
        link.asset_group = self._client.get_service(
            "AssetGroupService"
        ).asset_group_path(self._customer_id, asset_group_id)
        link.asset = self._client.get_service("AssetService").asset_path(
            self._customer_id, new_asset_id
        )
        link.field_type = getattr(self._client.enums.AssetFieldTypeEnum, field_type)

        removed_link = self._client.get_service(
            "AssetGroupAssetService"
        ).asset_group_asset_path(
            self._customer_id, asset_group_id, old_asset_id, field_type
        )
        unlink_old = self._client.get_type("MutateOperation")
        unlink_old.asset_group_asset_operation.remove = removed_link
        return [link_new, unlink_old], removed_link

    def _send_image_swap(
        self, operations: list[Any], field_type: str, source: str
    ) -> Any:
        """Issue the bulk mutate; translate the two refusals worth naming."""
        service = self._get_service("GoogleAdsService")
        try:
            response = service.mutate(
                customer_id=self._customer_id,
                mutate_operations=operations,
            )
        except GoogleAdsException as exc:
            # Each helper re-raises the refusal it recognises and returns
            # quietly otherwise, so an unrecognised failure falls through to
            # the bare `raise` and _wrap_mutate_error's curated detail.
            self._raise_asset_count_refusal(exc, field_type)
            self._raise_image_constraint_refusal(exc, field_type, source)
            raise
        return list(response.mutate_operation_responses)

    def _raise_asset_count_refusal(
        self, exc: GoogleAdsException, field_type: str
    ) -> None:
        """Re-raise a ``NOT_ENOUGH_*_ASSET`` refusal as advice."""
        shortfall = next(
            (
                code
                for code in _NOT_ENOUGH_IMAGE_ASSET_ERRORS
                if self._has_error_code(exc, "asset_group_error", code)
            ),
            None,
        )
        if shortfall is None:
            return
        # Class name / curated detail only, never the exception: its repr
        # carries the request metadata (developer token, authorization
        # header) — see mureo/google_ads/accounts.py (#603).
        logger.warning(
            "Performance Max %s image swap refused for asset-count reasons (%s)",
            field_type,
            shortfall,
        )
        raise RuntimeError(
            f"Google Ads refused the swap: the asset group would be left with "
            f"too few {field_type} assets ({shortfall}). The link and the "
            f"removal were sent as one atomic request, so the count does not "
            f"dip mid-flight — the asset group is already at or below the "
            f"Performance Max minimum for {field_type}. Add another "
            f"{field_type} to the asset group first, then retry."
        ) from exc

    def _raise_image_constraint_refusal(
        self, exc: GoogleAdsException, field_type: str, source: str
    ) -> None:
        """Re-raise an ``ImageError`` shape refusal as the slot's rule.

        Only reachable for a file mureo could not measure itself; anything
        it can probe was refused before the upload.
        """
        constraint = next(
            (
                code
                for code in _IMAGE_CONSTRAINT_ERRORS
                if self._has_error_code(exc, "image_error", code)
            ),
            None,
        )
        if constraint is None:
            return
        spec = PMAX_IMAGE_FIELD_TYPES[field_type]
        logger.warning(
            "Performance Max %s image swap refused on image constraints (%s)",
            field_type,
            constraint,
        )
        orphan = (
            " The uploaded asset is still in the account, unlinked and not serving."
            if source == "uploaded"
            else ""
        )
        raise RuntimeError(
            f"Google Ads refused the image for {field_type} ({constraint}). "
            f"That slot takes a {spec.ratio_label} image of at least "
            f"{spec.min_width}x{spec.min_height} pixels; Google recommends "
            f"{spec.recommended}. mureo could not read this file's dimensions "
            f"itself (GIF and unrecognised headers are not probed), so the "
            f"check happened server-side. Supply a correctly proportioned "
            f"image — mureo does not crop or resize." + orphan
        ) from exc
