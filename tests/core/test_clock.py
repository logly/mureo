"""The server clock mureo injects into its MCP responses (#460).

An agent has no reliable notion of "today": it reads STATE.json, sees
``reports.daily.period`` / ``last_synced_at`` / ``action_log`` timestamps
and mistakes that history for the current date. The fix is a single
server-side clock whose value travels in MCP responses, so a Bash-less
headless host never has to shell out to ``date``.

Contract pinned here:
  - the clock is timezone-aware and uses the HOST's local offset (ad ops
    reasoning is local-day based, so a UTC-only stamp would roll the day
    at the wrong moment for JST/PST operators),
  - the ISO rendering carries that explicit UTC offset,
  - ``server_now_iso`` derives from ``server_now``, so a test can freeze
    the clock by patching one function.

Marks: unit — pure calculation, no I/O.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit

_OFFSET_SUFFIX = re.compile(r"[+-]\d{2}:\d{2}$")


def test_server_now_is_timezone_aware() -> None:
    from mureo.core.clock import server_now

    now = server_now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_server_now_tracks_the_real_clock() -> None:
    from mureo.core.clock import server_now

    delta = abs(server_now() - datetime.now(timezone.utc))
    assert delta < timedelta(minutes=5)


def test_server_now_iso_carries_an_explicit_utc_offset() -> None:
    from mureo.core.clock import server_now_iso

    text = server_now_iso()
    assert _OFFSET_SUFFIX.search(text), f"no UTC offset in {text!r}"
    parsed = datetime.fromisoformat(text)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None


def test_server_now_iso_is_second_precision() -> None:
    """Seconds, not microseconds — the value is read by humans and models."""
    from mureo.core.clock import server_now_iso

    assert datetime.fromisoformat(server_now_iso()).microsecond == 0


def test_server_now_iso_derives_from_server_now(monkeypatch) -> None:
    """Patching ``server_now`` alone must move the ISO rendering too — that
    is the injection point every clock test in this repo relies on."""
    import mureo.core.clock as clock

    frozen = datetime(2026, 7, 28, 10, 12, 33, tzinfo=timezone(timedelta(hours=9)))
    monkeypatch.setattr(clock, "server_now", lambda: frozen)
    assert clock.server_now_iso() == "2026-07-28T10:12:33+09:00"
