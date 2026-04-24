"""Meta Ads tool definitions — Conversions API (CAPI).

Tool descriptions follow ``docs/tdqs-style-guide.md``. The Conversions
API lets advertisers send server-side events directly to Meta rather
than relying on the browser pixel. Server events are attributed to the
same pixel and appear alongside browser events in reporting. mureo
hashes PII fields (em, ph, fn, ln, zip) with SHA-256 before
transmission as required by Meta.
"""

from __future__ import annotations

from mcp.types import Tool

# Reusable parameter fragments.
_ACCOUNT_ID_PARAM = {
    "type": "string",
    "description": (
        "Meta Ads account ID in the format 'act_XXXXXXXXXX' (e.g. "
        "'act_1234567890'). Optional — falls back to META_ADS_ACCOUNT_ID "
        "from the configured credentials. The leading 'act_' prefix is "
        "required."
    ),
}

_PIXEL_ID_PARAM = {
    "type": "string",
    "description": (
        "Meta Pixel ID the event is attributed to. Find via "
        "meta_ads.pixels.list. CAPI events flow into the same pixel as "
        "browser events; dedupe happens on event_id if one is supplied "
        "in user_data / custom_data."
    ),
}

_USER_DATA_DESCRIPTION = (
    "User identifying fields for attribution. Supported keys: em "
    "(email), ph (phone), fn (first_name), ln (last_name), zp (zip), "
    "ct (city), st (state), country, external_id, client_ip_address, "
    "client_user_agent, fbc (click ID), fbp (browser ID). mureo hashes "
    "em / ph / fn / ln / zp / ct / st / country / external_id with "
    "SHA-256 before sending — pass raw PII; do not pre-hash."
)

_TEST_EVENT_CODE_DESCRIPTION = (
    "Meta Events Manager test_event_code. When set, the event is "
    "routed to the test event stream visible in Events Manager instead "
    "of production reporting. Use for validation; drop the field once "
    "verified. Get the code from Events Manager → Test Events tab."
)

_EVENT_SOURCE_URL_DESCRIPTION = (
    "Fully-qualified URL where the event occurred. Required by Meta "
    "for action_source='website' events; recommended for any "
    "browser-triggered CAPI event to improve attribution match rate."
)

