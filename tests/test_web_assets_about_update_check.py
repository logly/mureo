"""Static-content guards for the About-tab update check.

Two operator-visible regressions are pinned here (no build step — the
assets are read straight from ``mureo/_data/web/`` at runtime):

* The "Update all" button (``data-about-update-button``) carries the
  ``hidden`` attribute and is revealed by JS only when an update exists.
  Because ``.btn { display: inline-flex }`` is an author rule it overrides
  the UA ``[hidden] { display: none }`` — so without a targeted
  ``.btn[hidden]`` rule the button shows even when everything is up to
  date.
* The passive dashboard load (``renderUpdates``) must POLL when the
  server answers ``status: "checking"`` (a cold/stale cache starts a pip
  check in the background). Without polling the summary is stuck on
  "Checking for updates…" forever, since only the manual button polled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# "Update all" only shows when an update exists (CSS lets `hidden` win)
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_btn_hidden_rule_present() -> None:
    """A targeted ``.btn[hidden]`` rule must hide the button — otherwise
    ``.btn``'s ``display: inline-flex`` overrides the UA ``[hidden]`` rule
    and "Update all" is visible with no updates."""
    css = _read("app.css")
    assert ".btn[hidden]" in css
    idx = css.index(".btn[hidden]")
    assert "display: none" in css[idx : idx + 80]


@pytest.mark.unit
def test_update_all_button_starts_hidden_in_markup() -> None:
    """The markup default must be ``hidden`` so the button is absent until
    JS reveals it on an available update."""
    html = _read("app.html")
    start = html.index("data-about-update-button")
    # The attribute list for this button must include ``hidden``.
    assert "hidden" in html[start : start + 60]


# ---------------------------------------------------------------------------
# Passive load polls when the server is still "checking"
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_shared_poll_helper_exists() -> None:
    js = _read("dashboard.js")
    assert "function pollUpdatesUntilSettled" in js


@pytest.mark.unit
def test_passive_render_polls_when_checking() -> None:
    """``renderUpdates`` (the on-load path) must hand off to the poll loop
    when the first ``/api/updates`` answer is ``checking`` — not just show
    the message and stop."""
    js = _read("dashboard.js")
    start = js.index("async function renderUpdates()")
    end = js.index("function renderAll", start)
    body = js[start:end]
    assert 'body.status === "checking"' in body
    assert "pollUpdatesUntilSettled()" in body


@pytest.mark.unit
def test_manual_check_refreshes_then_polls() -> None:
    """The manual "check now" button still forces a fresh check
    (``/api/updates/refresh``) and then polls until it settles."""
    js = _read("dashboard.js")
    start = js.index("async function runCheckNow()")
    end = js.index("async function renderUpdates()", start)
    body = js[start:end]
    assert "/api/updates/refresh" in body
    assert "pollUpdatesUntilSettled()" in body
