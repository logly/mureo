"""Meta Ads Conversions API (CAPI) Mixin

Send conversion events to Meta Ads from the server side.
Browser pixel accuracy has decreased due to iOS ATT, etc.,
making CAPI essential for improving measurement accuracy.

Endpoint: POST https://graph.facebook.com/v21.0/{pixel_id}/events
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mureo.meta_ads._hash_utils import normalize_user_data

logger = logging.getLogger(__name__)


class ConversionsMixin:
    """Meta Ads Conversions API (CAPI)

    Used via multiple inheritance with MetaAdsApiClient.
    """

    async def _post(  # type: ignore[empty-body]
        self, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    async def send_event(
        self,
        pixel_id: str,
        events: list[dict[str, Any]],
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """Send conversion events.

        Args:
            pixel_id: Meta Pixel ID
            events: List of event data. Each event includes event_name,
                     event_time, action_source, and user_data.
            test_event_code: Test mode code (None for production)

        Returns:
            API response (events_received, fbtrace_id, etc.)

        Raises:
            RuntimeError: If the API request fails
        """
        # Auto-hash PII in user_data
        normalized_events = []
        for event in events:
            normalized = {**event}
            if "user_data" in normalized:
                normalized["user_data"] = normalize_user_data(normalized["user_data"])
            normalized_events.append(normalized)

        post_data: dict[str, Any] = {
            "data": json.dumps(normalized_events),
        }
        if test_event_code is not None:
            post_data["test_event_code"] = test_event_code

        logger.info(
            "CAPI event send: pixel_id=%s, events=%d, test=%s",
            pixel_id,
            len(events),
            test_event_code or "none",
        )

        return await self._post(f"/{pixel_id}/events", data=post_data)

    async def send_purchase_event(
        self,
        pixel_id: str,
        event_time: int,
        user_data: dict[str, Any],
        currency: str,
        value: float,
        content_ids: list[str] | None = None,
        event_source_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """Helper to send a purchase event.

        Args:
            pixel_id: Meta Pixel ID
            event_time: Event timestamp (UNIX timestamp)
            user_data: User information (em, ph, client_ip_address, etc.)
            currency: Currency code (USD, JPY, etc.)
            value: Purchase amount
            content_ids: List of product IDs
            event_source_url: Event source URL
            test_event_code: Test mode code

        Returns:
            API response
        """
        custom_data: dict[str, Any] = {
            "currency": currency,
            "value": value,
        }
        if content_ids is not None:
            custom_data["content_ids"] = content_ids

        event: dict[str, Any] = {
            "event_name": "Purchase",
            "event_time": event_time,
            "action_source": "website",
            "user_data": user_data,
            "custom_data": custom_data,
        }
        if event_source_url is not None:
            event["event_source_url"] = event_source_url

        return await self.send_event(pixel_id, [event], test_event_code=test_event_code)

    async def send_lead_event(
        self,
        pixel_id: str,
        event_time: int,
        user_data: dict[str, Any],
        event_source_url: str | None = None,
        test_event_code: str | None = None,
    ) -> dict[str, Any]:
        """Helper to send a lead event.

        Args:
            pixel_id: Meta Pixel ID
            event_time: Event timestamp (UNIX timestamp)
            user_data: User information
            event_source_url: Event source URL
            test_event_code: Test mode code

        Returns:
            API response
        """
        event: dict[str, Any] = {
            "event_name": "Lead",
            "event_time": event_time,
            "action_source": "website",
            "user_data": user_data,
        }
        if event_source_url is not None:
            event["event_source_url"] = event_source_url

        return await self.send_event(pixel_id, [event], test_event_code=test_event_code)
