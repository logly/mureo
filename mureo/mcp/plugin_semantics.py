"""Phase 2 of #114: derive safety semantics for plugin MCP tools and
promote *mutating* plugin calls into STATE.json's ``action_log``.

A plugin opts into richer treatment purely through **standard MCP**
metadata — no new mureo Protocol surface:

- ``Tool.annotations.readOnlyHint`` → believed verbatim, either way:
  ``True`` means the tool is a read and stays in the dedicated plugin
  audit log only (no STATE.json write), ``False`` means it mutates.
- **No** ``readOnlyHint`` at all (no annotations, or annotations that
  omit it — e.g. ``destructiveHint`` only) → the name is consulted
  through the shared read vocabulary
  (:func:`mureo.core.tool_names.is_read_only_tool_name`), and only a
  name that does not read as a read falls through to the conservative
  **mutating** default (issue #517). A bridged surface is not obliged
  to annotate: of 85 tools on one real Amazon manifest, two omit the
  hint and both are plainly ``list_`` reads — promoting those to
  STATE.json's ``action_log`` with a 14-day ``observation_due`` filed
  invoice listings as changes to review.
- Optional ``Tool.meta["mureo"]``:
    - ``reversal``: a dict recorded verbatim into the action_log
      entry's ``reversible_params`` so ``rollback_plan_get`` can see
      the intent. NOTE: the rollback *planner* only builds an actual
      reversal when ``reversal["operation"]`` is in its built-in
      allow-list — arbitrary plugin operations are recorded for audit
      but not auto-reversible. Honest scope, documented.
    - ``throttle``: ``{"rate": float, "burst": int}`` → a dedicated
      Throttler for that tool; invalid/absent ⇒ shared default.
    - ``identity``: argument-key declarations for action-log identity, e.g.
      ``{"campaign_id": "campaignId", "entity_type": "placement",
      "entity_id": "placementId"}``. Common argument names are also detected
      when this declaration is absent.

Mutations are promoted to the action_log **only when a STATE.json
already exists in cwd** — we never litter an arbitrary working
directory with a new STATE.json just because a plugin tool ran. The
plugin audit log (Phase 1) always captures the call regardless.
Promotion is best-effort and never raises (auditing/strategy
visibility must not break the tool call).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.core import clock
from mureo.core.platform_keys import plugin_platform_key
from mureo.core.tool_names import is_read_only_tool_name
from mureo.policy.declarations import BidDeclaration, BudgetDeclaration
from mureo.throttle import ThrottleConfig

if TYPE_CHECKING:
    from mcp.types import Tool

logger = logging.getLogger(__name__)

# Phase 4 (#114): structural strategy parity. A built-in mutation gets
# an observation window (set contextually by its platform skill) so the
# daily-check evidence loop reviews the outcome. An arbitrary plugin has
# no per-platform skill to set one, so the mechanical promotion applies
# a conservative default window — long enough to avoid single-day-noise
# conclusions (daily-check requires ≥7 consecutive days) and matching
# the "keyword/creative changes 14 days" guidance in ActionLogEntry.
# A plugin may shorten/lengthen it via meta["mureo"]["observation_days"].
_DEFAULT_OBSERVATION_DAYS = 14


#: Accepted ``budget.unit`` spellings → whether the value is in micros.
_BUDGET_UNITS = {"currency": False, "micros": True}

#: Accepted ``bid.unit`` spellings → whether the value is in micros. Shares the
#: budget vocabulary: ``currency`` means "compare as-is" (minor units for the
#: ``bid_amount`` channel, currency units for ``cpc_bid``), ``micros`` divides
#: by 1e6 — exactly like the built-in ``cpc_bid_micros`` path.
_BID_UNITS = {"currency": False, "micros": True}


@dataclass(frozen=True)
class IdentityDeclaration:
    """Argument keys and target kind used to identify a plugin mutation."""

    campaign_id_key: str | None = None
    ad_id_key: str | None = None
    entity_type: str | None = None
    entity_id_key: str | None = None


@dataclass(frozen=True)
class ToolSemantics:
    """Safety classification derived from a plugin tool's MCP metadata."""

    mutating: bool
    reversal: dict[str, Any] | None = None
    throttle: ThrottleConfig | None = None
    observation_days: int | None = None
    budget: BudgetDeclaration | None = None
    bid: BidDeclaration | None = None
    identity: IdentityDeclaration | None = None


