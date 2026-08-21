"""The metrics windows a mureo write may name (Issue #659).

mureo reports on exactly three windows. They are a **closed vocabulary**:
the reporting dashboard's period toggle, its per-window staleness thresholds
and every skill that persists a rollup are keyed to these tokens, so a
window outside the set is a bucket no default view reads.

Why this is a module of its own
-------------------------------
The rule has to be stated once and read from both ends. The **write** side
lives in :mod:`mureo.context.state` (and the MCP tool over it), the **read**
side in :mod:`mureo.web.reports`, and ``mureo.context`` cannot import
``mureo.web`` — the same layering that put
:data:`~mureo.core.platform_keys.BUILTIN_PLATFORM_DISPLAY_NAMES` here (#609).
Two copies of "which windows exist" would be free to drift, and the drift
would be invisible: the writer would accept a window the dashboard cannot
render, which is the failure #659 reports.

Strict on write, tolerant on read
---------------------------------
The asymmetry is deliberate, and it is not an inconsistency:

- **Write** — refuse. A write that lands where no default view looks is not
  a successful write; it is a silent one. Refusing puts the mismatch in
  front of the caller at the only moment it is still cheap to fix (the
  figures are in hand and can be re-filed under a real window). Reported in
  #659: a daily check wrote ``SINCE_LAUNCH_17D``, truthfully reported
  success, and the card stayed stale for three days with nothing anywhere
  naming the contradiction.
- **Read** — tolerate. Labels already on disk are real figures, correctly
  collected, filed under a name no view expects. Refusing to read them would
  delete data mureo did collect in order to tidy a vocabulary. So
  :func:`~mureo.web.report_document._available_periods` still surfaces them, and the
  report summary NAMES them (``non_canonical_periods``) so an operator can
  see what accumulated and decide.

And never normalise
-------------------
There is no "closest window" mapping here on purpose. Filing a
``LAST_8_DAYS`` figure under ``LAST_7_DAYS`` would present eight days of
spend as a seven-day answer — precisely the mislabelling #638's staleness
rule exists to prevent. Refusing is honest; guessing is not.
"""

from __future__ import annotations

__all__ = [
    "CANONICAL_METRICS_WINDOWS",
    "METRICS_WINDOW_RULE",
    "is_canonical_metrics_window",
    "reject_non_canonical_metrics_window",
]


CANONICAL_METRICS_WINDOWS: dict[str, int] = {
    "YESTERDAY": 1,
    "LAST_7_DAYS": 7,
    "LAST_30_DAYS": 30,
}
"""Window token → the length of that window in days, in toggle order.

The length is part of the definition, not decoration: the read side derives
each window's staleness threshold from it (a figure older than the window it
summarises no longer overlaps that window at all). A fourth window is
therefore a deliberate decision with a defined length — never something a
caller can bring into existence by naming it.
"""


METRICS_WINDOW_RULE = (
    "A window outside this list is refused, never rounded onto a neighbour "
    "(eight days of figures are not a seven-day answer). If your analysis "
    "covers another span, report it in your reply instead of inventing a "
    "window token: no view reads one, so the write would report success "
    "while the dashboard truthfully keeps showing the last real figures as "
    "stale."
)
"""The rule a caller needs, stated ONCE and shown on every path (#659).

There are two ways a caller learns the vocabulary is closed, and they must
not be two different explanations:

- **Before the call** — the MCP tool schema pastes this into the
  ``metrics_period`` / ``periods`` descriptions, next to the ``enum``. That
  is the surface that actually matters: the ``enum`` makes the JSON-Schema
  layer reject a bad window before any handler runs, so the agent's error
  reads ``'SINCE_LAUNCH_17D' is not one of [...]`` and NOTHING mureo writes
  reaches it. The allowed values survive that; the reason does not, unless
  it was already in the schema the model read.
- **On refusal** — :func:`reject_non_canonical_metrics_window` appends it to
  the ``ValueError`` raised for callers that do not go through the schema
  (an out-of-tree writer calling ``set_platform_metrics`` directly, or a
  host that does not validate).

Kept short on purpose: a tool description is loaded on every session, not
only when something goes wrong.
"""


def is_canonical_metrics_window(window: object) -> bool:
    """Is ``window`` one of mureo's windows?

    Takes ``object`` rather than ``str`` because the callers sit at a
    boundary (MCP arguments, an out-of-tree writer's dict keys) where the
    value's type is not guaranteed. Anything that is not a canonical token —
    including ``None`` and a non-string — is simply not one.
    """
    return isinstance(window, str) and window in CANONICAL_METRICS_WINDOWS


def reject_non_canonical_metrics_window(window: object, *, field: str) -> None:
    """Raise :class:`ValueError` unless ``window`` is a canonical window.

    ``field`` names where the value came from (``"metrics_period"`` or
    ``"periods"``) so the caller is told which argument to fix.

    The message states the whole allow-list rather than only rejecting: an
    agent that reached for "since launch" needs to know what the alternatives
    ARE. The reason comes from :data:`METRICS_WINDOW_RULE` rather than being
    written out again here — the same sentences the tool schema shows, so a
    caller cannot be told two different things depending on which path
    refused it.

    Note where this message does and does not surface: through the MCP
    server the schema ``enum`` rejects a bad window first, so a normal tool
    call never reaches this text. It is the message for the callers that
    bypass the schema — a bridge or out-of-tree writer calling
    :func:`~mureo.context.state.set_platform_metrics` directly, or a host
    that does not validate — which is exactly why the rule itself has to
    live in the schema too.
    """
    if is_canonical_metrics_window(window):
        return
    allowed = ", ".join(CANONICAL_METRICS_WINDOWS)
    raise ValueError(
        f"{field} {window!r} is not a mureo metrics window. "
        f"Allowed windows: {allowed}. {METRICS_WINDOW_RULE}"
    )
