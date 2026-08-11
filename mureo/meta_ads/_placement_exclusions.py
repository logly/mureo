"""Ad-set publisher exclusions mixin (#544).

Meta's analogue of Google's excluded placements / app categories is not a
separate resource: it lives inside the ad set's ``targeting`` spec, as
``excluded_publisher_categories`` (Audience Network app categories),
``excluded_publisher_list_ids`` (Audience Network block lists) and
``excluded_brand_safety_content_types``.

They are reachable through the general ``meta_ads_ad_sets_update``
``targeting`` argument, but only as an opaque blob — mureo could not tell
an exclusion change from any other targeting edit, so it could neither
record it with an observation window nor reverse it. This mixin names the
operation, which is what puts it on the same guarantees as the Google
exclusion surface.

Writes always go through :meth:`AdSetsMixin.update_ad_set`'s
read-modify-write merge: Meta replaces the WHOLE targeting spec on write,
so sending only the exclusion keys would silently clear geo_locations,
custom audiences and everything else.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The ad-set targeting keys that express "do not deliver here". Order is
#: the order they appear in a read result.
EXCLUSION_KEYS: tuple[str, ...] = (
    "excluded_publisher_categories",
    "excluded_publisher_list_ids",
    "excluded_brand_safety_content_types",
)


class PlacementExclusionsMixin:
    """Read and write an ad set's publisher / placement exclusions."""

    async def get_ad_set(  # type: ignore[empty-body]
        self, ad_set_id: str
    ) -> dict[str, Any]: ...

    async def update_ad_set(  # type: ignore[empty-body]
        self, ad_set_id: str, **kwargs: Any
    ) -> dict[str, Any]: ...

    async def get_excluded_placements(self, ad_set_id: str) -> dict[str, Any]:
        """Return the ad set's current exclusion lists.

        Every key is always present; a facet the ad set has never set reads
        as an empty list rather than being absent, so a caller (and the
        rollback reversal built from this) can tell "no exclusions" from
        "unknown" without a second lookup.
        """
        ad_set = await self.get_ad_set(ad_set_id)
        targeting = ad_set.get("targeting")
        if not isinstance(targeting, dict):
            targeting = {}
        result: dict[str, Any] = {"ad_set_id": ad_set_id}
        for key in EXCLUSION_KEYS:
            value = targeting.get(key)
            result[key] = list(value) if isinstance(value, list) else []
        return result

    async def set_excluded_placements(
        self,
        ad_set_id: str,
        *,
        excluded_publisher_categories: list[str] | None = None,
        excluded_publisher_list_ids: list[str] | None = None,
        excluded_brand_safety_content_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Replace the supplied exclusion facets on one ad set.

        Each supplied facet is set to exactly the list given — Meta has no
        append semantics here, so the caller sends the complete intended
        set. An omitted facet is left untouched; an explicit empty list
        clears that facet.
        """
        supplied = {
            "excluded_publisher_categories": excluded_publisher_categories,
            "excluded_publisher_list_ids": excluded_publisher_list_ids,
            "excluded_brand_safety_content_types": excluded_brand_safety_content_types,
        }
        delta = {key: value for key, value in supplied.items() if value is not None}
        if not delta:
            raise ValueError(
                "At least one of excluded_publisher_categories, "
                "excluded_publisher_list_ids or "
                "excluded_brand_safety_content_types must be supplied."
            )
        result = await self.update_ad_set(ad_set_id, targeting=delta)
        return {"ad_set_id": ad_set_id, "applied": delta, "result": result}
