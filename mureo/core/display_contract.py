"""What the dashboard is allowed to read, and what it may not (Issue #706).

STATE.json is the agent's working memory. It is prose-heavy **by design**:
it is written for the next AI decision, and the reasoning that decision
needs is long. The dashboard had been rendering that memory directly, and
what an operator got (measured on two live clients, 2026-08-26) was walls
of jargon, thirty-row value dumps with whole sentences sitting in numeric
columns, and work-journal action logs showing raw ``**`` markdown on
screen.

So the two audiences are separated. The agent's prose keeps every home it
already has; the **dashboard reads only this contract** — a small, strictly
structured surface, written under the guards below. This module is the
write-side rule, in the shape #659 settled on for the metrics windows and
#662 for the report summary: **say what is allowed, refuse what is not,
never repair by guesswork.**

Refused, never truncated
------------------------
Every bound here refuses the write. #662 says why in as many words: a
sentence cut in half is worse than a long one — it reads like a bug in
mureo, and the operator cannot tell what was removed. The caller is holding
the content at the moment of refusal and can shorten it; nobody downstream
ever can.

Three kinds of refusal, one reason each
---------------------------------------
- **Over a bound.** A field on this surface has a place on screen, and that
  place has a size. Over the bound it is not "a longer line", it is the
  wall of prose the contract exists to remove.
- **Outside a vocabulary.** ``tone``, ``status`` and a breakdown row's
  ``state`` are closed sets, because each is rendered as a chip or a colour.
  A value no view knows is a value no view draws — the same silent-write
  failure #659 refuses a metrics window for.
- **Prose where a value belongs.** ``stated_values`` is a chip row: a label
  and a figure. A sentence there is exactly the reported defect ("sentences
  in numeric columns"), so a value is a real number or a short string, and
  nothing else.

What is NOT decided here
------------------------
Nothing in this module derives, computes or rewrites anything. The KPI
funnel and the daily chart are deliberately outside the contract — they are
computed from canonical totals and ``PlatformState.daily`` (#690), so no
agent writes them and no agent can get them wrong.

One rule, two paths
-------------------
:data:`DISPLAY_CONTRACT_RULE` and :data:`ACTION_LOG_DISPLAY_RULE` are each
written ONCE and shown on both paths: the MCP tool pastes them into the
descriptions a model reads *before* it calls, and the refusals below append
them. The description is the half that prevents the bad write; the refusal
is what makes the description true.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "ACTION_LOG_DISPLAY_RULE",
    "ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS",
    "ACTION_LOG_DISPLAY_TITLE_MAX_CHARS",
    "BREAKDOWN_NOTE_MAX_CHARS",
    "BREAKDOWN_STATES",
    "DISPLAY_CONTRACT_RULE",
    "DISPLAY_OVERWRITE_RULE",
    "DISPLAY_PROVENANCE_FIELDS",
    "DISPLAY_SECTIONS",
    "DISPLAY_SOURCE_MAX_CHARS",
    "HIGHLIGHTS_MAX_ITEMS",
    "HIGHLIGHT_TEXT_MAX_CHARS",
    "HIGHLIGHT_TONES",
    "HIGHLIGHT_TONE_BY_SEVERITY",
    "HIGHLIGHT_TONE_RULE",
    "NAV_MESSAGE_MAX_CHARS",
    "PROPOSAL_BODY_MAX_CHARS",
    "PROPOSAL_DATE_MAX_CHARS",
    "PROPOSAL_STATUSES",
    "PROPOSAL_TITLE_MAX_CHARS",
    "STATED_VALUE_LABEL_MAX_CHARS",
    "STATED_VALUE_MAX_CHARS",
    "validate_action_log_display",
    "validate_display_contract",
]


# ---------------------------------------------------------------------------
# The bounds. Defined here and ONLY here — the schema descriptions, the
# refusals and the skills all read them from this module, so a limit cannot
# be stated in one place and enforced at another.
# ---------------------------------------------------------------------------

NAV_MESSAGE_MAX_CHARS: int = 80
"""The operator-facing navigation line (運用ナビ), in characters.

One line at the top of a client's report saying what to do next. One line
is the whole point: it is read at a glance, above the numbers, and a
second sentence there is a paragraph by tomorrow.
"""

HIGHLIGHTS_MAX_ITEMS: int = 3
"""How many highlights a client may state.

