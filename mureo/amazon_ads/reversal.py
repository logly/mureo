"""Automatic before-state capture for Amazon Ads mutations (#121).

Amazon writes used to reach ``STATE.json``'s ``action_log`` with
``reversible_params=None``, so ``rollback_apply`` could only answer
NOT_SUPPORTED: the bridge forwards Amazon's own tools verbatim and no agent
reliably authors a reversal hint. This module closes that gap the same way
:mod:`mureo.mcp.native_reversal` does for built-in Google/Meta toggles —
by reading the entity's CURRENT state *before* the mutation and recording a
reversal that names the same tool with the previous values.

The pair table
--------------
:data:`_REVERSIBLE` maps a mutation to the query tool that reads its
before-state. Every entry was derived from the real Amazon tool manifest by
reading BOTH inputSchemas, and a pair exists only where the query can filter
by the very id the mutation writes (``campaignIdFilter`` ↔ ``campaignId``,
and so on). Mutations whose query counterpart keys on something else, and
create/delete verbs (whose "reversal" would be a destructive or
id-inventing call), are deliberately absent.

What is verified and what is not
--------------------------------
- LIVE-VERIFIED (observed against a real account, 2026-08-01): the query
  envelopes ``{"campaigns": [...]}`` and ``{"ads": [...]}``; that
  ``body.accessRequestedAccount`` and ``body.adProductFilter`` are REQUIRED
  by ``query_campaign``/``query_ad``; and that ``adProductFilter.include``
  accepts exactly ONE ad product per call.
- INFERRED from the manifest's write-side inputSchemas (never observed in a
  query response): the per-item field names (``campaignId``/``adId``/
  ``targetId``…, ``state``, ``budgets``, ``name``, ``bid``) and the
  ad-group / target / portfolio envelope keys. No Amazon tool declares an
  ``outputSchema``, so the parser treats every one of those as a
  possibility, not a promise: a field it cannot find is simply not
  reversed. A wrong reversal is worse than none.
- INFERRED, and load-bearing for the whole design: that an update item
  carrying only some fields leaves the omitted ones unchanged (PATCH, not
  PUT). That is inferred from Amazon shipping dedicated single-field update
  tools (``update_campaign_state``, ``update_campaign_budget``,
  ``update_target_bid``) alongside the general ones — a replace-semantics
  API could not offer those — and is NOT live-verified. If Amazon in fact
  replaced omitted fields with defaults, a field-scoped reversal would
  under-restore.

``adProductFilter`` is not on any mutation payload
--------------------------------------------------
Four of the five query tools require it, and it can only name one ad
product per call. Rather than defaulting to a product (which would silently
query the wrong surface and could "find" nothing — or, worse, look right),
the capture builds a probe ORDER: ad products already observed for these
exact ids (:data:`_AD_PRODUCT_CACHE`) first, then any ``adProduct`` the
mutation itself declares (``update_campaign``, ``update_ad_group``), then
the rest of the enum — querying only the still-unresolved ids each round
and stopping as soon as every id is resolved. Order is a pure cost
heuristic and cannot corrupt the result: an entity is accepted only when
its id field equals a requested id. Worst case is five reads before one
write; ``query_portfolio`` declares no ``adProductFilter`` at all and
always costs exactly one.

Two bounds, because this runs before a write
--------------------------------------------
A best-effort capture must never hold a mutation hostage, so the reads are
bounded twice: :data:`READ_TIMEOUT_SECONDS` caps any single read (a hung
endpoint fails fast) and :data:`CAPTURE_DEADLINE_SECONDS` caps the capture
as a whole (five merely-slow reads would otherwise each return in time and
still stall the write for most of a minute). The deadline is checked before
every probe and also caps that probe's own timeout. On expiry — and equally
when a probe simply fails — the capture stops probing and hands back
whatever it has: a partial reversal whose unresolved entities are recorded
as caveats, or no reversal at all. Either way the write proceeds
immediately — an unreversed write beats a delayed one.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    #: ``AmazonAdsBridge.handle_mcp_tool`` — capture goes through the bridge's
    #: own dispatch so it inherits authentication and token refresh.
    Dispatch = Callable[[str, dict[str, Any]], Awaitable[list[Any]]]

#: ``adProductFilter.include`` enum. Exactly one per call ("Only one ad
#: product can be queried at a time" — live-verified), so the length of this
#: tuple is the hard bound on how many reads one capture may perform.
#:
#: SPONSORED_PRODUCTS leads purely as a commonality heuristic — it is the
#: ad product most advertisers run, so probing it first usually resolves on
#: the first read. That ordering is NOT a live-verified fact and is
#: correctness-neutral: whichever order is used, an entity is accepted only
#: when its id matches, so a "wrong" first probe costs one read, never a
#: wrong answer.
AD_PRODUCTS: tuple[str, ...] = (
    "SPONSORED_PRODUCTS",
    "AMAZON_DSP",
    "SPONSORED_BRANDS",
    "SPONSORED_DISPLAY",
    "SPONSORED_TELEVISION",
)

#: Inner bound — per-read ceiling on a capture's query. A hung read must not
#: hold the mutation hostage: on timeout the capture degrades to "no
#: reversal", exactly like any other read failure, and the mutation proceeds.
READ_TIMEOUT_SECONDS = 10.0

#: Outer bound — ceiling on the WHOLE capture, however many probes it takes.
#: The per-read timeout alone is not enough: five merely-slow reads would
#: each return in time and still stall a write for most of a minute. The
#: deadline is checked before every read and also caps that read's own
#: timeout, so a slow endpoint costs at most this much and then the write
#: proceeds — with whatever was captured before the deadline (unresolved
#: entities become caveats), or with no reversal at all if nothing was.
CAPTURE_DEADLINE_SECONDS = 15.0


def _monotonic() -> float:
    """Elapsed-time source for the capture deadline.

    A thin indirection so tests can drive the deadline deterministically
    instead of sleeping through it (wall-clock timing in tests is flaky).
    """
    return time.monotonic()


#: ``(id_field, entity_id) -> ad product``, learned from a probe that
#: actually resolved that id. Repeated captures on the same entity — the
#: common case in an optimisation loop — then hit on the first read instead
#: of walking the enum. Process-local, insertion-ordered, and bounded: the
#: oldest keys are evicted past :data:`_AD_PRODUCT_CACHE_MAX`. A stale entry
#: is self-correcting, since a miss simply falls through to a fresh probe.
_AD_PRODUCT_CACHE: dict[tuple[str, str], str] = {}
_AD_PRODUCT_CACHE_MAX = 512


@dataclass(frozen=True)
class ReversiblePair:
    """One mutation ↔ query pairing, verified against both inputSchemas.

    Attributes:
        query_tool: The tool that reads the before-state.
        collection: ``body`` key holding the mutation's item array.
        id_field: Item key identifying the entity (required by the mutation).
        id_filter: The query filter that selects exactly those ids.
        envelope: Expected response envelope key.
        fields: Fields this pairing may restore — the intersection of what
            the mutation can change and what the resource model exposes.
        ad_product_filter: Whether the query REQUIRES ``adProductFilter``.
    """

    query_tool: str
    collection: str
    id_field: str
    id_filter: str
    envelope: str
    fields: tuple[str, ...]
    ad_product_filter: bool = True


_CAMPAIGN_FIELDS = ("state", "budgets", "name")

_REVERSIBLE: dict[str, ReversiblePair] = {
    "campaign_management-update_campaign_state": ReversiblePair(
        query_tool="campaign_management-query_campaign",
        collection="campaigns",
        id_field="campaignId",
        id_filter="campaignIdFilter",
        envelope="campaigns",
        fields=("state",),
    ),
    "campaign_management-update_campaign_budget": ReversiblePair(
        query_tool="campaign_management-query_campaign",
        collection="campaigns",
        id_field="campaignId",
        id_filter="campaignIdFilter",
        envelope="campaigns",
        fields=("budgets",),
    ),
    "campaign_management-update_campaign": ReversiblePair(
        query_tool="campaign_management-query_campaign",
        collection="campaigns",
        id_field="campaignId",
        id_filter="campaignIdFilter",
        envelope="campaigns",
        fields=_CAMPAIGN_FIELDS,
    ),
    "campaign_management-update_ad": ReversiblePair(
        query_tool="campaign_management-query_ad",
        collection="ads",
        id_field="adId",
        id_filter="adIdFilter",
        envelope="ads",
        fields=("state", "name"),
    ),
    "campaign_management-update_ad_group": ReversiblePair(
        query_tool="campaign_management-query_ad_group",
        collection="adGroups",
        id_field="adGroupId",
        id_filter="adGroupIdFilter",
        envelope="adGroups",
        fields=("state", "name", "bid"),
    ),
    "campaign_management-update_target_bid": ReversiblePair(
        query_tool="campaign_management-query_target",
        collection="targets",
        id_field="targetId",
        id_filter="targetIdFilter",
        envelope="targets",
        fields=("bid",),
    ),
    "campaign_management-update_target": ReversiblePair(
        query_tool="campaign_management-query_target",
        collection="targets",
        id_field="targetId",
        id_filter="targetIdFilter",
        envelope="targets",
        fields=("state", "bid"),
    ),
    # query_portfolio is the one query tool that does NOT declare
    # adProductFilter, so a portfolio capture is always a single read.
    "campaign_management-update_portfolio": ReversiblePair(
        query_tool="campaign_management-query_portfolio",
        collection="portfolios",
        id_field="portfolioId",
        id_filter="portfolioIdFilter",
        envelope="portfolios",
        fields=("state", "name", "budget"),
        ad_product_filter=False,
    ),
}


def is_reversible_tool(name: str) -> bool:
    """True if ``name`` is a mutation this module can capture a reversal for."""
    return name in _REVERSIBLE


async def capture_reversal(
    dispatch: Dispatch, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Read the before-state of ``name``'s targets and build its reversal.

    Returns ``{"operation": name, "params": {...}}`` — the same tool with the
    previous values, directly executable by :mod:`mureo.rollback.planner` —
    plus ``caveats`` naming anything the capture could NOT restore. Returns
    ``None`` when the tool is not paired, when the arguments carry no usable
    account/id, or when nothing could be read back.

    A failing or timed-out probe is absorbed by :func:`_read_prior_state`,
    which logs it and returns what earlier rounds resolved — so a read
    failure degrades this call to a partial reversal, or to ``None``, rather
    than propagating. Anything raised outside that loop (a malformed
    ``dispatch``, an unexpected programming error) still surfaces, and
    :meth:`AmazonAdsBridge.capture_reversal` is the outer best-effort
    boundary that turns it into ``None``.
    """
    pair = _REVERSIBLE.get(name)
    if pair is None:
        return None
    body = arguments.get("body")
    if not isinstance(body, dict):
        return None
    account = body.get("accessRequestedAccount")
    if not isinstance(account, dict) or not account:
        return None
    raw_items = body.get(pair.collection)
    items = [i for i in raw_items if isinstance(i, dict)] if raw_items else []
    ids = _target_ids(pair, items)
    if not ids:
        return None
    prior = await _read_prior_state(dispatch, pair, account, items, ids)
    return _build_reversal(name, pair, account, items, prior)


