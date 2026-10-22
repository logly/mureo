"""``GET /api/reports/ops-history`` — the detail section's feed (#849).

Relays :func:`mureo.web.reports.build_ops_history` for one client and one
date window. Same rules as ``/api/reports/summary``: read-only, Host-gated
like every GET, ``client`` resolved through the one multi-account seam
(:func:`~mureo.web.report_clients.state_store_for_client`), and nothing
secret on the wire.

The window defaults to the last :data:`DEFAULT_WINDOW_DAYS` calendar days
ending today, both ends included, by the server's clock
(:func:`mureo.core.clock.server_now`) — the same window the client card's
counts cover. A date that is not exactly ``YYYY-MM-DD``, or an ``until``
before ``since``, is a 400 whose code names the parameter
(``since_invalid`` / ``until_invalid`` / ``until_before_since``) and does
not echo the value.

The response carries ``enabled`` whatever the setting: while ops history is
off the browser draws nothing.

Here rather than in ``handlers.py``, which is over the file-size budget.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Final

from mureo.context.ops_history_counts import OPS_HISTORY_WINDOW_DAYS, window_start
from mureo.core import clock
from mureo.web._helpers import flatten_query, send_error_json, send_json
from mureo.web.reports import build_ops_history

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

#: How many calendar days, today included, the feed covers by default.
DEFAULT_WINDOW_DAYS: Final = OPS_HISTORY_WINDOW_DAYS

#: The one date form accepted. Checked before ``date.fromisoformat``, which
#: from Python 3.11 also reads ``20261005`` and week dates.
_DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OpsHistoryQueryError(ValueError):
    """A ``since`` / ``until`` the feed cannot read. The message is its code."""


def _day(value: str | None, name: str, default: date) -> date:
    text = (value or "").strip()
    if not text:
        return default
    code = f"{name}_invalid"
    if not _DATE.match(text):
        raise OpsHistoryQueryError(code)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise OpsHistoryQueryError(code) from exc


def resolve_window(query: dict[str, str], today: date) -> tuple[date, date]:
    """The inclusive ``(since, until)`` a request asks for.

    Raises:
        OpsHistoryQueryError: a bound is not a date, or ``until`` is
            before ``since``.
    """
    since = _day(query.get("since"), "since", window_start(today, DEFAULT_WINDOW_DAYS))
    until = _day(query.get("until"), "until", today)
    if until < since:
        raise OpsHistoryQueryError("until_before_since")
    return since, until


def serve_ops_history(handler: BaseHTTPRequestHandler) -> None:
    """GET ``/api/reports/ops-history?client=&since=&until=``."""
    query = flatten_query(handler.path)
    client = query.get("client") or None
    try:
        since, until = resolve_window(query, clock.server_now().date())
    except OpsHistoryQueryError as exc:
        send_error_json(handler, 400, str(exc))
        return
    send_json(handler, build_ops_history(client, since, until))


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "OpsHistoryQueryError",
    "resolve_window",
    "serve_ops_history",
]
