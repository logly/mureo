"""The ``platforms`` / ``campaigns`` / ``ads`` entries' two codec halves (#881).

Split out of :mod:`mureo.context.state_codec` for the reason
:mod:`mureo.context._action_log_codec` was: that file is at the repo's size
limit. The document-level loop and the import-time coverage check stay
there; the check builds these models' rows from :data:`PLATFORM_KNOWN_KEYS` /
:data:`CAMPAIGN_KNOWN_KEYS` / :data:`AD_KNOWN_KEYS`, so a model field this
module does not name still fails at import.

**No object entry can block a write** — the rule #859 set for ``action_log``,
applied to a platform entry, a campaign entry (top-level ``campaigns`` and
``platforms.<key>.campaigns``) and an ad entry. There is no mode: the strict
writer and the read-only view build every object entry the same way.

- An entry missing a required key — ``account_id`` (platform),
  ``campaign_id`` / ``campaign_name`` / ``status`` (campaign), ``ad_id``
  (ad) — or carrying keys the codec does not know reads with the missing
  keys as ``""`` and keeps its on-disk dict as ``raw``. A campaign or ad
  whose required key is null or not a string reads it as ``""`` too. A
  platform's ``account_id`` that is present is read as found, whatever its
  type, exactly as before: :func:`~mureo.context.platform_accounts.
  normalize_account_id` already folds a hand-edited number to its string, so
  such an id keeps joining. ``""`` is the unknown id
  (:data:`~mureo.context.platform_accounts.UNKNOWN_ACCOUNT_ID`): it joins no
  account and matches no upsert.
- **A value the model cannot represent** — a ``campaigns`` or ``ads`` value
  that is not a list or holds an entry that is not an object, or a
  ``device_targeting`` that is not a list — is kept in the ENCLOSING entry's
  ``raw``. The parsed field holds what the model can represent (the object
  entries of a list; ``()`` for ``campaigns``, ``None`` for ``ads`` /
  ``device_targeting`` otherwise), and on write the value is emitted
  verbatim as long as the field still equals what the stored value parses
  to. A mureo writer that changes the field (an upsert into that platform,
  ads supplied for that campaign) writes the model's list; when the stored
  value was a list, its non-object entries are re-inserted at their original
  positions, so a writer never drops them. Any other stored value (a string,
  ``null``, an object) is replaced.

On write, an entry with ``raw`` is re-emitted in its on-disk key order with
mureo's current values on top (:func:`mureo.context._preserve.
preserved_dict`, the rule ``action_log`` uses): unknown keys are copied,
a required key whose current value is ``""`` is emitted exactly as found
(absent stays absent), and a field mureo set that is not on disk follows in
the codec's order. An entry without ``raw`` — every entry mureo constructs —
is emitted exactly as before. A preserved platform without a ``campaigns``
key gains none unless a writer added a campaign.

A campaign's or platform's ``raw`` holds only what that re-emission reads
(:func:`_trimmed_raw`), not a copy of every figure in the entry.

A value with no enclosing entry — a top-level ``campaigns`` that is not a
list of objects, a ``platforms`` value or a platform value that is not an
object, a top-level value that is not an object — is refused by
:func:`mureo.context.state_codec.parse_state` with a ``ValueError`` naming
the section (in both modes, except the top-level ``campaigns``, which the
read-only view reads tolerantly). Keeping those verbatim is #882.

Dependency-free beyond stdlib and :mod:`mureo.context.models` /
:mod:`mureo.context._preserve` — the discipline ``state_codec`` keeps.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from mureo.context._preserve import preserved_dict
from mureo.context.models import (
    NOT_COLLECTED_REASON_MAX_CHARS,
    AdState,
    CampaignSnapshot,
    PlatformState,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

logger = logging.getLogger(__name__)

_AD_REQUIRED_KEYS: tuple[str, ...] = ("ad_id",)
#: Emitted only when set, in this order.
_AD_OPTIONAL_KEYS: tuple[str, ...] = ("name", "status", "effective_status", "as_of")
AD_KNOWN_KEYS: frozenset[str] = frozenset((*_AD_REQUIRED_KEYS, *_AD_OPTIONAL_KEYS))

_CAMPAIGN_REQUIRED_KEYS: tuple[str, ...] = ("campaign_id", "campaign_name", "status")
#: Emitted always, ``null`` when unset — the shape every campaign has had.
_CAMPAIGN_ALWAYS_KEYS: tuple[str, ...] = (
    "bidding_strategy_type",
    "bidding_details",
    "daily_budget",
    "device_targeting",
    "campaign_goal",
    "notes",
)
#: Emitted only when set (#656 / #468), after the keys above.
_CAMPAIGN_OPTIONAL_KEYS: tuple[str, ...] = ("monthly_budget", "metrics", "ads")
CAMPAIGN_KNOWN_KEYS: frozenset[str] = frozenset(
    (*_CAMPAIGN_REQUIRED_KEYS, *_CAMPAIGN_ALWAYS_KEYS, *_CAMPAIGN_OPTIONAL_KEYS)
)

_PLATFORM_REQUIRED_KEYS: tuple[str, ...] = ("account_id",)
PLATFORM_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "account_id",
        "campaigns",
        "totals",
        "metrics_period",
        "periods",
        "daily",
        "conversion_action_types",
        "not_collected",
    }
)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def is_object_list(value: Any) -> bool:
    """Whether ``value`` is a list whose every entry is an object."""
    return isinstance(value, list) and all(isinstance(x, dict) for x in value)


def _ads_representable(value: Any) -> bool:
    return value is None or is_object_list(value)


def _device_targeting_representable(value: Any) -> bool:
    return value is None or isinstance(value, list)


def _unrepresentable(
    entry: dict[str, Any], required: tuple[str, ...], known: frozenset[str]
) -> bool:
    """Whether a required key is not a string or an unknown key is present."""
    if any(not isinstance(entry.get(k), str) for k in required):
        return True
    return any(k not in known for k in entry)


def _required_strings(
    entry: dict[str, Any], required: tuple[str, ...]
) -> dict[str, str]:
    """The required keys of ``entry``; anything but a string is ``""``."""
    return {k: entry[k] if isinstance(entry.get(k), str) else "" for k in required}


def _trimmed_raw(
    entry: dict[str, Any],
    required: tuple[str, ...],
    known: frozenset[str],
    kept: tuple[tuple[str, Callable[[Any], Any], Callable[[Any], bool]], ...],
) -> dict[str, Any]:
    """What re-emitting ``entry`` reads of it, in its on-disk key order.

    :func:`~mureo.context._preserve.preserved_dict` (always ``opaque=False``
    here) reads a required key's value and an unknown key's value, and only
    the POSITION of every other known key — the entry's current value is
    written there. :func:`_kept_values` reads a ``kept`` key's value only
    when the model cannot represent it. Everything else is stored as a
    placeholder instead of a copy of the platform's ``daily`` / ``periods``
    or every campaign's ``metrics``, which each ``dataclasses.replace`` would
    deep-copy again: ``None`` for a known key, ``[]`` for a ``kept`` key the
    model represents (``[]``, not ``None``, because a ``null`` ``campaigns``
    is itself an unrepresentable value, kept as found).
    """
    representable = {key: ok for key, _parse, ok in kept}
    result: dict[str, Any] = {}
    for key, value in entry.items():
        if key in required or key not in known:
            result[key] = value
        elif key in representable:
            result[key] = [] if representable[key](value) else value
        else:
            result[key] = None
    return result


def parse_ad(a: dict[str, Any]) -> AdState:
    """Create an :class:`AdState` from an object entry of a campaign's ``ads``."""
    keep = _unrepresentable(a, _AD_REQUIRED_KEYS, AD_KNOWN_KEYS)
    return AdState(
        **_required_strings(a, _AD_REQUIRED_KEYS),
        name=a.get("name"),
        status=a.get("status"),
        effective_status=a.get("effective_status"),
        as_of=a.get("as_of"),
        raw=a if keep else None,
    )