def _target_ids(pair: ReversiblePair, items: list[dict[str, Any]]) -> list[str]:
    """Ordered, de-duplicated entity ids the mutation writes to."""
    ids: list[str] = []
    for item in items:
        value = item.get(pair.id_field)
        if isinstance(value, str) and value and value not in ids:
            ids.append(value)
    return ids


def _probe_order(
    pair: ReversiblePair, items: list[dict[str, Any]], ids: list[str]
) -> tuple[str | None, ...]:
    """The ad products to query with, best-first — see the module docstring.

    ``(None,)`` means "send no ``adProductFilter``", valid only for the query
    tool that does not declare one. Otherwise EVERY ad product is in the
    sequence: hints (cache, then the mutation's own ``adProduct``) only move
    a product to the front, so a hint that resolves some ids never strands
    the rest — the remaining products are still probed for them.
    """
    if not pair.ad_product_filter:
        return (None,)
    order: list[str] = []
    for hint in (*_cached_ad_products(pair, ids), *_declared_ad_products(items)):
        # Unknown values are dropped rather than sent: adProductFilter is a
        # closed enum, and an invalid one would fail the whole query.
        if hint in AD_PRODUCTS and hint not in order:
            order.append(hint)
    order.extend(product for product in AD_PRODUCTS if product not in order)
    return tuple(order)


