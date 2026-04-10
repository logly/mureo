"""Display Ads operations mixin (Responsive Display Ads).

Separated from `_ads.py` to keep that file focused on Responsive Search
Ad operations and to avoid the file growing past the project's 800-line
soft limit.

This module provides `create_display_ad`, which:

1. Validates RDA inputs (texts, counts, URL) without any network I/O.
2. Verifies the target ad group belongs to a DISPLAY campaign via a
   single GAQL query (fail-fast for the most common misuse).
3. Uploads the marketing/square/logo image files. Tracks every
   uploaded asset so partial-upload failures can report the orphans
   for manual cleanup.
4. Builds and submits the AdGroupAd mutation, with the gRPC call
   wrapped in run_in_executor so it does not block the event loop.

If the upload phase fails, the orphaned (already-uploaded) asset
resource names are surfaced both in the raised exception and in the
WARN log so the caller can clean them up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._rda_validator import (
    RDAValidationResult,
    validate_rda_inputs,
)
from mureo.google_ads.client import _wrap_mutate_error

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class RDAUploadError(RuntimeError):
    """Raised when image upload phase of create_display_ad fails.

    Carries the resource names of any assets that were uploaded
    successfully before the failure, so callers can clean them up.
    """

    def __init__(self, message: str, orphaned_assets: list[str]) -> None:
        self.orphaned_assets = orphaned_assets
        if orphaned_assets:
            message = (
                f"{message} (orphaned uploaded assets: "
                f"{', '.join(orphaned_assets)})"
            )
        super().__init__(message)


class _DisplayAdsMixin:
    """Responsive Display Ad creation mixin."""

    _customer_id: str
    _client: GoogleAdsClient

    # Stubs satisfied by the GoogleAdsApiClient base class
    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    def _get_service(self, service_name: str) -> Any: ...

    async def _search(self, query: str) -> Any: ...

    if TYPE_CHECKING:
        # upload_image_asset is provided at runtime by _MediaMixin via
        # multiple inheritance on GoogleAdsApiClient. Declared in a
        # TYPE_CHECKING block so it is visible to mypy without
        # shadowing the real implementation in the MRO.
        async def upload_image_asset(
            self, file_path: str, name: str | None = None
        ) -> dict[str, Any]: ...

    async def _verify_ad_group_is_display(self, ad_group_id: str) -> None:
        """Raise ValueError if the given ad group is not in a DISPLAY campaign.

        Single GAQL query, no mutation. Used as a fail-fast pre-check
        before any image upload happens, to avoid leaving orphaned
        assets when the user accidentally targets a search ad group.
        """
        query = (
            "SELECT campaign.advertising_channel_type "
            "FROM ad_group "
            f"WHERE ad_group.id = {ad_group_id}"
        )
        try:
            response = await self._search(query)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError(f"Failed to verify ad group {ad_group_id}: {exc}") from exc

        for row in response:
            channel_type = row.campaign.advertising_channel_type
            display_value = self._client.enums.AdvertisingChannelTypeEnum.DISPLAY
            if channel_type != display_value:
                raise ValueError(
                    f"ad_group_id {ad_group_id} does not belong to a DISPLAY "
                    f"campaign (channel_type={channel_type}). create_display_ad "
                    f"requires a DISPLAY campaign."
                )
            return
        raise ValueError(f"ad_group_id {ad_group_id} not found")

    async def _upload_images_or_raise(
        self,
        marketing_paths: list[str],
        square_paths: list[str],
        logo_paths: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Upload all image assets, tracking orphans on partial failure."""
        uploaded: list[dict[str, Any]] = []
        marketing_assets: list[dict[str, Any]] = []
        square_assets: list[dict[str, Any]] = []
        logo_assets: list[dict[str, Any]] = []
        try:
            for path in marketing_paths:
                asset = await self.upload_image_asset(path)
                uploaded.append(asset)
                marketing_assets.append(asset)
            for path in square_paths:
                asset = await self.upload_image_asset(path)
                uploaded.append(asset)
                square_assets.append(asset)
            for path in logo_paths:
                asset = await self.upload_image_asset(path)
                uploaded.append(asset)
                logo_assets.append(asset)
        except Exception as exc:
            orphans = [a["resource_name"] for a in uploaded]
            logger.warning(
                "RDA image upload failed after %d successful uploads. "
                "Orphaned assets in account: %s",
                len(uploaded),
                orphans,
            )
            raise RDAUploadError(
                f"RDA image upload failed: {exc}",
                orphaned_assets=orphans,
            ) from exc
        return marketing_assets, square_assets, logo_assets

    def _build_rda_operation(
        self, ad_group_id: str, validated: RDAValidationResult
    ) -> Any:
        """Construct the AdGroupAdOperation for an RDA mutation.

        Pure proto-construction, no I/O. Splitting this out keeps
        create_display_ad readable and lets us add unit tests around
        proto field assignment if needed.
        """
        op = self._client.get_type("AdGroupAdOperation")
        ad_group_ad = op.create
        ad_group_ad.ad_group = self._client.get_service("AdGroupService").ad_group_path(
            self._customer_id, ad_group_id
        )
        ad_group_ad.status = self._client.enums.AdGroupAdStatusEnum.PAUSED
        ad = ad_group_ad.ad

        # Headlines (short, repeated)
        for h in validated.headlines:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = h
            ad.responsive_display_ad.headlines.append(text_asset)

        # Long headline (singular composite proto field — must set
        # sub-fields directly, not assign a new message via `=`).
        ad.responsive_display_ad.long_headline.text = validated.long_headline

        # Descriptions (repeated)
        for d in validated.descriptions:
            text_asset = self._client.get_type("AdTextAsset")
            text_asset.text = d
            ad.responsive_display_ad.descriptions.append(text_asset)

        ad.responsive_display_ad.business_name = validated.business_name

        # Marketing images (repeated)
        for asset_resource in validated.marketing_image_asset_resource_names:
            image_asset = self._client.get_type("AdImageAsset")
            image_asset.asset = asset_resource
            ad.responsive_display_ad.marketing_images.append(image_asset)

        # Square marketing images (repeated)
        for asset_resource in validated.square_marketing_image_asset_resource_names:
            image_asset = self._client.get_type("AdImageAsset")
            image_asset.asset = asset_resource
            ad.responsive_display_ad.square_marketing_images.append(image_asset)

        # Logo images (repeated, optional)
        for asset_resource in validated.logo_image_asset_resource_names:
            image_asset = self._client.get_type("AdImageAsset")
            image_asset.asset = asset_resource
            ad.responsive_display_ad.logo_images.append(image_asset)

        ad.final_urls.append(validated.final_url)
        return op

    @_wrap_mutate_error("display ad creation")
    async def create_display_ad(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Responsive Display Ad (RDA).

        Pre-validates inputs, verifies the target ad group is in a
        DISPLAY campaign, uploads any local image files, then submits
        the ad. If image upload fails partway through, the resource
        names of already-uploaded assets are reported in the raised
        RDAUploadError so they can be cleaned up.

        Args:
            params: RDA parameters.
                ad_group_id: Target ad group (required, must be DISPLAY).
                headlines: List of short headlines (1-5, each <=30 width).
                long_headline: Single long headline (<=90 width, required).
                descriptions: List of descriptions (1-5, each <=90 width).
                business_name: Business name (<=25 width, required).
                marketing_image_paths: Local file paths for marketing
                    images (1.91:1, 1-15 files). Uploaded automatically.
                square_marketing_image_paths: Local file paths for
                    square marketing images (1:1, 1-15 files).
                logo_image_paths: Optional local file paths for logo
                    images (up to 5).
                final_url: Landing page URL (required, https/http).
        """
        ad_group_id = params["ad_group_id"]
        self._validate_id(ad_group_id, "ad_group_id")

        marketing_paths = list(params.get("marketing_image_paths", []))
        square_paths = list(params.get("square_marketing_image_paths", []))
        logo_paths = list(params.get("logo_image_paths") or [])
        headlines = list(params.get("headlines", []))
        long_headline = params.get("long_headline", "")
        descriptions = list(params.get("descriptions", []))
        business_name = params.get("business_name", "")
        final_url = params.get("final_url", "")

        # Step 1: Pre-validate texts and counts using placeholder
        # resource names. This catches text/count errors before any
        # network call.
        validate_rda_inputs(
            headlines=headlines,
            long_headline=long_headline,
            descriptions=descriptions,
            business_name=business_name,
            marketing_image_asset_resource_names=["__placeholder__"]
            * len(marketing_paths),
            square_marketing_image_asset_resource_names=["__placeholder__"]
            * len(square_paths),
            logo_image_asset_resource_names=(
                ["__placeholder__"] * len(logo_paths) if logo_paths else None
            ),
            final_url=final_url,
        )

        # Step 2: Verify the target ad group is actually in a DISPLAY
        # campaign before uploading anything. Avoids orphaned assets in
        # the most common misuse (wrong ad group selected).
        await self._verify_ad_group_is_display(ad_group_id)

        # Step 3: Upload images, tracking orphans on partial failure.
        marketing_assets, square_assets, logo_assets = (
            await self._upload_images_or_raise(
                marketing_paths, square_paths, logo_paths
            )
        )

        # Step 4: Build the validated result with real resource names.
        # No re-validation of texts/counts is needed — we already
        # validated above and the uploads do not change those.
        validated = RDAValidationResult(
            headlines=tuple(headlines[:5]),
            long_headline=long_headline,
            descriptions=tuple(descriptions[:5]),
            business_name=business_name,
            marketing_image_asset_resource_names=tuple(
                a["resource_name"] for a in marketing_assets
            ),
            square_marketing_image_asset_resource_names=tuple(
                a["resource_name"] for a in square_assets
            ),
            logo_image_asset_resource_names=tuple(
                a["resource_name"] for a in logo_assets
            ),
            final_url=final_url,
        )

        # Step 5: Build and submit the mutation. Wrap the gRPC call in
        # run_in_executor so it does not block the event loop.
        op = self._build_rda_operation(ad_group_id, validated)
        ad_group_ad_service = self._get_service("AdGroupAdService")

        def _do_mutate() -> Any:
            return ad_group_ad_service.mutate_ad_group_ads(
                customer_id=self._customer_id,
                operations=[op],
            )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, _do_mutate)
        except Exception as exc:
            # Surface the orphaned assets so they can be cleaned up
            orphans = (
                [a["resource_name"] for a in marketing_assets]
                + [a["resource_name"] for a in square_assets]
                + [a["resource_name"] for a in logo_assets]
            )
            logger.warning(
                "RDA mutation failed after uploading %d assets. "
                "Orphaned assets in account: %s",
                len(orphans),
                orphans,
            )
            raise RDAUploadError(
                f"RDA creation failed: {exc}",
                orphaned_assets=orphans,
            ) from exc

        return {
            "resource_name": response.results[0].resource_name,
            "uploaded_assets": {
                "marketing": [a["resource_name"] for a in marketing_assets],
                "square_marketing": [a["resource_name"] for a in square_assets],
                "logo": [a["resource_name"] for a in logo_assets],
            },
        }
