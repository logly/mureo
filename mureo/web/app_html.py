"""The one edit ``app.html`` takes on its way out of the server (#790).

``mureo configure`` is a static document plus a handful of JSON endpoints:
the server hands ``app.html`` over byte for byte and every "does this
install have X" question is answered in the browser, by hiding a node.
This module is the single exception, and it is one because of what the
node in question does.

The **Guardrails card** writes the ``currency`` bullet of the ACTIVE
workspace's STRATEGY.md. On a backend that keeps a client roster that
workspace is not any client's file — it is the operator's own ambient one
— so the card is not "a control showing one client's value", it is a
control writing the wrong document. Currency belongs beside the other
per-client settings, on the client's own edit form, which is the
multi-client layer's surface.

**Why the omission is server-side.** Hiding it in the browser would mean
the markup, and a Save button wired to a real endpoint, reach the page
anyway: one `<script>` that fails to load, one exception earlier in the
render, and the card is on screen and live. Cutting the card out of the
document is the only spelling where a script that never runs cannot show
it. The cost is this module — two marker comments and a slice — and it is
paid only on the request for ``/``.

The roster question itself is NOT answered here. It goes through
:func:`~mureo.web.report_clients.agency_client_seam_present`, the same
predicate the Reports triage layer uses for "is this a multi-client
backend", so there is exactly one answer to that question in the web
layer and it costs a ``getattr`` — no registry read, no second endpoint.
"""

from __future__ import annotations

import logging

from mureo.web.report_clients import agency_client_seam_present

logger = logging.getLogger(__name__)

__all__ = [
    "GUARDRAILS_CARD_END",
    "GUARDRAILS_CARD_START",
    "AppHtmlError",
    "render_app_html",
    "strip_guardrails_card",
]

#: The comments in ``app.html`` that fence the Guardrails card. They are
#: markup with a job: a card delimited by nothing could only be found by
#: matching `<div>` nesting in a regular expression, which is the kind of
#: cut that silently eats a neighbour the day someone wraps the section.
GUARDRAILS_CARD_START = "<!-- guardrails-card:start -->"
GUARDRAILS_CARD_END = "<!-- guardrails-card:end -->"


class AppHtmlError(Exception):
    """The served document could not be rendered for this backend.

    Carries a short, secret-free ``code`` the handler maps to an error
    envelope, exactly like
    :class:`~mureo.web.strategy_currency.StrategyCurrencyError`.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def strip_guardrails_card(html: str) -> str:
    """``html`` without the Guardrails card.

    Raises :class:`AppHtmlError` unless the markers delimit exactly one
    span. That is deliberately loud: the alternative to a cut that cannot
    unambiguously find its card is a page that still HAS the card — or
    half of one — served to the one backend the omission exists to
    protect. A packaging defect is a 500; a live control writing the
    wrong STRATEGY.md is not.
    """
    start, end = _card_span(html)
    return html[: _line_start(html, start)] + html[_after_line(html, end) :]


def _card_span(html: str) -> tuple[int, int]:
    """Where the card starts and ends, or raise.

    Two failures, two codes, because they are fixed differently:
    ``guardrails_card_markers_missing`` means a marker has to be put back,
    ``guardrails_card_markers_ambiguous`` means the markers are there but
    do not fence one region — duplicated, or in the wrong order.

    Counting is the point. ``find`` alone answers "where is the first
    one", which happily cuts from the first start to the first end: a
    duplicated start would swallow a neighbouring card as if it were this
    one's content, and a duplicated end would leave a stray marker comment
    in the served document. Neither is a cut anybody asked for.
    """
    starts = html.count(GUARDRAILS_CARD_START)
    ends = html.count(GUARDRAILS_CARD_END)
    start = html.find(GUARDRAILS_CARD_START)
    end = html.find(GUARDRAILS_CARD_END)
    if starts == 0 or ends == 0:
        code = "guardrails_card_markers_missing"
    elif starts > 1 or ends > 1 or end < start:
        code = "guardrails_card_markers_ambiguous"
    else:
        return start, end
    logger.error(
        "app.html does not fence the Guardrails card with exactly one "
        "%r ... %r pair (%d / %d found, %s); the card cannot be omitted "
        "for a multi-client backend",
        GUARDRAILS_CARD_START,
        GUARDRAILS_CARD_END,
        starts,
        ends,
        code,
    )
    raise AppHtmlError(code)


def _line_start(html: str, index: int) -> int:
    """``index``, backed up over the indentation on its own line.

    Only over blanks: anything else on that line is content that stays.
    """
    line = html.rfind("\n", 0, index) + 1
    return line if html[line:index].strip() == "" else index


def _after_line(html: str, index: int) -> int:
    """Just past the end marker, and past the newline that follows it."""
    cut = index + len(GUARDRAILS_CARD_END)
    return cut + 1 if html[cut : cut + 1] == "\n" else cut


def render_app_html(body: bytes) -> bytes:
    """``app.html`` as this backend should serve it.

    A single-workspace install (the OSS default) gets the file unchanged,
    bytes in, bytes out — the decode below never runs for it.
    """
    if not agency_client_seam_present():
        return body
    return strip_guardrails_card(body.decode("utf-8")).encode("utf-8")