def _cached_ad_products(pair: ReversiblePair, ids: list[str]) -> tuple[str, ...]:
    """Ad products previously observed for ``ids``, in id order."""
    return tuple(
        product
        for product in (_AD_PRODUCT_CACHE.get((pair.id_field, i)) for i in ids)
        if product is not None
    )


def _declared_ad_products(items: list[dict[str, Any]]) -> tuple[str, ...]:
    """``adProduct`` values the pending mutation itself carries, in item order."""
    return tuple(
        item["adProduct"]
        for item in items
        if isinstance(item.get("adProduct"), str) and item["adProduct"]
    )


def _remember_ad_products(
    pair: ReversiblePair, resolved: dict[str, dict[str, Any]], ad_product: str
) -> None:
    """Record which ad product resolved these ids, evicting oldest past the cap."""
    for entity_id in resolved:
        key = (pair.id_field, entity_id)
        _AD_PRODUCT_CACHE.pop(key, None)  # re-insert to refresh insertion order
        _AD_PRODUCT_CACHE[key] = ad_product
    while len(_AD_PRODUCT_CACHE) > _AD_PRODUCT_CACHE_MAX:
        del _AD_PRODUCT_CACHE[next(iter(_AD_PRODUCT_CACHE))]


def clear_ad_product_cache() -> None:
    """Drop every learned id → ad-product association (process-local)."""
    _AD_PRODUCT_CACHE.clear()


