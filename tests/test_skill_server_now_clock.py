"""The date-sensitive skills must establish "today" from ``server_now`` (#460).

``/daily-check`` (and ``sync-state`` / ``budget-pacing``) used to run with a
stale notion of today: the agent read STATE.json, saw old dates
(``reports.daily.period``, ``last_synced_at``, ``action_log`` timestamps) and
concluded "today's data is already fetched — re-displaying", using a days-old
date. The MCP side now injects ``server_now`` into the read responses; these
skills must be told to treat that value as the ONLY source of the current
date. Shelling out to ``date`` is not an option — ``/daily-check`` must run in
Bash-less headless hosts.

Pinned here, in BOTH the packaged copy (``mureo/_data/skills``) and the
repo-root mirror (``skills/``), kept byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills"
_MIRROR = _ROOT / "skills"

_SKILLS = ("daily-check", "sync-state", "budget-pacing")


def _packaged(name: str) -> Path:
    return _PACKAGED / name / "SKILL.md"


def _mirror(name: str) -> Path:
    return _MIRROR / name / "SKILL.md"


def _body(name: str) -> str:
    return _packaged(name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", _SKILLS)
def test_copies_are_byte_identical(name: str) -> None:
    assert (
        _packaged(name).read_bytes() == _mirror(name).read_bytes()
    ), f"{name}: packaged and mirror copies differ"


@pytest.mark.parametrize("name", _SKILLS)
def test_server_now_is_the_clock_source(name: str) -> None:
    """The skill must name the tool that carries the clock AND the field."""
    body = _body(name)
    assert "mureo_state_get" in body, f"{name}: must name the tool carrying the clock"
    assert "server_now" in body
    assert (
        "only source of the current date" in body
    ), f"{name}: must declare server_now the ONLY source of today"


@pytest.mark.parametrize("name", _SKILLS)
def test_state_json_dates_are_history_not_today(name: str) -> None:
    """The three date fields the failure mode came from must be named as
    history so a future edit cannot quietly reintroduce "read the date from
    STATE.json"."""
    body = _body(name)
    assert "history" in body
    for field in ("last_synced_at", "action_log"):
        assert field in body, f"{name}: must name {field} as history, not today"


@pytest.mark.parametrize("name", _SKILLS)
def test_server_now_is_never_written_into_state(name: str) -> None:
    """``server_now`` is a response envelope field; persisting it recreates
    the stale-date bug for the next reader."""
    # Case-insensitive: the sentence opens the rule in some skills and
    # closes it in others — the prohibition is what matters, not the casing.
    assert "never write `server_now`" in _body(name).lower()


def test_shared_tool_selection_documents_the_clock() -> None:
    """``_mureo-shared`` owns the host-portability table every skill reads.
    Its "Read STATE.json -> `Read` tool" row is misleading for date-sensitive
    work, so the clock rule has to live next to it — otherwise a skill not
    edited for #460 keeps inferring today from the file it just read."""
    packaged = _PACKAGED / "_mureo-shared" / "SKILL.md"
    mirror = _MIRROR / "_mureo-shared" / "SKILL.md"
    assert packaged.read_bytes() == mirror.read_bytes()
    body = packaged.read_text(encoding="utf-8")
    assert "| Establish the current date |" in body
    assert "server_now" in body
    assert "only** source of today" in body
    assert "on EVERY host, including Code" in body
    assert "never write `server_now` back into STATE.json" in body


def test_daily_check_forbids_the_already_fetched_short_circuit() -> None:
    """The exact observed failure: "today's report is already fetched —
    re-displaying" against a days-old date."""
    body = _body("daily-check")
    assert "already fetched" in body
    assert "re-display" in body
    assert "reports.daily.period" in body or "reports.*.period" in body


def test_budget_pacing_derives_elapsed_days_from_server_now() -> None:
    """Pacing math is date arithmetic — the month, elapsed days and remaining
    days must all come off ``server_now``, not off STATE.json history."""
    body = _body("budget-pacing")
    elapsed_lines = [ln for ln in body.splitlines() if "Elapsed days" in ln]
    assert elapsed_lines, "budget-pacing must keep its elapsed-days step"
    assert any(
        "server_now" in ln for ln in elapsed_lines
    ), "elapsed-days math must derive from server_now"
    remaining_lines = [ln for ln in body.splitlines() if "days remaining" in ln]
    assert any(
        "server_now" in ln for ln in remaining_lines
    ), "remaining-days math must derive from server_now"
