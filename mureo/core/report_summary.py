"""What a stored report summary must state, and what it may not (Issue #662).

A report summary has always been ``{totals, flags, narrative}`` — headline
numbers, notable items, short text. Nothing checked any of it, and "short
text" is a word in a description, so what an operator got was ~700
characters in one paragraph: the period, the figures, the per-ad and
per-adspot findings, the verdict and the proposal all inside one string.
``totals`` and ``flags`` existed for most of it and went unused. The
information was not wrong; nobody read it.

This module is the write-side rule, in the shape #659 settled on for the
metrics windows: **say what is allowed, refuse what is not, never repair by
guesswork.**

Why a description is load-bearing here
--------------------------------------
#659 could close its vocabulary with a JSON-Schema ``enum``, so a bad window
never reached mureo's own message. A summary is a free-form object written
by an agent — there is no ``enum`` for prose, and no mechanical constraint
that can express "the figures go in the other field". So the rule
(:data:`REPORT_SUMMARY_RULE`) is written ONCE and shown on both paths: the
MCP tool pastes it into the ``summary`` description the model reads *before*
it calls, and :func:`validate_report_summary` appends it to every refusal.
The description is the half that prevents the wall; the refusal is what
makes the description true.

The three rules
---------------
- **The narrative is bounded.** :data:`NARRATIVE_MAX_CHARS` characters, and
  over it the write is REFUSED — never truncated. #662 says why in as many
  words: a sentence cut in half is worse than a long one. It reads like a
  bug in mureo, and the operator cannot tell what was removed.
- **A headline metric is a number.** ``"¥773,957"`` is the observed failure
  in miniature: written where the view reads figures, and the view can
  render nothing from it. Refusing it puts the mismatch in front of the
  caller while the figures are still in hand.
- **Everything else is stored as written.** A key outside
  :data:`REPORT_TOTALS_KEYS` is passed through untouched (see below).

Why non-canonical keys are NOT refused
--------------------------------------
The alternative was tempting — #659 refuses a window outside its list — but
the two cases are not the same. A metrics window is the whole meaning of the
write; a totals block also legitimately carries context that is not one of
mureo's six metrics: a CVR, a per-goal target and current value, a
per-platform split. Refusing those would send exactly that content back into
the paragraph this issue exists to empty. So they are stored, and the read
side already ignores them for the figure row (``reportSummaryTotals`` in
``reports_format.js``) rather than presenting a metric mureo has no label
for as a headline number.

For the same reason there is no "at least one figure" requirement: a goal
review's headline numbers are targets, not spend and CPA, and a report with
nothing to state numerically is a real report.

Nor is there a rule against numbers IN the narrative. "CPA is 68% below
target" is a judgement, and a mechanical no-digits rule would refuse it
while a wall of prose with the numbers spelled out would pass. The bound is
what makes the paragraph a paragraph.

One vocabulary, two languages
-----------------------------
:data:`REPORT_TOTALS_KEYS` is the list the browser renders as figures
(``REPORTS_SUMMARY_TOTAL_KEYS``). A drift between them would be invisible —
the write side accepting a figure the view never prints, or refusing one it
does — so ``tests/test_report_summary.py`` pins the two together.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "NARRATIVE_MAX_CHARS",
    "REPORT_SUMMARY_RULE",
    "REPORT_TOTALS_KEYS",
    "validate_report_summary",
]


REPORT_TOTALS_KEYS: tuple[str, ...] = (
    "spend",
    "conversions",
    "cpa",
    "ctr",
    "clicks",
    "impressions",
)
"""The metrics a report may state as headline figures, in render order.

The same vocabulary the platform cards use — a report is not a place to
invent a metric name, because a name no view knows is a figure no view
prints.
"""


NARRATIVE_MAX_CHARS: int = 400
"""How long the prose may be, in characters.