async def _read_prior_state(
    dispatch: Dispatch,
    pair: ReversiblePair,
    account: dict[str, Any],
    items: list[dict[str, Any]],
    ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Query the current state of ``ids``; return them keyed by id.

    Each round asks only for the ids still unresolved, and the loop stops as
    soon as none are left — or as soon as :data:`CAPTURE_DEADLINE_SECONDS`
    is spent, or a probe fails. All three exits return what was resolved so
    far, so the write proceeds immediately and earlier rounds' entities are
    never thrown away. Ids that no probe resolves are simply absent — the
    caller records no reversal for them rather than inventing one.
    """
    found: dict[str, dict[str, Any]] = {}
    remaining = list(ids)
    deadline = _monotonic() + CAPTURE_DEADLINE_SECONDS
    for ad_product in _probe_order(pair, items, ids):
        budget = deadline - _monotonic()
        if budget <= 0:
            break  # out of time — return the partial capture, do not stall
        try:
            result = await _read_once(
                dispatch, pair, account, remaining, ad_product, budget
            )
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001 — capture never blocks a write
            # A failed or timed-out probe ends the walk but must NOT discard
            # entities resolved in earlier rounds: they are real before-states,
            # and dropping them would silently turn a recoverable partial
            # reversal into no reversal at all. The unresolved ones become
            # caveats downstream, exactly as a deadline stop does.
            #
            # The failure's text is deliberately NOT logged — only its type,
            # matching AmazonAdsBridge.capture_reversal. The diagnostic value
            # is in which query failed and how much survived; the message
            # could carry anything the platform put in it.
            logger.warning(
                "Amazon before-state read %r failed (%s); keeping the %d "
                "entit%s already captured",
                pair.query_tool,
                type(exc).__name__,
                len(found),
                "y" if len(found) == 1 else "ies",
            )
            break
        resolved = _parse_entities(result, pair, set(remaining))
        if resolved and ad_product is not None:
            _remember_ad_products(pair, resolved, ad_product)
        found.update(resolved)
        remaining = [i for i in remaining if i not in found]
        if not remaining:
            break
    return found


async def _read_once(
    dispatch: Dispatch,
    pair: ReversiblePair,
    account: dict[str, Any],
    ids: list[str],
    ad_product: str | None,
    budget: float,
) -> list[Any]:
    """One doubly-bounded query through the bridge's dispatch.

    Bounded by the per-read timeout AND by what is left of the capture
    deadline, so no single read can overrun the outer bound. A timeout is
    raised as an ordinary failure; :func:`_read_prior_state` catches it,
    keeps whatever earlier rounds resolved, and lets the mutation go ahead.
    """
    timeout = min(READ_TIMEOUT_SECONDS, budget)
    try:
        return await asyncio.wait_for(
            dispatch(pair.query_tool, _query_arguments(pair, account, ids, ad_product)),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"Amazon before-state read {pair.query_tool!r} exceeded {timeout:.1f}s"
        ) from exc


def _query_arguments(
    pair: ReversiblePair,
    account: dict[str, Any],
    ids: list[str],
    ad_product: str | None,
) -> dict[str, Any]:
    """Build the query payload: the caller's account verbatim + the id filter."""
    body: dict[str, Any] = {
        "accessRequestedAccount": copy.deepcopy(account),
        pair.id_filter: {"include": list(ids)},
    }
    if ad_product is not None:
        body["adProductFilter"] = {"include": [ad_product]}
    return {"body": body}


def _parse_entities(
    result: list[Any], pair: ReversiblePair, wanted: set[str]
) -> dict[str, dict[str, Any]]:
    """Pull the wanted entities out of an MCP tool result. Never raises.

    Defensive on every axis, because no Amazon tool declares an
    ``outputSchema``: non-text blocks, non-JSON text and unexpected shapes
    are skipped.

    ONLY the declared ``envelope`` key is read. Scanning the payload's other
    lists for something id-shaped was tried and removed: a sibling list of a
    different resource can carry the same id *and* a same-named field —
    ``{"bidRecommendations": [{"targetId": "T1", "bid": {"suggested": 0.02}}]}``
    passes every structural check a scanner can apply, and would have been
    recorded as a confident, uncaveated bid to "restore". The envelope key is
    live-verified for campaigns and ads, and in both verified cases it equals
    the write-side array name (``campaigns``, ``ads``); that is the rule
    inferred for ``adGroups`` / ``targets`` / ``portfolios``. Should the
    inference ever be wrong, the capture records NOTHING — which is exactly
    the outcome this module prefers over a plausible-looking wrong value.

    Within that envelope an entity is accepted only when its ``id_field``
    matches a requested id AND it carries at least one field this pairing
    can restore.
    """
    found: dict[str, dict[str, Any]] = {}
    for block in result if isinstance(result, list) else []:
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if not isinstance(payload, dict):
            continue
        entities = payload.get(pair.envelope)
        if isinstance(entities, list):
            found.update(_match_entities(entities, pair, wanted))
    return found


def _match_entities(
    group: list[Any], pair: ReversiblePair, wanted: set[str]
) -> dict[str, dict[str, Any]]:
    """Entities in ``group`` whose id is wanted (see :func:`_parse_entities`)."""
    matched: dict[str, dict[str, Any]] = {}
    for entity in group:
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get(pair.id_field)
        if not isinstance(entity_id, str) or entity_id not in wanted:
            continue
        if not any(field in entity for field in pair.fields):
            continue
        matched[entity_id] = entity
    return matched


def _build_reversal(
    name: str,
    pair: ReversiblePair,
    account: dict[str, Any],
    items: list[dict[str, Any]],
    prior: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Assemble the executable reversal, or ``None`` if nothing is restorable.

    Only a field the mutation actually sets AND the query actually returned
    is restored. Everything else — an unreadable entity, a field missing from
    the response, a changed field outside this pairing — is reported as a
    caveat, which the rollback planner surfaces as a PARTIAL plan.
    """
    restored_items: list[dict[str, Any]] = []
    caveats: list[str] = []
    for item in items:
        entity_id = item.get(pair.id_field)
        if not isinstance(entity_id, str):
            continue
        before = prior.get(entity_id)
        if before is None:
            caveats.append(
                f"{pair.id_field} {entity_id}: prior state could not be read; "
                f"this entity is not reversed."
            )
            continue
        restored = {pair.id_field: entity_id}
        for field in pair.fields:
            if field in item and field in before:
                restored[field] = copy.deepcopy(before[field])
        missing = sorted(set(item) - set(restored))
        if len(restored) == 1:
            caveats.append(
                f"{pair.id_field} {entity_id}: no prior value was readable for "
                f"{missing}; this entity is not reversed."
            )
            continue
        restored_items.append(restored)
        if missing:
            caveats.append(
                f"{pair.id_field} {entity_id}: {missing} are not reversed "
                f"(no prior value in the query response)."
            )
    if not restored_items:
        return None
    reversal: dict[str, Any] = {
        "operation": name,
        "params": {
            "body": {
                "accessRequestedAccount": copy.deepcopy(account),
                pair.collection: restored_items,
            }
        },
    }
    if caveats:
        reversal["caveats"] = caveats
    return reversal


__all__ = [
    "AD_PRODUCTS",
    "CAPTURE_DEADLINE_SECONDS",
    "READ_TIMEOUT_SECONDS",
    "ReversiblePair",
    "capture_reversal",
    "clear_ad_product_cache",
    "is_reversible_tool",
]
