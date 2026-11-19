"""One coroutine per ChatGPT Ads mutation tool, and the spend-limit read (#994).

Merged into :data:`mureo.chatgpt_ads.handlers.HANDLERS`, so every handler here
runs through :func:`~mureo.chatgpt_ads.handlers.run_tool`. Each one checks its
arguments before the first request and sends the API object as given: the
budget and bidding objects replace the platform's whole object, so editing
them here would change what the operator asked for.

The value checks are public because :mod:`mureo.chatgpt_ads.reversal` runs a
recorded reversal through the same checks: a reversal that the tool would
refuse at rollback time is not worth recording.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mureo.chatgpt_ads._errors import ChatGPTAdsAPIError
from mureo.chatgpt_ads._validation import (
    id_value,
    integer,
    name_value,
    number,
    path_id,
)
from mureo.chatgpt_ads.tools_mutations import (
    BID_STRATEGIES,
    BIDDING_CONFIG_KEYS,
    BILLING_EVENT_TYPES,
    BUDGET_CONTEXT_KEYS,
    BUDGET_KEYS,
    MAX_BID_MICROS,
    MAX_BID_MULTIPLIER_MICROS,
    MIN_BID_MULTIPLIER_MICROS,
    MIN_BUDGET_MICROS,
    MULTIPLIER_KEYS,
    SCHEDULE_KEYS,
    SCHEDULE_MAX_SECONDS,
    SCHEDULE_MIN_SECONDS,
)
from mureo.core.tool_failure import failure_payload

if TYPE_CHECKING:
    from mureo.chatgpt_ads.client import ChatGPTAdsClient

Handler = Callable[["ChatGPTAdsClient", dict[str, Any]], Awaitable[Any]]

_SPEND_LIMITS_PATH = "/ad_account/spend_limit_windows"
_TO_ADS_MANAGER = "Change the budget type in Ads Manager."


def status_handler(prefix: str, id_key: str, action: str) -> Handler:
    """``POST {prefix}/{id}/{action}`` with no body (pause, activate,
    archive)."""

    async def _handler(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
        return await client.post(f"{prefix}/{path_id(arguments, id_key)}/{action}")

    return _handler


def required_name(arguments: dict[str, Any]) -> str:
    """The ``name`` argument, which the tool requires."""
    value = name_value(arguments, "name")
    if value is None:
        raise ValueError("name is required: 3-1000 characters, not all spaces")
    return value


def schedule_value(value: object, key: str) -> int | None:
    """One ``start_time`` / ``end_time`` value; ``None`` clears that end."""
    if value is None:
        return None
    return integer(value, key, SCHEDULE_MIN_SECONDS, SCHEDULE_MAX_SECONDS)


def _schedule(arguments: dict[str, Any]) -> dict[str, int | None]:
    """The schedule keys given; a present ``null`` clears that end."""
    return {
        key: schedule_value(arguments[key], key)
        for key in SCHEDULE_KEYS
        if key in arguments
    }


def budget_value(value: object) -> dict[str, Any]:
    """A complete ``budget`` object: one or both amounts, nothing else."""
    if not isinstance(value, dict) or not value or set(value) - set(BUDGET_KEYS):
        raise ValueError(
            "budget must be an object with daily_spend_limit_micros and/or "
            "lifetime_spend_limit_micros, nothing else"
        )
    for key, amount in value.items():
        integer(amount, f"budget.{key}", MIN_BUDGET_MICROS)
    return value


def current_budget_keys(campaign: object) -> frozenset[str] | None:
    """The budget amounts a campaign answer holds (value not ``null``).

    ``None`` when the answer has no budget object or none of the two amounts,
    so the budget type cannot be told.
    """
    budget = campaign.get("budget") if isinstance(campaign, dict) else None
    if not isinstance(budget, dict):
        return None
    keys = frozenset(key for key in BUDGET_KEYS if budget.get(key) is not None)
    return keys or None


def _multipliers(value: object) -> None:
    key = "bidding_config.custom_audience_bid_multipliers"
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    for item in value:
        if not isinstance(item, dict) or set(item) != MULTIPLIER_KEYS:
            raise ValueError(
                f"each {key} item needs exactly custom_audience_id and "
                "bid_multiplier_micros"
            )
        id_value(item["custom_audience_id"], f"{key}[].custom_audience_id")
        integer(
            item["bid_multiplier_micros"],
            f"{key}[].bid_multiplier_micros",
            MIN_BID_MULTIPLIER_MICROS,
            MAX_BID_MULTIPLIER_MICROS,
        )


def bidding_config_value(value: object) -> dict[str, Any]:
    """A complete ``bidding_config`` object in the request shape."""
    if not isinstance(value, dict) or set(value) - BIDDING_CONFIG_KEYS:
        raise ValueError(
            f"bidding_config must be an object with only: {', '.join(sorted(BIDDING_CONFIG_KEYS))}"
        )
    if value.get("billing_event_type") not in BILLING_EVENT_TYPES:
        raise ValueError(
            "bidding_config.billing_event_type is required: "
            f"{' or '.join(BILLING_EVENT_TYPES)}"
        )
    if "strategy" in value and value["strategy"] not in BID_STRATEGIES:
        raise ValueError(
            f"bidding_config.strategy must be one of {', '.join(BID_STRATEGIES)}; "
            "omit it and max_bid_micros for automatic bidding"
        )
    if "max_bid_micros" in value:
        integer(
            value["max_bid_micros"], "bidding_config.max_bid_micros", 1, MAX_BID_MICROS
        )
    if "custom_audience_bid_multipliers" in value:
        _multipliers(value["custom_audience_bid_multipliers"])
    return value


async def _campaigns_update(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    campaign_id = path_id(arguments, "campaign_id")
    body: dict[str, Any] = _schedule(arguments)
    if "name" in arguments:
        body["name"] = required_name(arguments)
    # Checked here rather than in the schema: the tool schemas keep to type,
    # properties, required and additionalProperties at the top level.
    if not body:
        raise ValueError("give at least one of name, start_time, end_time")
    return await client.post(f"/campaigns/{campaign_id}", body)


def _budget_kind_refusal(current: frozenset[str] | None, sent: set[str]) -> Any:
    """The refusal when the budget sent would change the budget type."""
    if current is None:
        return failure_payload(
            "budget_unreadable",
            "The campaign's current budget does not read as "
            "daily_spend_limit_micros and/or lifetime_spend_limit_micros, so "
            "mureo cannot tell whether this change keeps the budget type. "
            f"Nothing was changed. {_TO_ADS_MANAGER}",
            refused=True,
        )
    if set(current) == sent:
        return None
    return failure_payload(
        "budget_kind_change",
        f"The campaign's budget has {', '.join(sorted(current))}; the budget "
        f"sent has {', '.join(sorted(sent))}. The platform replaces the whole "
        "budget object, so a different set of amounts would add or remove a "
        f"limit. Nothing was changed. {_TO_ADS_MANAGER}",
        refused=True,
    )


async def _campaigns_update_budget(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    """Replace the budget amounts, never the budget type.

    A budget without ``daily_spend_limit_micros`` deletes a campaign's daily
    limit, which no daily cap would see; so the campaign is read first and a
    budget whose amounts differ from the current ones is refused. The budget
    context keys are checked and never sent.
    """
    campaign_id = path_id(arguments, "campaign_id")
    budget = budget_value(arguments.get("budget"))
    for key in BUDGET_CONTEXT_KEYS:
        if key in arguments:
            number(arguments[key], key, 0)
    campaign = await client.get(f"/campaigns/{campaign_id}")
    refusal = _budget_kind_refusal(current_budget_keys(campaign), set(budget))
    if refusal is not None:
        return refusal
    return await client.post(f"/campaigns/{campaign_id}", {"budget": budget})


async def _ad_groups_update(client: ChatGPTAdsClient, arguments: dict[str, Any]) -> Any:
    ad_group_id = path_id(arguments, "ad_group_id")
    name = required_name(arguments)
    return await client.post(f"/ad_groups/{ad_group_id}", {"name": name})


async def _ad_groups_update_bid(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    ad_group_id = path_id(arguments, "ad_group_id")
    config = bidding_config_value(arguments.get("bidding_config"))
    return await client.post(f"/ad_groups/{ad_group_id}", {"bidding_config": config})


def daily_spend_limits(windows: object) -> list[Any]:
    """The active and upcoming daily rules of a spend-limits resource.

    A non-empty ``daily_limits`` array when the answer carries one; otherwise
    the single ``daily_limit`` (absent or ``null`` = none), so an empty array
    beside a populated ``daily_limit`` still counts as one rule.
    """
    if not isinstance(windows, dict):
        return []
    rules = windows.get("daily_limits")
    if isinstance(rules, list) and rules:
        return rules
    single = windows.get("daily_limit")
    return [] if single is None else [single]


def _check_rule_shapes(windows: dict[str, Any]) -> None:
    """Stop unless the daily-rule fields have the documented types.

    The count of rules decides whether the write is safe, so a field that
    cannot be counted (``daily_limits`` that is not an array, a
    ``daily_limit`` that is not an object) is not read as "no rule".
    """
    rules, single = windows.get("daily_limits"), windows.get("daily_limit")
    if (rules is None or isinstance(rules, list)) and (
        single is None or isinstance(single, dict)
    ):
        return
    raise ChatGPTAdsAPIError(
        "the spend-limits answer carries daily rules in an unexpected shape; "
        "nothing was changed",
        status=0,
    )


def _expected_revision(windows: dict[str, Any]) -> int:
    """The revision to send: 0 when the answer has none, as the API reference
    says; a revision that is present but unusable stops the write, because a
    guessed one could overwrite a change made in between."""
    if "revision" not in windows:
        return 0
    revision = windows["revision"]
    if type(revision) is not int or revision < 0:
        raise ChatGPTAdsAPIError(
            "the spend-limits answer carries an unusable revision; nothing was "
            "changed",
            status=0,
        )
    return revision


async def _account_spend_limits_get(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    return await client.get(_SPEND_LIMITS_PATH)


async def _account_daily_spend_limit_set(
    client: ChatGPTAdsClient, arguments: dict[str, Any]
) -> Any:
    """Upsert the one daily rule, conditional on the current revision.

    The single-rule form (no ``window_id``) cannot say which of several rules
    it means, so with more than one the change is refused before any write.
    """
    amount = integer(arguments.get("amount_micros"), "amount_micros", 0)
    windows = await client.get(_SPEND_LIMITS_PATH)
    if not isinstance(windows, dict):
        raise ChatGPTAdsAPIError(
            "the spend-limits answer is not a JSON object; nothing was changed",
            status=0,
        )
    _check_rule_shapes(windows)
    rules = daily_spend_limits(windows)
    if len(rules) > 1:
        return failure_payload(
            "multiple_daily_spend_limits",
            f"The account has {len(rules)} active or upcoming daily spending "
            "limits; mureo changes only a single one. Edit them in Ads Manager.",
            refused=True,
        )
    return await client.post(
        "/ad_account/daily_spend_limit",
        {"amount_micros": amount, "expected_revision": _expected_revision(windows)},
    )


MUTATION_HANDLERS: dict[str, Handler] = {
    "chatgpt_ads_campaigns_pause": status_handler("/campaigns", "campaign_id", "pause"),
    "chatgpt_ads_campaigns_enable": status_handler(
        "/campaigns", "campaign_id", "activate"
    ),
    "chatgpt_ads_ad_groups_pause": status_handler("/ad_groups", "ad_group_id", "pause"),
    "chatgpt_ads_ad_groups_enable": status_handler(
        "/ad_groups", "ad_group_id", "activate"
    ),
    "chatgpt_ads_ads_pause": status_handler("/ads", "ad_id", "pause"),
    "chatgpt_ads_ads_enable": status_handler("/ads", "ad_id", "activate"),
    "chatgpt_ads_campaigns_update": _campaigns_update,
    "chatgpt_ads_campaigns_update_budget": _campaigns_update_budget,
    "chatgpt_ads_ad_groups_update": _ad_groups_update,
    "chatgpt_ads_ad_groups_update_bid": _ad_groups_update_bid,
    "chatgpt_ads_account_daily_spend_limit_set": _account_daily_spend_limit_set,
    "chatgpt_ads_account_spend_limits_get": _account_spend_limits_get,
}

__all__ = [
    "MUTATION_HANDLERS",
    "Handler",
    "bidding_config_value",
    "budget_value",
    "current_budget_keys",
    "daily_spend_limits",
    "required_name",
    "schedule_value",
    "status_handler",
]