The number is chosen for what is LEFT once the structure is used. The
figures are in ``totals`` and every finding is its own ``flags`` entry, so
the narrative carries the judgement and the proposal — two to four
sentences. 400 characters is about seventy words of English, and Japanese
carries roughly twice the content per character, so it is a comfortable
bound in both rather than a tight one in either. It refuses the
~700-character report #662 was filed about by a clear margin rather than by
a hair, which matters: a bound that a normal report brushes against becomes
noise an agent works around, and the point is not brevity for its own sake
but that everything else has a field of its own.
"""


REPORT_SUMMARY_RULE = (
    "Write the structure, not one paragraph. Headline figures go in "
    "``totals`` (" + ", ".join(REPORT_TOTALS_KEYS) + ") as raw numbers — "
    '773957, not "¥773,957"; 0.0466, not "4.66%". Each finding goes in '
    "``flags`` as its own entry, with the detail in its ``params``. "
    "``narrative`` keeps only the judgement and the proposal, at most "
    f"{NARRATIVE_MAX_CHARS} characters: a longer one is refused, never "
    "truncated, because a sentence cut in half is worse than a long one."
)
"""The rule a writer needs, stated ONCE and shown on both paths (#662).

Kept to a few sentences on purpose: a tool description is loaded on every
session, not only when something goes wrong.
"""


def validate_report_summary(summary: dict[str, Any]) -> None:
    """Raise :class:`ValueError` unless ``summary`` is a report, not a wall.

    Checks the narrative bound and the headline figures (see the module
    docstring for what is deliberately NOT checked). Everything else in the
    object — ``generated_at``, ``period``, ``flags`` (validated separately by
    :mod:`mureo.analysis.report_flags`), and any field a skill adds — passes
    through untouched.

    Called at the write boundary, so a refusal leaves the document exactly as
    it was: this runs before ``reports[kind]`` is replaced, never after.
    """
    _reject_overlong_narrative(summary.get("narrative"))
    _reject_unrenderable_figures(summary)


def _reject_overlong_narrative(narrative: Any) -> None:
    """The bound itself. ``None`` / absent is not an error — a report may
    have no prose to add."""
    if narrative is None:
        return
    if not isinstance(narrative, str):
        raise ValueError(
            "narrative must be a string (prose). A list of findings belongs "
            f"in flags. {REPORT_SUMMARY_RULE}"
        )
    if len(narrative) > NARRATIVE_MAX_CHARS:
        raise ValueError(
            f"narrative is {len(narrative)} characters; the limit is "
            f"{NARRATIVE_MAX_CHARS}. Nothing has been written and nothing "
            f"was truncated. {REPORT_SUMMARY_RULE}"
        )


def _reject_unrenderable_figures(summary: dict[str, Any]) -> None:
    """Every canonical metric in the headline block must be a real number."""
    source = _headline_figures(summary)
    if source is None:
        return
    for key in REPORT_TOTALS_KEYS:
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"totals[{key!r}] is {value!r} — a headline figure must be a "
                f"raw number, and a string is rendered as nothing. "
                f"{REPORT_SUMMARY_RULE}"
            )
        if not math.isfinite(value):
            raise ValueError(
                f"totals[{key!r}] is {value!r} — a headline figure must be a "
                f"finite number. {REPORT_SUMMARY_RULE}"
            )


def _headline_figures(summary: dict[str, Any]) -> dict[str, Any] | None:
    """The block the VIEW reads as headline figures, or ``None``.

    Mirrors ``reportSummaryTotals`` (``reports_format.js``) deliberately:
    both field names are read because the product uses two for the same
    thing, ``totals`` wins where a report carries both, and one nested
    ``totals`` is unwrapped (a payload keyed by platform states its headline
    row there). Checking a field the view does not read would refuse a
    report that renders correctly — and miss one that does not.
    """
    source: dict[str, Any] | None = None
    for name in ("kpis", "totals"):
        candidate = summary.get(name)
        if candidate is None:
            continue
        if not isinstance(candidate, dict):
            raise ValueError(
                f"{name} must be an object keyed by metric name. "
                f"{REPORT_SUMMARY_RULE}"
            )
        source = candidate
    if source is None:
        return None
    nested = source.get("totals")
    if isinstance(nested, dict):
        return nested
    return source
