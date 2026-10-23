"""The ``decisions`` section's two codec halves (#758, phase 3).

Split out of :mod:`mureo.context.state_codec` for the reason
:mod:`mureo.context.display_codec` was: that file is at the repo's size
limit. The import-time coverage check stays there; it builds the
:class:`~mureo.context.decisions.DecisionRecord` row from
:data:`DECISION_KNOWN_KEYS`, so a model field this module does not name
still fails at import.

**No object record can block a write** — the rule #859 set for
``action_log``, applied to ``decisions`` (#882). A decision record IS
history — the rationale is the payload — so a record the model refuses (a
required key missing, a bound or vocabulary failed, a malformed ``approval``
included) is neither raised over nor dropped: both read modes keep it
OPAQUE, IN PLACE, with its on-disk dict as :attr:`DecisionRecord.raw`, and
it is written back verbatim. Only its ``decision_id`` is read (see
:func:`_opaque_decision`), and no reader matches it
(:func:`mureo.context.decisions.parsed_decisions`).

A record the model takes that carries keys the codec does not know keeps
its on-disk dict as ``raw`` too, and is read like any other; on write its
unknown keys are re-emitted in their place (``preserved_dict`` with
``opaque=False``) — the ``action_log`` rule (#859). The two are told apart
by :func:`mureo.context._preserve.is_opaque_decision`: an opaque record's
``status`` is empty, which no record the model takes can hold.

Only a record that is not an object is refused (``ValueError``); the
section-level loop decides whether that raises (``strict=True``, the writer
contract) or is skipped (``strict=False``, the read-only Reports view) — the
``action_log`` rule. A ``decisions`` value that is not a list is kept by
:func:`mureo.context.state_codec.parse_state` on the document itself.

Dependency-free beyond stdlib and the :mod:`mureo.context` modules it names
— the discipline ``state_codec`` keeps.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from mureo.context._preserve import (
    exact_string,
    is_opaque_decision,
    preserved_dict,
)
from mureo.context.approval import approval_to_dict, parse_approval
from mureo.context.decisions import DecisionRecord
from mureo.context.expected import expected_to_list, parse_expected

logger = logging.getLogger(__name__)

#: Keys a stored record cannot be missing. A record with no ``rationale``
#: is not a decision record, and defaulting one would manufacture a reason
#: nobody gave — so the record is kept opaque rather than filled in.
_DECISION_REQUIRED_KEYS: tuple[str, ...] = (
    "decision_id",
    "recorded_at",
    "status",
    "title",
    "rationale",
)

#: The optional string keys, emitted as the field's value itself.
_DECISION_PLAIN_KEYS: tuple[str, ...] = (
    "platform",
    "campaign_id",
    "entity_type",
    "entity_id",
    "supersedes",
    "batch_id",
    "session_id",
    "client",
    "journal_call_id",
    "journal_tool",
)

#: The optional keys, in the order :func:`decision_to_dict` emits them. Each
#: is emitted only when set, so a record written before a key existed
#: round-trips byte-identically and gains no new key on the next write.
_DECISION_OPTIONAL_KEYS: tuple[str, ...] = (
    "metrics",
    *_DECISION_PLAIN_KEYS,
    "related_actions",
    "expected",
    "applied_params",
    "approval",
)

#: Every on-disk key the codec reads. The coverage check in
#: :mod:`mureo.context.state_codec` is built from this set, so a model field
#: missing here fails at import.
DECISION_KNOWN_KEYS: frozenset[str] = frozenset(
    (*_DECISION_REQUIRED_KEYS, *_DECISION_OPTIONAL_KEYS)
)


def _parse_decision(item: dict[str, Any]) -> DecisionRecord:
    """Build one :class:`DecisionRecord` from its stored dict; may be refused.

    Only names the keys: every bound and vocabulary is enforced by the
    model itself (see its docstring), so the two halves cannot disagree
    about what a valid record is. A record carrying a key the codec does
    not know keeps its dict as ``raw``, so that key is written back.
    """
    for name in _DECISION_REQUIRED_KEYS:
        if name not in item:
            raise ValueError(f"decision record is missing required field {name!r}")
    unknown = any(key not in DECISION_KNOWN_KEYS for key in item)
    return DecisionRecord(
        decision_id=item["decision_id"],
        recorded_at=item["recorded_at"],
        status=item["status"],
        title=item["title"],
        rationale=item["rationale"],
        metrics=item.get("metrics"),
        platform=item.get("platform"),
        campaign_id=item.get("campaign_id"),
        entity_type=item.get("entity_type"),
        entity_id=item.get("entity_id"),
        related_actions=item.get("related_actions") or (),
        supersedes=item.get("supersedes"),
        batch_id=item.get("batch_id"),
        session_id=item.get("session_id"),
        client=item.get("client"),
        # #848 — absent on every record written before ops history.
        # #888 — read without the one-primary rule: a legacy declaration may
        # list several effects and mark none.
        expected=parse_expected(item.get("expected"), require_primary=False),
        applied_params=item.get("applied_params"),
        journal_call_id=item.get("journal_call_id"),
        journal_tool=item.get("journal_tool"),
        # #854 — absent on every record written before it existed. A
        # malformed one is refused here in BOTH read modes, which makes the
        # record opaque (#882), as on an ``action_log`` entry (#859).
        approval=parse_approval(item.get("approval")),
        raw=item if unknown else None,
    )


def _opaque_decision(item: dict[str, Any]) -> DecisionRecord:
    """The record for a dict the model refused: ``decision_id`` only (#882).

    The id is read so the writer's duplicate-id check still sees it — a new
    record under the id of a kept one would leave two records of one id on
    disk — and only in a shape the model takes unchanged, so the verbatim
    write-back stays byte-identical. Every other field is its empty default;
    the record is never validated (``raw`` is set).
    """
    return DecisionRecord(
        decision_id=exact_string(item.get("decision_id")) or "",
        recorded_at="",
        status="",
        title="",
        rationale="",
        raw=item,
    )


def _parse_decision_entry(item: dict[str, Any]) -> DecisionRecord:
    """The record for one object entry — opaque when the model refuses it."""
    try:
        return _parse_decision(item)
    except (ValueError, KeyError, TypeError) as exc:
        # DEBUG, not WARNING: the read-only Reports view reads strictly on
        # every poll, so a per-record WARNING would flood the log. Only the
        # exception TYPE is logged: its message can quote a value, which is
        # free text an agent wrote and the write path's scrubber never saw on
        # a hand-edited file.
        logger.debug(
            "keeping a refused decisions record opaque (%s)", type(exc).__name__
        )
        return _opaque_decision(item)


def parse_decisions(raw: list[Any], *, strict: bool) -> tuple[DecisionRecord, ...]:
    """Parse a ``decisions`` list, every object record kept in place (#882).

    Both modes build every object record the same way (see
    :func:`_parse_decision_entry`). ``strict=True`` (the writer contract)
    raises only on a record that is not an object; ``strict=False`` skips
    such a record, logging its type at DEBUG (the read-only Reports view
    re-parses on every poll), so one cannot blank out a whole document.
    """
    parsed: list[DecisionRecord] = []
    for item in raw:
        if isinstance(item, dict):
            parsed.append(_parse_decision_entry(item))
            continue
        if strict:
            raise ValueError(
                f"decision record must be an object; got {type(item).__name__}"
            )
        logger.debug("skipping non-object decision record (%s)", type(item).__name__)
    return tuple(parsed)


def decision_to_dict(record: DecisionRecord) -> dict[str, Any]:
    """Serialize one record; optional fields are emitted only when set.

    ``related_actions`` is emitted only when non-empty, on the same rule, so
    a decision that names no action gains no key rather than storing ``[]``
    — which would read as "checked, and there were none". A record WITH
    ``raw`` (#882) is re-emitted in its on-disk shape through
    :func:`mureo.context._preserve.preserved_dict`: verbatim when it is
    opaque, its unknown keys kept in place when the model took it.
    """
    canonical = _canonical_decision_dict(record)
    if record.raw is None:
        return canonical
    return preserved_dict(
        record.raw,
        canonical,
        required=_DECISION_REQUIRED_KEYS,
        known=DECISION_KNOWN_KEYS,
        opaque=is_opaque_decision(record),
    )


def _canonical_decision_dict(record: DecisionRecord) -> dict[str, Any]:
    """The record's fields in the codec's order, optional keys only when set."""
    result: dict[str, Any] = {
        key: getattr(record, key) for key in _DECISION_REQUIRED_KEYS
    }
    if record.metrics is not None:
        result["metrics"] = copy.deepcopy(record.metrics)
    for name in _DECISION_PLAIN_KEYS:
        value = getattr(record, name)
        if value is not None:
            result[name] = value
    if record.related_actions:
        result["related_actions"] = list(record.related_actions)
    if record.expected:
        result["expected"] = expected_to_list(record.expected)
    if record.applied_params is not None:
        result["applied_params"] = copy.deepcopy(record.applied_params)
    if record.approval is not None:
        result["approval"] = approval_to_dict(record.approval)
    return result


__all__ = ["DECISION_KNOWN_KEYS", "decision_to_dict", "parse_decisions"]
