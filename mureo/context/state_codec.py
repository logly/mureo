"""STATE.json <-> :class:`~mureo.context.models.StateDocument` codec (#538).

Both directions of one contract. :func:`parse_state` and :func:`render_state`
are inverses, and every field of the schema appears exactly twice — once in
each — so the optionality rules that keep a round-trip byte-stable (emit
``metrics`` / ``ads`` / ``periods`` / ``daily`` / ``conversion_action_types``
only when
they are actually present) can only be checked with both halves in front of
you. Keeping them apart would let the two sides drift, and drift here silently
rewrites an operator's STATE.json.

Extracted verbatim from :mod:`mureo.context.state`, which keeps the file /
lock / merge layer its name promises. Every public name here is re-exported
from that module, so no caller had to move.

The read side has two modes and the distinction is load-bearing:

- ``strict=True`` is the **writer contract** — a nonconforming entry raises,
  exactly as it always has.
- ``strict=False`` is the **read-only Reports view** — a nonconforming entry
  is skipped and logged at DEBUG (never WARNING: the dashboard re-parses on
  every poll, so a per-entry warning would flood the daemon log), so one
  hand-authored campaign cannot blank out a whole document.

Each tolerant branch documents its own reasoning below.

``action_log`` is the exception to "nonconforming raises" (#859). The log is
the operator's append-only history and its indices are positional
(``rollback_of`` / ``evaluation_of``), so no object entry can block a write.
An entry missing a required key (``timestamp`` / ``action`` / ``platform``),
holding a non-string one, or carrying keys the codec does not know is kept IN
PLACE in both modes — those required fields read as ``""`` — and written back
verbatim from :attr:`ActionLogEntry.raw`. An entry the model refuses (a
malformed ``approval`` included) is kept OPAQUE: only its three required keys
are read, and it too is written back verbatim. Strict mode refuses only an
entry that is not an object and tolerant mode skips only that (invalid JSON
is refused before any of this, in both).

Dependency-free beyond stdlib and the frozen ``mureo.context.models``
dataclasses — the same discipline :mod:`mureo.context.platform_accounts`
keeps, and for the same reason: ``mureo.core.__init__`` ->
``runtime_context`` -> ``state_store`` -> ``mureo.context.state`` is a real
import chain, so a module inside it that reached back into ``mureo.core``
would close the cycle.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

from mureo.context._decision_codec import (
    DECISION_COVERAGE,
    decision_to_dict,
    parse_decisions,
)
from mureo.context.approval import approval_to_dict, tolerant_approval
from mureo.context.display_codec import (
    display_contract_to_dict,
    parse_display_contract,
)
from mureo.context.models import (
    NOT_COLLECTED_REASON_MAX_CHARS,
    ActionLogEntry,
    AdState,
    BatchRecord,
    CampaignSnapshot,
    DisplayBreakdown,
    DisplayBreakdownRow,
    DisplayContract,
    DisplayHighlight,
    DisplayProposal,
    DisplayStatedValue,
    PlatformState,
    StateDocument,
)
from mureo.context.settings import SETTINGS_COVERAGE, parse_settings, settings_to_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Codec field coverage — checked at import, not only under pytest
# ---------------------------------------------------------------------------
#
# Everywhere else in the tree, a field is carried across a rebuild by
# ``dataclasses.replace`` and cannot be forgotten. This module is the one place
# that CANNOT use it: it maps to an external JSON schema, so both halves list
# every field by hand. A field added to a model but not to this file is
# silently lost the moment a document is written and read back — the same
# omission-shaped failure, in the one file where the structural fix does not
# apply.
#
# So the omission is made loud instead. Each model below declares the fields
# this codec handles, and the check runs at MODULE IMPORT: any `import mureo`,
# a REPL, a `pytest -k` that never collects the round-trip test. Adding a field
# without visiting this file raises immediately with the two functions to edit,
# rather than costing an operator their data.
#
# This verifies DECLARATION, not behaviour — that the field is known here, not
# that it survives. Behaviour is the round-trip test's job
# (tests/test_dataclass_field_preservation.py::TestCodecRoundTrip).

#: The ``action_log`` keys every entry must carry. Read with ``.get`` (#859):
#: a missing or null value reads as ``""`` and the entry keeps its ``raw``
#: dict, so it is written back without the key rather than with an invented
#: one.
_ACTION_LOG_REQUIRED_KEYS: tuple[str, ...] = ("timestamp", "action", "platform")

#: The optional ``action_log`` keys, in the order ``_action_log_entry_to_dict``
#: emits them. Each is emitted only when set, so an entry written before a key
#: existed round-trips byte-identically and gains no new key on the next write.
_ACTION_LOG_OPTIONAL_KEYS: tuple[str, ...] = (
    "campaign_id",
    "ad_id",
    "entity_type",
    "entity_id",
    "batch_id",
    "summary",
    "command",
    "metrics_at_action",
    "observation_due",
    "reversible_params",
    "rollback_of",
    "evaluation_of",
    "origin",
    "external_id",
    "occurred_at",
    "display_title",
    "display_summary",
    "reason",
    "session_id",
    "client",
    "decision_id",
    "evaluation",
    "applied_params",
    "approval",
)

#: Every on-disk key the codec reads. Any other key on an entry is unknown and
#: makes the parser keep the entry's ``raw`` dict (#859). ``_CODEC_COVERAGE``
#: is built from this set, so a model field missing here fails at import.
_ACTION_LOG_KNOWN_KEYS: frozenset[str] = frozenset(
    (*_ACTION_LOG_REQUIRED_KEYS, *_ACTION_LOG_OPTIONAL_KEYS)
)

_CODEC_COVERAGE: tuple[tuple[type, frozenset[str], str], ...] = (
    (
        StateDocument,
        frozenset(
            {
                "version",
                "last_synced_at",
                "customer_id",
                "campaigns",
                "platforms",
                "action_log",
                "reports",
                "workspace_not_collected",
                "batches",
                "display",
                "decisions",
                "settings",
            }
        ),
        "parse_state / render_state",
    ),
    (
        PlatformState,
        frozenset(
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
        ),
        "parse_state / _platform_state_to_dict",
    ),
    (
        ActionLogEntry,
        # ``raw`` is not an on-disk key: it IS the on-disk dict (#859).
        _ACTION_LOG_KNOWN_KEYS | {"raw"},
        "_parse_action_log_entry / _action_log_entry_to_dict",
    ),
    (
        CampaignSnapshot,
        frozenset(
            {
                "campaign_id",
                "campaign_name",
                "status",
                "bidding_strategy_type",
                "bidding_details",
                "daily_budget",
                "monthly_budget",
                "device_targeting",
                "campaign_goal",
                "notes",
                "metrics",
                "ads",
            }
        ),
        "_parse_campaign / _snapshot_to_dict",
    ),
    (
        AdState,
        frozenset({"ad_id", "name", "status", "effective_status", "as_of"}),
        "_parse_ad / _ad_state_to_dict",
    ),
    (
        BatchRecord,
        frozenset({"batch_id", "label", "started_at", "ended_at"}),
        "_parse_batches / _batch_record_to_dict",
    ),
    # The display contract (#706). Its two halves live in
    # ``mureo.context.display_codec`` — this file is at the repo's size limit
    # — but the coverage check stays here, so the omission is still loud from
    # a bare ``import mureo``.
    (
        DisplayContract,
        frozenset(
            {
                "nav_message",
                "highlights",
                "proposals",
                "breakdown",
                "stated_values",
                "source",
                "generated_at",
            }
        ),
        "display_codec.parse_display_contract / .display_contract_to_dict",
    ),
    (
        DisplayHighlight,
        frozenset({"tone", "text"}),
        "display_codec._parse_highlights / ._highlight_to_dict",
    ),
    (
        DisplayProposal,
        frozenset({"title", "body", "status", "date"}),
        "display_codec._parse_proposals / ._proposal_to_dict",
    ),
    (
        DisplayBreakdown,
        frozenset({"campaigns", "adgroups"}),
        "display_codec._parse_breakdown / ._breakdown_to_dict",
    ),
    (
        DisplayBreakdownRow,
        frozenset({"name", "spend", "mcpa", "target_cpa", "state", "note"}),
        "display_codec._parse_breakdown_rows / ._breakdown_row_to_dict",
    ),
    (
        DisplayStatedValue,
        frozenset({"label", "value"}),
        "display_codec._parse_stated_values / ._stated_value_to_dict",
    ),
    DECISION_COVERAGE,
    SETTINGS_COVERAGE,
)


def _assert_codec_coverage() -> None:
    """Fail loudly if a model has a field this codec does not name."""
    for model, handled, functions in _CODEC_COVERAGE:
        declared = {f.name for f in dataclass_fields(model)}
        missing = declared - handled
        if missing:
            raise RuntimeError(
                f"{model.__name__} has field(s) {sorted(missing)} that "
                f"mureo.context.state_codec does not handle. Add them to BOTH "
                f"halves of {functions} and to _CODEC_COVERAGE — otherwise the "
                "field is silently dropped on every STATE.json write."
            )
        stale = handled - declared
        if stale:
            raise RuntimeError(
                f"_CODEC_COVERAGE lists field(s) {sorted(stale)} that "
                f"{model.__name__} no longer declares; remove them here and "
                f"from {functions}."
            )


_assert_codec_coverage()


# Required campaign fields
_CAMPAIGN_REQUIRED_FIELDS: tuple[str, ...] = (
    "campaign_id",
    "campaign_name",
    "status",
)


def _parse_ad(a: dict[str, Any]) -> AdState:
    """Create an :class:`AdState` from a dict (``ad_id`` required).

    ``ad_id`` is type-checked, not merely present-checked: it is the key every
    later run matches on to diff statuses, so a hand-edited numeric id would
    silently never match the string ids the platforms return.
    """
    if not isinstance(a, dict) or "ad_id" not in a:
        raise ValueError(f"Ad is missing required field 'ad_id': {a}")
    if not isinstance(a["ad_id"], str) or not a["ad_id"]:
        raise ValueError(f"Ad 'ad_id' must be a non-empty string: {a}")
    return AdState(
        ad_id=a["ad_id"],
        name=a.get("name"),
        status=a.get("status"),
        effective_status=a.get("effective_status"),
        as_of=a.get("as_of"),
    )


def _parse_ads(raw: Any, *, strict: bool) -> tuple[AdState, ...] | None:
    """Parse a campaign's ``ads`` list (#468).

    Returns ``None`` when the key is absent — "ad-level status was never
    fetched", which must stay distinguishable from ``()`` ("fetched, no ads").
    ``strict=True`` raises on a nonconforming entry (the writer contract);
    ``strict=False`` skips it, so one hand-authored ad cannot blank out a
    whole document for the read-only Reports view.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        if strict:
            raise ValueError(f"Campaign 'ads' must be a list: {raw!r}")
        logger.debug("skipping non-list campaign 'ads' value: %r", raw)
        return None
    if strict:
        return tuple(_parse_ad(a) for a in raw)
    parsed: list[AdState] = []
    for a in raw:
        try:
            parsed.append(_parse_ad(a))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING — see _parse_campaigns.
            logger.debug("skipping unparseable ad entry: %s", exc)
    return tuple(parsed)


