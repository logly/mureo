"""The ``display`` section's half of the STATE.json codec (#706).

Both directions of the display contract — :func:`parse_display_contract` and
:func:`display_contract_to_dict` are inverses — kept beside each other for
the reason :mod:`mureo.context.state_codec` states about the document as a
whole: every field appears exactly twice, once in each, and the optionality
rules that keep a round-trip byte-stable can only be checked with both
halves in front of you. It lives in its own module only because that file
is already at the repo's size limit; ``_CODEC_COVERAGE`` there still names
these models, so a field added to one of them without visiting this file
fails at import.

Strict on write, tolerant on read
--------------------------------
This module is the TOLERANT half, and it deliberately checks **shape and
nothing else**. Every bound and every vocabulary in
:mod:`mureo.core.display_contract` is a WRITE rule: the writer is refused
while it still holds the content and can shorten it. By the time a value is
on disk, refusing it would only delete something an operator has — the
asymmetry #659 settled for the metrics windows, and #662 for a report's
prose.

So a row is dropped only when there is no row: not an object, or missing
the one field that identifies it (a highlight with no text, a breakdown row
with no name, a stated value with no label). A ``tone`` outside the
vocabulary, a note longer than the bound, a value that is not a number —
all of those are kept exactly as written and handed to the view, which
decides how to draw something it was not expecting.

It also cannot import :mod:`mureo.core.display_contract` even if it wanted
to: ``mureo.core.__init__`` → ``runtime_context`` → ``state_store`` →
``mureo.context.state`` → this module is a real import chain, and reaching
back into ``mureo.core`` from inside it would close the cycle. The
dependency-free rule that keeps ``state_codec`` importable is the same rule
here.
"""

from __future__ import annotations

from typing import Any

from mureo.context.models import (
    DisplayBreakdown,
    DisplayBreakdownRow,
    DisplayContract,
    DisplayHighlight,
    DisplayProposal,
    DisplayStatedValue,
)

__all__ = [
    "display_contract_to_dict",
    "parse_display_contract",
]

#: A breakdown row's three figures, in render order. One tuple, read by both
#: halves, so a figure cannot be parsed and then not emitted.
_BREAKDOWN_FIGURES: tuple[str, ...] = ("spend", "mcpa", "target_cpa")