def parse_ads(value: Any) -> tuple[AdState, ...] | None:
    """A campaign's ``ads`` (#468): its object entries, or ``None``.

    ``None`` when the key is absent — "ad-level status was never fetched",
    which must stay distinguishable from ``()`` ("fetched, no ads") — and
    when the value is not a list (the campaign's ``raw`` keeps it).
    """
    if not isinstance(value, list):
        return None
    return tuple(parse_ad(a) for a in value if isinstance(a, dict))


def _parse_device_targeting(value: Any) -> tuple[Any, ...] | None:
    """``device_targeting`` as a tuple; ``None`` unless it is a list."""
    return tuple(value) if isinstance(value, list) else None


#: A campaign's values the model may not represent: ``(key, parser,
#: representable)``. The key is also the :class:`CampaignSnapshot` field.
_CAMPAIGN_KEPT: tuple[tuple[str, Callable[[Any], Any], Callable[[Any], bool]], ...] = (
    ("ads", parse_ads, _ads_representable),
    ("device_targeting", _parse_device_targeting, _device_targeting_representable),
)


def _campaign_keeps_raw(c: dict[str, Any]) -> bool:
    return (
        _unrepresentable(c, _CAMPAIGN_REQUIRED_KEYS, CAMPAIGN_KNOWN_KEYS)
        or not _ads_representable(c.get("ads"))
        or not _device_targeting_representable(c.get("device_targeting"))
    )


