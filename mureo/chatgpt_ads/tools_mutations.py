"""The ChatGPT Ads tools that change the account (#994), and the spend-limit read.

Pure data, built by :func:`mureo.chatgpt_ads.tools.build_tool` with the same
throttle and closed schemas as the read tools. Each mutation declares
``readOnlyHint=False`` plus what the plugin safety layer needs to treat it
like a built-in change (:mod:`mureo.mcp.plugin_semantics`): ``identity`` so
its ``action_log`` entry names the entity, and ``budget`` / ``bid`` so the
STRATEGY.md caps see the proposed amount. Amounts are micros, and the
declarations say so, so the caps compare currency units.

One tool, one kind of change: budget and bid edits are tools of their own
rather than fields of the general update tools. ``action_log`` records a
mutation under its tool name, and the change-import matcher
(:func:`mureo.change_import.dedupe.action_kind`) reads the kind of change off
that name, so a budget edit recorded under a generic campaign-edit name could
never be recognised as mureo's own in the platform's change history.

Argument shapes mirror the API's own objects, so a value read with a ``*_get``
tool can be passed back unchanged; that is also how a recorded reversal
restores a prior value.
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

#: Smallest campaign budget amount the API accepts, in micros (one unit).
MIN_BUDGET_MICROS = 1_000_000
#: The two amounts a campaign ``budget`` object holds.
BUDGET_KEYS = ("daily_spend_limit_micros", "lifetime_spend_limit_micros")
#: ``max_bid_micros`` bounds.
MAX_BID_MICROS = 30_400_000_000_000
#: ``bid_multiplier_micros`` bounds (0.1x to 10x).
MIN_BID_MULTIPLIER_MICROS = 100_000
MAX_BID_MULTIPLIER_MICROS = 10_000_000
#: Range the API accepts for ``start_time`` / ``end_time`` (Unix seconds,
#: 2000-01-01 to 2100-01-01).
SCHEDULE_MIN_SECONDS = 946_684_800
SCHEDULE_MAX_SECONDS = 4_102_444_800
SCHEDULE_KEYS = ("start_time", "end_time")
#: mureo's cross-provider budget context keys (currency units, never sent to
#: the platform). The strategy gate reads them for the percentage-increase and
#: account-total caps; a closed schema without them would leave both caps
#: with nothing to compare. Spelled out as any provider outside the policy
#: package has to; a test holds them equal to the names the gate reads.
_CONVENTION_CURRENT_KEY = "current_daily_budget"
_CONVENTION_TOTAL_KEY = "projected_total_daily_budget"
BUDGET_CONTEXT_KEYS = (_CONVENTION_CURRENT_KEY, _CONVENTION_TOTAL_KEY)
BILLING_EVENT_TYPES = ("impression", "click")
#: Strategies a request may name. Responses can also say ``automated_bid``,
#: which a request expresses by omitting both ``strategy`` and
#: ``max_bid_micros``.
BID_STRATEGIES = ("fixed_bid", "maximize_clicks", "maximize_conversions")

_MUTATES = ToolAnnotations(readOnlyHint=False)

_CAMPAIGN_IDENTITY = {"identity": {"campaign_id": "campaign_id"}}
_AD_GROUP_IDENTITY = {
    "identity": {"entity_type": "ad_group", "entity_id": "ad_group_id"}
}
_AD_IDENTITY = {"identity": {"ad_id": "ad_id"}}

_CAMPAIGN_ID = id_param("Campaign", "cmpn_123")
_AD_GROUP_ID = id_param("Ad group", "adgrp_123")
_AD_ID = id_param("Ad", "ad_123")

_NAME = {
    "type": "string",
    "minLength": NAME_MIN_CHARS,
    "maxLength": NAME_MAX_CHARS,
    "pattern": NAME_PATTERN,
    "description": "New name: 3 to 1000 characters on one line, not all spaces.",
}


def _schedule_param(which: str) -> dict[str, Any]:
    return {
        "type": ["integer", "null"],
        "minimum": SCHEDULE_MIN_SECONDS,
        "maximum": SCHEDULE_MAX_SECONDS,
        "description": (
            f"New {which} as Unix seconds, or null to clear it. Omit to leave "
            "it unchanged."
        ),
    }


_BUDGET = {
    "type": "object",
    "additionalProperties": False,
    "minProperties": 1,
    "properties": {
        key: {"type": "integer", "minimum": MIN_BUDGET_MICROS} for key in BUDGET_KEYS
    },
    "description": (
        "The complete new budget, in micros of the account currency (1,000,000 "
        "= one unit; 75000000 is 75.00). The platform replaces the whole budget "
        "object: a key left out is removed, and an amount replaces the old one "
        "rather than adding to it. daily_spend_limit_micros and/or "
        "lifetime_spend_limit_micros, each at least 1000000."
    ),
}

_MULTIPLIER: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["custom_audience_id", "bid_multiplier_micros"],
    "properties": {
        "custom_audience_id": {"type": "string", "pattern": ID_PATTERN},
        "bid_multiplier_micros": {
            "type": "integer",
            "minimum": MIN_BID_MULTIPLIER_MICROS,
            "maximum": MAX_BID_MULTIPLIER_MICROS,
        },
    },
}

_BIDDING_CONFIG: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["billing_event_type"],
    "properties": {
        "billing_event_type": {"type": "string", "enum": list(BILLING_EVENT_TYPES)},
        "strategy": {"type": "string", "enum": list(BID_STRATEGIES)},
        "max_bid_micros": {
            "type": "integer",
            "minimum": 1,
            "maximum": MAX_BID_MICROS,
        },
        "custom_audience_bid_multipliers": {"type": "array", "items": _MULTIPLIER},
    },
    "description": (
        "The complete new bidding config; the platform replaces the whole "
        "object. Amounts are micros of the account currency (1,000,000 = one "
        "unit). With impression billing the bid is per impression, not per "
        "thousand: CPM / 1000. Omitting both strategy and max_bid_micros "
        "selects automatic bidding. bid_multiplier_micros 1000000 = 1.0x."
    ),
}

_MAX_BID_PATH = "bidding_config.max_bid_micros"
#: The keys a ``bidding_config`` and one of its multipliers may carry.
BIDDING_CONFIG_KEYS = frozenset(_BIDDING_CONFIG["properties"])
MULTIPLIER_KEYS = frozenset(_MULTIPLIER["properties"])

_REVERSAL_NOTE = (
    "mureo records a reversal in STATE.json action_log, so rollback_apply can "
    "undo it."
)


def _status_tool(entity: str, noun: str, id_key: str, example: str, verb: str) -> Tool:
    """One pause / enable tool; ``verb`` is ``pause`` or ``enable``."""
    other = "enable" if verb == "pause" else "pause"
    if verb == "pause":
        effect = f"Pauses one ChatGPT Ads {noun}: it stops spending."
    else:
        effect = (
            f"Activates one paused ChatGPT Ads {noun}: it becomes eligible to "
            "spend again."
        )
    description = (
        f"{effect} Returns the updated platform object unchanged. Mutates the "
        f"account. {_REVERSAL_NOTE} Archive is not available here; use Ads "
        f"Manager. For the opposite change use chatgpt_ads_{entity}_{other}."
    )
    return build_tool(
        f"chatgpt_ads_{entity}_{verb}",
        description,
        {id_key: id_param(noun.capitalize(), example)},
        [id_key],
        annotations=_MUTATES,
        declarations=_IDENTITY_BY_KEY[id_key],
    )


_IDENTITY_BY_KEY = {
    "campaign_id": _CAMPAIGN_IDENTITY,
    "ad_group_id": _AD_GROUP_IDENTITY,
    "ad_id": _AD_IDENTITY,
}

_STATUS_TOOLS = tuple(
    _status_tool(entity, noun, id_key, example, verb)
    for entity, noun, id_key, example in (
        ("campaigns", "campaign", "campaign_id", "cmpn_123"),
        ("ad_groups", "ad group", "ad_group_id", "adgrp_123"),
        ("ads", "ad", "ad_id", "ad_123"),
    )
    for verb in ("pause", "enable")
)

_CAMPAIGNS_UPDATE = build_tool(
    "chatgpt_ads_campaigns_update",
    "Updates one ChatGPT Ads campaign's name and/or schedule. Returns the "
    "updated platform object unchanged. Mutates the account; partial update: "
    "only the fields given change, and null clears start_time or end_time. "
    f"{_REVERSAL_NOTE} Give at least one of name, start_time, end_time. For "
    "the budget use chatgpt_ads_campaigns_update_budget; to pause or activate "
    "use chatgpt_ads_campaigns_pause / chatgpt_ads_campaigns_enable. Archive "
    "is not available here.",
    {
        "campaign_id": _CAMPAIGN_ID,
        "name": _NAME,
        "start_time": _schedule_param("start time"),
        "end_time": _schedule_param("end time"),
    },
    ["campaign_id"],
    annotations=_MUTATES,
    declarations=_CAMPAIGN_IDENTITY,
)


def _context_param(what: str) -> dict[str, Any]:
    return {
        "type": "number",
        "minimum": 0,
        "description": (
            f"{what}, in account-currency units (75.0 is 75.00), NOT micros. "
            "Read by mureo's STRATEGY.md budget caps only; never sent to the "
            "platform."
        ),
    }


_CAMPAIGNS_UPDATE_BUDGET = build_tool(
    "chatgpt_ads_campaigns_update_budget",
    "Sets one ChatGPT Ads campaign's budget amounts. Returns the updated "
    "platform object unchanged. Mutates spend: the budget sent replaces the "
    "whole budget object, amounts in micros of the account currency "
    "(1,000,000 = one unit), and a new amount replaces the old one rather "
    "than adding to it. The budget type cannot change here: mureo reads the "
    "campaign first (one more request) and refuses, changing nothing, when "
    "the keys sent differ from the keys the campaign's budget has (a daily "
    "budget stays daily; switch types in Ads Manager). The platform rejects a "
    "lifetime budget below the amount already spent, and can reject a daily "
    "budget below an ad group's effective bid. STRATEGY.md budget caps apply; "
    "pass current_daily_budget and projected_total_daily_budget (currency "
    "units) so the increase and account-total caps can be checked. "
    f"{_REVERSAL_NOTE} Read the current budget with chatgpt_ads_campaigns_get "
    "first.",
    {
        "campaign_id": _CAMPAIGN_ID,
        "budget": _BUDGET,
        _CONVENTION_CURRENT_KEY: _context_param("The campaign's current daily budget"),
        _CONVENTION_TOTAL_KEY: _context_param(
            "The account's total daily budget across campaigns after this change"
        ),
    },
    ["campaign_id", "budget"],
    annotations=_MUTATES,
    declarations={
        **_CAMPAIGN_IDENTITY,
        "budget": {
            "daily": "budget.daily_spend_limit_micros",
            "lifetime": "budget.lifetime_spend_limit_micros",
            "unit": "micros",
        },
    },
)

_AD_GROUPS_UPDATE = build_tool(
    "chatgpt_ads_ad_groups_update",
    "Renames one ChatGPT Ads ad group. Returns the updated platform object "
    f"unchanged. Mutates the account. {_REVERSAL_NOTE} For bids use "
    "chatgpt_ads_ad_groups_update_bid; to pause or activate use "
    "chatgpt_ads_ad_groups_pause / chatgpt_ads_ad_groups_enable. Archive is "
    "not available here.",
    {"ad_group_id": _AD_GROUP_ID, "name": _NAME},
    ["ad_group_id", "name"],
    annotations=_MUTATES,
    declarations=_AD_GROUP_IDENTITY,
)

_AD_GROUPS_UPDATE_BID = build_tool(
    "chatgpt_ads_ad_groups_update_bid",
    "Sets one ChatGPT Ads ad group's bidding config. Returns the updated "
    "platform object unchanged. Mutates spend: the config sent replaces the "
    "whole bidding_config object. Bids are micros of the account currency "
    "(1,000,000 = one unit); with impression billing the bid is per "
    "impression (CPM / 1000). Omitting both strategy and max_bid_micros "
    "selects automatic bidding. The STRATEGY.md bid caps "
    "(max_cpc_bid_per_ad_group, max_bid_amount_per_ad_set) read "
    "max_bid_micros only: audience bid multipliers (up to 10x) and the "
    "strategies without a bid (automatic, maximize_*) are not bounded by "
    "them, and with impression billing the amount is per impression (CPM = "
    "amount x 1000), so a per-click cap does not meaningfully constrain it. The "
    f"campaign budget is what bounds spend. {_REVERSAL_NOTE} Read the current "
    "config with chatgpt_ads_ad_groups_get first.",
    {"ad_group_id": _AD_GROUP_ID, "bidding_config": _BIDDING_CONFIG},
    ["ad_group_id", "bidding_config"],
    annotations=_MUTATES,
    # One amount on both bid channels: which of the two STRATEGY.md bid caps
    # an operator wrote says nothing about the billing event of this ad
    # group, so each cap that is set holds the bid.
    declarations={
        **_AD_GROUP_IDENTITY,
        "bid": {
            "bid_amount": _MAX_BID_PATH,
            "cpc_bid": _MAX_BID_PATH,
            "unit": "micros",
        },
    },
)

_ACCOUNT_DAILY_SPEND_LIMIT_SET = build_tool(
    "chatgpt_ads_account_daily_spend_limit_set",
    "Sets the ChatGPT Ads account's daily spending limit, shared by every "
    "campaign and renewed at midnight in the account time zone. Returns the "
    "platform's answer unchanged (the account's spend limits after the "
    "change). Mutates spend; amount in micros of the account currency. "
    "Available only for accounts on invoice billing; otherwise the result is "
    "feature_not_enabled or an API error. mureo reads the current revision "
    "first; with more than one daily rule it refuses and points to Ads "
    "Manager. A decrease below spend already counted is rejected. The "
    "STRATEGY.md cap max_daily_budget_per_campaign also holds this amount, "
    f"although the limit is account-wide. {_REVERSAL_NOTE} Read the limits "
    "with chatgpt_ads_account_spend_limits_get.",
    {
        "amount_micros": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "New daily limit in micros of the account currency (1,000,000 "
                "= one unit; 100000000 is 100.00). Use multiples of the "
                "currency's smallest unit."
            ),
        }
    },
    ["amount_micros"],
    annotations=_MUTATES,
    # Declared rather than left to the gate's built-in scan, which reads an
    # undeclared ``amount_micros`` as a daily budget in micros anyway: the
    # declaration states the unit instead of relying on that convention.
    declarations={"budget": {"daily": "amount_micros", "unit": "micros"}},
)

_ACCOUNT_SPEND_LIMITS_GET = build_tool(
    "chatgpt_ads_account_spend_limits_get",
    "Gets the ChatGPT Ads account's spending limits. Returns the platform "
    "object unchanged: data (date range limits), daily_limit / daily_limits "
    "(the active or upcoming daily rule, amounts in micros, with spent and "
    "remaining micros), revision and the earliest allowed start dates. "
    "Read-only. Available only for accounts on invoice billing and keys that "
    "may manage billing. Use this before "
    "chatgpt_ads_account_daily_spend_limit_set.",
    {},
    [],
)

MUTATION_TOOLS: tuple[Tool, ...] = (
    *_STATUS_TOOLS,
    _CAMPAIGNS_UPDATE,
    _CAMPAIGNS_UPDATE_BUDGET,
    _AD_GROUPS_UPDATE,
    _AD_GROUPS_UPDATE_BID,
    _ACCOUNT_DAILY_SPEND_LIMIT_SET,
    _ACCOUNT_SPEND_LIMITS_GET,
)

__all__ = [
    "BIDDING_CONFIG_KEYS",
    "BID_STRATEGIES",
    "BUDGET_CONTEXT_KEYS",
    "BILLING_EVENT_TYPES",
    "BUDGET_KEYS",
    "MAX_BID_MICROS",
    "MAX_BID_MULTIPLIER_MICROS",
    "MIN_BID_MULTIPLIER_MICROS",
    "MIN_BUDGET_MICROS",
    "MULTIPLIER_KEYS",
    "MUTATION_TOOLS",
    "SCHEDULE_KEYS",
    "SCHEDULE_MAX_SECONDS",
    "SCHEDULE_MIN_SECONDS",
]
