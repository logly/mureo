"""The ChatGPT Ads tools that create and archive campaigns, ad groups and ads (#995).

Pure data, built like :mod:`mureo.chatgpt_ads.tools_mutations` and from its
fragments (name, budget, bidding config, schedule, identity and money
declarations), so a create and an update of the same field cannot drift
apart.

Nothing is created able to spend: the create tools take no ``status`` and
the handler always sends ``paused``, so an entity starts serving only through
the matching ``*_enable`` tool. A create carries an ``Idempotency-Key``: for
a repeat with the same key the platform returns the existing object when it
can see the matching earlier create, which is what makes repeating a create
whose answer was lost the safest next step. Neither a create nor an archive records a reversal: a created entity
has no id before the call, and an archive has no undo on the platform.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool, ToolAnnotations

from mureo.chatgpt_ads.tools import (
    ID_PATTERN,
    NAME_MAX_CHARS,
    NAME_MIN_CHARS,
    NAME_PATTERN,
    build_tool,
    id_param,
)
from mureo.chatgpt_ads.tools_mutations import (
    AD_GROUP_IDENTITY,
    BID_DECLARATION,
    BIDDING_CONFIG,
    BUDGET,
    BUDGET_DECLARATION,
    CAMPAIGN_IDENTITY,
    CONVENTION_TOTAL_KEY,
    IDENTITY_BY_KEY,
    MAX_BID_MULTIPLIER_MICROS,
    MIN_BUDGET_MICROS,
    MUTATES,
    NAME,
    context_param,
    schedule_param,
)

#: The ``Idempotency-Key`` header the API accepts is 1-255 characters; mureo
#: keeps to letters, digits, ``_`` and ``-`` so a key quoted back in an error
#: message is copied without escaping.
IDEMPOTENCY_KEY_MAX_CHARS = 255
IDEMPOTENCY_KEY_PATTERN = f"^[A-Za-z0-9_-]{{1,{IDEMPOTENCY_KEY_MAX_CHARS}}}$"
#: ``bidding_type`` values; it cannot be changed once the campaign exists.
BIDDING_TYPES = ("impressions", "clicks", "conversions")
#: ``targeting.platforms.included`` values.
TARGETING_PLATFORMS = (
    "ios_app",
    "android_app",
    "web",
    "desktop_web",
    "ios_web",
    "android_web",
)
#: Locations one ``include`` list may name.
MAX_LOCATION_IDS = 2500
#: Country codes are ISO 3166-1 alpha-2, the form the reference documents.
COUNTRY_PATTERN = "^[A-Z]{2}$"
#: Countries one ``countries`` list may name: ISO 3166-1 assigns 249 codes.
MAX_COUNTRIES = 250
#: Ids one audience or conversion-setting list may name: the reference
#: states no limit; this bounds one request body.
MAX_LISTED_IDS = 1000
#: The keys of one ``include`` location; only ``id`` is required.
LOCATION_KEYS = ("id", "name", "type", "country_code", "region_code")
#: Length of a location's descriptive fields, copied from a search result.
MAX_LOCATION_LABEL_CHARS = 255
MAX_CONTEXT_HINTS = 2000
#: Length of one context hint: the reference states no per-item limit; this
#: bounds one request body.
MAX_CONTEXT_HINT_CHARS = 1000
#: The only creative type exposed: a single-image chat card. Multi-image and
#: product-template creatives are not offered.
CHAT_CARD = "chat_card"
CREATIVE_TITLE_MIN_CHARS = 3
CREATIVE_TITLE_MAX_CHARS = 50
CREATIVE_BODY_MAX_CHARS = 100
TARGET_URL_MAX_CHARS = 2048
IMAGE_CROP_KEYS = ("x", "y", "width", "height")

#: A change that removes something and records no reversal: an archive, or
#: an audience membership removal.
DESTROYS = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
_NAME_BOUNDS = f"{NAME_MIN_CHARS} to {NAME_MAX_CHARS} characters"

_PAUSED_NOTE = (
    "Always created paused (there is no status argument), so it cannot spend "
    "until chatgpt_ads_{entity}_enable is called."
)
_IDEMPOTENCY_NOTE = (
    "Each call carries an idempotency key (generated unless idempotency_key "
    "is given); if the answer is lost, repeat the call with that "
    "idempotency_key and the same arguments: when the platform can see the "
    "earlier create it returns that entity instead of creating a second one. "
    "No reversal is recorded: to undo, leave it paused or archive it."
)

IDEMPOTENCY_KEY = {
    "type": "string",
    "minLength": 1,
    "maxLength": IDEMPOTENCY_KEY_MAX_CHARS,
    "pattern": IDEMPOTENCY_KEY_PATTERN,
    "description": (
        f"Optional key for repeating a create: 1-{IDEMPOTENCY_KEY_MAX_CHARS} "
        "letters, digits, '_' or '-'. Omit it on a first attempt and mureo "
        "generates one; pass the key an error message names to repeat that "
        "attempt, which returns the earlier entity when the platform can see "
        "it."
    ),
}


def _ids(what: str) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": MAX_LISTED_IDS,
        "items": {"type": "string", "pattern": ID_PATTERN},
        "description": f"{what} At most {MAX_LISTED_IDS}.",
    }


_LOCATION: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id"],
    "properties": {
        "id": {"type": "string", "pattern": ID_PATTERN},
        **{
            key: {"type": "string", "maxLength": MAX_LOCATION_LABEL_CHARS}
            for key in LOCATION_KEYS[1:]
        },
    },
}

_GEO: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "countries": {
            "type": "array",
            "maxItems": MAX_COUNTRIES,
            "items": {"type": "string", "pattern": COUNTRY_PATTERN},
            "description": (
                f"ISO 3166-1 alpha-2 country codes, e.g. 'US'. At most "
                f"{MAX_COUNTRIES}."
            ),
        },
        "include": {
            "type": "array",
            "maxItems": MAX_LOCATION_IDS,
            "items": _LOCATION,
            "description": (
                "Regions or markets by id, from chatgpt_ads_locations_search. "
                f"At most {MAX_LOCATION_IDS}; the other fields of a result "
                f"(name, type, ...) may be copied along, up to "
                f"{MAX_LOCATION_LABEL_CHARS} characters each."
            ),
        },
    },
}

_AUDIENCES: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"ids": _ids("Custom audience ids.")},
}

TARGETING: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "locations": _GEO,
        "excluded_locations": _GEO,
        "custom_audiences": _AUDIENCES,
        "excluded_custom_audiences": _AUDIENCES,
        "platforms": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "included": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(TARGETING_PLATFORMS)},
                }
            },
        },
    },
    "description": (
        "Where and to whom the campaign serves; sent unchanged. locations / "
        f"excluded_locations take countries (ISO codes, at most {MAX_COUNTRIES}) "
        "and include (location ids from chatgpt_ads_locations_search, at most "
        f"{MAX_LOCATION_IDS}); custom_audiences / excluded_custom_audiences "
        f"take ids (at most {MAX_LISTED_IDS}); "
        "platforms.included narrows the surfaces. Omit for the platform "
        "default."
    ),
}

_CROP_EDGE = {"type": "number", "minimum": 0, "maximum": 1}

CREATIVE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "title", "body", "target_url"],
    "properties": {
        "type": {"type": "string", "enum": [CHAT_CARD]},
        "title": {
            "type": "string",
            "minLength": CREATIVE_TITLE_MIN_CHARS,
            "maxLength": CREATIVE_TITLE_MAX_CHARS,
            "pattern": NAME_PATTERN,
        },
        "body": {"type": "string", "maxLength": CREATIVE_BODY_MAX_CHARS},
        "target_url": {
            "type": "string",
            "maxLength": TARGET_URL_MAX_CHARS,
            # A host with no user-info ('@') before the path, and no
            # backslash anywhere; the handler parses the rest.
            "pattern": r"^[Hh][Tt][Tt][Pp][Ss]?://[^\s/?#@\\]+(?:[/?#][^\s\\]*)?$",
        },
        "file_id": {"type": "string", "pattern": ID_PATTERN},
        "image_crop": {
            "type": "object",
            "additionalProperties": False,
            "required": list(IMAGE_CROP_KEYS),
            "properties": {key: _CROP_EDGE for key in IMAGE_CROP_KEYS},
        },
    },
    "description": (
        f"A single-image chat card: type '{CHAT_CARD}'; title "
        f"{CREATIVE_TITLE_MIN_CHARS}-{CREATIVE_TITLE_MAX_CHARS} characters on "
        f"one line; body up to {CREATIVE_BODY_MAX_CHARS}; target_url the "
        f"http(s) landing page with a host and no credentials, up to "
        f"{TARGET_URL_MAX_CHARS}; file_id from chatgpt_ads_images_upload_file; "
        "image_crop (needs file_id) a square crop with x, y, width, height as "
        "fractions 0-1 of the image."
    ),
}


def _create_description(entity: str, effect: str, notes: str) -> str:
    paused = _PAUSED_NOTE.format(entity=entity)
    return f"{effect} {paused} {notes} {_IDEMPOTENCY_NOTE}"


_CAMPAIGNS_CREATE = build_tool(
    "chatgpt_ads_campaigns_create",
    _create_description(
        "campaigns",
        "Creates one ChatGPT Ads campaign. Returns the new platform object "
        "unchanged (its id is what chatgpt_ads_ad_groups_create needs). "
        "Mutates the account.",
        "budget takes exactly one of daily_spend_limit_micros or "
        "lifetime_spend_limit_micros, in micros (1,000,000 = one unit). "
        "bidding_type cannot be changed later: impressions pairs with "
        "impression billing and fixed_bid; clicks with click billing and "
        "fixed_bid or maximize_clicks; conversions with click billing and "
        "fixed_bid or maximize_conversions, and needs exactly one conversion "
        "event setting. Maximize strategies need a daily budget; a lifetime "
        "budget allows fixed bidding only. The platform enforces these. "
        "STRATEGY.md budget caps apply; pass projected_total_daily_budget "
        "for the account-total cap. Location ids come from "
        "chatgpt_ads_locations_search.",
    ),
    {
        "name": {**NAME, "description": f"Campaign name: {_NAME_BOUNDS}."},
        "budget": {
            **BUDGET,
            "maxProperties": 1,
            "description": (
                "The budget, in micros of the account currency (1,000,000 = "
                "one unit; 75000000 is 75.00): exactly one of "
                "daily_spend_limit_micros or lifetime_spend_limit_micros, at "
                f"least {MIN_BUDGET_MICROS}. The daily minimum also depends on "
                "the currency."
            ),
        },
        "bidding_type": {
            "type": "string",
            "enum": list(BIDDING_TYPES),
            "description": (
                "What the campaign optimizes for; fixed for its lifetime. "
                "Decides which billing events and strategies its ad groups may use."
            ),
        },
        "targeting": TARGETING,
        "start_time": {
            **schedule_param("start time"),
            "type": "integer",
            "description": "Start as Unix seconds. Omit for the platform default.",
        },
        "end_time": {
            **schedule_param("end time"),
            "type": "integer",
            "description": "End as Unix seconds. Omit for no end.",
        },
        "conversion_event_setting_ids": _ids(
            "Conversion event setting ids. bidding_type 'conversions' needs "
            "exactly one active standard event setting; cannot be changed later."
        ),
        CONVENTION_TOTAL_KEY: context_param(
            "The account's total daily budget across campaigns after this create"
        ),
        "idempotency_key": IDEMPOTENCY_KEY,
    },
    ["name", "budget", "bidding_type"],
    annotations=MUTATES,
    declarations=BUDGET_DECLARATION,
)

_AD_GROUPS_CREATE = build_tool(
    "chatgpt_ads_ad_groups_create",
    _create_description(
        "ad_groups",
        "Creates one ChatGPT Ads ad group in a campaign. Returns the new "
        "platform object unchanged (its id is what chatgpt_ads_ads_create "
        "needs). Mutates the account.",
        "Bids are micros of the account currency (1,000,000 = one unit); "
        "with impression billing the bid is per impression (CPM / 1000). "
        "Omitting both strategy and max_bid_micros selects automatic bidding. "
        "The billing event and strategy must suit the campaign's "
        "bidding_type; the platform enforces it. The STRATEGY.md bid caps "
        "(max_cpc_bid_per_ad_group, max_bid_amount_per_ad_set) read "
        "max_bid_micros only: audience bid multipliers (up to "
        f"{MAX_BID_MULTIPLIER_MICROS // 1_000_000}x) and the "
        "strategies without a bid (automatic, maximize_*) are not bounded by "
        "them, and with impression billing the amount is per impression (CPM = "
        "amount x 1000), so a per-click cap does not meaningfully constrain "
        "it. The campaign budget is what bounds spend.",
    ),
    {
        "campaign_id": id_param("Campaign", "cmpn_123"),
        "name": {**NAME, "description": f"Ad group name: {_NAME_BOUNDS}."},
        "bidding_config": {
            **BIDDING_CONFIG,
            "description": (
                "The bidding config. Amounts are micros of the account "
                "currency (1,000,000 = one unit). With impression billing the "
                "bid is per impression, not per thousand: CPM / 1000. Omitting "
                "both strategy and max_bid_micros selects automatic bidding. "
                "bid_multiplier_micros 1000000 = 1.0x."
            ),
        },
        "context_hints": {
            "type": "array",
            "maxItems": MAX_CONTEXT_HINTS,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_CONTEXT_HINT_CHARS,
            },
            "description": (
                "Free-form descriptions or keywords for when the ads are "
                "useful; they guide placement, not hard eligibility. At most "
                f"{MAX_CONTEXT_HINTS}, each 1 to {MAX_CONTEXT_HINT_CHARS} "
                "characters."
            ),
        },
        "idempotency_key": IDEMPOTENCY_KEY,
    },
    ["campaign_id", "name", "bidding_config"],
    annotations=MUTATES,
    declarations={**CAMPAIGN_IDENTITY, **BID_DECLARATION},
)

_ADS_CREATE = build_tool(
    "chatgpt_ads_ads_create",
    _create_description(
        "ads",
        "Creates one ChatGPT Ads ad in an ad group. Returns the new platform "
        "object unchanged. Mutates the account; the ad enters the platform's "
        "review on creation (review_status in_review, then approved or "
        "rejected).",
        "Only single-image chat cards are offered. Upload the image first "
        "with chatgpt_ads_images_upload_file and pass its file_id as "
        "creative.file_id.",
    ),
    {
        "ad_group_id": id_param("Ad group", "adgrp_123"),
        "name": {**NAME, "description": f"Ad name: {_NAME_BOUNDS}."},
        "creative": CREATIVE,
        "idempotency_key": IDEMPOTENCY_KEY,
    },
    ["ad_group_id", "name", "creative"],
    annotations=MUTATES,
    # The ad has no id before the call; its ad group is the one id known.
    declarations=AD_GROUP_IDENTITY,
)


def _archive_tool(entity: str, noun: str, id_key: str, example: str) -> Tool:
    description = (
        f"Archives one ChatGPT Ads {noun}, irreversibly: the platform has no "
        "restore, and mureo records no reversal, so it cannot be undone. "
        "Returns the updated platform object unchanged (status archived). "
        f"Mutates the account. To stop spending reversibly use "
        f"chatgpt_ads_{entity}_pause instead. Whether the {noun}'s children "
        "are archived with it is not documented."
    )
    return build_tool(
        f"chatgpt_ads_{entity}_archive",
        description,
        {id_key: id_param(noun.capitalize(), example)},
        [id_key],
        annotations=DESTROYS,
        declarations=IDENTITY_BY_KEY[id_key],
    )


CREATE_TOOLS: tuple[Tool, ...] = (
    _CAMPAIGNS_CREATE,
    _AD_GROUPS_CREATE,
    _ADS_CREATE,
    _archive_tool("campaigns", "campaign", "campaign_id", "cmpn_123"),
    _archive_tool("ad_groups", "ad group", "ad_group_id", "adgrp_123"),
    _archive_tool("ads", "ad", "ad_id", "ad_123"),
)

__all__ = [
    "BIDDING_TYPES",
    "CHAT_CARD",
    "COUNTRY_PATTERN",
    "CREATE_TOOLS",
    "CREATIVE",
    "CREATIVE_BODY_MAX_CHARS",
    "CREATIVE_TITLE_MAX_CHARS",
    "CREATIVE_TITLE_MIN_CHARS",
    "DESTROYS",
    "IDEMPOTENCY_KEY",
    "IDEMPOTENCY_KEY_MAX_CHARS",
    "IDEMPOTENCY_KEY_PATTERN",
    "IMAGE_CROP_KEYS",
    "LOCATION_KEYS",
    "MAX_CONTEXT_HINTS",
    "MAX_CONTEXT_HINT_CHARS",
    "MAX_COUNTRIES",
    "MAX_LISTED_IDS",
    "MAX_LOCATION_IDS",
    "MAX_LOCATION_LABEL_CHARS",
    "TARGETING",
    "TARGETING_PLATFORMS",
    "TARGET_URL_MAX_CHARS",
]
