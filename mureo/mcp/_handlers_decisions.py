"""MCP handler for ``mureo_decision_record`` (#758, phase 3).

One call, one appended record. Everything the record needs that the caller
must NOT supply — the id and the timestamp — is minted here from the server
clock (#460), and everything the caller CAN get wrong — an index into
``action_log``, a ``supersedes``, a ``batch_id`` — is validated inside the
file lock by :func:`mureo.context.decisions.append_decision` rather than
here, so a concurrent append cannot make a check stale between the two.

Path resolution goes through the shared
:func:`mureo.mcp._helpers.resolve_workspace_path`: an MCP caller must not be
able to point this at a STATE.json outside the active workspace, and a
second copy of that check is where the two would drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from mureo.context._decision_codec import decision_to_dict
from mureo.context.batch import BatchError
from mureo.context.decisions import DecisionRecord, append_decision, new_decision_id
from mureo.core.clock import server_now_iso
from mureo.mcp._helpers import _json_result, _opt, _require, resolve_workspace_path

if TYPE_CHECKING:
    from mcp.types import TextContent

#: How ``mureo_state_get`` may scope the ``decisions`` section.
#:
#: Two values, not three: unlike ``action_log`` there is no useful "pending"
#: here. A ``proposed`` record superseded by nothing IS the open question,
#: but answering "which are still open" means walking every ``supersedes``
#: chain, and the section's whole point is that an old decision stays
#: readable — a filtered view that quietly drops the record you were about
#: to re-propose would defeat it.
DECISIONS_SCOPES: Final[tuple[str, ...]] = ("all", "none")


def _build_record(arguments: dict[str, Any]) -> DecisionRecord:
    """Assemble the record a call describes, with the server's own stamps.

    ``recorded_at`` is taken once and fed to :func:`new_decision_id`, so the
    id an operator reads back names the moment the record says it was made.
    The model raises ``ValueError`` on every bound and vocabulary, which is
    already the dispatcher's caller-error channel.
    """
    recorded_at = server_now_iso()
    return DecisionRecord(
        decision_id=new_decision_id(recorded_at),
        recorded_at=recorded_at,
        status=_require(arguments, "status"),
        title=_require(arguments, "title"),
        rationale=_require(arguments, "rationale"),
        metrics=_opt(arguments, "metrics"),
        platform=_opt(arguments, "platform"),
        campaign_id=_opt(arguments, "campaign_id"),
        entity_type=_opt(arguments, "entity_type"),
        entity_id=_opt(arguments, "entity_id"),
        related_actions=_opt(arguments, "related_actions") or (),
        supersedes=_opt(arguments, "supersedes"),
        batch_id=_opt(arguments, "batch_id"),
    )


async def handle_decision_record(arguments: dict[str, Any]) -> list[TextContent]:
    """Append one decision record and return it as stored.

    The response echoes the STORED record — with the server's id, timestamp
    and actor stamps on it — rather than the arguments, because the
    ``decision_id`` is what the next call passes as ``supersedes`` and the
    caller has no other way to learn it.

    ``BatchError`` is re-raised as ``ValueError``: it is a bad argument like
    any other, and the dispatcher classifies it as one (``invalid_args`` in
    the journal) instead of as an mureo-side failure.
    """
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    record = _build_record(arguments)
    try:
        doc, index = append_decision(path, record)
    except BatchError as exc:
        raise ValueError(str(exc)) from exc
    return _json_result(
        {
            "decision": decision_to_dict(doc.decisions[index]),
            "index": index,
            "decisions_total": len(doc.decisions),
        }
    )


def apply_decisions_scope(payload: dict[str, Any], scope: Any) -> None:
    """Scope ``payload['decisions']`` in place for a ``mureo_state_get``.

    ``all`` (the default) leaves the section as rendered. ``none`` drops it
    and leaves ``decisions_total`` plus a ``decisions_scope`` marker behind,
    on the same rule ``action_log`` follows: a section that is absent
    because it was filtered must never read as a section that is absent
    because it is empty.

    ``decisions_total`` is emitted in BOTH modes whenever the document has
    any decisions. The trail is the one section an agent is meant to consult
    before re-proposing something, so a count it can see is worth the key:
    "there are 14 of these" is actionable where silence is not.

    A document with no decisions gains neither key — the legacy response
    shape is unchanged for every workspace that has never recorded one.
    """
    if scope not in DECISIONS_SCOPES:
        raise ValueError(f"decisions must be one of {list(DECISIONS_SCOPES)}")
    records = payload.get("decisions")
    if not records:
        return
    payload["decisions_total"] = len(records)
    if scope == "none":
        payload["decisions_scope"] = scope
        payload.pop("decisions", None)


__all__ = ["DECISIONS_SCOPES", "apply_decisions_scope", "handle_decision_record"]
