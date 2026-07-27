"""The server clock mureo injects into its MCP responses (#460).

An agent has no trustworthy notion of "today". It reads STATE.json, sees
``reports.daily.period`` / ``last_synced_at`` / ``action_log`` timestamps
and mistakes that history for the current date — which is how
``/daily-check`` came to short-circuit with "today's data is already
fetched" against a days-old date. Shelling out to ``date`` is not an
option: the workflow skills must run in Bash-less headless hosts, so the
clock has to travel inside MCP responses.

This module is the single source of that clock:

- :func:`server_now` — the host's local wall clock, timezone-aware. Ad
  operations reason in local days (a JST operator's "yesterday" is not
  UTC's), so the local offset is deliberate; UTC-only would roll the day
  at the wrong moment.
- :func:`server_now_iso` — ISO 8601 **with an explicit UTC offset** and
  second precision (e.g. ``2026-07-28T10:12:33+09:00``).

Injection point: ``server_now`` is resolved through the module global at
call time, so freezing the clock in a test is a single
``monkeypatch.setattr(mureo.core.clock, "server_now", lambda: frozen)``.
For that to hold, call sites either import :func:`server_now_iso` by name
(it looks ``server_now`` up on each call) or reach the datetime through
the module — ``from mureo.core import clock`` / ``clock.server_now()`` —
when they need to do date arithmetic (e.g. an ``observation_due``
window). Never bind ``server_now`` itself into another module's
namespace: that copy would survive the patch.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["server_now", "server_now_iso"]


def server_now() -> datetime:
    """Current server time as a timezone-aware datetime in the host's zone."""
    return datetime.now().astimezone()


def server_now_iso() -> str:
    """:func:`server_now` as ISO 8601 with a UTC offset, second precision."""
    return server_now().isoformat(timespec="seconds")