Three is what a card can carry as chips without becoming a list. A fourth
highlight is not extra information on screen — it is the point at which
none of them is read.
"""

HIGHLIGHT_TEXT_MAX_CHARS: int = 60
"""A highlight's text, in characters — a chip, not a sentence."""

PROPOSAL_TITLE_MAX_CHARS: int = 30
"""A proposal's title, in characters. It is the row an operator scans."""

PROPOSAL_BODY_MAX_CHARS: int = 80
"""A proposal's body, in characters — the one line under the title.

The reasoning behind a proposal is long and belongs in the agent's own
prose, which keeps every home it already has. This is what fits beside the
title on the screen where the operator decides whether to open it.
"""

PROPOSAL_DATE_MAX_CHARS: int = 12
"""A proposal's date, in characters.

Long enough for ``2026-08-27`` and for a short label beside it, short
enough that a sentence cannot arrive here. **No format is imposed** — the
contract names none, and mureo does not invent one for a field it only
displays — but a date field is not a place for prose, and the bound is what
says so.
"""

BREAKDOWN_NOTE_MAX_CHARS: int = 40
"""A breakdown row's note, in characters — a table cell.

Deliberately the shortest bound here. It sits in a row beside four figures,
and text in a table steals the width the figures need.
"""

STATED_VALUE_LABEL_MAX_CHARS: int = 24
"""A stated value's label, in characters — a chip's caption."""

STATED_VALUE_MAX_CHARS: int = 12
"""A stated value's value, when it is a string, in characters.

A value is normally a NUMBER. A string is allowed because a report
legitimately states things a number cannot carry (``"3 of 7"``,
``"¥12,400"``, ``"未設定"``), and refusing those would push exactly that
content back into the prose this contract exists to empty. Twelve
characters is what a chip holds; past it, it is a sentence.
"""

DISPLAY_SOURCE_MAX_CHARS: int = 24
"""How long a contract's ``source`` may be, in characters.

It holds a skill name (``daily-check``, ``tracking-health``), which is what
makes the screen attributable: the contract is replaced wholesale by
whoever writes it last, so "who put this here, and when" is the one
question a reader cannot answer from the content. Long enough for every
skill mureo ships and a plugin's own, short enough that it cannot become a
second ``nav_message``.
"""


ACTION_LOG_DISPLAY_TITLE_MAX_CHARS: int = 40
"""An action-log entry's display title, in characters."""

ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS: int = 120
"""An action-log entry's display summary, in characters.

The stored ``summary`` runs to several hundred characters and is written
for the next agent — it stays exactly as it is, and stays readable in the
drill-down. This is the one line the dashboard shows instead.
"""


# ---------------------------------------------------------------------------
# The vocabularies. Closed, because each value is rendered as a chip or a
# colour and a value no view knows is a value no view draws.
# ---------------------------------------------------------------------------

HIGHLIGHT_TONES: tuple[str, ...] = ("good", "watch", "bad")
"""How a highlight is coloured. Three tones, in severity order."""

PROPOSAL_STATUSES: tuple[str, ...] = ("proposed", "done")
"""Where a proposal stands: still awaiting a decision, or carried out."""

BREAKDOWN_STATES: tuple[str, ...] = (
    "target_met",
    "improving",
    "watch",
    "worsening",
    "no_data",
)
"""How a breakdown row is doing, as a closed set.

Two verdicts that need no action (the target is being met; it is moving the
right way), two that do (keep an eye on it; it is moving the wrong way), and
the honest fifth: not enough delivery to judge. ``no_data`` is a state
rather than an omission for the reason ``not_collected`` exists one level up
(#638) — "nothing to judge from" and "nobody looked" must not render as the
same blank cell.
"""