def parse_campaign(c: dict[str, Any]) -> CampaignSnapshot:
    """Create a :class:`CampaignSnapshot` from an object campaign entry."""
    return CampaignSnapshot(
        **_required_strings(c, _CAMPAIGN_REQUIRED_KEYS),
        bidding_strategy_type=c.get("bidding_strategy_type"),
        bidding_details=c.get("bidding_details"),
        daily_budget=c.get("daily_budget"),
        monthly_budget=c.get("monthly_budget"),
        device_targeting=_parse_device_targeting(c.get("device_targeting")),
        campaign_goal=c.get("campaign_goal"),
        notes=c.get("notes"),
        metrics=c.get("metrics"),
        ads=parse_ads(c.get("ads")),
        raw=(
            _trimmed_raw(
                c, _CAMPAIGN_REQUIRED_KEYS, CAMPAIGN_KNOWN_KEYS, _CAMPAIGN_KEPT
            )
            if _campaign_keeps_raw(c)
            else None
        ),
    )


def parse_campaigns(value: Any) -> tuple[CampaignSnapshot, ...]:
    """The object entries of a ``campaigns`` value; ``()`` unless it is a list."""
    if not isinstance(value, list):
        return ()
    return tuple(parse_campaign(c) for c in value if isinstance(c, dict))


def _parse_conversion_action_types(raw: Any) -> tuple[str, ...] | None:
    """Parse a platform's ``conversion_action_types`` override (#342).

    Returns a tuple of non-empty string action_types, or ``None`` when the
    field is absent / not a list / has no usable entries (so the counters
    fall back to the built-in generic set). Tolerant by design — a malformed
    value degrades to "no override" rather than raising.
    """
    if not isinstance(raw, list):
        return None
    cleaned = tuple(str(x).strip() for x in raw if isinstance(x, str) and x.strip())
    return cleaned or None


def parse_not_collected(raw: Any) -> dict[str, Any] | None:
    """Parse a "why this was not collected" note.

    Both of them: a platform's ``not_collected`` (#638) and the document's
    ``workspace_not_collected`` (#661). They are the same two fields under the
    same rules, so they are normalised by one function — two copies is how the
    two levels would start disagreeing about what a note IS, while an operator
    reads them side by side. What they mean, and what retires each, is what
    differs, and that is decided by the readers, not here.

    Returns ``{"attempted_at": ..., "reason": ...}`` (``attempted_at`` only
    when it is a usable string), or ``None`` when there is no usable note.

    **No reason means no note.** The reason IS the payload: a note carrying
    only a timestamp tells an operator that something happened and refuses to
    say what, which is the exact non-answer this field exists to end.

    Tolerant like the other optional platform fields — a hand-edited value
    costs the note, never the document — and normalising to the two known keys
    here keeps every reader (dashboard, CLI, a plugin) working from one shape.

    ``reason`` is capped at
    :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS`, the same
    bound the write helper and the dashboard apply. Doing it on READ too is
    what stops a page of API JSON from a hand edit or an outside writer being
    re-serialised in full on every subsequent write.
    """
    if not isinstance(raw, dict):
        return None
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    note: dict[str, Any] = {}
    attempted_at = raw.get("attempted_at")
    if isinstance(attempted_at, str) and attempted_at.strip():
        note["attempted_at"] = attempted_at.strip()
    note["reason"] = reason.strip()[:NOT_COLLECTED_REASON_MAX_CHARS]
    return note


def _platform_account_id(platform_key: str, p: dict[str, Any]) -> str:
    """A platform's ``account_id`` as found, or ``""`` (unknown) when absent.

    Logged at DEBUG (expected for a hand-authored file; never a per-poll
    WARNING — the read-only view re-parses on every poll).
    """
    if "account_id" in p:
        # Annotated local so mypy treats the dict[str, Any] value as the
        # declared str; a hand-edited number is read as found (see the
        # module docstring).
        account_id: str = p["account_id"]
        return account_id
    logger.debug("platform %r missing 'account_id'; reading it as ''", platform_key)
    return ""


#: A platform's values the model may not represent, as :data:`_CAMPAIGN_KEPT`.
_PLATFORM_KEPT: tuple[tuple[str, Callable[[Any], Any], Callable[[Any], bool]], ...] = (
    ("campaigns", parse_campaigns, is_object_list),
)


