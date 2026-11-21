"""Before-state capture for the ChatGPT Ads mutations (#994).

mureo's dispatch calls :meth:`ChatGPTAdsProvider.capture_reversal` before a
mutating tool runs (:class:`mureo.mcp.tool_provider.MCPReversibleToolProvider`);
this module does the work. It reads the entity through one of the provider's
own read tools, run by :func:`~mureo.chatgpt_ads.handlers.run_tool` like any
call, and returns ``{"operation", "params"[, "caveats"]}`` naming one of the
provider's tools with the prior values. That lands in ``STATE.json``'s
``action_log`` and is what ``rollback_apply`` executes.

Every value a reversal carries has passed the check the named tool runs on
its arguments (the public checks of :mod:`mureo.chatgpt_ads.handlers_mutations`),
so a recorded reversal is one the tool accepts at rollback time.

- A pause reverses to the matching enable, and an enable to the pause, only
  when the entity was in the opposite state before; an archived entity, or
  one already in the requested state, gets no reversal.
- A campaign update reverses to the same tool with the prior value of each
  field the call sets. A field whose prior value fails the check is left out
  and named in ``caveats``, which the rollback planner reports as a PARTIAL
  plan; with nothing left there is no reversal.
- A budget, a bidding config or an ad group name is restored whole or not at
  all: the platform replaces the whole budget and bidding objects, so a
  partial object would remove a limit or a multiplier, and a silently
  different config is worse than none.
- The account daily limit reverses to its prior amount only when exactly one
  daily rule existed: with none there is nothing to set back (removing a
  limit is a different operation), and with several the tool itself refuses.

Best effort, unconditionally. One read per capture, bounded by
:data:`REVERSAL_READ_DEADLINE_SECONDS`, so a slow read delays the write by at
most that much. Any failure returns ``None`` and the write goes ahead without
a reversal; only the exception's type is logged (no message, no arguments),
which keeps any platform or credential text out of the log. A stop
(:data:`~mureo.core.control_flow.STOP_EXCEPTIONS`) is not a failure and is
re-raised: the call is over, and carrying on into the write would ignore
that.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mureo.chatgpt_ads._api import REVERSAL_READ_DEADLINE_SECONDS
from mureo.chatgpt_ads._validation import integer
from mureo.chatgpt_ads.credentials import load_chatgpt_ads_credentials
from mureo.chatgpt_ads.handlers import run_tool
from mureo.chatgpt_ads.handlers_mutations import (
    bidding_config_value,
    budget_value,
    current_budget_keys,
    daily_spend_limits,
    required_name,
    schedule_value,
)
from mureo.chatgpt_ads.tools_mutations import (
    BIDDING_CONFIG_KEYS,
    BUDGET_KEYS,
    SCHEDULE_KEYS,
)
from mureo.core.control_flow import STOP_EXCEPTIONS

logger = logging.getLogger(__name__)

#: Caveat for a reversal that sets a lower lifetime budget than the call did.
LIFETIME_BELOW_SPEND_CAVEAT = (
    "the platform rejects a lifetime budget below the amount already spent"
)

#: Most audience multipliers one bid reversal carries; a config with more
#: gets no reversal. With the id shape the tool's check holds each item to,
#: this bounds what one ``action_log`` entry adds to STATE.json.
MAX_REVERSAL_MULTIPLIERS = 1000

_AUTOMATED_BID = "automated_bid"

#: The billing event each ``target_strategy`` a response names for a fixed
#: bid belongs to. A target strategy missing from this map gets no reversal:
#: its request shape is not known, and guessing could set a different bid.
_FIXED_BID_BILLING_EVENTS = {"target_cpc": "click"}

#: Every key a response ``bidding_config`` is known to carry: the request's
#: keys plus the fixed bid's read-back shape.
_RESPONSE_BIDDING_KEYS = BIDDING_CONFIG_KEYS | {"target_strategy", "target_micros"}

#: ``(mutation name, its arguments, the prior read)`` → reversal or ``None``.
Builder = Callable[[str, dict[str, Any], Any], Any]


@dataclass(frozen=True)
class _Capture:
    """How one mutation reads its before-state and turns it into a reversal."""

    read_tool: str
    id_key: str | None
    build: Builder


def _accepted(check: Callable[..., Any], *args: Any) -> bool:
    """Whether the tool's own check accepts these values."""
    try:
        check(*args)
    except ValueError:
        return False
    return True