HIGHLIGHT_TONE_BY_SEVERITY: dict[str, str] = {
    "action": "bad",
    "watch": "watch",
    "positive": "good",
}
"""Report-flag severity → the highlight tone that says the same thing.

A skill has already graded its findings on the report's severity axis
(``mureo.analysis.report_flags.SEVERITIES``), and a chip is the same
judgement in fewer characters. Without one table the two vocabularies get
mapped by feel, and the same finding ends up amber on one client's card and
red on another's.

``info`` is deliberately ABSENT, and that is the load-bearing half: a
neutral note is not a highlight. There are at most
:data:`HIGHLIGHTS_MAX_ITEMS` chips on a card, so an informational flag
taking one of them costs a slot that an action or a win needed, and the
information is not lost — it stays in the report, where a reader who wants
it will look. ``tests/test_display_contract.py`` pins this map against the
severity axis, so a fifth severity cannot appear without a decision being
made here about whether it is a chip at all.
"""


HIGHLIGHT_TONE_RULE = (
    "Map a finding's severity to a chip tone: "
    + " / ".join(
        f"{severity} → {tone}" for severity, tone in HIGHLIGHT_TONE_BY_SEVERITY.items()
    )
    + ". info does NOT become a highlight — a neutral note would spend one of "
    f"the {HIGHLIGHTS_MAX_ITEMS} chips an action or a win needed, and it is "
    "still in the report for whoever wants it."
)
"""The severity → tone mapping as one sentence, stated ONCE (#706).

Shown to the writer wherever it composes chips — the skills — rather than
only to the reader.
"""


#: The sections a display contract is made of, in the order the report is
#: read down the page. Named once so the write API, the codec and the tool
#: schema cannot disagree about what the contract contains.
DISPLAY_SECTIONS: tuple[str, ...] = (
    "nav_message",
    "highlights",
    "proposals",
    "breakdown",
    "stated_values",
)

#: Who wrote this screen, and when. Not sections — nothing is rendered FROM
#: them — but part of the contract, and required alongside any section that
#: is (see :func:`validate_display_contract`).
#:
#: The contract is replaced wholesale by whoever writes it last, which is the
#: design: a screen is one moment, and merging two runs produces a moment
#: that never happened. The cost is that a reader cannot tell whose answer
#: survived. These two fields are that cost paid off — the screen names its
#: author and its age, so a card that lost a section to a later run still
#: says who last spoke.
DISPLAY_PROVENANCE_FIELDS: tuple[str, ...] = ("source", "generated_at")


DISPLAY_OVERWRITE_RULE = (
    "``display`` is REPLACED WHOLE and the last writer wins — there is no "
    "merge. Before you write it, read the current one (``mureo_state_get``). "
    "Of what another skill wrote TODAY, carry exactly one thing into your "
    "own write: its ``proposals`` that are still live — not yet done, and "
    "not contradicted by what you just found. Everything else you write from "
    "your own run alone, because a screen assembled from two runs shows a "
    "moment that never happened. And carry over NOTHING ELSE: never copy "
    "another skill's ``nav_message``, ``highlights``, ``breakdown`` or "
    "``stated_values``, which would put its judgement under your name when "
    "you cannot vouch for it. Name yourself in ``source`` so the screen says "
    "whose answer it is."
)
"""The rule a second writer needs, stated ONCE and shown on every path (#706).

The whole-section replacement is deliberate — see
:func:`mureo.context.state.set_display` — but "deliberate" is not the same
as "harmless": a weekly review's proposals disappearing when the evening's
daily-check writes its own screen is a real loss, and the daily-check has no
way to know it happened unless it looks first.

So the fix is a READ before the write, and one narrow carry-over.
``proposals`` is the only section that carries, because it is the only one
that is a standing commitment rather than a reading of this moment: a
recommendation stays true until it is done or withdrawn, while a
``nav_message`` or a ``breakdown`` row is a statement about the figures in
front of the skill that wrote it. Copying one of those forward would put a
judgement on screen under an author who never made it — the same reason
#545 refuses to let mureo plan a rollback for a change it only observed.
"""


