"""The reasoning behind a change, kept past the session (#758, phase 3).

``action_log`` says WHAT changed and, since phase 2, why that one call was
dispatched. Neither answers the question an operator actually asks weeks
later: *what did we consider, what did we decide, and on what numbers?* A
proposal that was rejected changed nothing, so it is correctly absent from
``action_log`` — and it is exactly the record that stops the next session
proposing it again.

**Why not ``display.proposals``.** That section already holds proposals,
and it cannot be this: ``mureo_state_display_set`` REPLACES the whole
``display`` contract on every write, so Monday's proposal is gone the
moment Tuesday's skill draws the screen. It is a screen — one moment,
bounded to a card's width — and a screen is not a history. ``decisions``
is the history: append-only like ``action_log``, unbounded by what fits in
a dashboard row, and never rewritten.

**Append-only, so a status change is a NEW record.** Adopting a proposal
does not edit the ``proposed`` record; it appends an ``adopted`` one that
names the first in ``supersedes``. Editing in place would destroy the one
thing the trail is for — that the decision was first made as a proposal,
at a time, on figures that were true then. The same reason ``action_log``
records a reversal as an entry rather than deleting the entry it reverses.

The pure half lives here with the model, the cross-reference checks and the
queries. The writer, which needs STATE.json's file lock, is
:func:`mureo.context.decision_store.append_decision` (#879):
:mod:`mureo.context.state_codec` reads :class:`DecisionRecord`, so this module
sits below :mod:`mureo.context.state_io` and does not import it.
"""

from __future__ import annotations

import copy
import math
import re
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from mureo.context._preserve import copied_raw, is_opaque_decision
from mureo.context.approval import parse_approval
from mureo.context.batch import ID_ENTROPY_BYTES, BatchError, find_batch
from mureo.context.expected import ExpectedEffect, parse_expected
from mureo.core.scrub import scrub_text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.approval import ApprovalRef
    from mureo.context.models import StateDocument

#: What a record may say about the decision it holds. A closed vocabulary,
#: because every reader (a later session deciding whether to re-propose, an
#: operator reading the trail) branches on it: a free-text status would be
#: spelled four ways within a month and read by nothing.
#:
#: ``deferred`` is not ``rejected``. "Not now" and "no" call for different
#: behaviour next week, and collapsing them would either bury a live idea or
#: keep re-raising a dead one.
DECISION_STATUSES: Final[tuple[str, ...]] = (
    "proposed",
    "adopted",
    "rejected",
    "deferred",
)

#: The decision in one line, the length a person reads off a list.
DECISION_TITLE_MAX_CHARS: Final = 120

#: The reasoning. Generous — this is the paragraph the whole feature exists
#: to keep — but bounded, because STATE.json is read whole on every write.
DECISION_RATIONALE_MAX_CHARS: Final = 2000

#: How many figures a decision may be judged on. A handful of headline
#: numbers is evidence; a hundred is a report, and a report belongs in
#: ``reports`` where it has a shape.
DECISION_METRICS_MAX_KEYS: Final = 20

#: Longest string a single ``metrics`` value may be. These land in a numeric
#: column beside real figures, so anything longer is prose that belongs in
#: ``rationale`` — the same call ``DisplayStatedValue`` makes one level up.
DECISION_METRIC_VALUE_MAX_CHARS: Final = 200

#: How many ``action_log`` entries one decision may claim. A decision that
#: names fifty changes is a batch, and a batch already has an id of its own
#: (``batch_id``). The bound also keeps the write-time validation loop — and
#: the operator's reading of it — finite.
DECISION_RELATED_ACTIONS_MAX: Final = 50

#: What a ``metrics`` value may be. Flat scalars only: the figures have to
#: stay comparable to an ``action_log`` entry's ``metrics_at_action`` and
#: renderable in a column, and a nested object would be neither.
_METRIC_VALUE_TYPES: Final = (str, int, float, bool)

