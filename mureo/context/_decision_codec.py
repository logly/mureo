"""The ``decisions`` section's two codec halves (#758, phase 3).

Split out of :mod:`mureo.context.state_codec` for the reason
:mod:`mureo.context.display_codec` was: that file is at the repo's size
limit. The coverage entry the codec checks at import lives here too
(:data:`DECISION_COVERAGE`), so adding a field to
:class:`~mureo.context.decisions.DecisionRecord` without visiting this file
still raises immediately instead of costing an operator that field.

**Tolerant like ``action_log``, not like ``batches``.** A batch record is
bookkeeping ABOUT history and a malformed one costs only a label, so it is
dropped in both modes. A decision record IS history — the rationale is the
payload — so the writer contract stays strict: ``strict=True`` raises on a
malformed record rather than silently discarding somebody's reasoning, and
only the read-only Reports view (``strict=False``) skips it, so one
hand-edited record cannot blank out a whole document.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from mureo.context.decisions import DecisionRecord

logger = logging.getLogger(__name__)

#: Fields this module maps, for :mod:`mureo.context.state_codec`'s
#: import-time coverage check. Spliced into its ``_CODEC_COVERAGE`` table as
#: one entry so that file, already over the size limit, gains one line.
DECISION_COVERAGE: tuple[type, frozenset[str], str] = (
    DecisionRecord,
    frozenset(
        {
            "decision_id",
            "recorded_at",
            "status",
            "title",
            "rationale",
            "metrics",
            "platform",
            "campaign_id",
            "entity_type",
            "entity_id",
            "related_actions",
            "supersedes",
            "batch_id",
            "session_id",
            "client",
        }
    ),
    "_decision_codec.parse_decisions / .decision_to_dict",
)


#: How much of a ``decision_id`` a log line may quote. Ids are minted
#: server-side and short, so this only bounds what a hand-edited file can
#: push into the log under that key.
_LABEL_MAX_CHARS = 64

#: Keys a stored record cannot be missing. A record with no ``rationale``
#: is not a decision record, and defaulting one would manufacture a reason
#: nobody gave — so the absence is named rather than filled in.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "decision_id",
    "recorded_at",
    "status",
    "title",
    "rationale",
)


def _record_label(item: Any) -> str:
    """How a record is named in a log line: by its id, never by its body.

    A stored record is free text an agent wrote, and a hand-edited file
    never crossed the write path's scrubber — so its ``rationale`` may hold
    a secret that STATE.json's own writer would have redacted. Copying it
    whole into the application log would republish it under different
    rules, in a file nobody thinks of as holding decisions. The id is what
    the operator needs to find the offending record anyway.
    """
    if isinstance(item, dict):
        candidate = item.get("decision_id")
        if isinstance(candidate, str) and candidate.strip():
            return repr(candidate.strip()[:_LABEL_MAX_CHARS])
    return f"<no decision_id, {type(item).__name__}>"


def _parse_decision(item: Any) -> DecisionRecord:
    """Build one :class:`DecisionRecord` from its stored dict.

    Only names the keys: every bound and vocabulary is enforced by the
    model itself (see its docstring), so the two halves cannot disagree
    about what a valid record is.

    Refusals name the shape, not the value, because these messages reach
    the log by way of :func:`parse_decisions` — see :func:`_record_label`.
    """
    if not isinstance(item, dict):
        raise ValueError(
            f"decision record must be an object; got {type(item).__name__}"
        )
    for name in _REQUIRED_FIELDS:
        if name not in item:
            raise ValueError(f"decision record is missing required field {name!r}")
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
    )


def parse_decisions(raw: Any, *, strict: bool) -> tuple[DecisionRecord, ...]:
    """Parse the ``decisions`` section.

    Absent reads as empty in both modes — every document written before this
    section existed has no key, and that is not a defect to report.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        if strict:
            raise ValueError(f"'decisions' must be a list; got {type(raw).__name__}")
        logger.debug(
            "skipping non-list 'decisions' value of type %s", type(raw).__name__
        )
        return ()
    if strict:
        return tuple(_parse_decision(item) for item in raw)
    parsed: list[DecisionRecord] = []
    for item in raw:
        try:
            parsed.append(_parse_decision(item))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING: the read-only Reports view re-parses on
            # every poll, so a per-record warning would flood the log.
            logger.debug(
                "skipping unparseable decision record %s: %s",
                _record_label(item),
                exc,
            )
    return tuple(parsed)


def decision_to_dict(record: DecisionRecord) -> dict[str, Any]:
    """Serialize one record; optional fields are emitted only when set.

    ``related_actions`` is emitted only when non-empty, on the same rule, so
    a decision that names no action gains no key rather than storing ``[]``
    — which would read as "checked, and there were none".
    """
    result: dict[str, Any] = {
        "decision_id": record.decision_id,
        "recorded_at": record.recorded_at,
        "status": record.status,
        "title": record.title,
        "rationale": record.rationale,
    }
    if record.metrics is not None:
        result["metrics"] = copy.deepcopy(record.metrics)
    for name in (
        "platform",
        "campaign_id",
        "entity_type",
        "entity_id",
        "supersedes",
        "batch_id",
        "session_id",
        "client",
    ):
        value = getattr(record, name)
        if value is not None:
            result[name] = value
    if record.related_actions:
        result["related_actions"] = list(record.related_actions)
    return result


__all__ = ["DECISION_COVERAGE", "decision_to_dict", "parse_decisions"]