DISPLAY_CONTRACT_RULE = (
    "The dashboard reads THIS section and nothing else — keep your reasoning "
    "where it already goes. Every bound below refuses the write rather than "
    "truncating it, because a sentence cut in half is worse than a long one. "
    f"nav_message: one line, at most {NAV_MESSAGE_MAX_CHARS} characters. "
    f"highlights: at most {HIGHLIGHTS_MAX_ITEMS} items of {{tone, text}}, "
    f"tone one of {'/'.join(HIGHLIGHT_TONES)}, text at most "
    f"{HIGHLIGHT_TEXT_MAX_CHARS} characters. proposals: {{title, body, "
    f"status, date}}, title at most {PROPOSAL_TITLE_MAX_CHARS} and body at "
    f"most {PROPOSAL_BODY_MAX_CHARS} characters, status one of "
    f"{'/'.join(PROPOSAL_STATUSES)}. breakdown.campaigns / "
    "breakdown.adgroups: rows of {name, spend, mcpa, target_cpa, state, "
    "note} — the three figures are raw numbers, state is one of "
    f"{'/'.join(BREAKDOWN_STATES)}, note at most {BREAKDOWN_NOTE_MAX_CHARS} "
    f"characters. stated_values: {{label, value}}, label at most "
    f"{STATED_VALUE_LABEL_MAX_CHARS} characters and value a raw number or a "
    f"string of at most {STATED_VALUE_MAX_CHARS} characters — a sentence "
    "there is refused, because it lands in a numeric column. Do NOT write "
    "the KPI funnel or the daily chart: mureo computes both from the stored "
    "totals."
)
"""The rule a writer needs, stated ONCE and shown on both paths (#706).

Kept to a few sentences on purpose: a tool description is loaded on every
session, not only when something goes wrong.
"""


ACTION_LOG_DISPLAY_RULE = (
    "``display_title`` and ``display_summary`` are the ONE LINE the dashboard "
    f"shows for this entry: title at most {ACTION_LOG_DISPLAY_TITLE_MAX_CHARS} "
    f"characters, summary at most {ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS}. "
    "Over either bound the append is refused, never truncated. They do not "
    "replace ``summary`` — write that as fully as the next agent needs; these "
    "two are what an operator reads at a glance."
)
"""The action-log display line's rule, stated ONCE (#706)."""


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


def validate_display_contract(display: dict[str, Any]) -> None:
    """Raise :class:`ValueError` unless ``display`` is a contract, not prose.

    Called at the write boundary and BEFORE the state lock is taken, so a
    refusal leaves STATE.json byte-for-byte as it was.

    Refuses in the order a reader meets the sections, so the first thing a
    caller is told about is the first thing it wrote.
    """
    if not isinstance(display, dict):
        raise ValueError(f"display must be an object. {DISPLAY_CONTRACT_RULE}")
    _require_source(display)
    unknown = sorted(
        set(display) - set(DISPLAY_SECTIONS) - set(DISPLAY_PROVENANCE_FIELDS)
    )
    if unknown:
        # Unlike a report summary's ``totals`` — where a key mureo has no
        # label for is still the report's own content and is stored (#662) —
        # this surface is read by ONE view with a fixed layout. A section it
        # does not draw is a write that reports success and shows nothing.
        raise ValueError(
            f"display has section(s) {unknown} that the dashboard does not "
            f"read. Allowed sections: {', '.join(DISPLAY_SECTIONS)}. "
            f"{DISPLAY_CONTRACT_RULE}"
        )
    _validate_nav_message(display.get("nav_message"))
    _validate_highlights(display.get("highlights"))
    _validate_proposals(display.get("proposals"))
    _validate_breakdown(display.get("breakdown"))
    _validate_stated_values(display.get("stated_values"))


def validate_action_log_display(
    *, display_title: Any = None, display_summary: Any = None
) -> None:
    """Raise :class:`ValueError` unless the log's display line fits on screen.

    Both fields are optional — an entry without them is every entry written
    before they existed, and the dashboard falls back to what it always
    read.
    """
    _reject_overlong(
        display_title,
        field="display_title",
        limit=ACTION_LOG_DISPLAY_TITLE_MAX_CHARS,
        rule=ACTION_LOG_DISPLAY_RULE,
    )
    _reject_overlong(
        display_summary,
        field="display_summary",
        limit=ACTION_LOG_DISPLAY_SUMMARY_MAX_CHARS,
        rule=ACTION_LOG_DISPLAY_RULE,
    )