#: C0/C1 control characters, minus TAB and LF.
#:
#: Stripped from every free-text field rather than refused: they are not
#: content, and refusing a write over an invisible byte an agent never meant
#: to send would cost the rationale the section exists to keep. Left in, they
#: are a real hazard — STATE.json is read back by ``mureo journal``, the CLI
#: and the dashboard, and an ESC sequence written by a model can clear the
#: operator's screen or spoof a confirmation prompt (the reason
#: :func:`mureo.cli._tty.terminal_safe` exists on the read side). CR is
#: stripped with them: alone it only overwrites a line.
#:
#: TAB and LF survive because a ``rationale`` may legitimately be a short
#: paragraph, and dropping a newline would join two words into one.
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def new_decision_id(recorded_at: str = "") -> str:
    """Mint a decision id.

    Prefixed with the record's timestamp for the same reason
    :func:`mureo.context.batch.new_batch_id` is: the operator reads these
    ids out of tool output and types them back into the ``supersedes`` of
    the next call, and ``dec-20260919T101233-1f4c9a02`` says which
    decision it was where a bare UUID does not. Uniqueness comes from the
    random suffix, so two decisions recorded in the same second are still
    distinct.
    """
    suffix = secrets.token_hex(ID_ENTROPY_BYTES)
    stamp = "".join(ch for ch in recorded_at[:19] if ch.isdigit() or ch == "T")
    return f"dec-{stamp}-{suffix}" if stamp else f"dec-{suffix}"