def _toggle(prior_status: str, operation: str, id_key: str) -> Builder:
    def _build(name: str, arguments: dict[str, Any], prior: Any) -> Any:
        if not isinstance(prior, dict) or prior.get("status") != prior_status:
            return None
        return {"operation": operation, "params": {id_key: arguments[id_key]}}

    return _build


def _not_restored(field: str) -> str:
    return f"{field}: the prior value could not be read, so it is not restored"


def _field_accepted(field: str, prior: dict[str, Any]) -> bool:
    if field not in prior:
        return False
    if field == "name":
        return _accepted(required_name, {"name": prior["name"]})
    return _accepted(schedule_value, prior[field], field)


def _campaign_update(name: str, arguments: dict[str, Any], prior: Any) -> Any:
    if not isinstance(prior, dict):
        return None
    params: dict[str, Any] = {"campaign_id": arguments["campaign_id"]}
    caveats: list[str] = []
    for field in ("name", *SCHEDULE_KEYS):
        if field not in arguments:
            continue
        if _field_accepted(field, prior):
            params[field] = prior[field]
        else:
            caveats.append(_not_restored(field))
    if len(params) == 1:
        return None
    found: dict[str, Any] = {"operation": name, "params": params}
    if caveats:
        found["caveats"] = caveats
    return found


def _prior_budget(prior: Any) -> dict[str, Any] | None:
    """Every amount the prior budget held, or ``None`` unless all pass."""
    keys = current_budget_keys(prior)
    if keys is None:
        return None
    restored = {key: prior["budget"][key] for key in BUDGET_KEYS if key in keys}
    return restored if _accepted(budget_value, restored) else None


def _campaign_budget(name: str, arguments: dict[str, Any], prior: Any) -> Any:
    restored = _prior_budget(prior)
    if restored is None:
        return None
    found: dict[str, Any] = {
        "operation": name,
        "params": {"campaign_id": arguments["campaign_id"], "budget": restored},
    }
    lifetime = "lifetime_spend_limit_micros"
    sent = arguments.get("budget")
    sent_lifetime = sent.get(lifetime) if isinstance(sent, dict) else None
    if (
        type(sent_lifetime) is int
        and lifetime in restored
        and restored[lifetime] < sent_lifetime
    ):
        found["caveats"] = [LIFETIME_BELOW_SPEND_CAVEAT]
    return found


def _ad_group_rename(name: str, arguments: dict[str, Any], prior: Any) -> Any:
    if not isinstance(prior, dict) or not _accepted(required_name, prior):
        return None
    params = {"ad_group_id": arguments["ad_group_id"], "name": prior["name"]}
    return {"operation": name, "params": params}


def _fixed_bid(present: dict[str, Any]) -> dict[str, Any] | None:
    """The request's ``fixed_bid`` for a response's ``target_strategy``.

    ``None`` unless the target strategy is one mureo knows, paired with its
    billing event, carries ``target_micros``, and the config does not also
    carry the request's own ``strategy`` / ``max_bid_micros``: a config with
    both shapes does not say which bid is in force.
    """
    target = present.get("target_strategy")
    if (
        not isinstance(target, str)
        or target not in _FIXED_BID_BILLING_EVENTS
        or _FIXED_BID_BILLING_EVENTS[target] != present.get("billing_event_type")
        or "target_micros" not in present
        or "strategy" in present
        or "max_bid_micros" in present
    ):
        return None
    return {"strategy": "fixed_bid", "max_bid_micros": present["target_micros"]}


def _request_bidding(config: object) -> dict[str, Any] | None:
    """A response ``bidding_config`` in the request shape, or ``None``.

    A response names a bid in one of two shapes. ``strategy`` and
    ``max_bid_micros`` read back as sent, except that ``automated_bid`` is
    how a response names automatic bidding, which a request expresses by
    leaving out ``strategy`` and ``max_bid_micros``. A fixed bid reads back
    as ``target_strategy`` / ``target_micros`` and is restored as
    ``fixed_bid`` with that amount (see :func:`_fixed_bid`).

    The platform replaces the whole object, so dropping a key would restore
    a different config: a key outside :data:`_RESPONSE_BIDDING_KEYS`, or any
    other value that is present but fails the tool's check, means no
    reversal. A key whose value is null is absent.
    """
    if not isinstance(config, dict):
        return None
    present = {key: value for key, value in config.items() if value is not None}
    if not set(present) <= _RESPONSE_BIDDING_KEYS:
        return None
    restored: dict[str, Any] = {"billing_event_type": present.get("billing_event_type")}
    if "target_strategy" in present or "target_micros" in present:
        bid = _fixed_bid(present)
        if bid is None:
            return None
        restored.update(bid)
    elif present.get("strategy") != _AUTOMATED_BID:
        for key in ("strategy", "max_bid_micros"):
            if key in present:
                restored[key] = present[key]
    multipliers = present.get("custom_audience_bid_multipliers")
    if multipliers is not None:
        if (
            isinstance(multipliers, list)
            and len(multipliers) > MAX_REVERSAL_MULTIPLIERS
        ):
            return None
        restored["custom_audience_bid_multipliers"] = copy.deepcopy(multipliers)
    return restored if _accepted(bidding_config_value, restored) else None