def _parse_campaigns(
    raw: list[dict[str, Any]], *, strict: bool
) -> tuple[CampaignSnapshot, ...]:
    """Parse a campaign list.

    ``strict=True`` (the canonical contract relied on by every writer) raises
    on the first nonconforming entry. ``strict=False`` skips entries that fail
    validation, logging each one — used only by the read-only Reports view so a
    single variant/hand-authored campaign cannot blank out a whole document
    (whose platforms/periods/reports the dashboard actually renders).
    """
    if strict:
        return tuple(_parse_campaign(c, strict=True) for c in raw)
    parsed: list[CampaignSnapshot] = []
    for c in raw:
        try:
            parsed.append(_parse_campaign(c, strict=False))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING: the read-only Reports view re-parses on every
            # poll, so a per-entry WARNING would flood the log for a STATE.json
            # with many nonconforming (e.g. legacy / hand-authored) campaigns.
            logger.debug("skipping unparseable campaign entry: %s", exc)
    return tuple(parsed)


def _parse_action_log(
    raw: list[dict[str, Any]], *, strict: bool
) -> tuple[ActionLogEntry, ...]:
    """Parse the action_log list.

    Both modes keep every object entry IN PLACE (#859): the log is
    append-only and ``rollback_of`` / ``evaluation_of`` are positional, so the
    writer and the read-only view must see the same indices. An entry the
    codec cannot represent is written back verbatim (see
    :func:`_parse_action_log_entry`).

    ``strict=True`` (the writer contract) raises only on an entry that is not
    an object. ``strict=False`` skips such an entry, logging it, so one cannot
    blank out a whole document in the read-only Reports view.
    """
    if strict:
        return tuple(_parse_action_log_entry(e) for e in raw)
    parsed: list[ActionLogEntry] = []
    for e in raw:
        try:
            parsed.append(_parse_action_log_entry(e, strict=False))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING — see _parse_campaigns: avoid per-render log
            # flood from a STATE.json with many nonconforming action_log entries.
            logger.debug("skipping unparseable action_log entry: %s", exc)
    return tuple(parsed)