def parse_platform(platform_key: str, p: dict[str, Any]) -> PlatformState:
    """Create a :class:`PlatformState` from an object platform entry."""
    campaigns = p.get("campaigns", [])
    keep = "account_id" not in p or any(k not in PLATFORM_KNOWN_KEYS for k in p)
    return PlatformState(
        account_id=_platform_account_id(platform_key, p),
        campaigns=parse_campaigns(campaigns),
        totals=p.get("totals"),
        metrics_period=p.get("metrics_period"),
        periods=p.get("periods"),
        daily=p.get("daily"),
        conversion_action_types=_parse_conversion_action_types(
            p.get("conversion_action_types")
        ),
        not_collected=parse_not_collected(p.get("not_collected")),
        raw=(
            _trimmed_raw(
                p, _PLATFORM_REQUIRED_KEYS, PLATFORM_KNOWN_KEYS, _PLATFORM_KEPT
            )
            if keep or not is_object_list(campaigns)
            else None
        ),
    )


def carries_unread_content(ps: PlatformState) -> bool:
    """Whether ``ps`` holds content its fields do not show (#881).

    A key the codec does not know, or a ``campaigns`` value the model cannot
    represent. Both are kept in ``raw`` and written back on every write, and
    neither is counted by a reader of the fields — so an entry carrying one
    is not empty, whatever its fields say.
    """
    if ps.raw is None:
        return False
    if any(key not in PLATFORM_KNOWN_KEYS for key in ps.raw):
        return True
    return "campaigns" in ps.raw and not is_object_list(ps.raw["campaigns"])


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def _with_non_objects(stored: list[Any], current: list[Any]) -> list[Any]:
    """``current`` with ``stored``'s non-object entries put back (#881).

    Each at its original index — ``list.insert`` clamps one past the end to
    an append — in original order, so a writer that replaced the object
    entries never drops the entries the model could not hold.
    """
    result = list(current)
    for index, item in enumerate(stored):
        if not isinstance(item, dict):
            result.insert(index, copy.deepcopy(item))
    return result


def _kept_values(
    raw: Mapping[str, Any],
    model: object,
    kept: tuple[tuple[str, Callable[[Any], Any], Callable[[Any], bool]], ...],
    canonical: Mapping[str, Any],
) -> dict[str, Any]:
    """What to write for each ``kept`` value the model could not represent.

    The stored value verbatim while ``model``'s field still equals what that
    value parses to — i.e. no writer has changed it since the read.
    Re-deriving this at render time is safe for the reason
    ``_action_log_codec._action_log_refused`` is: the parser has no mode and
    no external state, so it answers exactly as parse time did. Once a writer
    changed it, the model's list (``canonical``) with the stored list's
    non-object entries put back; a stored value that is not a list is
    replaced.

    Known limit (#882): a writer that sets the field to exactly what the
    stored value parses to — ``device_targeting=None`` over a stored
    ``"mobile only"`` — is indistinguishable from no change, so the stored
    value is written back.
    """
    result: dict[str, Any] = {}
    for key, parse, representable in kept:
        if key not in raw or representable(raw[key]):
            continue
        stored = raw[key]
        if parse(stored) == getattr(model, key):
            result[key] = copy.deepcopy(stored)
        elif key in canonical and isinstance(stored, list):
            result[key] = _with_non_objects(stored, canonical[key])
    return result


def ad_state_to_dict(a: AdState) -> dict[str, Any]:
    """Convert an :class:`AdState` to a dictionary.

    Optional fields are emitted only when set: an absent ``effective_status``
    must stay absent rather than becoming an empty string a later run could
    read as an observed value. An ad with ``raw`` is re-emitted in its
    on-disk shape (#881).
    """
    canonical: dict[str, Any] = {"ad_id": a.ad_id}
    for key in _AD_OPTIONAL_KEYS:
        value = getattr(a, key)
        if value is not None:
            canonical[key] = value
    if a.raw is None:
        return canonical
    return preserved_dict(
        a.raw, canonical, required=_AD_REQUIRED_KEYS, known=AD_KNOWN_KEYS, opaque=False
    )