def _require_source(display: dict[str, Any]) -> None:
    """A contract that shows anything must say who wrote it.

    Required only alongside CONTENT. A call that states no section is the
    clear — it takes the screen down, leaves no document to attribute, and
    is the one write for which "who" has nowhere to be stored.

    ``generated_at`` is deliberately NOT required of the caller: the server
    stamps it (:func:`mureo.context.state.set_display`), the #460 rule every
    other timestamp in this document follows. A model-supplied "now" is how
    a drifted clock gets persisted and read back later as fact, and the age
    of the screen is precisely the thing a reader must be able to trust.
    """
    if not any(section in display for section in DISPLAY_SECTIONS):
        return
    source = display.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(
            "source is required: name the skill writing this screen (e.g. "
            "'daily-check'). The contract is replaced wholesale by whoever "
            "writes it last, so an unattributed screen cannot say whose "
            f"answer survived. {DISPLAY_OVERWRITE_RULE}"
        )
    _reject_overlong(
        source,
        field="source",
        limit=DISPLAY_SOURCE_MAX_CHARS,
        rule=DISPLAY_CONTRACT_RULE,
    )


def _reject_overlong(value: Any, *, field: str, limit: int, rule: str) -> None:
    """The bound itself. ``None`` / absent is never an error."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string. {rule}")
    if len(value) > limit:
        raise ValueError(
            f"{field} is {len(value)} characters; the limit is {limit}. "
            f"Nothing has been written and nothing was truncated. {rule}"
        )


def _reject_off_vocabulary(value: Any, *, field: str, allowed: tuple[str, ...]) -> None:
    """``field`` must name one of ``allowed`` — absent is fine, invented is not."""
    if value is None:
        return
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            f"{field} is {value!r}, which is not one of: {', '.join(allowed)}. "
            f"{DISPLAY_CONTRACT_RULE}"
        )


def _reject_non_number(value: Any, *, field: str) -> None:
    """A figure on this surface is a raw number — absent is fine.

    The same refusal :func:`~mureo.core.report_summary.validate_report_summary`
    makes, for the same reason: ``"¥773,957"`` sits where the view reads a
    figure and renders as nothing.
    """
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field} is {value!r} — a figure must be a raw number "
            f"(773957, not '¥773,957'). {DISPLAY_CONTRACT_RULE}"
        )
    if not math.isfinite(value):
        raise ValueError(
            f"{field} is {value!r} — a figure must be a finite number. "
            f"{DISPLAY_CONTRACT_RULE}"
        )


def _require_text(value: Any, *, field: str) -> None:
    """``field`` is required and must be a non-blank string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field} is required and must be a non-empty string. "
            f"{DISPLAY_CONTRACT_RULE}"
        )


def _require_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array. {DISPLAY_CONTRACT_RULE}")
    return value


def _require_object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object. {DISPLAY_CONTRACT_RULE}")
    return value


def _validate_nav_message(nav_message: Any) -> None:
    if nav_message is None:
        return
    _require_text(nav_message, field="nav_message")
    _reject_overlong(
        nav_message,
        field="nav_message",
        limit=NAV_MESSAGE_MAX_CHARS,
        rule=DISPLAY_CONTRACT_RULE,
    )


def _validate_highlights(highlights: Any) -> None:
    if highlights is None:
        return
    items = _require_list(highlights, field="highlights")
    if len(items) > HIGHLIGHTS_MAX_ITEMS:
        raise ValueError(
            f"highlights has {len(items)} items; the limit is "
            f"{HIGHLIGHTS_MAX_ITEMS}. Nothing has been written and nothing "
            f"was dropped — choose which {HIGHLIGHTS_MAX_ITEMS} matter. "
            f"{DISPLAY_CONTRACT_RULE}"
        )
    for index, item in enumerate(items):
        where = f"highlights[{index}]"
        _require_object(item, field=where)
        _require_text(item.get("tone"), field=f"{where}.tone")
        _reject_off_vocabulary(
            item.get("tone"), field=f"{where}.tone", allowed=HIGHLIGHT_TONES
        )
        _require_text(item.get("text"), field=f"{where}.text")
        _reject_overlong(
            item.get("text"),
            field=f"{where}.text",
            limit=HIGHLIGHT_TEXT_MAX_CHARS,
            rule=DISPLAY_CONTRACT_RULE,
        )


