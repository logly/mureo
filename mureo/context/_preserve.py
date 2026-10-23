"""Re-emitting an entry the codec kept with its on-disk dict (#859 / #881 / #882).

One rule, shared by every STATE.json entry that carries a ``raw`` field —
:class:`~mureo.context.models.ActionLogEntry` (#859),
:class:`~mureo.context.models.PlatformState` /
:class:`~mureo.context.models.CampaignSnapshot` /
:class:`~mureo.context.models.AdState` (#881) and
:class:`~mureo.context.decisions.DecisionRecord` (#882). Two copies of it
would be two answers to "what does a hand-authored entry look like after
mureo writes the document", and they would drift. The same holds for
:func:`exact_string`, the one shape in which an opaque entry's identifying
strings are read at all, and for :func:`copied_raw`, the defensive copy
every one of those models takes of its ``raw`` field. :func:`is_opaque_decision`
lives here rather than beside ``_opaque_decision`` in
:mod:`mureo.context._decision_codec` because :mod:`mureo.context.decisions`
needs it, and that codec imports ``decisions``. :func:`refuse_if_kept` is the
one refusal every writer gives before recording into a ``decisions`` /
``action_log`` kept as found, and :data:`KEPT_REWRITE_MESSAGE` the last-line
one :func:`mureo.context.state_codec.render_state` gives.

Stdlib only, so every codec imports it at module level without a cycle.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Collection

    from mureo.context.decisions import DecisionRecord
    from mureo.context.models import StateDocument

#: Why a writer refuses to record into a ``decisions`` / ``action_log`` kept
#: as found (#882): those sections are history, and recording would replace
#: a value somebody wrote. Names the section only, never the value.
KEPT_SECTION_MESSAGE: Final = (
    "STATE.json: '{section}' is not a list; fix the file by hand before {action}"
)

#: Why :func:`mureo.context.state_codec.render_state` refuses a document that
#: holds both a kept ``decisions`` / ``action_log`` and new records (#882):
#: the last line behind :func:`refuse_if_kept`.
KEPT_REWRITE_MESSAGE: Final = (
    "STATE.json: '{section}' was kept as written and cannot be rewritten; "
    "fix the file by hand"
)


def preserved_dict(
    raw: Mapping[str, Any],
    canonical: Mapping[str, Any],
    *,
    required: Collection[str],
    known: Collection[str],
    opaque: bool,
) -> dict[str, Any]:
    """Re-emit a preserved entry in its on-disk key order.

    ``canonical`` is the entry as the codec would emit it from its fields
    alone; ``required`` / ``known`` are the codec's required and known keys.

    A known key carries the entry's CURRENT value, so a mutation lands (and
    the model's normalisation applies, as it always has); one whose field is
    now unset is left out, so a cleared field stays cleared — except on an
    ``opaque`` entry (one the model refused), whose other optional fields
    were never read, so an unset one is emitted as found.
    A required key whose current value is empty is emitted exactly as found
    (absent stays absent, null stays null) rather than as an invented ``""``.
    An unknown key is copied through. Known fields set on the entry but not
    on disk (e.g. a stamped ``batch_id``) follow, in the codec's order; one
    whose value is ``None`` is not added, so a codec that emits some unset
    keys as ``null`` does not invent them on an entry that never had them.
    """
    result: dict[str, Any] = {}
    for key, raw_value in raw.items():
        if key in required:
            current = canonical[key]
            result[key] = current if current else copy.deepcopy(raw_value)
        elif key not in known:
            result[key] = copy.deepcopy(raw_value)
        elif key in canonical:
            result[key] = canonical[key]
        elif opaque:
            result[key] = copy.deepcopy(raw_value)
    for key, value in canonical.items():
        if key in raw or value is None or (key in required and not value):
            continue
        result[key] = value
    return result


def exact_string(value: Any) -> str | None:
    """``value`` when it is a non-blank string the model would not strip.

    How an OPAQUE entry (one the model refused) reads a string it still
    needs — an ``action_log`` entry's ``origin`` / ``external_id``, a
    decision record's ``decision_id``: only in a shape the model takes
    unchanged, so building the opaque entry cannot itself be refused and the
    verbatim write-back stays byte-identical.
    """
    if isinstance(value, str) and value and value == value.strip():
        return value
    return None


def copied_raw(raw: object) -> dict[str, Any] | None:
    """A ``raw`` field's defensive copy (#859 / #881 / #882); refuses a non-object.

    Shared by every model that keeps its on-disk dict: the codec reads ``raw``
    back at render time, so a caller still holding the source dict must not be
    able to change what is written.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("raw must be an object")
    return copy.deepcopy(dict(raw))


def is_opaque_decision(record: DecisionRecord) -> bool:
    """Whether ``record`` is an opaque decision record (#882).

    An opaque record is one the strict read refused and kept as written; it
    is the only kind with an empty ``status`` (every record the model takes
    holds one of :data:`~mureo.context.decisions.DECISION_STATUSES`). A
    record the model took that keeps ``raw`` for its unknown keys is not
    opaque.
    """
    return record.raw is not None and record.status == ""


def refuse_if_kept(doc: StateDocument, section: str, action: str) -> None:
    """Refuse ``action`` when ``doc`` kept ``section`` as found (#882).

    A ``decisions`` / ``action_log`` that is not a list is kept on
    :attr:`~mureo.context.models.StateDocument.raw` and reads as ``()``, so
    every other writer still works; recording into it would replace it.
    Raises ``ValueError`` with :data:`KEPT_SECTION_MESSAGE`.
    """
    if doc.raw is not None and section in doc.raw:
        raise ValueError(KEPT_SECTION_MESSAGE.format(section=section, action=action))


__all__ = [
    "KEPT_REWRITE_MESSAGE",
    "KEPT_SECTION_MESSAGE",
    "copied_raw",
    "exact_string",
    "is_opaque_decision",
    "preserved_dict",
    "refuse_if_kept",
]