def _parse_identity(raw: Any) -> IdentityDeclaration | None:
    """Parse ``meta["mureo"]["identity"]`` as an all-valid declaration.

    ``campaign_id``, ``ad_id``, and ``entity_id`` name top-level tool
    arguments. ``entity_type`` is the stable literal kind stored beside the
    generic entity id. A generic id/type must be supplied as a pair; malformed
    declarations are ignored whole so partial identity is never implied.
    """
    if not isinstance(raw, dict):
        return None

    def _text(name: str) -> str | None:
        value = raw.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    allowed = {"campaign_id", "ad_id", "entity_type", "entity_id"}
    if any(name not in allowed for name in raw):
        return None
    for name in raw:
        if _text(name) is None:
            return None
    entity_type = _text("entity_type")
    entity_id_key = _text("entity_id")
    if (entity_type is None) != (entity_id_key is None):
        return None
    declaration = IdentityDeclaration(
        campaign_id_key=_text("campaign_id"),
        ad_id_key=_text("ad_id"),
        entity_type=entity_type,
        entity_id_key=entity_id_key,
    )
    if not any((declaration.campaign_id_key, declaration.ad_id_key, entity_id_key)):
        return None
    return declaration


def _parse_budget(raw: Any) -> BudgetDeclaration | None:
    """Parse ``meta["mureo"]["budget"]``, or ``None`` when unusable (#414).

    A malformed hint is rejected WHOLE rather than half-applied: a partial
    declaration would re-create the exact silent-underenforcement the seam
    exists to remove. Requires a dict carrying at least one of ``daily`` /
    ``lifetime`` as a non-blank string key name; ``current`` is optional;
    ``unit`` is ``currency`` (default) or ``micros``.
    """
    if not isinstance(raw, dict):
        return None
    unit = raw.get("unit", "currency")
    if not isinstance(unit, str) or unit not in _BUDGET_UNITS:
        return None

    def _key(name: str) -> str | None:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    daily = _key("daily")
    lifetime = _key("lifetime")
    if daily is None and lifetime is None:
        return None
    # A declared-but-unusable key name (non-str) is a mistake, not an
    # omission — refuse the whole declaration so it surfaces in testing
    # rather than silently dropping one cap.
    for name in ("daily", "lifetime", "current"):
        if name in raw and _key(name) is None:
            return None
    return BudgetDeclaration(
        daily_key=daily,
        lifetime_key=lifetime,
        current_key=_key("current"),
        micros=_BUDGET_UNITS[unit],
    )


def _parse_bid(raw: Any) -> BidDeclaration | None:
    """Parse ``meta["mureo"]["bid"]``, or ``None`` when unusable.

    The bid twin of :func:`_parse_budget`, held to the identical whole-or-
    nothing discipline: a partial declaration would re-create the exact silent
    underenforcement this seam exists to remove. Requires a dict carrying at
    least one of ``bid_amount`` / ``cpc_bid`` as a non-blank string key name;
    ``unit`` is ``currency`` (default) or ``micros``.
    """
    if not isinstance(raw, dict):
        return None
    unit = raw.get("unit", "currency")
    if not isinstance(unit, str) or unit not in _BID_UNITS:
        return None

    def _key(name: str) -> str | None:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    bid_amount = _key("bid_amount")
    cpc_bid = _key("cpc_bid")
    if bid_amount is None and cpc_bid is None:
        return None
    # A declared-but-unusable key name (non-str) is a mistake, not an
    # omission — refuse the whole declaration so it surfaces in testing
    # rather than silently dropping one cap.
    for name in ("bid_amount", "cpc_bid"):
        if name in raw and _key(name) is None:
            return None
    return BidDeclaration(
        bid_amount_key=bid_amount,
        cpc_bid_key=cpc_bid,
        micros=_BID_UNITS[unit],
    )