def _platform_account_id(
    platform_key: str, platform_data: dict[str, Any], *, strict: bool
) -> str:
    """Resolve a platform's ``account_id``.

    ``strict=True`` (the writer contract) requires the key — a missing
    ``account_id`` raises ``KeyError`` exactly as before. ``strict=False``
    (the read-only Reports view) defaults a missing ``account_id`` to ``""``
    so an agent-/hand-authored STATE.json that omitted it still renders its
    platforms/totals/periods instead of blanking the whole dashboard. Logged
    at DEBUG (expected for non-canonical files; never per-poll WARNING noise).
    """
    if strict or "account_id" in platform_data:
        # KeyError in strict if absent — unchanged writer contract. Annotated
        # local so mypy treats the dict[str, Any] value as the declared str.
        account_id: str = platform_data["account_id"]
        return account_id
    logger.debug(
        "platform %r missing 'account_id'; defaulting to '' for the tolerant "
        "read-only view",
        platform_key,
    )
    return ""


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


def _parse_not_collected(raw: Any) -> dict[str, Any] | None:
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


def _parse_batches(raw: Any) -> tuple[BatchRecord, ...]:
    """Parse the declared bulk change sets (#549).

    Tolerant in both modes, unlike the campaign / action_log lists: a batch
    record is bookkeeping ABOUT history, not history itself — the members are
    in ``action_log`` and their ``batch_id`` stands on its own. A malformed
    record therefore costs a label, and dropping it is a far better trade than
    letting a hand-edited entry blank a whole document.
    """
    if not isinstance(raw, list):
        return ()
    records: list[BatchRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            logger.debug("skipping non-object batch record: %r", item)
            continue
        batch_id = item.get("batch_id")
        if not isinstance(batch_id, str) or not batch_id.strip():
            logger.debug("skipping batch record without a usable batch_id: %r", item)
            continue
        label = item.get("label")
        started_at = item.get("started_at")
        ended_at = item.get("ended_at")
        records.append(
            BatchRecord(
                batch_id=batch_id.strip(),
                label=label if isinstance(label, str) else "",
                started_at=started_at if isinstance(started_at, str) else "",
                ended_at=ended_at if isinstance(ended_at, str) else None,
            )
        )
    return tuple(records)


def parse_state(text: str, *, strict: bool = True) -> StateDocument:
    """Parse a JSON string and return a StateDocument.

    ``strict`` controls campaign-list, action_log AND platform validation:
    ``True`` (default) preserves the strict writer contract (raises on a missing
    required campaign field or platform ``account_id``, and on an action_log
    entry that is not an object); ``False`` tolerantly skips such campaign
    and action_log entries and defaults a missing platform ``account_id`` to
    ``""`` for the read-only Reports view. Every action_log entry that IS an
    object is kept in place in BOTH modes (#859): one missing or holding a
    non-string ``timestamp`` / ``action`` / ``platform``, carrying unknown
    keys, or refused by the model (a malformed ``approval`` included) is
    re-emitted verbatim by :func:`render_state`. Invalid JSON always raises
    regardless of ``strict``.

    Unknown top-level keys are ignored (and :func:`render_state` emits only
    the known ones), which is what keeps the ``mureo_state_get`` response
    field ``server_now`` from ever being persisted: a document echoed back
    into STATE.json with that key loses it on the next write instead of
    fossilising a stale "today" (#460).
    """
    data = json.loads(text)
    campaigns_raw = data.get("campaigns", [])
    campaigns = _parse_campaigns(campaigns_raw, strict=strict)

    # v2: platforms
    platforms: dict[str, PlatformState] | None = None
    platforms_raw = data.get("platforms")
    if platforms_raw is not None:
        platforms = {}
        for platform_key, platform_data in platforms_raw.items():
            platform_campaigns = _parse_campaigns(
                platform_data.get("campaigns", []), strict=strict
            )
            platforms[platform_key] = PlatformState(
                account_id=_platform_account_id(
                    platform_key, platform_data, strict=strict
                ),
                campaigns=platform_campaigns,
                totals=platform_data.get("totals"),
                metrics_period=platform_data.get("metrics_period"),
                periods=platform_data.get("periods"),
                daily=platform_data.get("daily"),
                conversion_action_types=_parse_conversion_action_types(
                    platform_data.get("conversion_action_types")
                ),
                not_collected=_parse_not_collected(platform_data.get("not_collected")),
            )

    # v2: action_log
    action_log_raw = data.get("action_log", [])
    action_log = _parse_action_log(action_log_raw, strict=strict)

    return StateDocument(
        version=data.get("version", "1"),
        last_synced_at=data.get("last_synced_at"),
        customer_id=data.get("customer_id"),
        campaigns=campaigns,
        platforms=platforms,
        action_log=action_log,
        reports=data.get("reports"),
        # #661 — the document-level counterpart of a platform's note, read
        # through the SAME normaliser so the two shapes can never drift.
        workspace_not_collected=_parse_not_collected(
            data.get("workspace_not_collected")
        ),
        batches=_parse_batches(data.get("batches")),
        # #706 — the dashboard's own surface. Tolerant in BOTH modes, like
        # the batch records: every bound and vocabulary on it is a WRITE
        # rule, so a value already on disk is content an operator has, and
        # refusing to read it would only delete that.
        display=parse_display_contract(data.get("display")),
        decisions=parse_decisions(data.get("decisions"), strict=strict),
        settings=parse_settings(data.get("settings")),
    )


def _parse_action_log_entry(
    e: dict[str, Any], *, strict: bool = True
) -> ActionLogEntry:
    """Create an ActionLogEntry from a dict (``TypeError`` if it is not one).

    A missing, null or non-string required key reads as ``""``, and an entry
    the codec cannot re-emit from its fields alone keeps its dict as ``raw``
    (#859). An entry the model refuses — a value ``ActionLogEntry`` rejects,
    or a malformed ``approval`` under ``strict=True`` — is kept OPAQUE in both
    modes: only the required keys are read and ``raw`` carries the rest, so it
    is written back verbatim instead of blocking the write. ``strict=False``
    drops a malformed ``approval`` and keeps the entry's other fields (see
    :func:`mureo.context.approval.tolerant_approval`).
    """
    if not isinstance(e, dict):
        raise TypeError(f"action_log entry must be an object, got {type(e).__name__}")
    raw = e if _action_log_unrepresentable(e) else None
    try:
        return _action_log_entry_from_dict(e, strict=strict, raw=raw)
    except ValueError:
        # DEBUG, not WARNING — the flood reason in _parse_campaigns. The value
        # is not logged: it is free text an operator typed.
        logger.debug("keeping a refused action_log entry opaque")
        required = _action_log_required(e)
        return ActionLogEntry(
            timestamp=required["timestamp"],
            action=required["action"],
            platform=required["platform"],
            raw=e,
        )


def _action_log_entry_from_dict(
    e: dict[str, Any], *, strict: bool, raw: dict[str, Any] | None
) -> ActionLogEntry:
    """Build the entry from every field ``e`` holds; the model may refuse it."""
    return ActionLogEntry(
        **_action_log_required(e),
        campaign_id=e.get("campaign_id"),
        ad_id=e.get("ad_id"),
        entity_type=e.get("entity_type"),
        entity_id=e.get("entity_id"),
        batch_id=e.get("batch_id"),
        summary=e.get("summary"),
        command=e.get("command"),
        metrics_at_action=e.get("metrics_at_action"),
        observation_due=e.get("observation_due"),
        reversible_params=e.get("reversible_params"),
        rollback_of=e.get("rollback_of"),
        evaluation_of=e.get("evaluation_of"),
        # #545 provenance. Absent on every entry written before it existed,
        # which is exactly what "mureo made this change" looks like.
        origin=e.get("origin"),
        external_id=e.get("external_id"),
        occurred_at=e.get("occurred_at"),
        # #706 — the operator-facing line. Absent on every entry written
        # before it existed, which is what "this entry has no display line"
        # looks like.
        display_title=e.get("display_title"),
        display_summary=e.get("display_summary"),
        # #758 phase 2 — the rationale and the writing session. Absent on
        # every entry written before they existed, which is what "nobody
        # recorded why, and we cannot say who" looks like.
        reason=e.get("reason"),
        session_id=e.get("session_id"),
        client=e.get("client"),
        # #848 ops history. Absent on every older entry.
        decision_id=e.get("decision_id"),
        evaluation=e.get("evaluation"),
        applied_params=e.get("applied_params"),
        # #854. Absent on every older entry. The read-only view drops a
        # malformed one rather than the whole entry.
        approval=tolerant_approval(e.get("approval"), strict=strict),
        raw=raw,
    )


def _action_log_refused(raw: Mapping[str, Any]) -> bool:
    """Whether the model refuses ``raw`` — i.e. it was parsed as an opaque entry."""
    try:
        _action_log_entry_from_dict(dict(raw), strict=True, raw=None)
    except ValueError:
        return True
    return False


def _action_log_required(e: dict[str, Any]) -> dict[str, str]:
    """The required keys of an action_log entry; anything but a string is ``""``."""
    return {
        k: e[k] if isinstance(e.get(k), str) else "" for k in _ACTION_LOG_REQUIRED_KEYS
    }


def _action_log_unrepresentable(e: dict[str, Any]) -> bool:
    """Whether the codec cannot re-emit ``e`` from its fields alone (#859).

    True when a required key is absent, null or not a string (re-emitting it
    as ``""`` would invent or lose a value) or when ``e`` carries a key the
    codec does not know (re-emitting the fields would drop it).
    """
    if any(not isinstance(e.get(k), str) for k in _ACTION_LOG_REQUIRED_KEYS):
        return True
    return any(k not in _ACTION_LOG_KNOWN_KEYS for k in e)


def _parse_campaign(c: dict[str, Any], *, strict: bool = True) -> CampaignSnapshot:
    """Create a CampaignSnapshot from a dict (with required field validation)."""
    for field_name in _CAMPAIGN_REQUIRED_FIELDS:
        if field_name not in c:
            raise ValueError(f"Campaign is missing required field '{field_name}': {c}")
    device_targeting_raw = c.get("device_targeting")
    device_targeting: tuple[dict[str, Any], ...] | None = None
    if device_targeting_raw is not None:
        device_targeting = tuple(device_targeting_raw)
    return CampaignSnapshot(
        campaign_id=c["campaign_id"],
        campaign_name=c["campaign_name"],
        status=c["status"],
        bidding_strategy_type=c.get("bidding_strategy_type"),
        bidding_details=c.get("bidding_details"),
        daily_budget=c.get("daily_budget"),
        monthly_budget=c.get("monthly_budget"),
        device_targeting=device_targeting,
        campaign_goal=c.get("campaign_goal"),
        notes=c.get("notes"),
        metrics=c.get("metrics"),
        ads=_parse_ads(c.get("ads"), strict=strict),
    )


def render_state(doc: StateDocument) -> str:
    """Generate a JSON string from a StateDocument."""
    data: dict[str, Any] = {
        "version": doc.version,
        "last_synced_at": doc.last_synced_at,
        "customer_id": doc.customer_id,
        "campaigns": [_snapshot_to_dict(c) for c in doc.campaigns],
    }

    # v2: platforms
    if doc.platforms is not None:
        data["platforms"] = {
            key: _platform_state_to_dict(ps) for key, ps in doc.platforms.items()
        }
    else:
        data["platforms"] = None

    data["action_log"] = [_action_log_entry_to_dict(e) for e in doc.action_log]

    # Optional reports section (stage-c forward-ready): emit only when present
    # so old STATE.json files don't gain a new key.
    if doc.reports is not None:
        data["reports"] = copy.deepcopy(doc.reports)

    # Why the WORKSPACE could not be collected (#661): emit only when there is
    # a note, so a document that has never had a workspace-level failure stays
    # byte-stable, and a cleared note leaves no key behind to be read as a
    # live one. Deliberately NOT inside ``reports`` — that section holds
    # stage-c analysis summaries, and a failure record is not one.
    if doc.workspace_not_collected:
        data["workspace_not_collected"] = copy.deepcopy(doc.workspace_not_collected)

    # Declared batches (#549): emit only when the workspace has any, so a
    # document written before this field existed stays byte-stable on
    # round-trip. ``ended_at`` is omitted while a batch is open.
    if doc.batches:
        data["batches"] = [_batch_record_to_dict(b) for b in doc.batches]

    # The display contract (#706): emitted only when it states something, so a
    # document that has never had one stays byte-stable on round-trip and a
    # cleared contract leaves no key behind for the dashboard to render as a
    # live one.
    if doc.display:
        data["display"] = display_contract_to_dict(doc.display)
    if doc.decisions:
        data["decisions"] = [decision_to_dict(d) for d in doc.decisions]
    if doc.settings is not None:
        data["settings"] = settings_to_dict(doc.settings)

    return json.dumps(data, ensure_ascii=False, indent=2)


def _platform_state_to_dict(ps: PlatformState) -> dict[str, Any]:
    """Convert a PlatformState to a dictionary."""
    result: dict[str, Any] = {
        "account_id": ps.account_id,
        "campaigns": [_snapshot_to_dict(c) for c in ps.campaigns],
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


def _action_log_entry_to_dict(e: ActionLogEntry) -> dict[str, Any]:
    """Convert an ActionLogEntry to a dictionary.

    An entry without ``raw`` — every entry mureo constructs — is emitted from
    its fields alone: the three required keys, then each optional key that is
    set (#545 / #706 / #758 / #848 / #854: an entry written before a key
    existed round-trips byte-identically and gains no new key). An entry WITH
    ``raw`` is re-emitted verbatim (#859), see
    :func:`_preserved_action_log_dict`.
    """
    canonical = _canonical_action_log_dict(e)
    if e.raw is None:
        return canonical
    return _preserved_action_log_dict(
        e.raw, canonical, opaque=_action_log_refused(e.raw)
    )


def _canonical_action_log_dict(e: ActionLogEntry) -> dict[str, Any]:
    """The entry's fields in the codec's order, optional keys only when set."""
    result: dict[str, Any] = {key: getattr(e, key) for key in _ACTION_LOG_REQUIRED_KEYS}
    for key in _ACTION_LOG_OPTIONAL_KEYS:
        value = getattr(e, key)
        if value is None:
            continue
        if key == "approval":
            result[key] = approval_to_dict(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _preserved_action_log_dict(
    raw: Mapping[str, Any], canonical: dict[str, Any], *, opaque: bool
) -> dict[str, Any]:
    """Re-emit a preserved entry in its on-disk key order (#859).

    A known key carries the entry's CURRENT value, so a mutation lands; one
    whose field is now unset is left out, so a cleared field stays cleared —
    except on an ``opaque`` entry (one the model refused), whose optional
    fields were never read, so an unset one is emitted as found.
    A required key whose current value is empty is emitted exactly as found
    (absent stays absent, null stays null) rather than as an invented ``""``.
    An unknown key is copied through. Known fields set on the entry but not
    on disk (e.g. a stamped ``batch_id``) follow, in the codec's order.
    """
    result: dict[str, Any] = {}
    for key, raw_value in raw.items():
        if key in _ACTION_LOG_REQUIRED_KEYS:
            current = canonical[key]
            result[key] = current if current else copy.deepcopy(raw_value)
        elif key not in _ACTION_LOG_KNOWN_KEYS:
            result[key] = copy.deepcopy(raw_value)
        elif key in canonical:
            result[key] = canonical[key]
        elif opaque:
            result[key] = copy.deepcopy(raw_value)
    for key, value in canonical.items():
        if key in raw or (key in _ACTION_LOG_REQUIRED_KEYS and not value):
            continue
        result[key] = value
    return result


def _batch_record_to_dict(b: BatchRecord) -> dict[str, Any]:
    """Convert a :class:`BatchRecord` to a dictionary.

    ``ended_at`` is emitted only once the batch is closed, so "open" is the
    absence of the key rather than a null a reader could misparse as a time.
    """
    result: dict[str, Any] = {
        "batch_id": b.batch_id,
        "label": b.label,
        "started_at": b.started_at,
    }
    if b.ended_at is not None:
        result["ended_at"] = b.ended_at
    return result


def _snapshot_to_dict(c: CampaignSnapshot) -> dict[str, Any]:
    """Convert a CampaignSnapshot to a dictionary."""
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
        result["ads"] = [_ad_state_to_dict(a) for a in c.ads]
    return result


def _ad_state_to_dict(a: AdState) -> dict[str, Any]:
    """Convert an :class:`AdState` to a dictionary.

    Optional fields are emitted only when set: an absent ``effective_status``
    must stay absent rather than becoming an empty string a later run could
    read as an observed value.
    """
    result: dict[str, Any] = {"ad_id": a.ad_id}
    for key, value in (
        ("name", a.name),
        ("status", a.status),
        ("effective_status", a.effective_status),
        ("as_of", a.as_of),
    ):
        if value is not None:
            result[key] = value
    return result


__all__ = [
    "parse_state",
    "render_state",
]