def _ad_group_bid(name: str, arguments: dict[str, Any], prior: Any) -> Any:
    if not isinstance(prior, dict):
        return None
    restored = _request_bidding(prior.get("bidding_config"))
    if restored is None:
        return None
    params = {"ad_group_id": arguments["ad_group_id"], "bidding_config": restored}
    return {"operation": name, "params": params}


def _account_daily_limit(name: str, arguments: dict[str, Any], prior: Any) -> Any:
    rules = daily_spend_limits(prior)
    if len(rules) != 1 or not isinstance(rules[0], dict):
        return None
    amount = rules[0].get("amount_micros")
    if not _accepted(integer, amount, "amount_micros", 0):
        return None
    return {"operation": name, "params": {"amount_micros": amount}}


def _toggle_captures() -> dict[str, _Capture]:
    captures: dict[str, _Capture] = {}
    for family, id_key in (
        ("campaigns", "campaign_id"),
        ("ad_groups", "ad_group_id"),
        ("ads", "ad_id"),
    ):
        read = f"chatgpt_ads_{family}_get"
        pause, enable = f"chatgpt_ads_{family}_pause", f"chatgpt_ads_{family}_enable"
        captures[pause] = _Capture(read, id_key, _toggle("active", enable, id_key))
        captures[enable] = _Capture(read, id_key, _toggle("paused", pause, id_key))
    return captures


_CAPTURES: dict[str, _Capture] = {
    **_toggle_captures(),
    "chatgpt_ads_campaigns_update": _Capture(
        "chatgpt_ads_campaigns_get", "campaign_id", _campaign_update
    ),
    "chatgpt_ads_campaigns_update_budget": _Capture(
        "chatgpt_ads_campaigns_get", "campaign_id", _campaign_budget
    ),
    "chatgpt_ads_ad_groups_update": _Capture(
        "chatgpt_ads_ad_groups_get", "ad_group_id", _ad_group_rename
    ),
    "chatgpt_ads_ad_groups_update_bid": _Capture(
        "chatgpt_ads_ad_groups_get", "ad_group_id", _ad_group_bid
    ),
    "chatgpt_ads_account_daily_spend_limit_set": _Capture(
        "chatgpt_ads_account_spend_limits_get", None, _account_daily_limit
    ),
}


async def _capture(name: str, arguments: dict[str, Any], plan: _Capture) -> Any:
    credentials = load_chatgpt_ads_credentials()
    if credentials is None:
        return None
    read_arguments = (
        {} if plan.id_key is None else {plan.id_key: arguments.get(plan.id_key)}
    )
    prior = await run_tool(
        plan.read_tool,
        read_arguments,
        credentials.api_key,
        deadline=REVERSAL_READ_DEADLINE_SECONDS,
    )
    return plan.build(name, arguments, prior)


async def capture_reversal(
    name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """The reversal of mutation ``name(arguments)``, or ``None``.

    A read-only tool or a name this module does not know returns ``None``
    without a request. Never raises except a stop (see the module docstring).
    """
    plan = _CAPTURES.get(name)
    if plan is None:
        return None
    try:
        found: dict[str, Any] | None = await _capture(name, arguments, plan)
    except STOP_EXCEPTIONS:
        raise
    except BaseException as exc:  # noqa: BLE001 — capture never blocks a write
        logger.warning(
            "ChatGPT Ads before-state capture failed for %r (%s); the mutation "
            "is recorded without a reversal",
            name,
            type(exc).__name__,
        )
        return None
    return found


__all__ = [
    "LIFETIME_BELOW_SPEND_CAVEAT",
    "MAX_REVERSAL_MULTIPLIERS",
    "capture_reversal",
]