def _meta_mureo(tool: Tool) -> dict[str, Any]:
    """Return ``meta["mureo"]`` if present, else ``{}``.

    MCP's ``Tool.meta`` field is aliased ``_meta``; a plugin author who
    builds ``Tool(meta=...)`` (the intuitive spelling) does NOT populate
    the real field — pydantic ``extra="allow"`` stashes it in
    ``__pydantic_extra__`` instead. Accept both so the documented and
    the intuitive spelling behave identically.
    """
    meta = getattr(tool, "meta", None)
    if not isinstance(meta, dict):
        extra = getattr(tool, "__pydantic_extra__", None)
        meta = extra.get("meta") if isinstance(extra, dict) else None
    if isinstance(meta, dict):
        section = meta.get("mureo")
        if isinstance(section, dict):
            return section
    return {}


def _is_read(tool: Tool) -> bool:
    """Is ``tool`` a read? Declaration first, name shape only as a fallback.

    An explicit ``readOnlyHint`` always wins — including an explicit
    ``False``, which is a plugin author saying "this mutates" and must not
    be overturned by a read-shaped name. Only when the hint is ABSENT does
    the name decide, through the same vocabulary the rollback planner and
    the guardrail pattern-fallback registration already share, so the three
    surfaces cannot answer "is this a read?" differently (#517).
    """
    hint = getattr(getattr(tool, "annotations", None), "readOnlyHint", None)
    if hint is not None:
        return hint is True
    return is_read_only_tool_name(getattr(tool, "name", "") or "")


