"""The report kinds a mureo write may name (Issue #671).

STATE.json's ``reports`` section is keyed by report kind, and the kind is
written by exactly one thing: a skill's report step, calling
``mureo_state_report_set``. So the vocabulary is not an abstract allow-list —
it is the set of reports mureo actually produces, and each entry here names
the skill that produces it.

Why this is a module of its own
-------------------------------
The same reason :mod:`mureo.core.metrics_windows` is one (#659): the rule has
to be stated once and read from both ends. The **write** side is the MCP
tool's ``report`` ``enum``; the **read** side is the browser's "latest
report" pick (``REPORT_KINDS`` in ``reports_format.js``, pinned to this list
by ``tests/test_report_kind_vocabulary.py``). Two copies of "which kinds
exist" would be free to drift, and #671 is what that drift looks like: the
enum said three, nine skills instructed nine, and because the dispatcher
runs JSON-Schema before the handler (#277), six shipped skills told an agent
to do something the tool refused — with a generic jsonschema message that
named neither the skill nor the vocabulary.

Strict on write, tolerant on read
---------------------------------
The same asymmetry the window vocabulary draws:

- **Write** — the ``enum`` refuses a kind nothing produces, at the schema
  layer, before any handler runs. A kind mureo has no skill for is a bucket
  no view has a reason to look in.
- **Read** — a document is read as it is found. :func:`set_report` merges
  into whatever ``reports`` already holds and every reader relays the
  section verbatim, so a kind that arrived from elsewhere (a hand-written
  STATE.json, an import, an older mureo) is preserved and still readable.
  It simply does not compete for the "latest report" block, which ranks only
  kinds mureo knows.

Adding a kind
-------------
A new entry is a new skill, not a new string: add the kind here with the
skill that writes it, and the enum, the tool description and the browser's
order follow. ``tests/test_report_kind_vocabulary.py`` extracts the kinds
the shipped SKILL.md files instruct and checks them against the schema an
agent is actually validated by — so a kind added on one side only fails
there rather than in a customer's run.
"""

from __future__ import annotations

__all__ = [
    "REPORT_KINDS",
    "REPORT_KIND_DESCRIPTION",
]


REPORT_KINDS: dict[str, str] = {
    "daily": "daily-check",
    "weekly": "weekly-report",
    "monthly": "monthly-report",
    "goal": "goal-review",
    "audience": "audience-review",
    "experiment": "experiment",
    "fatigue": "ad-fatigue-check",
    "pacing": "budget-pacing",
    "tracking": "tracking-health",
}
"""Report kind → the skill whose report step writes it.

The skill is part of the definition, not decoration: a kind nothing writes
is a view waiting for a report that never comes, and the pin checks both
directions.

**The order is the read side's tie-break, and only that.** "Latest report"
means the newest ``generated_at`` — a fixed preference would hide every
other kind behind ``daily``, which is written every day. This order decides
between reports that carry no usable timestamp: the recurring cadence
(daily → weekly → monthly), then the goal review, then the focused checks
alphabetically, because nothing distinguishes those five.
"""


REPORT_KIND_DESCRIPTION: str = (
    "Report kind: "
    + ", ".join(f"``{kind}`` ({skill})" for kind, skill in REPORT_KINDS.items())
    + "."
)
"""The ``report`` parameter's description, generated from the vocabulary.

Written out once so the schema an agent reads cannot list a different set of
kinds from the ``enum`` that validates it — the pair is what #671 was about.
Each kind is named with its skill, because that is the question an agent
actually has: which of these am I writing?
"""