def _text(value: Any) -> str | None:
    """``value`` when it is a non-blank string, else ``None``.

    Kept verbatim rather than stripped: the display surface prints what the
    report wrote, and a codec that quietly edits a value is a codec that
    makes the stored document and the rendered one two different things.
    """
    return value if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> float | int | None:
    """``value`` when it is a real number, else ``None``.

    ``bool`` is excluded even though it is an ``int`` subclass: ``True`` in a
    spend column is not a figure, and rendering it as ``1`` would invent one.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Annotated local: the parameter is ``Any`` (this sits at a boundary, so
    # the value's type is not guaranteed), and ``isinstance`` does not narrow
    # ``Any`` for mypy's return check.
    number: float | int = value
    return number


def _parse_highlights(raw: Any) -> tuple[DisplayHighlight, ...]:
    """Parse the highlight chips; an entry with no tone or no text is not one."""
    if not isinstance(raw, list):
        return ()
    parsed: list[DisplayHighlight] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tone = _text(item.get("tone"))
        text = _text(item.get("text"))
        if tone is None or text is None:
            continue
        parsed.append(DisplayHighlight(tone=tone, text=text))
    return tuple(parsed)


def _parse_proposals(raw: Any) -> tuple[DisplayProposal, ...]:
    """Parse the proposal rows; only ``title`` identifies one."""
    if not isinstance(raw, list):
        return ()
    parsed: list[DisplayProposal] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        if title is None:
            continue
        parsed.append(
            DisplayProposal(
                title=title,
                body=_text(item.get("body")),
                status=_text(item.get("status")),
                date=_text(item.get("date")),
            )
        )
    return tuple(parsed)


def _parse_breakdown_rows(raw: Any) -> tuple[DisplayBreakdownRow, ...]:
    """Parse one breakdown table; a row with no ``name`` names nothing."""
    if not isinstance(raw, list):
        return ()
    parsed: list[DisplayBreakdownRow] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if name is None:
            continue
        figures = {key: _number(item.get(key)) for key in _BREAKDOWN_FIGURES}
        parsed.append(
            DisplayBreakdownRow(
                name=name,
                state=_text(item.get("state")),
                note=_text(item.get("note")),
                **figures,
            )
        )
    return tuple(parsed)


def _parse_breakdown(raw: Any) -> DisplayBreakdown:
    """Parse both breakdown tables. An absent section is an empty pair."""
    if not isinstance(raw, dict):
        return DisplayBreakdown()
    return DisplayBreakdown(
        campaigns=_parse_breakdown_rows(raw.get("campaigns")),
        adgroups=_parse_breakdown_rows(raw.get("adgroups")),
    )


def _parse_stated_values(raw: Any) -> tuple[DisplayStatedValue, ...]:
    """Parse the chip row; a chip needs a label AND something to state."""
    if not isinstance(raw, list):
        return ()
    parsed: list[DisplayStatedValue] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"))
        if label is None:
            continue
        raw_value = item.get("value")
        number = _number(raw_value)
        value: float | int | str | None = (
            number if number is not None else _text(raw_value)
        )
        if value is None:
            continue
        parsed.append(DisplayStatedValue(label=label, value=value))
    return tuple(parsed)


def parse_display_contract(raw: Any) -> DisplayContract | None:
    """Build a :class:`DisplayContract` from the stored ``display`` object.

    Returns ``None`` when there is nothing to display — the key is absent,
    is not an object, or holds only entries with no shape. ``None`` and an
    empty contract are the same fact here (there is no screen to draw), and
    collapsing them is what keeps a document that has never had a contract
    byte-stable through a round trip.
    """
    if not isinstance(raw, dict):
        return None
    contract = DisplayContract(
        nav_message=_text(raw.get("nav_message")),
        highlights=_parse_highlights(raw.get("highlights")),
        proposals=_parse_proposals(raw.get("proposals")),
        breakdown=_parse_breakdown(raw.get("breakdown")),
        stated_values=_parse_stated_values(raw.get("stated_values")),
    )
    return contract or None


def _highlight_to_dict(highlight: DisplayHighlight) -> dict[str, Any]:
    return {"tone": highlight.tone, "text": highlight.text}


def _proposal_to_dict(proposal: DisplayProposal) -> dict[str, Any]:
    """Emit a proposal, omitting the three optional fields it does not state.

    An absent ``status`` must stay absent rather than becoming a null a
    reader could draw as a chip with no word in it.
    """
    result: dict[str, Any] = {"title": proposal.title}
    for key, value in (
        ("body", proposal.body),
        ("status", proposal.status),
        ("date", proposal.date),
    ):
        if value is not None:
            result[key] = value
    return result


def _breakdown_row_to_dict(row: DisplayBreakdownRow) -> dict[str, Any]:
    """Emit one table row, omitting every figure it has no value for.

    A row for an entity with no conversions has no ``mcpa``, and writing 0
    would state a perfect cost per acquisition rather than the absence of
    one.
    """
    result: dict[str, Any] = {"name": row.name}
    for key in _BREAKDOWN_FIGURES:
        value = getattr(row, key)
        if value is not None:
            result[key] = value
    for key, value in (("state", row.state), ("note", row.note)):
        if value is not None:
            result[key] = value
    return result


def _breakdown_to_dict(breakdown: DisplayBreakdown) -> dict[str, Any]:
    """Emit the breakdown pair, each table only when it has a row."""
    result: dict[str, Any] = {}
    if breakdown.campaigns:
        result["campaigns"] = [_breakdown_row_to_dict(r) for r in breakdown.campaigns]
    if breakdown.adgroups:
        result["adgroups"] = [_breakdown_row_to_dict(r) for r in breakdown.adgroups]
    return result


def _stated_value_to_dict(stated: DisplayStatedValue) -> dict[str, Any]:
    return {"label": stated.label, "value": stated.value}


def display_contract_to_dict(contract: DisplayContract) -> dict[str, Any]:
    """Convert a :class:`DisplayContract` to its JSON object.

    Every section is emitted only when it states something, so a contract
    that carries a nav line and nothing else round-trips as exactly that one
    key — and a section a later run empties leaves nothing behind to be read
    as a live one.
    """
    result: dict[str, Any] = {}
    if contract.nav_message is not None:
        result["nav_message"] = contract.nav_message
    if contract.highlights:
        result["highlights"] = [_highlight_to_dict(h) for h in contract.highlights]
    if contract.proposals:
        result["proposals"] = [_proposal_to_dict(p) for p in contract.proposals]
    breakdown = _breakdown_to_dict(contract.breakdown)
    if breakdown:
        result["breakdown"] = breakdown
    if contract.stated_values:
        result["stated_values"] = [
            _stated_value_to_dict(s) for s in contract.stated_values
        ]
    return result