@dataclass(frozen=True)
class DecisionRecord:
    """One decision, as it stood at one moment. Never edited afterwards.

    decision_id: Server-minted (:func:`new_decision_id`). Caller-supplied
        ids are not accepted by the MCP tool: an id is what ``supersedes``
        joins on, and a colliding one would silently chain two unrelated
        decisions together.
    recorded_at: When mureo wrote this record, from the server clock (the
        #460 rule). Never model-supplied — an agent's idea of "now" is the
        one thing it demonstrably gets wrong.
    status: One of :data:`DECISION_STATUSES`.
    title / rationale: What was decided, and why, in the agent's own words.
        Both required and non-blank: a decision with no reasoning is the
        state this whole section exists to end.
    metrics: The figures the decision was judged on
        (``{"cpa_7d": 5200, "conversions_7d": 45}``). The point is not the
        numbers but that they are the numbers as they were THEN: a
        rationale read next month against today's figures is unfalsifiable.
    platform / campaign_id / entity_type / entity_id: What the decision is
        about, when it is about one thing. ``entity_type`` and ``entity_id``
        are a pair under the same rule
        :class:`~mureo.context.models.ActionLogEntry` follows — half an
        identity names nothing.
    related_actions: Positional indices into the full, append-only
        ``action_log`` of the entries this decision produced. Same index
        semantics as ``rollback_of`` — the log is append-only, so an index
        never shifts — and validated against the log at write time, so a
        stray number cannot point the operator at somebody else's change.
    supersedes: The ``decision_id`` this record updates. An adoption, a
        rejection and a deferral are all new records naming the proposal
        they answer; nothing here is ever edited in place.
    batch_id: The declared change set this decision concerns, open or
        closed. Unlike an ``action_log`` append, a CLOSED batch is a
        perfectly good target: the decision about a bulk pass is routinely
        recorded after the pass is finished.
    session_id / client: Who wrote the record — the writing process's
        journal session and the connected MCP client label. Stamped by
        :func:`mureo.context.decision_store.append_decision`, exactly as on
        an ``action_log`` entry, so the two trails join on the same id.
    expected: What the decision should move, as structured effects (#848,
        :mod:`mureo.context.expected`) — the metrics the later evaluation
        treats as primary. Empty means nothing was declared.
    applied_params / journal_call_id / journal_tool: Set when mureo wrote
        the record for a call that carried the decision out (#848): the
        parameters the call sent (masked), and the ``call_id`` and tool name
        of that call's ``JOURNAL.jsonl`` record (the tool only for a call
        that wrote no ``action_log`` entry). ``None`` on a record written by
        ``mureo_decision_record``.
    approval: The external approval stated by the call that carried the
        decision out (#854, :mod:`mureo.context.approval`): recorded and
        shown, never verified. The newest record's wins, like
        ``applied_params``. ``None`` on every record written before it
        existed, which therefore gains no key on the next write.
    raw: The on-disk dict of a stored record the codec cannot re-emit from
        its fields alone (#882), in one of two cases. A record the model
        REFUSED — a hand-authored one missing a required key or failing a
        bound — is kept OPAQUE, in place: none of its fields is validated
        or read except ``decision_id`` (when it is a non-blank string the
        model would not strip; ``""`` otherwise), every other field holds
        its empty default (``status`` included, which is how an opaque
        record is told apart), and the codec writes ``raw`` back verbatim.
        Readers never match it (:func:`parsed_decisions`). A record the
        model TAKES that carries keys the codec does not know keeps ``raw``
        too and is validated and read like any other; the codec re-emits
        its unknown keys, the ``action_log`` rule (#859). ``None`` on every
        record mureo constructs.

    Every bound below is enforced on the WRITE path and **refused, never
    truncated** (the #706 rule): the caller still holds the sentence and can
    shorten it, while half a rationale reads as a bug in mureo and nobody
    downstream can tell what was cut.
    """

    decision_id: str
    recorded_at: str
    status: str
    title: str
    rationale: str
    metrics: dict[str, Any] | None = None
    platform: str | None = None
    campaign_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    related_actions: tuple[int, ...] = field(default_factory=tuple)
    supersedes: str | None = None
    batch_id: str | None = None
    session_id: str | None = None
    client: str | None = None
    expected: tuple[ExpectedEffect, ...] = field(default_factory=tuple)
    applied_params: dict[str, Any] | None = None
    journal_call_id: str | None = None
    journal_tool: str | None = None
    approval: ApprovalRef | None = None
    # Appended after every pre-#882 field, same positional-compatibility rule
    # as ``ActionLogEntry``.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate every bound and take a defensive copy of ``metrics``.

        An opaque record (#882, see
        :func:`mureo.context._preserve.is_opaque_decision`) is validated not
        at all: the model already refused it, and it is kept only to be
        written back.
        """
        object.__setattr__(self, "raw", copied_raw(self.raw))
        if is_opaque_decision(self):
            return
        object.__setattr__(self, "approval", parse_approval(self.approval))
        self._validate_required_text()
        self._validate_optional_text()
        self._validate_metrics()
        self._validate_related_actions()
        # The model re-validates the SHAPE only. The one-primary rule is a
        # boundary rule for a new declaration (``parse_expected`` at the
        # tool), never applied to a stored one (#888).
        expected = parse_expected(self.expected, require_primary=False)
        object.__setattr__(self, "expected", expected)
        if self.applied_params is not None:
            if not isinstance(self.applied_params, dict):
                raise ValueError("applied_params must be an object")
            object.__setattr__(
                self, "applied_params", copy.deepcopy(self.applied_params)
            )

    def _validate_required_text(self) -> None:
        """The four fields a record cannot be honest without."""
        for name in ("decision_id", "recorded_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if self.status not in DECISION_STATUSES:
            raise ValueError(
                f"status must be one of {list(DECISION_STATUSES)}; got {self.status!r}"
            )
        _bounded(self, "title", DECISION_TITLE_MAX_CHARS)
        _bounded(self, "rationale", DECISION_RATIONALE_MAX_CHARS)

    def _validate_optional_text(self) -> None:
        """Blank is refused, not read as absent — see ``ActionLogEntry``."""
        for name in ("platform", "campaign_id", "supersedes", "batch_id"):
            _optional_label(self, name)
        for name in ("session_id", "client", "journal_call_id", "journal_tool"):
            _optional_label(self, name)
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together")
        _optional_label(self, "entity_type")
        _optional_label(self, "entity_id")

    def _validate_metrics(self) -> None:
        """Flat scalars, bounded in count and in width, cleaned on the way in."""
        if self.metrics is None:
            return
        if not isinstance(self.metrics, dict):
            raise ValueError("metrics must be an object of scalar values")
        if len(self.metrics) > DECISION_METRICS_MAX_KEYS:
            raise ValueError(
                f"metrics must hold at most {DECISION_METRICS_MAX_KEYS} keys; "
                f"got {len(self.metrics)}"
            )
        cleaned: dict[str, Any] = {}
        for key, value in self.metrics.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metrics keys must be non-empty strings")
            cleaned[key.strip()] = _clean_metric_value(key, value)
        object.__setattr__(self, "metrics", cleaned)

    def _validate_related_actions(self) -> None:
        """Non-negative ``action_log`` indices; ``bool`` is not an index."""
        raw = self.related_actions
        if not isinstance(raw, (list, tuple)):
            raise ValueError("related_actions must be a list of action_log indices")
        if len(raw) > DECISION_RELATED_ACTIONS_MAX:
            raise ValueError(
                f"related_actions must name at most "
                f"{DECISION_RELATED_ACTIONS_MAX} action_log entries; "
                f"got {len(raw)}"
            )
        for value in raw:
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(
                    "related_actions must hold non-negative action_log indices; "
                    f"got {value!r}"
                )
        object.__setattr__(self, "related_actions", tuple(raw))


def _clean_text(value: str) -> str:
    """Strip control characters and redact secret-shaped substrings.

    The two passes every free-text field on a record crosses, in the one
    place all of them cross it — the same single-boundary rule
    :func:`mureo.core.actor.normalize_reason` follows for an ``action_log``
    rationale, so STATE.json cannot disagree with ``JOURNAL.jsonl`` about
    what a secret is. A model that quotes the failing request into its
    reasoning ("retrying after api_key=… was rejected") must not leak the
    key into a file the operator commits.

    Whitespace is trimmed twice, before and after the control strip, so a
    value that was only ``"\x00 "`` ends up empty and is refused by the
    caller rather than stored as a space.
    """
    return scrub_text(_CONTROL_CHARS.sub("", value.strip()).strip())


def _bounded(record: DecisionRecord, name: str, limit: int) -> None:
    """Require a non-blank string of at most ``limit`` characters.

    The length is measured on the CLEANED value — what actually gets
    stored — so a refusal never counts characters the caller cannot see,
    and a title padded with invisible bytes is not rejected as too long.
    Over the bound it is **refused, never truncated**: the caller is
    holding the sentence and can shorten it.
    """
    value = getattr(record, name)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a non-empty string")
    cleaned = _clean_text(value)
    if not cleaned:
        raise ValueError(f"{name} must be a non-empty string")
    if len(cleaned) > limit:
        raise ValueError(
            f"{name} must be at most {limit} characters; got {len(cleaned)}"
        )
    object.__setattr__(record, name, cleaned)


def _clean_metric_value(key: str, value: Any) -> Any:
    """Return one ``metrics`` value as it will be stored, or refuse it.

    Three refusals, one cleaning pass:

    - **A nested object or list** is refused. These figures have to stay
      comparable to an ``action_log`` entry's ``metrics_at_action`` and
      renderable in a column; a structure is neither.
    - **A non-finite float** is refused. ``NaN`` and the infinities have no
      JSON spelling — :func:`json.dumps` writes them as bare ``NaN`` /
      ``Infinity``, which is not valid JSON, so a stricter reader refuses
      the WHOLE STATE.json over one figure.
    - **An over-long string** is refused rather than truncated, like every
      other bound here.

    A surviving string goes through :func:`_clean_text`, so a secret quoted
    into a metric note is redacted exactly as it is in ``rationale``.
    """
    if value is None or isinstance(value, bool):
        return value
    if not isinstance(value, _METRIC_VALUE_TYPES):
        raise ValueError(
            f"metrics[{key!r}] must be a string, number, boolean or null; "
            f"nested values are refused (got {type(value).__name__})"
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            f"metrics[{key!r}] must be a finite number; {value!r} has no JSON "
            "spelling and would make the whole STATE.json unreadable"
        )
    if not isinstance(value, str):
        return value
    cleaned = _clean_text(value)
    if len(cleaned) > DECISION_METRIC_VALUE_MAX_CHARS:
        raise ValueError(
            f"metrics[{key!r}] must be at most "
            f"{DECISION_METRIC_VALUE_MAX_CHARS} characters; got {len(cleaned)}. "
            "A figure that needs a sentence belongs in rationale"
        )
    return cleaned


def _optional_label(record: DecisionRecord, name: str) -> None:
    """Require a non-blank string when the field is set at all."""
    value = getattr(record, name)
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    object.__setattr__(record, name, value.strip())


def parsed_decisions(doc: StateDocument) -> tuple[DecisionRecord, ...]:
    """The records the model took, in write order — opaque ones left out.

    An opaque record (#882) is a hand-authored one the model refused, see
    :func:`mureo.context._preserve.is_opaque_decision`. It stays in
    ``doc.decisions`` at its on-disk
    position so the write keeps it, but none of its fields was validated —
    its ``status``, ``supersedes`` and ``expected`` are empty defaults, not
    what it says — so no reader may match, chain or evaluate against it. A
    record the model took with unknown keys (``raw`` set too) is returned
    like any other. Every reader of the
    trail goes through here; only the writer's duplicate-id check and the
    positional lookup of a just-written record read ``doc.decisions``
    directly.
    """
    return tuple(record for record in doc.decisions if not is_opaque_decision(record))


def decision_by_id(doc: StateDocument, decision_id: str) -> DecisionRecord | None:
    """Return the record ``decision_id`` names, or ``None``.

    Never an opaque record (see :func:`parsed_decisions`).
    """
    wanted = decision_id.strip() if isinstance(decision_id, str) else ""
    if not wanted:
        return None
    for record in parsed_decisions(doc):
        if record.decision_id == wanted:
            return record
    return None


def latest_decisions(
    doc: StateDocument, *, limit: int = 10
) -> tuple[DecisionRecord, ...]:
    """The ``limit`` most recently RECORDED decisions, newest first.

    Ordered by position, not by ``recorded_at``: the section is append-only,
    so position is write order, and it stays right even when a hand-edited
    or replayed timestamp is not. Pinned by a test, because "newest first"
    is the half a caller reads off the front of the tuple.

    The read helper for the surfaces that come next — the dashboard's
    rendering of the trail, and the skill step that asks "what did we
    already propose about this?" before proposing it again. Pure: it takes
    a document, never a path, so a caller that already holds one does not
    re-read the file. Opaque records are left out (see
    :func:`parsed_decisions`).
    """
    if limit <= 0:
        return ()
    return tuple(reversed(parsed_decisions(doc)[-limit:]))


def _check_related_actions(doc: StateDocument, record: DecisionRecord) -> None:
    """Every ``related_actions`` index must address an existing entry."""
    log_len = len(doc.action_log)
    for index in record.related_actions:
        if index >= log_len:
            raise ValueError(
                f"related_actions[{index}] is out of range (action_log has "
                f"{log_len} entries)"
            )


def _check_supersedes(doc: StateDocument, record: DecisionRecord) -> None:
    """``supersedes`` must name a decision that is actually on record."""
    if record.supersedes is None:
        return
    if decision_by_id(doc, record.supersedes) is None:
        raise ValueError(
            f"supersedes names no recorded decision: {record.supersedes!r}. "
            "Read the decision_id out of the record you are updating; a "
            "chain that starts nowhere cannot be followed back."
        )


def _check_unique_id(doc: StateDocument, record: DecisionRecord) -> None:
    """A ``decision_id`` may appear once.

    The id is what ``supersedes`` joins on and what an operator types back
    into the next call. A second record under an id already on file would
    chain two unrelated decisions together, and :func:`decision_by_id` —
    which answers with the FIRST match — would resolve the join to
    whichever happened to be written first. Checked inside the lock, so a
    concurrent append cannot slip between the check and the write.

    The MCP tool mints the id server-side and cannot collide in practice;
    this refuses the library caller, the replay and the hand-built record
    that can.

    Reads ``doc.decisions`` whole, opaque records included (#882): no reader
    matches an opaque record, but it is still written back under its id, so
    a new record under that id would leave the file with two of one id.
    """
    if any(r.decision_id == record.decision_id for r in doc.decisions):
        raise ValueError(
            f"decision_id {record.decision_id!r} is already on record. Ids are "
            "minted per record (see new_decision_id); reusing one would make "
            "supersedes ambiguous."
        )


def _check_batch(doc: StateDocument, record: DecisionRecord) -> None:
    """``batch_id`` must name a declared batch — open OR closed.

    Deliberately NOT :func:`mureo.context.batch.ensure_joinable`. Refusing a
    closed batch is right for an ``action_log`` append, whose membership was
    already reported and must stay true; a decision joins nothing. Judging a
    bulk pass after it is finished is the normal case, and refusing it would
    push the operator's verdict back into chat.
    """
    if record.batch_id is None:
        return
    if find_batch(doc, record.batch_id) is None:
        raise BatchError(
            f"Unknown batch_id {record.batch_id!r}; a decision can only name a "
            "batch that was declared with mureo_batch_begin."
        )


__all__ = [
    "DECISION_METRIC_VALUE_MAX_CHARS",
    "DECISION_METRICS_MAX_KEYS",
    "DECISION_RATIONALE_MAX_CHARS",
    "DECISION_RELATED_ACTIONS_MAX",
    "DECISION_STATUSES",
    "DECISION_TITLE_MAX_CHARS",
    "DecisionRecord",
    "decision_by_id",
    "latest_decisions",
    "new_decision_id",
    "parsed_decisions",
]
