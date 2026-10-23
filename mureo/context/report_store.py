"""Write STATE.json's ``reports`` summaries and the ``display`` contract.

Split out of :mod:`mureo.context.state` in #917, verbatim apart from the long
functions being broken into named steps and the longest rationale moving from
their docstrings into the sections below; :mod:`mureo.context.state`
re-exports both public writers, so existing imports keep working.

The display contract is replaced whole (#706)
---------------------------------------------

**The whole section is replaced by exactly what :func:`set_display` states.**
An omitted section is written as absent, not inherited.

That is the same granularity :func:`set_report` keeps, read one level up.
``set_report``'s unit is a report KIND — what one skill writes in one pass
— and it preserves the other kinds because they are other reports, written
by other passes, about other questions. The display contract's unit is the
whole contract, because that is what one pass produces: the nav line, the
highlights, the proposals, the tables and the chips all describe ONE
client at ONE moment, off one set of figures. Merging them per section
would put last week's highlights beside today's nav line with nothing on
screen able to say they came from different runs — and a screen that
silently mixes two moments is worse than one that shows a section fewer.

So a call that states nothing CLEARS the contract, and the document loses
the key entirely rather than keeping an empty one a reader could render.

**One writer per run, and it owns the whole screen.** The contract is
written by exactly ONE skill per run — the one producing that run's
report — and that skill states every section it wants shown. Two skills
writing different sections in the same run is outside the design: the
second call does not merge into the first, it replaces it, so what
survives is whatever ran last. There is deliberately no partial-update
entry point and no per-section lock beyond the document lock every
mutator here shares; concurrent partial writers would need a merge policy,
and any merge policy re-creates the mixed-moment screen this whole-section
replacement exists to prevent. If a future run needs two writers, they
compose their sections BEFORE calling, not by calling twice.

**The second writer's rule lives in
:data:`~mureo.core.display_contract.DISPLAY_OVERWRITE_RULE`** and is not
enforced here, because it cannot be: whether another skill's proposal is
still live is a judgement about today's findings, which only the caller
holds. mureo states the rule where the caller reads it — the tool
description and every skill that writes a contract — and this module
guarantees only the part a machine can: the write is whole, and it is
attributed (see :func:`_stated_display_sections`).

Everything else in the document — platforms, campaigns, ``action_log``,
``reports``, ``batches`` — is untouched by construction (``replace``).
``last_synced_at`` IS re-stamped, as :func:`set_report` re-stamps it: this
write happens in the same pass as the report it summarises, so treating
the two differently would make the card's age depend on which of them ran
last.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.context.models import DisplayContract, StateDocument

from mureo.context.display_codec import parse_display_contract
from mureo.context.history import append_report_history, validate_report_kind_path
from mureo.context.state_io import _locked_state_mutation, _now_iso
from mureo.core.display_contract import validate_display_contract
from mureo.core.report_summary import validate_report_summary


def _with_report(
    doc: StateDocument, path: Path, report: str, summary: dict[str, Any]
) -> StateDocument:
    """``doc`` with ``reports[report] = summary`` — :func:`set_report`'s locked step.

    The version written is appended to ``history/reports/<kind>.jsonl``
    first, on this lock (#758 phase 4a).
    """
    # Start from a shallow copy of the existing reports (or {} when the
    # document predates the reports section) so sibling report kinds are
    # preserved rather than wiped.
    reports = dict(doc.reports) if doc.reports else {}
    reports[report] = summary
    append_report_history(path, report, summary)
    return replace(doc, last_synced_at=_now_iso(), reports=reports)


def set_report(path: Path, report: str, summary: dict[str, Any]) -> StateDocument:
    """Persist a structured analysis ``summary`` into STATE.json ``reports``.

    Merges ``reports[report] = summary`` into the document's ``reports``
    section (a ``{<kind>: <summary>}`` map the read-only dashboard renders),
    re-stamps ``last_synced_at``, and writes back atomically. Other report
    keys and the rest of the document (campaigns, platforms, action_log) are
    preserved. When ``reports`` is ``None`` (old STATE.json), it starts from
    ``{}`` — so the call is backward compatible.

    Every version written is also appended to
    ``history/reports/<kind>.jsonl`` first, so the one it replaces survives
    it (#758 phase 4a); a failed append fails the write.

    The kind is checked here only as a safe file name (it names the archive);
    its vocabulary (:data:`~mureo.core.report_kinds.REPORT_KINDS`) is enforced
    on the MCP tool over this function, as an ``enum`` the schema layer
    applies before any handler runs — the same place the caller reads what
    the kinds ARE. A document that arrived from elsewhere carrying some other
    key keeps it: strict on write, tolerant on read (#671).

    The summary must state its structure (#662): the narrative is bounded and
    a headline figure is a number — see
    :func:`~mureo.core.report_summary.validate_report_summary` for the rule
    and for what is deliberately left free. Validation happens BEFORE the
    lock is taken, so a refused write leaves the document byte-for-byte
    untouched, and it is a WRITE rule only: a paragraph already on disk still
    reads back verbatim and survives a write of a sibling report kind.

    Args:
        path: STATE.json location.
        report: Report kind key — see
            :data:`~mureo.core.report_kinds.REPORT_KINDS`.
        summary: The free-form summary object to store under that key.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: if ``summary`` states a narrative over the bound, or a
            headline figure that is not a number, or ``report`` cannot name a
            file (:func:`~mureo.context.history.validate_report_kind_path`).
    """
    validate_report_summary(summary)
    validate_report_kind_path(report)

    def _build(doc: StateDocument) -> StateDocument:
        return _with_report(doc, path, report, summary)

    return _locked_state_mutation(path, _build)


def _stated_display_sections(
    written_at: str,
    source: str | None,
    nav_message: str | None,
    highlights: list[dict[str, Any]] | None,
    proposals: list[dict[str, Any]] | None,
    breakdown: dict[str, Any] | None,
    stated_values: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """The sections the call states, attributed — ``source`` and ``generated_at``.

    **The screen says who drew it.** ``source`` is REQUIRED alongside any
    section that renders — the skill's own name — and ``generated_at`` is
    stamped here from the server's clock. Last-writer-wins is the design,
    but it costs a reader the ability to tell whose answer survived, and
    these two fields are that cost paid off: a card whose weekly proposals
    were replaced by the evening's daily-check still says who last spoke and
    when. A call that states no section needs neither: the clear takes the
    screen down, and there is no document left to attribute.

    ``generated_at`` is deliberately NOT accepted from the caller. It is the
    #460 rule every other timestamp in this document follows
    (``action_log.timestamp``, ``not_collected.attempted_at``,
    ``AdState.as_of``): a model-supplied "now" is how a drifted clock gets
    persisted and read back later as fact, and the age of a screen is exactly
    the thing a reader has to be able to trust. It is stamped from the SAME
    clock read as ``last_synced_at``, so the two cannot disagree by a hair
    and read as two events.
    """
    return {
        key: value
        for key, value in (
            ("source", source),
            # ``generated_at`` is stamped here, not accepted (the #460 rule —
            # see the docstring). Placed in the same dict so the validator and
            # the codec see one shape, and so a clear (no section supplied)
            # drops it with everything else.
            ("generated_at", written_at if source is not None else None),
            ("nav_message", nav_message),
            ("highlights", highlights),
            ("proposals", proposals),
            ("breakdown", breakdown),
            ("stated_values", stated_values),
        )
        if value is not None
    }


def _validated_display_contract(supplied: dict[str, Any]) -> DisplayContract | None:
    """Validate the stated sections and parse them into the contract.

    Every value is bounded and every vocabulary closed, and an over-long or
    off-vocabulary write is **refused, never truncated** — see
    :func:`~mureo.core.display_contract.validate_display_contract` for the
    rule and for what is deliberately not checked.

    Validation happens BEFORE the lock is taken, so a refused write leaves
    STATE.json byte-for-byte untouched, and it is a WRITE rule only: a
    contract already on disk is read back exactly as it is (see
    :func:`mureo.context.display_codec.parse_display_contract`).
    """
    # Outside the lock and before the file is opened: a rejected write must
    # leave the document exactly as it was, including its ``last_synced_at``.
    validate_display_contract(supplied)
    return parse_display_contract(supplied)


def _with_display(
    doc: StateDocument, written_at: str, contract: DisplayContract | None
) -> StateDocument:
    """``doc`` with ``display`` replaced by ``contract`` — the locked step."""
    # One field, by ``replace``: every other section is carried over. One
    # clock read for the whole write, so the screen's age and the
    # document's cannot disagree by a hair and read as two events.
    return replace(doc, last_synced_at=written_at, display=contract)


def set_display(
    path: Path,
    *,
    source: str | None = None,
    nav_message: str | None = None,
    highlights: list[dict[str, Any]] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    breakdown: dict[str, Any] | None = None,
    stated_values: list[dict[str, Any]] | None = None,
) -> StateDocument:
    """Write the client's ``display`` contract — what the DASHBOARD reads (#706).

    STATE.json is the agent's working memory and is prose-heavy by design.
    This section is the other audience: the operator's screen. The whole
    section is replaced by exactly what this call states; an omitted section
    is written as absent, not inherited. A call that states nothing clears
    the contract (the key is removed). Validation:
    :func:`_validated_display_contract`; attribution: :func:`_stated_display_sections`;
    why the whole section, by one writer per run: the module docstring.

    Args:
        path: STATE.json location.
        source: The skill writing this screen (``"daily-check"``). Required
            whenever any section is stated; omitted only for the clear.
        nav_message: The one operator-facing (navigation) line. Operators and
            the mockup call it by a Japanese name, which the MCP tool
            description keeps so the agent can match an operator's wording.
        highlights: Up to three ``{tone, text}`` chips.
        proposals: ``{title, body, status, date}`` rows.
        breakdown: ``{campaigns: [...], adgroups: [...]}`` — rows of
            ``{name, spend, mcpa, target_cpa, state, note}``.
        stated_values: ``{label, value}`` chips, a raw number or short string.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: a value is over its bound or outside a closed vocabulary,
            prose stands where a figure belongs, or a section has no ``source``.
    """
    written_at = _now_iso()
    supplied = _stated_display_sections(
        written_at, source, nav_message, highlights, proposals, breakdown, stated_values
    )
    contract = _validated_display_contract(supplied)

    def _build(doc: StateDocument) -> StateDocument:
        return _with_display(doc, written_at, contract)

    return _locked_state_mutation(path, _build)


__all__ = ["set_display", "set_report"]
