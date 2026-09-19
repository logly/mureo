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

The pure half lives here with the model and the queries; the writer needs
STATE.json's file lock and reaches into :mod:`mureo.context.state` for it
lazily, for the import-cycle reason :mod:`mureo.context.batch` documents.
"""

from __future__ import annotations

import math
import re
import secrets
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from mureo.context.batch import ID_ENTROPY_BYTES, BatchError, find_batch

if TYPE_CHECKING:
    from pathlib import Path

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
        :func:`append_decision`, exactly as on an ``action_log`` entry, so
        the two trails join on the same id.

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

    def __post_init__(self) -> None:
        """Validate every bound and take a defensive copy of ``metrics``."""
        self._validate_required_text()
        self._validate_optional_text()
        self._validate_metrics()
        self._validate_related_actions()

    def _validate_required_text(self) -> None:
        """The four fields a record cannot be honest without."""
        for name in ("decision_id", "recorded_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        if self.status not in DECISION_STATUSES:
            raise ValueError(
                f"status must be one of {list(DECISION_STATUSES)}; "
                f"got {self.status!r}"
            )
        _bounded(self, "title", DECISION_TITLE_MAX_CHARS)
        _bounded(self, "rationale", DECISION_RATIONALE_MAX_CHARS)

    def _validate_optional_text(self) -> None:
        """Blank is refused, not read as absent — see ``ActionLogEntry``."""
        for name in ("platform", "campaign_id", "supersedes", "batch_id"):
            _optional_label(self, name)
        for name in ("session_id", "client"):
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

    The import is deliberately lazy: ``mureo.core.__init__`` ->
    ``runtime_context`` -> ``state_store`` -> ``mureo.context.state`` ->
    ``state_codec`` -> ``_decision_codec`` -> this module is a real import
    chain, so reaching ``mureo.core`` at module load would close the cycle
    — the same reason :func:`mureo.context.batch.batch_open_hours` imports
    the clock inside itself.
    """
    from mureo.core.scrub import scrub_text

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


def decision_by_id(doc: StateDocument, decision_id: str) -> DecisionRecord | None:
    """Return the record ``decision_id`` names, or ``None``."""
    wanted = decision_id.strip() if isinstance(decision_id, str) else ""
    if not wanted:
        return None
    for record in doc.decisions:
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
    re-read the file.
    """
    if limit <= 0:
        return ()
    return tuple(reversed(doc.decisions[-limit:]))


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
    """
    if decision_by_id(doc, record.decision_id) is not None:
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


def append_decision(path: Path, record: DecisionRecord) -> tuple[StateDocument, int]:
    """Append ``record`` to STATE.json's ``decisions``.

    Every cross-reference is validated INSIDE the lock, against the document
    as it is about to be written: an index, a ``supersedes`` or a
    ``batch_id`` checked outside it could be made stale by a concurrent
    append between the check and the write.

    ``session_id`` and ``client`` are stamped here when unset, from
    :mod:`mureo.core.actor` — the same choke-point rule
    :func:`mureo.context.state.append_action_log` follows, so a decision and
    the actions it produced carry the same session id. An explicit value is
    kept: a replayed or imported record names the session that made the
    decision, not the one writing it down.

    Returns:
        The written document and the record's index in ``decisions``.

    Raises:
        ValueError: ``decision_id`` is already on record, a
            ``related_actions`` index is out of range, or ``supersedes``
            names no recorded decision.
        BatchError: ``batch_id`` names no declared batch.
    """
    # Lazy, for the cycle ``mureo.core.__init__`` -> ``runtime_context`` ->
    # ``state_store`` -> ``mureo.context.state`` closes at module level.
    from mureo.context.state import _locked_state_mutation
    from mureo.core.actor import client_info, session_id

    position = -1

    def _build(doc: StateDocument) -> StateDocument:
        nonlocal position
        _check_unique_id(doc, record)
        _check_related_actions(doc, record)
        _check_supersedes(doc, record)
        _check_batch(doc, record)
        stamped = replace(
            record,
            session_id=(
                record.session_id if record.session_id is not None else session_id()
            ),
            client=record.client if record.client is not None else client_info(),
        )
        position = len(doc.decisions)
        # ``replace`` carries every other section across by construction —
        # the reason ``append_action_log`` stopped enumerating them.
        return replace(doc, decisions=(*doc.decisions, stamped))

    return _locked_state_mutation(path, _build), position


__all__ = [
    "DECISION_METRIC_VALUE_MAX_CHARS",
    "DECISION_METRICS_MAX_KEYS",
    "DECISION_RATIONALE_MAX_CHARS",
    "DECISION_RELATED_ACTIONS_MAX",
    "DECISION_STATUSES",
    "DECISION_TITLE_MAX_CHARS",
    "DecisionRecord",
    "append_decision",
    "decision_by_id",
    "latest_decisions",
    "new_decision_id",
]
