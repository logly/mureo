"""The ``action_log`` entry model (#851).

Split out of :mod:`mureo.context.models` for the reason
:mod:`mureo.context.display_models` was: that file is at the repo's size
limit. :mod:`mureo.context.models` re-exports :class:`ActionLogEntry` and
:data:`EXTERNAL_ORIGIN`, so ``from mureo.context.models import
ActionLogEntry`` keeps working and is still the path callers import from.

Imports nothing from :mod:`mureo.context.models`, which imports this module.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.context._preserve import copied_raw
from mureo.context.approval import parse_approval

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.approval import ApprovalRef

#: The #848 ``ActionLogEntry`` maps, refused unless they are objects.
_OBJECT_FIELDS: tuple[str, ...] = ("evaluation", "applied_params")

#: ``ActionLogEntry.origin`` value for a change mureo OBSERVED rather than
#: performed (#545). ``origin is None`` — every entry written before this
#: field existed, and every entry mureo writes for its own dispatch — means
#: mureo-originated. The two must never collapse into one another: mureo can
#: vouch for the arguments of its own change and can often reverse it, and can
#: do neither for a change made in a platform's UI.
EXTERNAL_ORIGIN = "external"


@dataclass(frozen=True)
class ActionLogEntry:
    """Immutable record of a single action performed on a campaign.

    metrics_at_action: Key metrics at the time of action (e.g., {"cpa": 5200, "conversions": 45}).
        Used by the agent to evaluate the outcome of the action after the observation window.
    observation_due: ISO 8601 date when the agent should evaluate the outcome (e.g., "2026-04-15").
        Typical windows: budget changes 7 days, keyword/creative changes 14 days.
    reversible_params: Structured hint describing how to reverse this action. Shape:
        ``{"operation": "<tool_name>", "params": {...}, "caveats": [...]}``.
        Agents set this when making reversible changes (budget update, status toggle,
        etc.) so ``mureo.rollback.plan_rollback()`` can build a concrete reversal plan.
        ``None`` means the action was not marked reversible (read-only query, create,
        delete, or simply not annotated). The ``operation`` value must be in the
        rollback planner's allow-list (see ``mureo.rollback.planner._ALLOWED_OPERATIONS``);
        values outside it — including destructive verbs like ``.delete`` — are refused
        so a prompt-injected or buggy agent cannot smuggle a privileged call through
        the rollback path.
    ad_id: The ad this action targeted, when it was ad-level (#468). Without it an
        ad-level pause could only be recorded as free text, so a later run could not
        match what mureo did against the ad statuses it observes — and would have to
        guess whether a stopped ad was its own doing or an operator's manual change.
    entity_type / entity_id: Generic sub-campaign identity for targets that are not
        ads, such as Google ad groups, Meta ad sets, or placements (#524). The pair
        lets a later run suppress a repeated recommendation for the same entity
        without suppressing unrelated changes across the whole campaign.
    evaluation_of: Positional index (into the full, append-only action_log) of the
        action whose ``observation_due`` this entry evaluates and closes. Same
        index semantics as ``rollback_of``: the log is append-only, so an entry's
        index never shifts. ``mureo_outcome_evaluate`` is pure and writes nothing,
        so without this marker a past-due observation would stay "pending" forever
        (re-evaluated every daily-check, the set growing unbounded). Appending an
        entry with ``evaluation_of=<index>`` records that the outcome was reviewed
        and takes the source out of the pending set. ``None`` means this entry is
        not an evaluation record.
    batch_id: The logical batch this action was dispatched as part of (#549), or
        ``None`` for a standalone action — which every entry written before this
        field existed is, so old STATE.json files parse unchanged and gain no new
        key on the next write. Membership is what makes "undo what I did on
        Monday" expressible: ``rollback_plan_get`` takes the id and reports the
        reversibility of EVERY member before anything is applied, so the operator
        never has to reconstruct a change set from memory. Stamped automatically
        by :func:`mureo.context.state.append_action_log` from the workspace's open
        batch, so a native, hosted-connector and bridged/plugin mutation all join
        the same unit without any per-platform code.
    origin: Who made this change (#545). ``None`` — the default, and what every
        entry written before this field existed carries — means mureo did:
        mureo dispatched it, a policy gate saw it, and its ``reversible_params``
        are mureo's own. :data:`EXTERNAL_ORIGIN` means mureo only OBSERVED it,
        having read it out of a platform's change feed after the fact. The
        distinction is load-bearing rather than cosmetic: mureo cannot vouch for
        an external change's arguments, did not record the prior value, and
        therefore refuses to plan a rollback for it (see
        :func:`mureo.rollback.planner.plan_rollback`). Collapsing the two would
        let mureo claim it can undo work it never did.
    external_id: The change feed's identity for an external change, namespaced by
        platform (``"google_ads|customers/…/changeEvents/…"``). It is what makes
        importing idempotent — the same change polled twice must not be recorded
        twice — so it is only meaningful together with ``origin``, and setting it
        without :data:`EXTERNAL_ORIGIN` is refused rather than ignored.
    occurred_at: When the PLATFORM says an external change happened, which is
        routinely hours or days before mureo saw it. ``timestamp`` stays what it
        has always been — when mureo wrote this entry, stamped server-side (#460)
        — so nothing here reintroduces a model-supplied "now"; ``occurred_at`` is
        history reported by the platform and must never be read as the current
        date. The observation window anchors on it, because a change that has
        been live for a week is already due for review, not due in a fortnight.
        ``None`` for a mureo-originated entry, where the two coincide.
    display_title / display_summary: The ONE LINE the dashboard shows for this
        entry (#706). ``summary`` is a work-journal note written for the next
        agent — it runs to several hundred characters, and rendering it on a
        card is what turned the action log into a wall of prose. These two are
        the operator-facing version, bounded by
        :data:`~mureo.core.display_contract.ACTION_LOG_DISPLAY_TITLE_MAX_CHARS`
        / :data:`~mureo.core.display_contract.
        ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS` at the write boundary
        (:func:`mureo.context.state.append_action_log`), which REFUSES an
        over-long value rather than truncating it.

        They ADD a rendering; they replace nothing. ``summary`` keeps being
        written as fully as the next agent needs, and stays readable in the
        drill-down. ``None`` — the default, and what every entry written
        before these fields existed carries — means this entry has no display
        line, so an old STATE.json parses unchanged and gains no new key on
        the next write.

        The bound lives on the WRITE path rather than in this model, for the
        same reason ``set_report``'s does: an entry already on disk is real
        history, and a document that arrived from elsewhere must stay
        readable rather than being refused wholesale.
    reason: WHY this change was made, in the agent's own words at the moment
        it dispatched the call (#758 phase 2). Every mutating tool takes a
        ``reason`` parameter and
        :func:`mureo.context.state.append_action_log` stamps it here, so the
        rationale survives the session that held it. Bounded by
        :data:`~mureo.core.actor.ACTION_REASON_MAX_CHARS` on the write path,
        which REFUSES an over-long value rather than truncating it — the same
        rule the display fields follow. ``None`` — the default, and what
        every entry written before this field existed carries — means no
        rationale was given.

        Only ever mureo's OWN motive. An ``origin="external"`` entry does
        not inherit the importing call's rationale: mureo did not make that
        change and has no standing to say why it was made.
    session_id: The journal session of the process that WROTE this entry —
        which is not always the process that made the change (an import or
        a replay writes somebody else's). The same id the matching
        ``JOURNAL.jsonl`` records carry, which is what joins the curated
        summary to the complete call record: given an entry, an operator can
        pull every call that session also made. Stamped by
        ``append_action_log`` when unset; an explicit value is kept.
    client: The MCP client label (``"<name>/<version>"``) the writing process
        was serving, or ``None`` for a CLI or library write — which is an
        honest answer, not a gap: nothing there had a client. Documents the
        writer, like ``session_id``, and is stamped alongside it.
    decision_id / evaluation / applied_params: Ops history (#848, see
        :mod:`mureo.context.ops_linkage`): the decision carried out, the
        evaluation table of an ``outcome_evaluated`` record, and the masked
        parameters the call sent. ``None`` on every older entry.
    approval: The external approval this change carried out (#854): recorded
        and shown, never verified. ``None`` on every older entry, so old
        STATE.json files parse unchanged and gain no new key on the next write.
    raw: The entry's on-disk dict, kept only when the codec could not
        represent it fully (#859) — a required key (``timestamp`` /
        ``action`` / ``platform``) was absent, null or not a string, the dict
        carried keys the codec does not know, or this model refused a value
        on it (a malformed ``approval`` included; the entry is then opaque:
        only its timestamp / action / platform and its linking fields
        ``rollback_of`` / ``evaluation_of`` / ``origin`` / ``external_id``
        are read). ``None`` on every entry mureo itself constructs. Used by
        :func:`mureo.context.state_codec.render_state` to write the unknown
        and required keys back as found (absent stays absent) while known
        keys carry the current, model-normalised value — or, for an opaque
        entry, the whole dict verbatim — so a whole-document write neither
        drops operator data nor invents it.
    """

    timestamp: str
    action: str
    platform: str
    campaign_id: str | None = None
    ad_id: str | None = None
    summary: str | None = None
    command: str | None = None
    metrics_at_action: dict[str, Any] | None = None
    observation_due: str | None = None
    reversible_params: dict[str, Any] | None = None
    rollback_of: int | None = None
    evaluation_of: int | None = None
    # Appended after every pre-#524 field to preserve positional-constructor
    # compatibility for third-party callers of this public dataclass.
    entity_type: str | None = None
    entity_id: str | None = None
    # Appended after every pre-#549 field, same positional-compatibility rule.
    batch_id: str | None = None
    # Appended after every pre-#545 field, same positional-compatibility rule.
    origin: str | None = None
    external_id: str | None = None
    occurred_at: str | None = None
    # Appended after every pre-#706 field, same positional-compatibility rule.
    display_title: str | None = None
    display_summary: str | None = None
    # Appended after every pre-#758 field, same positional-compatibility rule.
    reason: str | None = None
    session_id: str | None = None
    client: str | None = None
    # Appended after every pre-#848 field, same positional-compatibility rule.
    decision_id: str | None = None
    evaluation: dict[str, Any] | None = None
    applied_params: dict[str, Any] | None = None
    # Appended after every pre-#854 field, same positional-compatibility rule.
    approval: ApprovalRef | None = None
    # Appended after every pre-#859 field, same positional-compatibility rule.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Take defensive copies of mutable dict fields."""
        object.__setattr__(self, "approval", parse_approval(self.approval))
        object.__setattr__(self, "raw", copied_raw(self.raw))
        self._validate_origin()
        self._validate_actor()
        if self.batch_id is not None:
            if not isinstance(self.batch_id, str) or not self.batch_id.strip():
                raise ValueError("batch_id must be a non-empty string")
            object.__setattr__(self, "batch_id", self.batch_id.strip())
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together")
        if self.entity_type is not None and self.entity_id is not None:
            if not isinstance(self.entity_type, str) or not self.entity_type.strip():
                raise ValueError("entity_type must be a non-empty string")
            if not isinstance(self.entity_id, str) or not self.entity_id.strip():
                raise ValueError("entity_id must be a non-empty string")
            object.__setattr__(self, "entity_type", self.entity_type.strip())
            object.__setattr__(self, "entity_id", self.entity_id.strip())
        for name in ("metrics_at_action", "reversible_params", *_OBJECT_FIELDS):
            value = getattr(self, name)
            if name in _OBJECT_FIELDS and not isinstance(value, (dict, type(None))):
                raise ValueError(f"{name} must be an object")
            if value is not None:
                object.__setattr__(self, name, copy.deepcopy(value))

    def _validate_actor(self) -> None:
        """Enforce the #758 rationale/identity invariants.

        A non-string here is a caller bug — a hand-edited STATE.json, a
        recorder passing an id through unconverted — and it has to say so
        by field name. Left alone it used to surface three frames later as
        ``'int' object has no attribute 'strip'``, which names neither the
        field nor the file.

        ``reason`` and the two identity fields differ on BLANK on purpose.
        An empty rationale is a real answer ("none was given") and reads as
        ``None``; an empty ``session_id`` or ``client`` is a broken write,
        because the process that wrote the entry always had an identity —
        so those are refused, matching ``batch_id`` and ``origin``.
        """
        if self.reason is not None:
            if not isinstance(self.reason, str):
                raise ValueError("reason must be a string")
            # The LENGTH bound lives on the write path (see the field
            # docstring), not here: an entry already on disk is history.
            object.__setattr__(self, "reason", self.reason.strip() or None)
        for name in ("session_id", "client", "decision_id"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            if not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())

    def _validate_origin(self) -> None:
        """Enforce the #545 provenance invariants.

        Three refusals, all of the same kind: a half-declared provenance is
        worse than none, because every downstream surface (rollback, dedup,
        daily-check) reads one of these fields and would draw a confident
        conclusion from a value the others contradict.
        """
        if self.origin is not None:
            if not isinstance(self.origin, str) or not self.origin.strip():
                raise ValueError("origin must be a non-empty string")
            object.__setattr__(self, "origin", self.origin.strip())
        if self.external_id is not None:
            if not isinstance(self.external_id, str) or not self.external_id.strip():
                raise ValueError("external_id must be a non-empty string")
            object.__setattr__(self, "external_id", self.external_id.strip())
            # An external_id on a mureo-originated entry has no meaning and
            # would poison dedup: the next import would treat mureo's own
            # action as a change it had already imported.
            if self.origin != EXTERNAL_ORIGIN:
                raise ValueError(
                    f"external_id requires origin={EXTERNAL_ORIGIN!r}; got "
                    f"origin={self.origin!r}"
                )
        if self.occurred_at is not None and (
            not isinstance(self.occurred_at, str) or not self.occurred_at.strip()
        ):
            raise ValueError("occurred_at must be a non-empty string")
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", self.occurred_at.strip())

    @property
    def is_external(self) -> bool:
        """Did mureo merely observe this change rather than perform it?

        A property, not a field: it derives from ``origin`` so the two can
        never disagree, and it keeps the dataclass field set — which IS the
        plugin ABI — unchanged by its addition.
        """
        return self.origin == EXTERNAL_ORIGIN


__all__ = [
    "EXTERNAL_ORIGIN",
    "ActionLogEntry",
]
