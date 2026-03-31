"""B2B optimization suggestion mixin."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._analysis_constants import _INFORMATIONAL_PATTERNS

if TYPE_CHECKING:
    from google.ads.googleads.client import GoogleAdsClient

logger = logging.getLogger(__name__)


class _BtoBAnalysisMixin:
    """Mixin providing B2B optimization suggestion methods."""

    # Type declarations for attributes/methods provided by parent class
    _customer_id: str
    _client: GoogleAdsClient

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str: ...  # type: ignore[empty-body]

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None: ...
    async def get_search_terms_report(self, **kwargs: Any) -> list[dict[str, Any]]: ...  # type: ignore[empty-body]
    async def list_schedule_targeting(  # type: ignore[empty-body]
        self, campaign_id: str
    ) -> list[dict[str, Any]]: ...
    async def analyze_device_performance(  # type: ignore[empty-body]
        self, campaign_id: str, period: str = "LAST_30_DAYS"
    ) -> dict[str, Any]: ...

    # =================================================================
    # B2B optimization suggestions
    # =================================================================

    async def suggest_btob_optimizations(
        self,
        campaign_id: str,
        period: str = "LAST_30_DAYS",
    ) -> dict[str, Any]:
        """Run optimization checks for B2B businesses and generate improvement suggestions."""
        self._validate_id(campaign_id, "campaign_id")

        campaign = await self.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"Campaign ID {campaign_id} not found"}

        suggestions: list[dict[str, Any]] = []

        # 1. Ad schedule (non-business hours delivery check)
        await self._check_schedule_for_btob(campaign_id, suggestions)

        # 2. Device CPA disparity check
        await self._check_device_for_btob(campaign_id, period, suggestions)

        # 3. Informational search terms ratio check
        await self._check_search_terms_for_btob(campaign_id, period, suggestions)

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "period": period,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        }

    async def _check_schedule_for_btob(
        self,
        campaign_id: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """B2B optimization check for ad schedule."""
        try:
            schedules = await self.list_schedule_targeting(campaign_id)
        except Exception:
            return

        if not schedules:
            suggestions.append(
                {
                    "category": "schedule",
                    "priority": "HIGH",
                    "message": "No ad schedule is configured. "
                    "For B2B, concentrating delivery during business hours (weekdays 9-18) "
                    "can reduce wasted costs.",
                }
            )
            return

        # Weekend delivery check
        weekend_days = {"SATURDAY", "SUNDAY"}
        weekend_schedules = [
            s for s in schedules if s.get("day_of_week", "") in weekend_days
        ]
        if weekend_schedules:
            suggestions.append(
                {
                    "category": "schedule",
                    "priority": "MEDIUM",
                    "message": "Ads are being delivered on weekends. "
                    "In B2B, weekend conversion rates tend to be low. "
                    "Consider stopping delivery or lowering bid adjustments.",
                }
            )

    async def _check_device_for_btob(
        self,
        campaign_id: str,
        period: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """B2B optimization check for device CPA."""
        try:
            device_result = await self.analyze_device_performance(campaign_id, period)
        except Exception:
            return

        devices = device_result.get("devices", [])
        mobile = next(
            (d for d in devices if d["device_type"] in ("MOBILE", "2")),
            None,
        )
        desktop = next(
            (d for d in devices if d["device_type"] in ("DESKTOP", "1")),
            None,
        )

        if mobile and desktop:
            mobile_cpa = mobile.get("cpa")
            desktop_cpa = desktop.get("cpa")
            if (
                mobile_cpa
                and desktop_cpa
                and desktop_cpa > 0
                and mobile_cpa > desktop_cpa * 1.3
            ):
                suggestions.append(
                    {
                        "category": "device",
                        "priority": "MEDIUM",
                        "message": f"Mobile CPA ({mobile_cpa}) is higher than desktop ({desktop_cpa}). "
                        "In B2B, conversions tend to come more from desktop. "
                        "Consider lowering mobile bid adjustments.",
                    }
                )

        # Tablet zero-conversion check
        tablet = next(
            (d for d in devices if d["device_type"] in ("TABLET", "6")),
            None,
        )
        if tablet and tablet.get("conversions", 0) == 0 and tablet.get("cost", 0) > 0:
            suggestions.append(
                {
                    "category": "device",
                    "priority": "LOW",
                    "message": f"Tablet has 0 conversions with a cost of {tablet['cost']}. "
                    "In B2B, inquiries from tablets are rare. Consider excluding tablet delivery.",
                }
            )

    async def _check_search_terms_for_btob(
        self,
        campaign_id: str,
        period: str,
        suggestions: list[dict[str, Any]],
    ) -> None:
        """B2B optimization check for search terms."""
        try:
            search_terms = await self.get_search_terms_report(
                campaign_id=campaign_id, period=period
            )
        except Exception:
            return

        if not search_terms:
            return

        total = len(search_terms)
        informational_count = 0
        for t in search_terms:
            term = t.get("search_term", "").lower()
            if any(p in term for p in _INFORMATIONAL_PATTERNS):
                informational_count += 1

        if total > 0:
            ratio = informational_count / total * 100
            if ratio > 20:
                suggestions.append(
                    {
                        "category": "search_terms",
                        "priority": "MEDIUM",
                        "message": f"Informational search terms account for {round(ratio)}% of total. "
                        "In B2B, terms like explanatory or comparison queries "
                        "tend to have low conversion rates. Consider adding negative keywords.",
                    }
                )