def derive_semantics(tool: Tool) -> ToolSemantics:
    """Classify one plugin tool from standard MCP annotations + meta."""
    mutating = not _is_read(tool)

    section = _meta_mureo(tool)
    reversal = section.get("reversal")
    reversal = reversal if isinstance(reversal, dict) else None

    throttle: ThrottleConfig | None = None
    raw = section.get("throttle")
    if isinstance(raw, dict):
        try:
            throttle = ThrottleConfig(
                rate=float(raw["rate"]),
                burst=int(raw["burst"]),
                hourly_limit=(
                    int(raw["hourly_limit"])
                    if raw.get("hourly_limit") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            throttle = None  # malformed hint → fall back to shared default

    observation_days: int | None = None
    raw_days = section.get("observation_days")
    # bool is an int subclass — exclude it; require a positive int.
    if isinstance(raw_days, int) and not isinstance(raw_days, bool) and raw_days > 0:
        observation_days = raw_days

    return ToolSemantics(
        mutating=mutating,
        reversal=reversal,
        throttle=throttle,
        observation_days=observation_days,
        budget=_parse_budget(section.get("budget")),
        bid=_parse_bid(section.get("bid")),
        identity=_parse_identity(section.get("identity")),
    )


_CAMPAIGN_ID_KEYS = ("campaign_id", "campaignId")
_AD_ID_KEYS = ("ad_id", "adId")
_ENTITY_ID_KEYS = (
    ("ad_group_id", "ad_group"),
    ("adGroupId", "ad_group"),
    ("ad_set_id", "ad_set"),
    ("adSetId", "ad_set"),
    ("placement_id", "placement"),
    ("placementId", "placement"),
    ("adspot_id", "adspot"),
    ("adspotId", "adspot"),
)


def _identity_value(arguments: dict[str, Any], key: str | None) -> str | None:
    """Return one scalar argument as a non-blank string identity."""
    if key is None:
        return None
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_identity_value(
    arguments: dict[str, Any], keys: tuple[str, ...]
) -> str | None:
    """Return the first populated identity among equivalent key spellings."""
    for key in keys:
        value = _identity_value(arguments, key)
        if value is not None:
            return value
    return None


def extract_mutation_identity(
    arguments: dict[str, Any], declaration: IdentityDeclaration | None = None
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract campaign, ad, and generic entity identity from tool arguments.

    An explicit declaration is authoritative: only its declared keys are
    extracted, so an undeclared context id cannot silently become the target.
    With no declaration, common top-level spellings provide a backward-
    compatible fallback, including the cheap campaign-level fix. In that
    fallback an ``ad_id`` is the canonical target and parent context such as
    ``ad_group_id`` / ``ad_set_id`` is not also promoted.
    """
    if declaration is not None:
        campaign_id = _identity_value(arguments, declaration.campaign_id_key)
        ad_id = _identity_value(arguments, declaration.ad_id_key)
        declared_entity_id = _identity_value(arguments, declaration.entity_id_key)
        declared_entity_type = (
            declaration.entity_type if declared_entity_id is not None else None
        )
        return campaign_id, ad_id, declared_entity_type, declared_entity_id

    campaign_id = _first_identity_value(arguments, _CAMPAIGN_ID_KEYS)
    ad_id = _first_identity_value(arguments, _AD_ID_KEYS)
    entity_type: str | None = None
    entity_id: str | None = None
    if ad_id is None:
        direct_type = _identity_value(arguments, "entity_type")
        direct_id = _identity_value(arguments, "entity_id")
        if direct_type is not None and direct_id is not None:
            entity_type, entity_id = direct_type, direct_id
    if entity_id is None and ad_id is None:
        for key, kind in _ENTITY_ID_KEYS:
            candidate = _identity_value(arguments, key)
            if candidate is not None:
                entity_type, entity_id = kind, candidate
                break
    return campaign_id, ad_id, entity_type, entity_id


def record_mutation_action_log(
    *,
    tool: str,
    source: str,
    reversal: dict[str, Any] | None,
    arguments: dict[str, Any] | None = None,
    identity: IdentityDeclaration | None = None,
    observation_days: int | None = None,
    provider: str = "",
) -> None:
    """Append a plugin mutation to STATE.json's action_log. Never raises.

    ``source`` is the pip distribution and ``provider`` the entry-point
    name the calling provider was registered under; together they are the
    canonical platform key (#537). ``provider`` defaults to ``""`` for a
    caller that cannot name it (an instance whose breadcrumb is missing),
    which writes the legacy ``plugin:<dist>`` short form rather than
    fabricating a provider.

    No-op (jsonl audit still has it) when there is no STATE.json in cwd.
    Called only after a *successful* call; a failed mutation did not
    change platform state, so it is intentionally NOT promoted here —
    failed attempts live in the Phase 1 jsonl audit only (by design).

    Phase 4 (#114): an ``observation_due`` window is always set so the
    entry enters the same evidence/outcome-review loop a built-in
    mutation does (daily-check step 9 / ``_mureo-learning``). It is
    ``observation_days`` (when the plugin declared one) or the
    conservative default. ``metrics_at_action`` is intentionally left
    unset — capturing baseline metrics is platform-specific analytics
    that does not exist for an arbitrary plugin; the outcome review
    falls back to a qualitative read, by design.
    """
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        # Server clock (#460) — same stamp/format as every other writer.
        now = clock.server_now()
        days = observation_days or _DEFAULT_OBSERVATION_DAYS
        campaign_id, ad_id, entity_type, entity_id = extract_mutation_identity(
            arguments or {}, identity
        )
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action=tool,
            # Issues #481 / #537: the canonical key every surface joins on
            # — distribution AND provider, so a distribution shipping
            # several platforms does not file them all under one name. See
            # mureo.core.platform_keys.
            platform=plugin_platform_key(source or "unknown", provider),
            campaign_id=campaign_id,
            ad_id=ad_id,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=f"plugin tool {tool} (mutating)",
            command=tool,
            observation_due=(now + timedelta(days=days)).date().isoformat(),
            reversible_params=reversal,
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "plugin action_log promotion failed for tool %r", tool, exc_info=True
        )
