"""One ``action_log`` entry's two codec halves (#859).

Split out of :mod:`mureo.context.state_codec` for the reason
:mod:`mureo.context.display_codec` and :mod:`mureo.context._decision_codec`
were: that file is at the repo's size limit. The list-level loop (strict vs
tolerant) and the import-time coverage check stay there; the check builds
its ``ActionLogEntry`` row from :data:`ACTION_LOG_KNOWN_KEYS`, so a model
field this module does not name still fails at import.

**No object entry can block a write.** The log is the operator's
append-only history and its indices are positional (``rollback_of`` /
``evaluation_of``), so every entry that is a JSON object is kept IN PLACE,
and both read modes build it the same way:

- an entry missing a required key (``timestamp`` / ``action`` /
  ``platform``), holding a non-string one, or carrying keys the codec does
  not know reads with those required fields as ``""`` and keeps its on-disk
  dict as :attr:`ActionLogEntry.raw`. On write, the unknown keys and the
  required keys are emitted as found; the known keys carry the entry's
  current value, normalised by the model exactly as before;
- an entry holding a value the model refuses (a malformed ``approval``
  included) is kept OPAQUE: only its required keys and its linking fields
  (``rollback_of`` / ``evaluation_of`` / ``origin`` / ``external_id``, when
  they hold a value the model takes as is) are read, and it is written back
  verbatim in full.

Only an entry that is not an object is refused (``TypeError``); the
list-level loop decides whether that raises or is skipped.

Dependency-free beyond stdlib and :mod:`mureo.context.models` /
:mod:`mureo.context.approval` — the discipline ``state_codec`` keeps, since
``mureo.core`` -> ... -> ``mureo.context.state`` is a real import chain.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from mureo.context.approval import approval_to_dict, parse_approval
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: The ``action_log`` keys every entry must carry. Read with ``.get`` (#859):
#: a missing, null or non-string value reads as ``""`` and the entry keeps its
#: ``raw`` dict, so it is written back as found rather than with an invented
#: value.
_ACTION_LOG_REQUIRED_KEYS: tuple[str, ...] = ("timestamp", "action", "platform")

#: The optional ``action_log`` keys, in the order :func:`action_log_entry_to_dict`
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
#: makes the parser keep the entry's ``raw`` dict (#859). The coverage check
#: in :mod:`mureo.context.state_codec` is built from this set, so a model
#: field missing here fails at import.
ACTION_LOG_KNOWN_KEYS: frozenset[str] = frozenset(
    (*_ACTION_LOG_REQUIRED_KEYS, *_ACTION_LOG_OPTIONAL_KEYS)
)


def parse_action_log_entry(e: dict[str, Any]) -> ActionLogEntry:
    """Create an ActionLogEntry from a dict (``TypeError`` if it is not one).

    A missing, null or non-string required key reads as ``""``, and an entry
    the codec cannot re-emit from its fields alone keeps its dict as ``raw``
    (#859). An entry the model refuses — a value ``ActionLogEntry`` rejects,
    a malformed ``approval`` included — is kept OPAQUE: only its required
    keys and linking fields are read (see :func:`_opaque_entry`) and ``raw``
    carries the rest, so it is written back verbatim instead of blocking the
    write. There is no mode: the strict writer and the read-only view build
    the same entry from the same dict, so :func:`_action_log_refused` can
    re-derive opacity at render time.
    """
    if not isinstance(e, dict):
        raise TypeError(f"action_log entry must be an object, got {type(e).__name__}")
    raw = e if _action_log_unrepresentable(e) else None
    try:
        return _action_log_entry_from_dict(e, raw=raw)
    except ValueError as exc:
        # DEBUG, not WARNING: the read-only view re-parses on every poll. Only
        # the exception TYPE is logged — its message can quote a value, which
        # is free text an operator typed.
        logger.debug(
            "keeping a refused action_log entry opaque (%s)", type(exc).__name__
        )
        return _opaque_entry(e)


def _action_log_entry_from_dict(
    e: dict[str, Any], *, raw: dict[str, Any] | None
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
        # #706 — the operator-facing line. Absent on every older entry.
        display_title=e.get("display_title"),
        display_summary=e.get("display_summary"),
        # #758 phase 2 — the rationale and the writing session. Absent on
        # every older entry: "nobody recorded why, and we cannot say who".
        reason=e.get("reason"),
        session_id=e.get("session_id"),
        client=e.get("client"),
        # #848 ops history. Absent on every older entry.
        decision_id=e.get("decision_id"),
        evaluation=e.get("evaluation"),
        applied_params=e.get("applied_params"),
        # #854. Absent on every older entry. A malformed one is refused here
        # in BOTH read modes, which makes the entry opaque (#859).
        approval=parse_approval(e.get("approval")),
        raw=raw,
    )


def _opaque_entry(e: dict[str, Any]) -> ActionLogEntry:
    """The entry for a dict the model refused: required and linking fields only.

    The linking fields are read independently of the refusal, because
    leaving them unread would fail open: a refused rollback record must
    still tell the executor its target was already reversed, an evaluation
    record must still close its observation, and an imported change must
    still be seen by the import dedupe. Each is read only in a shape the
    model takes unchanged — so this construction cannot itself be refused
    and the verbatim write-back stays byte-identical.
    """
    required = _action_log_required(e)
    origin = _exact_string(e.get("origin"))
    external_id = _exact_string(e.get("external_id"))
    return ActionLogEntry(
        timestamp=required["timestamp"],
        action=required["action"],
        platform=required["platform"],
        rollback_of=_index_or_none(e.get("rollback_of")),
        evaluation_of=_index_or_none(e.get("evaluation_of")),
        origin=origin,
        # The model requires origin="external" beside an external_id.
        external_id=external_id if origin == EXTERNAL_ORIGIN else None,
        raw=e,
    )


def _index_or_none(value: Any) -> int | None:
    """``value`` when it is an int (``bool`` excluded, as everywhere), else None."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _exact_string(value: Any) -> str | None:
    """``value`` when it is a non-blank string the model would not strip."""
    if isinstance(value, str) and value and value == value.strip():
        return value
    return None


def _action_log_refused(raw: Mapping[str, Any]) -> bool:
    """Whether the model refuses ``raw`` — i.e. it was parsed as an opaque entry.

    Re-deriving this at render time is safe: it runs the very function
    :func:`parse_action_log_entry` ran, with no mode (both read modes build
    an entry the same way) and no external state, on the dict the entry
    kept. So it answers exactly as parse time did.
    """
    try:
        _action_log_entry_from_dict(dict(raw), raw=None)
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
    return any(k not in ACTION_LOG_KNOWN_KEYS for k in e)


def action_log_entry_to_dict(e: ActionLogEntry) -> dict[str, Any]:
    """Convert an ActionLogEntry to a dictionary.

    An entry without ``raw`` — every entry mureo constructs — is emitted from
    its fields alone: the three required keys, then each optional key that is
    set (#545 / #706 / #758 / #848 / #854: an entry written before a key
    existed round-trips byte-identically and gains no new key). An entry WITH
    ``raw`` is re-emitted in its on-disk shape (#859), see
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

    A known key carries the entry's CURRENT value, so a mutation lands (and
    the model's normalisation applies, as it always has); one whose field is
    now unset is left out, so a cleared field stays cleared — except on an
    ``opaque`` entry (one the model refused), whose other optional fields
    were never read, so an unset one is emitted as found.
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
        elif key not in ACTION_LOG_KNOWN_KEYS:
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


__all__ = [
    "ACTION_LOG_KNOWN_KEYS",
    "action_log_entry_to_dict",
    "parse_action_log_entry",
]
