"""Meta Ads targeting-discovery mixin.

Read-only resolution of Meta's internal targeting IDs (interests and
category classes) needed to build an ad-set ``targeting`` spec. Both
methods hit the API-root ``/search`` endpoint, which is NOT scoped to
the ad account id — unlike every other read path in this client.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Valid ``class`` values for the adTargetingCategory search. Named
# ``category_class`` at the tool/handler boundary because ``class`` is a
# Python keyword; the value is passed to Graph verbatim as ``class``.
_VALID_CATEGORY_CLASSES: frozenset[str] = frozenset(
    {
        "behaviors",
        "demographics",
        "life_events",
        "industries",
        "income",
        "family_statuses",
        "user_device",
        "user_os",
    }
)


class TargetingMixin:
    """Meta Ads targeting-discovery mixin (read-only).

    Resolves interest / behavior / demographic names to the internal IDs
    consumed by ``targeting.flexible_spec`` / ``interests``. Used via
    multiple inheritance with MetaAdsApiClient.
    """

    async def _get(  # type: ignore[empty-body]
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def search_targeting_interests(
        self,
        query: str,
        *,
        limit: int = 25,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search interest targeting IDs by keyword.

        Args:
            query: Interest keyword (e.g. "camping"). Must be non-empty
                (leading / trailing whitespace is stripped).
            limit: Maximum results to return. Default 25.
            locale: Optional Graph locale (e.g. "ja_JP"); passed through
                only when set so Meta returns localized names.

        Returns:
            List of interest records — each has id, name,
            audience_size_lower_bound, audience_size_upper_bound, path,
            topic, and related fields.

        Raises:
            ValueError: ``query`` is empty or whitespace-only.
        """
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("query must be a non-empty string")
        params: dict[str, Any] = {
            "type": "adinterest",
            "q": clean_query,
            "limit": limit,
        }
        if locale is not None:
            params["locale"] = locale
        result = await self._get("/search", params)
        return result.get("data", [])  # type: ignore[no-any-return]

    async def list_targeting_categories(
        self,
        category_class: str,
        *,
        limit: int = 200,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        """List a full targeting category catalogue.

        Args:
            category_class: One of the valid adTargetingCategory classes
                (behaviors, demographics, life_events, industries, income,
                family_statuses, user_device, user_os). Maps to Graph's
                ``class`` query param.
            limit: Maximum records to return. Default 200 — catalogues are
                finite but larger than keyword-search results.
            locale: Optional Graph locale (e.g. "ja_JP"); passed through
                only when set.

        Returns:
            List of category records — each has id, name,
            audience_size_lower_bound, audience_size_upper_bound, path,
            and an optional description.

        Raises:
            ValueError: ``category_class`` is not a recognized class.
                Fail fast at the boundary — Graph's error for a bad class
                is cryptic.
        """
        if category_class not in _VALID_CATEGORY_CLASSES:
            raise ValueError(
                f"Unknown category_class: {category_class!r}. Valid classes: "
                + ", ".join(sorted(_VALID_CATEGORY_CLASSES))
            )
        params: dict[str, Any] = {
            "type": "adTargetingCategory",
            "class": category_class,
            "limit": limit,
        }
        if locale is not None:
            params["locale"] = locale
        result = await self._get("/search", params)
        return result.get("data", [])  # type: ignore[no-any-return]
