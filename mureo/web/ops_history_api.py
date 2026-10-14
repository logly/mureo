"""``GET /api/reports/ops-history`` — the detail section's feed (#849).

Relays :func:`mureo.web.reports.build_ops_history` for one client and one
date window. Same rules as ``/api/reports/summary``: read-only, Host-gated
like every GET, ``client`` resolved through the one multi-account seam
(:func:`~mureo.web.report_clients.state_store_for_client`), and nothing
secret on the wire.

The window defaults to the last :data:`DEFAULT_WINDOW_DAYS` days —
``since`` is today minus that many days and ``until`` is today, both
inclusive, by the server's clock (:func:`mureo.core.clock.server_now`), the
same window the client card's counts cover. A date that is not
``YYYY-MM-DD``, or an ``until`` before ``since``, is a 400 whose message
names the parameter and does not echo the value.

The response carries ``enabled`` whatever the setting: while ops history is
off the browser draws nothing.

Here rather than in ``handlers.py``, which is over the file-size budget.
"""

from __future__ import annotations

import urllib.parse
from datetime import date, timedelta
from typing import TYPE_CHECKING, Final

from mureo.context.ops_history_counts import OPS_HISTORY_WINDOW_DAYS
from mureo.core import clock
from mureo.web._helpers import send_error_json, send_json
from mureo.web.reports import build_ops_history

if TYPE_CHECKING:
    from http.server import BaseHTTPRequestHandler

#: How many days back the feed reaches when ``since`` is not given.
DEFAULT_WINDOW_DAYS: Final = OPS_HISTORY_WINDOW_DAYS


class OpsHistoryQueryError(ValueError):
    """A ``since`` / ``until`` the feed cannot read. The message is plain."""


def _query(request_path: str) -> dict[str, str]:
    if "?" not in request_path:
        return {}
    parsed = urllib.parse.parse_qs(request_path.split("?", 1)[1])
    return {key: values[0] for key, values in parsed.items() if values}


def _day(value: str | None, name: str, default: date) -> date:
    text = (value or "").strip()
    if not text:
        return default
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise OpsHistoryQueryError(f"{name} must be a YYYY-MM-DD date") from exc


def resolve_window(query: dict[str, str], today: date) -> tuple[date, date]:
    """The inclusive ``(since, until)`` a request asks for.

    Raises:
        OpsHistoryQueryError: a bound is not a date, or ``until`` is
            before ``since``.
    """
    since = _day(
        query.get("since"), "since", today - timedelta(days=DEFAULT_WINDOW_DAYS)
    )
    until = _day(query.get("until"), "until", today)
    if until < since:
        raise OpsHistoryQueryError("until is before since")
    return since, until


def serve_ops_history(handler: BaseHTTPRequestHandler) -> None:
    """GET ``/api/reports/ops-history?client=&since=&until=``."""
    query = _query(handler.path)
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