def _canonical_campaign(c: CampaignSnapshot) -> dict[str, Any]:
    """The campaign's fields in the codec's order."""
    device_targeting: list[dict[str, Any]] | None = None
    if c.device_targeting is not None:
        device_targeting = list(c.device_targeting)
    result: dict[str, Any] = {
        "campaign_id": c.campaign_id,
        "campaign_name": c.campaign_name,
        "status": c.status,
        "bidding_strategy_type": c.bidding_strategy_type,
        "bidding_details": c.bidding_details,
        "daily_budget": c.daily_budget,
        "device_targeting": device_targeting,
        "campaign_goal": c.campaign_goal,
        "notes": c.notes,
    }
    # The campaign's own monthly budget (#656): emit only where the platform
    # has that concept and it was read, so a per-day campaign stays
    # byte-stable and an absent figure is never written as a 0.
    if c.monthly_budget is not None:
        result["monthly_budget"] = c.monthly_budget
    # Optional metrics: emit only when present so old STATE.json files don't
    # gain a new key (no diff churn / bloat).
    if c.metrics is not None:
        result["metrics"] = copy.deepcopy(c.metrics)
    # Ad-level state (#468): emit only when it was actually fetched, so a
    # campaign that predates this field stays byte-stable on round-trip.
    if c.ads is not None:
        result["ads"] = [ad_state_to_dict(a) for a in c.ads]
    return result


def snapshot_to_dict(c: CampaignSnapshot) -> dict[str, Any]:
    """Convert a :class:`CampaignSnapshot` to a dictionary.

    A campaign with ``raw`` is re-emitted in its on-disk shape (#881), its
    ``ads`` / ``device_targeting`` as found while unchanged.
    """
    canonical = _canonical_campaign(c)
    if c.raw is None:
        return canonical
    kept = _kept_values(c.raw, c, _CAMPAIGN_KEPT, canonical)
    return preserved_dict(
        c.raw,
        {**canonical, **kept},
        required=_CAMPAIGN_REQUIRED_KEYS,
        known=CAMPAIGN_KNOWN_KEYS,
        opaque=False,
    )


def _canonical_platform(ps: PlatformState) -> dict[str, Any]:
    """The platform entry's fields in the codec's order."""
    result: dict[str, Any] = {
        "account_id": ps.account_id,
        "campaigns": [snapshot_to_dict(c) for c in ps.campaigns],
    }
    # Optional platform-level rollup: emit only when present.
    if ps.totals is not None:
        result["totals"] = copy.deepcopy(ps.totals)
    if ps.metrics_period is not None:
        result["metrics_period"] = ps.metrics_period
    # Per-period rollups: emit only when non-empty so legacy files (and
    # entries with no per-period data) stay byte-stable on round-trip.
    if ps.periods:
        result["periods"] = copy.deepcopy(ps.periods)
    # #690 — day-grain history: emit only when non-empty, on the same rule as
    # ``periods``, so an entry that has never accumulated a day stays
    # byte-stable on round-trip and gains no key.
    if ps.daily:
        result["daily"] = copy.deepcopy(ps.daily)
    # #342 — operator conversion override: emit only when set, as a JSON list,
    # so legacy entries stay byte-stable.
    if ps.conversion_action_types:
        result["conversion_action_types"] = list(ps.conversion_action_types)
    # #638 — why the figures did not move: emit only when there is a note, so
    # a document that has never had a failed collection stays byte-stable, and
    # a cleared note leaves no key behind to be read as a live one.
    if ps.not_collected:
        result["not_collected"] = copy.deepcopy(ps.not_collected)
    return result


def platform_state_to_dict(ps: PlatformState) -> dict[str, Any]:
    """Convert a :class:`PlatformState` to a dictionary.

    An entry with ``raw`` is re-emitted in its on-disk shape (#881), its
    ``campaigns`` as found while unchanged. One that had no ``campaigns`` key
    gains none until a writer adds a campaign.
    """
    canonical = _canonical_platform(ps)
    if ps.raw is None:
        return canonical
    if "campaigns" not in ps.raw and not ps.campaigns:
        canonical = {k: v for k, v in canonical.items() if k != "campaigns"}
    kept = _kept_values(ps.raw, ps, _PLATFORM_KEPT, canonical)
    return preserved_dict(
        ps.raw,
        {**canonical, **kept},
        required=_PLATFORM_REQUIRED_KEYS,
        known=PLATFORM_KNOWN_KEYS,
        opaque=False,
    )


__all__ = [
    "AD_KNOWN_KEYS",
    "CAMPAIGN_KNOWN_KEYS",
    "PLATFORM_KNOWN_KEYS",
    "ad_state_to_dict",
    "carries_unread_content",
    "is_object_list",
    "parse_ad",
    "parse_ads",
    "parse_campaign",
    "parse_campaigns",
    "parse_not_collected",
    "parse_platform",
    "platform_state_to_dict",
    "snapshot_to_dict",
]
