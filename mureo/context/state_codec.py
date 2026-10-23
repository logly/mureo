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

The read side has two modes:

- ``strict=True`` is the **writer contract** — what is left of
  "nonconforming raises" (below) raises: an ``action_log`` entry or a
  ``decisions`` record that is not an object.
- ``strict=False`` is the **read-only Reports view** — such an entry is
  skipped and logged at DEBUG (never WARNING: the dashboard re-parses on
  every poll, so a per-entry warning would flood the daemon log), so one
  hand-authored entry cannot blank out a whole document.

Each tolerant branch documents its own reasoning below.

``action_log`` was the first exception to "nonconforming raises" (#859). The log is
the operator's append-only history and its indices are positional
(``rollback_of`` / ``evaluation_of``), so no object entry can block a write.
Both modes build every object entry the same way (see
:mod:`mureo.context._action_log_codec`): an entry missing a required key
(``timestamp`` / ``action`` / ``platform``), holding a non-string one, or
carrying keys the codec does not know is kept IN PLACE — those required
fields read as ``""`` — and its unknown and required keys are written back as
found (known keys are normalised by the model exactly as before). An entry
the model refuses (a malformed ``approval`` included) is kept OPAQUE: only its
required keys and linking fields are read, and it is written back verbatim
in full. Strict mode refuses only an entry that is not an object and
tolerant mode skips only that (invalid JSON is refused before any of this,
in both).

``platforms`` / ``campaigns`` / ``ads`` entries follow the same rule (#881):
both modes build every object entry the same way, keep a hand-authored one
with its on-disk dict and write it back in that shape, and keep a
``campaigns`` / ``ads`` value the model cannot represent inside the
enclosing entry, written back verbatim until a mureo writer replaces it —
see :mod:`mureo.context._platform_codec`.

``decisions`` records follow it too (#882): both modes keep a record the
model refuses OPAQUE, in place, written back verbatim, and no reader matches
it; a record the model takes keeps keys the codec does not know and writes
them back — see :mod:`mureo.context._decision_codec`. Strict mode refuses
only a record that is not an object and tolerant mode skips only that.

A section with no enclosing entry to be kept in (#882) — a top-level
``campaigns`` that is not a list of objects, a ``platforms`` that is not an
object or holding a value that is not one, a ``decisions`` that is not a
list — is kept on the document itself, :attr:`StateDocument.raw` (its shape
is defined there), in both modes. :func:`render_state` writes it back
verbatim while the model's section is still what the parser left, and lets
the model's value win once a writer has filled ``campaigns`` / ``platforms``;
a kept ``decisions`` / ``action_log`` is never replaced (the writers refuse
to record into it, and :func:`_refuse_rewrite_of_kept` is the last line).
The one difference
between the modes: the read-only view still reads the object entries of a
top-level ``campaigns`` list that also holds non-objects (it is never
written back). Every kept item — a section, a platform value, a refused
decision record — is logged once at DEBUG, by type, never by value: the
read-only Reports view reads strictly on every poll, so a WARNING would
flood the log. Only a top-level value that is not an object is still
refused.

Dependency-free beyond stdlib, the frozen ``mureo.context.models``
dataclasses and the private codec modules beside it — the same discipline
:mod:`mureo.context.platform_accounts` keeps, and for the same reason: every
consumer can import it without an import cycle.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

from mureo.context._action_log_codec import (
    ACTION_LOG_KNOWN_KEYS,
    action_log_entry_to_dict,
    parse_action_log_entry,
)
from mureo.context._decision_codec import (
    DECISION_KNOWN_KEYS,
    decision_to_dict,
    parse_decisions,
)
from mureo.context._platform_codec import (
    AD_KNOWN_KEYS,
    CAMPAIGN_KNOWN_KEYS,
    PLATFORM_KNOWN_KEYS,
    is_object_list,
    parse_campaigns,
    parse_not_collected,
    parse_platform,
    platform_state_to_dict,
    snapshot_to_dict,
)
from mureo.context._preserve import KEPT_REWRITE_MESSAGE
from mureo.context.decisions import DecisionRecord
from mureo.context.display_codec import (
    display_contract_to_dict,
    parse_display_contract,
)
from mureo.context.models import (
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
                # Not an on-disk key: the on-disk values of the sections the
                # model cannot hold, keyed by section name (#882).
                "raw",
            }
        ),
        "parse_state / render_state",
    ),
    (
        PlatformState,
        # ``raw`` is not an on-disk key: it IS the on-disk dict (#881).
        PLATFORM_KNOWN_KEYS | {"raw"},
        "_platform_codec.parse_platform / .platform_state_to_dict",
    ),
    (
        ActionLogEntry,
        # ``raw`` is not an on-disk key: it IS the on-disk dict (#859).
        ACTION_LOG_KNOWN_KEYS | {"raw"},
        "_action_log_codec.parse_action_log_entry / .action_log_entry_to_dict",
    ),
    (
        DecisionRecord,
        # ``raw`` is not an on-disk key: it IS the on-disk dict (#882).
        DECISION_KNOWN_KEYS | {"raw"},
        "_decision_codec.parse_decisions / .decision_to_dict",
    ),
    (
        CampaignSnapshot,
        CAMPAIGN_KNOWN_KEYS | {"raw"},
        "_platform_codec.parse_campaign / .snapshot_to_dict",
    ),
    (
        AdState,
        AD_KNOWN_KEYS | {"raw"},
        "_platform_codec.parse_ad / .ad_state_to_dict",
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


def _kept_section(section: str, value: Any) -> dict[str, Any]:
    """``{section: value}`` for :attr:`StateDocument.raw`, logged once (#882).

    The log names the section and the value's type, never the value: it is
    content an operator or an agent wrote by hand. DEBUG, not WARNING: the
    read-only Reports view reads strictly on every poll.
    """
    logger.debug(
        "keeping the %r section as found: the model cannot hold a %s there",
        section,
        type(value).__name__,
    )
    return {section: value}


def _parse_top_level_campaigns(
    raw: Any, *, strict: bool
) -> tuple[tuple[CampaignSnapshot, ...], dict[str, Any]]:
    """Parse the legacy v1 top-level ``campaigns`` list, and what is kept.

    Every object entry is built the same way in both modes (#881, see
    :func:`mureo.context._platform_codec.parse_campaign`). A value that is
    not a list of objects has no enclosing entry to be kept in, so it is
    kept on the document instead, in both modes (#882), and returned under
    ``"campaigns"`` for :attr:`StateDocument.raw`. ``strict=True`` (the
    writers) reads ``campaigns`` as ``()``, so the kept value is what is
    written back; ``strict=False`` (the read-only view, never written back)
    still reads the object entries of a list, skipping the others at DEBUG
    by type.
    """
    if is_object_list(raw):
        return parse_campaigns(raw), {}
    kept = _kept_section("campaigns", raw)
    if strict or not isinstance(raw, list):
        return (), kept
    for item in raw:
        if not isinstance(item, dict):
            logger.debug(
                "skipping a non-object top-level 'campaigns' entry (%s)",
                type(item).__name__,
            )
    return parse_campaigns(raw), kept


def _parse_platforms(
    raw: Any,
) -> tuple[dict[str, PlatformState] | None, dict[str, Any]]:
    """Parse the v2 ``platforms`` section, and what is kept (#882).

    ``None`` when it is absent. Every object entry is built the same way in
    both modes (#881, see :func:`mureo.context._platform_codec.
    parse_platform`). ``platforms`` that is not an object reads as ``None``
    and is kept whole; a platform value that is not an object is left out of
    ``platforms``, and the whole object is kept so the value is written back
    at its original position — the two shapes :attr:`StateDocument.raw`
    defines for ``"platforms"``.
    """
    if raw is None:
        return None, {}
    if not isinstance(raw, dict):
        return None, _kept_section("platforms", raw)
    platforms: dict[str, PlatformState] = {}
    for platform_key, platform_data in raw.items():
        if isinstance(platform_data, dict):
            platforms[platform_key] = parse_platform(platform_key, platform_data)
            continue
        # DEBUG for the reason ``_kept_section`` gives.
        logger.debug(
            "keeping a 'platforms' value as found: the model cannot hold a %s there",
            type(platform_data).__name__,
        )
    return platforms, ({} if len(platforms) == len(raw) else {"platforms": raw})


def _parse_decisions_section(
    raw: Any, *, strict: bool
) -> tuple[tuple[DecisionRecord, ...], dict[str, Any]]:
    """Parse the ``decisions`` section, and what is kept (#882).

    Absent reads as empty in both modes — every document written before this
    section existed has no key, and that is not a defect to report. A value
    that is not a list reads as ``()`` and is kept whole; a list is parsed by
    :func:`mureo.context._decision_codec.parse_decisions`, which keeps every
    object record in place.
    """
    if raw is None:
        return (), {}
    if not isinstance(raw, list):
        return (), _kept_section("decisions", raw)
    return parse_decisions(raw, strict=strict), {}


def _parse_action_log(
    raw: Any, *, strict: bool
) -> tuple[tuple[ActionLogEntry, ...], dict[str, Any]]:
    """Parse the action_log list, and what is kept (#882).

    ``null`` reads as empty, as for ``decisions``: writing ``[]`` over it
    loses nothing. Any other value that is not a list reads as ``()`` in both
    modes and is kept on :attr:`StateDocument.raw`, logged once at DEBUG by
    type, so it cannot block a write to another section;
    :func:`mureo.context.state.append_action_log` refuses to record an entry
    over it.

    Both modes keep every object entry IN PLACE (#859): the log is
    append-only and ``rollback_of`` / ``evaluation_of`` are positional, so the
    writer and the read-only view must see the same indices, and both build
    each entry identically (see
    :func:`mureo.context._action_log_codec.parse_action_log_entry`).

    Within a list, ``strict=True`` (the writer contract) raises only on an
    entry that is not an object. ``strict=False`` skips such an entry,
    logging it, so one cannot blank out a whole document in the read-only
    Reports view.
    """
    if raw is None:
        return (), {}
    if not isinstance(raw, list):
        return (), _kept_section("action_log", raw)
    if strict:
        return tuple(parse_action_log_entry(e) for e in raw), {}
    parsed: list[ActionLogEntry] = []
    for e in raw:
        try:
            parsed.append(parse_action_log_entry(e))
        except ValueError as exc:
            # DEBUG, not WARNING: the read-only Reports view re-parses on
            # every poll, so a per-entry WARNING would flood the log for a
            # STATE.json with many nonconforming action_log entries.
            logger.debug("skipping unparseable action_log entry: %s", exc)
    return tuple(parsed), {}


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

    ``strict=True`` (default) is the writer contract: it raises on an
    action_log entry or a ``decisions`` record that is not an object;
    ``strict=False`` skips those for the read-only Reports view. Everything
    else is built identically in BOTH modes and written back as found — an
    object entry the model cannot fully read (#859 / #881 / #882) and a
    section it cannot hold (:attr:`StateDocument.raw`, #882); see the module
    docstring. Invalid JSON always raises regardless of ``strict``, and so
    does a top-level value that is not an object.

    Unknown top-level keys are ignored (and :func:`render_state` emits only
    the known ones), which is what keeps the ``mureo_state_get`` response
    field ``server_now`` from ever being persisted: a document echoed back
    into STATE.json with that key loses it on the next write instead of
    fossilising a stale "today" (#460).
    """
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("STATE.json top level must be an object")
    campaigns, kept_campaigns = _parse_top_level_campaigns(
        data.get("campaigns", []), strict=strict
    )

    platforms, kept_platforms = _parse_platforms(data.get("platforms"))
    action_log, kept_log = _parse_action_log(data.get("action_log", []), strict=strict)
    decisions, kept_decisions = _parse_decisions_section(
        data.get("decisions"), strict=strict
    )
    kept = {**kept_campaigns, **kept_platforms, **kept_log, **kept_decisions}

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
        workspace_not_collected=parse_not_collected(
            data.get("workspace_not_collected")
        ),
        batches=_parse_batches(data.get("batches")),
        # #706 — the dashboard's own surface. Tolerant in BOTH modes, like
        # the batch records: every bound and vocabulary on it is a WRITE
        # rule, so a value already on disk is content an operator has, and
        # refusing to read it would only delete that.
        display=parse_display_contract(data.get("display")),
        decisions=decisions,
        settings=parse_settings(data.get("settings")),
        raw=kept or None,
    )


def render_state(doc: StateDocument) -> str:
    """Generate a JSON string from a StateDocument."""
    # Sections the parser kept (#882) and their rules: ``StateDocument.raw``.
    kept = doc.raw or {}
    _refuse_rewrite_of_kept(doc.decisions, doc.action_log, kept)
    data: dict[str, Any] = {
        "version": doc.version,
        "last_synced_at": doc.last_synced_at,
        "customer_id": doc.customer_id,
        "campaigns": _render_campaigns(doc.campaigns, kept),
        "platforms": _render_platforms(doc.platforms, kept),
    }
    if "action_log" in kept:
        data["action_log"] = copy.deepcopy(kept["action_log"])
    else:
        data["action_log"] = [action_log_entry_to_dict(e) for e in doc.action_log]

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
    if "decisions" in kept:
        data["decisions"] = copy.deepcopy(kept["decisions"])
    elif doc.decisions:
        data["decisions"] = [decision_to_dict(d) for d in doc.decisions]
    if doc.settings is not None:
        data["settings"] = settings_to_dict(doc.settings)

    return json.dumps(data, ensure_ascii=False, indent=2)


def _refuse_rewrite_of_kept(
    decisions: tuple[DecisionRecord, ...],
    action_log: tuple[ActionLogEntry, ...],
    kept: Mapping[str, Any],
) -> None:
    """Refuse to write a record over a kept ``decisions`` / ``action_log`` (#882).

    The last-line guard behind the writers' own refusal
    (:func:`mureo.context._preserve.refuse_if_kept`): those two sections are
    history, so
    a value kept as found is never replaced by a writer, and a document that
    holds both a kept value and new records is refused before any byte is
    written. Names the section only, never the value.
    """
    for section, records in (("decisions", decisions), ("action_log", action_log)):
        if records and section in kept:
            raise ValueError(KEPT_REWRITE_MESSAGE.format(section=section))


def _render_campaigns(
    campaigns: tuple[CampaignSnapshot, ...], kept: Mapping[str, Any]
) -> Any:
    """The top-level ``campaigns`` value to write (#882).

    The value the parser kept while ``campaigns`` is still ``()``; once a
    writer has filled it, the model's list wins.
    """
    if not campaigns and "campaigns" in kept:
        return copy.deepcopy(kept["campaigns"])
    return [snapshot_to_dict(c) for c in campaigns]


def _render_platforms(
    platforms: dict[str, PlatformState] | None, kept: Mapping[str, Any]
) -> Any:
    """The ``platforms`` value to write, with what the parser kept (#882).

    A whole ``platforms`` value the parser kept (anything but a dict, see
    :attr:`StateDocument.raw`) is written back while ``platforms`` is still
    ``None``; once a writer has filled it, the model's value wins. When the
    parser kept the whole object (some values were not objects), each kept
    value goes back at its original position unless ``platforms`` now holds
    its key; an object value ``platforms`` no longer holds stays out, and
    keys a writer added follow.
    """
    rendered = (
        None
        if platforms is None
        else {key: platform_state_to_dict(ps) for key, ps in platforms.items()}
    )
    if "platforms" not in kept:
        return rendered
    stored = kept["platforms"]
    if not isinstance(stored, dict):
        return copy.deepcopy(stored) if rendered is None else rendered
    current = rendered or {}
    in_place = {
        key: current[key] if key in current else copy.deepcopy(value)
        for key, value in stored.items()
        if key in current or not isinstance(value, dict)
    }
    return {**in_place, **current}


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


__all__ = [
    "parse_state",
    "render_state",
]