TOOLS: list[Tool] = [
    # === Conversions (CAPI) ===
    Tool(
        name="meta_ads.conversions.send",
        description=(
            "Sends a batch of arbitrary conversion events to the Meta "
            "Conversions API. Returns Meta's response including "
            "events_received and messages (warnings for missing fields). "
            "Mutating on Meta's side — events become part of the pixel's "
            "attribution stream. For common event types prefer the "
            "dedicated meta_ads.conversions.send_purchase or "
            "send_lead helpers, which enforce required fields and fewer "
            "mistakes. For other event names (AddToCart, InitiateCheckout, "
            "CompleteRegistration, custom events) use this generic tool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": _PIXEL_ID_PARAM,
                "events": {
                    "type": "array",
                    "minItems": 1,
                    "description": (
                        "Event payloads to send. Meta batches are "
                        "typically ≤1000 events per call."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_name": {
                                "type": "string",
                                "description": (
                                    "Standard event name (Purchase, Lead, "
                                    "AddToCart, InitiateCheckout, "
                                    "ViewContent, Search, Subscribe, "
                                    "CompleteRegistration, AddPaymentInfo) "
                                    "or a custom event string."
                                ),
                            },
                            "event_time": {
                                "type": "integer",
                                "description": (
                                    "UNIX timestamp (seconds) the event "
                                    "occurred. Must be within the last "
                                    "7 days; older events are rejected."
                                ),
                            },
                            "action_source": {
                                "type": "string",
                                "enum": [
                                    "website",
                                    "email",
                                    "app",
                                    "phone_call",
                                    "chat",
                                    "physical_store",
                                    "system_generated",
                                    "business_messaging",
                                    "other",
                                ],
                                "description": (
                                    "Where the conversion happened. "
                                    "Meta uses this to score attribution "
                                    "quality; 'website' is the most "
                                    "common for CAPI."
                                ),
                            },
                            "user_data": {
                                "type": "object",
                                "description": _USER_DATA_DESCRIPTION,
                            },
                            "custom_data": {
                                "type": "object",
                                "description": (
                                    "Event-specific metadata. Common "
                                    "keys: currency (ISO), value (number), "
                                    "content_ids (array), content_type, "
                                    "order_id, num_items, contents."
                                ),
                            },
                            "event_source_url": {
                                "type": "string",
                                "description": _EVENT_SOURCE_URL_DESCRIPTION,
                            },
                        },
                        "required": [
                            "event_name",
                            "event_time",
                            "action_source",
                            "user_data",
                        ],
                    },
                },
                "test_event_code": {
                    "type": "string",
                    "description": _TEST_EVENT_CODE_DESCRIPTION,
                },
            },
            "required": ["pixel_id", "events"],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_purchase",
        description=(
            "Sends a single Purchase event via the Meta Conversions API — "
            "the most common CAPI use case. Returns Meta's "
            "events_received acknowledgement. Mutating on Meta's side. "
            "Required fields model a typical purchase: amount, currency, "
            "and hashed user identifiers. For other event types use "
            "meta_ads.conversions.send_lead (leads) or the generic "
            "meta_ads.conversions.send (AddToCart / custom events / "
            "batching multiple events)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": _PIXEL_ID_PARAM,
                "event_time": {
                    "type": "integer",
                    "description": (
                        "UNIX timestamp (seconds) of the purchase. Must "
                        "be within the last 7 days."
                    ),
                },
                "user_data": {
                    "type": "object",
                    "description": _USER_DATA_DESCRIPTION,
                },
                "currency": {
                    "type": "string",
                    "description": (
                        "ISO 4217 currency code (USD, JPY, EUR, GBP). "
                        "Must match the ad account's reporting currency "
                        "or be one that Meta can convert."
                    ),
                },
                "value": {
                    "type": "number",
                    "minimum": 0,
                    "description": (
                        "Purchase amount in the specified currency. "
                        "Decimal for currencies with minor units (USD "
                        "9.99); integer is fine for JPY."
                    ),
                },
                "content_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Product IDs associated with the purchase — "
                        "catalog retailer_ids for DPA attribution. "
                        "Optional but recommended when a catalog is in "
                        "use."
                    ),
                },
                "event_source_url": {
                    "type": "string",
                    "description": _EVENT_SOURCE_URL_DESCRIPTION,
                },
                "test_event_code": {
                    "type": "string",
                    "description": _TEST_EVENT_CODE_DESCRIPTION,
                },
            },
            "required": [
                "account_id",
                "pixel_id",
                "event_time",
                "user_data",
                "currency",
                "value",
            ],
        },
    ),
    Tool(
        name="meta_ads.conversions.send_lead",
        description=(
            "Sends a single Lead event via the Meta Conversions API. "
            "Returns Meta's events_received acknowledgement. Mutating on "
            "Meta's side. Use for form submissions, trial signups, "
            "demo requests — anything where a prospect identifies "
            "themselves but no money changes hands. For money-moving "
            "events use meta_ads.conversions.send_purchase. For "
            "non-standard event names use meta_ads.conversions.send."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "account_id": _ACCOUNT_ID_PARAM,
                "pixel_id": _PIXEL_ID_PARAM,
                "event_time": {
                    "type": "integer",
                    "description": (
                        "UNIX timestamp (seconds) the lead occurred. "
                        "Must be within the last 7 days."
                    ),
                },
                "user_data": {
                    "type": "object",
                    "description": _USER_DATA_DESCRIPTION,
                },
                "event_source_url": {
                    "type": "string",
                    "description": _EVENT_SOURCE_URL_DESCRIPTION,
                },
                "test_event_code": {
                    "type": "string",
                    "description": _TEST_EVENT_CODE_DESCRIPTION,
                },
            },
            "required": ["pixel_id", "event_time", "user_data"],
        },
    ),
]