def _validate_proposals(proposals: Any) -> None:
    if proposals is None:
        return
    items = _require_list(proposals, field="proposals")
    for index, item in enumerate(items):
        where = f"proposals[{index}]"
        _require_object(item, field=where)
        _require_text(item.get("title"), field=f"{where}.title")
        _reject_overlong(
            item.get("title"),
            field=f"{where}.title",
            limit=PROPOSAL_TITLE_MAX_CHARS,
            rule=DISPLAY_CONTRACT_RULE,
        )
        _reject_overlong(
            item.get("body"),
            field=f"{where}.body",
            limit=PROPOSAL_BODY_MAX_CHARS,
            rule=DISPLAY_CONTRACT_RULE,
        )
        _reject_off_vocabulary(
            item.get("status"), field=f"{where}.status", allowed=PROPOSAL_STATUSES
        )
        _reject_overlong(
            item.get("date"),
            field=f"{where}.date",
            limit=PROPOSAL_DATE_MAX_CHARS,
            rule=DISPLAY_CONTRACT_RULE,
        )


def _validate_breakdown(breakdown: Any) -> None:
    if breakdown is None:
        return
    sections = _require_object(breakdown, field="breakdown")
    unknown = sorted(set(sections) - {"campaigns", "adgroups"})
    if unknown:
        raise ValueError(
            f"breakdown has key(s) {unknown}; it holds exactly two tables, "
            f"``campaigns`` and ``adgroups``. {DISPLAY_CONTRACT_RULE}"
        )
    for level in ("campaigns", "adgroups"):
        rows = sections.get(level)
        if rows is None:
            continue
        for index, row in enumerate(_require_list(rows, field=f"breakdown.{level}")):
            _validate_breakdown_row(row, where=f"breakdown.{level}[{index}]")


def _validate_breakdown_row(row: Any, *, where: str) -> None:
    _require_object(row, field=where)
    _require_text(row.get("name"), field=f"{where}.name")
    for figure in ("spend", "mcpa", "target_cpa"):
        _reject_non_number(row.get(figure), field=f"{where}.{figure}")
    _reject_off_vocabulary(
        row.get("state"), field=f"{where}.state", allowed=BREAKDOWN_STATES
    )
    _reject_overlong(
        row.get("note"),
        field=f"{where}.note",
        limit=BREAKDOWN_NOTE_MAX_CHARS,
        rule=DISPLAY_CONTRACT_RULE,
    )


def _validate_stated_values(stated_values: Any) -> None:
    if stated_values is None:
        return
    for index, item in enumerate(_require_list(stated_values, field="stated_values")):
        where = f"stated_values[{index}]"
        _require_object(item, field=where)
        _require_text(item.get("label"), field=f"{where}.label")
        _reject_overlong(
            item.get("label"),
            field=f"{where}.label",
            limit=STATED_VALUE_LABEL_MAX_CHARS,
            rule=DISPLAY_CONTRACT_RULE,
        )
        _reject_prose_value(item.get("value"), field=f"{where}.value")


def _reject_prose_value(value: Any, *, field: str) -> None:
    """A stated value is a number or a short string. A sentence is refused.

    This is the guard the whole section exists for. ``stated_values`` is a
    chip row — a caption and a figure — and the reported defect was whole
    sentences arriving in it. A number is always fine; a string is fine while
    it is short enough to still be a value. Anything else (an object, a list,
    a boolean, nothing at all) has no chip to be drawn as.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(
            f"{field} is {value!r} — a stated value is a raw number or a "
            f"string of at most {STATED_VALUE_MAX_CHARS} characters. "
            f"{DISPLAY_CONTRACT_RULE}"
        )
    if isinstance(value, (int, float)):
        _reject_non_number(value, field=field)
        return
    if not isinstance(value, str):
        raise ValueError(
            f"{field} is {value!r} — a stated value is a raw number or a "
            f"string of at most {STATED_VALUE_MAX_CHARS} characters, never a "
            f"structure. {DISPLAY_CONTRACT_RULE}"
        )
    if not value.strip():
        raise ValueError(
            f"{field} is blank — a stated value states something. "
            f"{DISPLAY_CONTRACT_RULE}"
        )
    if len(value) > STATED_VALUE_MAX_CHARS:
        raise ValueError(
            f"{field} is {len(value)} characters; a stated value is a raw "
            f"number or a string of at most {STATED_VALUE_MAX_CHARS} "
            "characters. That is prose, and it lands in a numeric column. "
            f"Nothing has been written and nothing was truncated. "
            f"{DISPLAY_CONTRACT_RULE}"
        )
