"""``mureo_history_query`` — one bounded read over every trail (#758, 4b).

Four records answer "what happened before today", and until now each had
its own door: ``action_log`` and the `daily` window only through the whole
``mureo_state_get``, the journal only through the ``mureo journal`` CLI,
and the phase-4a archives through no tool at all. An agent on a host with
no shell could not ask "what did we change on this campaign in July" at
all, and an agent that could had to pull a whole document to find out.

What these tests pin:

- **read-only, and classified as such.** The name ends in no mutating
  suffix, so no strategy reminder fires and the dispatcher injects no
  call-level ``reason`` into its schema. A query that asked WHY it was
  being made would be nonsense;
- **bounded on every source.** ``limit`` applies per source, the journal
  scan is capped at a fixed number of tail lines (nothing rotates
  ``JOURNAL.jsonl`` yet — #758 phase 6) and a dateless ``daily`` query
  falls back to a lookback window instead of opening every archived
  month. Where more matched than was returned, the section says
  ``truncated``, and the ``daily`` section reports the window it
  answered from;
- **the newest wins.** Every source returns the LAST ``limit`` matches,
  and ``action_log`` keeps each entry's index in the full log — that
  index is what phase 3's ``related_actions`` and ``evaluation_of``
  refer to;
- **a missing file is an answer, not an exception.** No STATE.json, no
  journal and no archive each come back empty and say so;
- **the semantic refusals happen before any read**: ``until`` before
  ``since``, half an entity pair, ``reports`` without a ``kind``,
  ``daily`` without a ``platform``.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import history
from mureo.context.models import ActionLogEntry, PlatformState, StateDocument
from mureo.context.state import write_state_file
from mureo.core import clock
from mureo.mcp import journal
from mureo.mcp._handlers_history import (
    HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS,
    HISTORY_QUERY_DEFAULT_LIMIT,
    HISTORY_QUERY_JOURNAL_SCAN_LINES,
    HISTORY_QUERY_MAX_LIMIT,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_TOOL = "mureo_history_query"
_PLATFORM = "google_ads"
_PLUGIN = "plugin:mureo-lineyahoo-bridge:yahoo_ads"

#: What the ``workspace`` fixture freezes the server clock to.
_TODAY = date(2026, 9, 19)


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """cwd = tmp_path, the journal inside it, no journal writes, clock frozen.

    The tool is dispatched through ``handle_call_tool``, which journals
    every call — including these. Writing into the same file the test just
    laid out would make the assertions depend on how many calls the test
    made before them, so the opt-out is set and the file stays exactly as
    the test wrote it.

    The clock is frozen because the `daily` source falls back to a
    lookback window measured from TODAY when no ``since`` is given. Left
    on the real clock, every dated fixture in this module would keep
    passing until the day it silently slid out of that window.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(journal, "journal_path", lambda: tmp_path / "JOURNAL.jsonl")
    monkeypatch.setenv(journal.OPT_OUT_ENV_VAR, "1")
    monkeypatch.setattr(
        clock, "server_now", lambda: datetime.combine(_TODAY, time(12, 0)).astimezone()
    )
    return tmp_path


async def _call(arguments: dict[str, Any]) -> dict[str, Any]:
    from mureo.mcp.server import handle_call_tool

    result = await handle_call_tool(_TOOL, arguments)
    return json.loads(result[0].text)


async def _refusal(arguments: dict[str, Any]) -> str:
    """The message of the ``ValueError`` the dispatcher answers with.

    Both halves of the refusal surface land here: a schema violation, which
    ``_validate_tool_input`` raises before the handler runs, and a semantic
    one (an entity pair, a ``kind`` without its source), which the handler
    raises itself. The dispatcher classifies both as ``invalid_args``.
    """
    from mureo.mcp.server import handle_call_tool

    with pytest.raises(ValueError) as caught:
        await handle_call_tool(_TOOL, arguments)
    return str(caught.value)


# ---------------------------------------------------------------------------
# Fixtures for the four sources
# ---------------------------------------------------------------------------


def _entry(day: str, **overrides: Any) -> ActionLogEntry:
    fields: dict[str, Any] = {
        "timestamp": f"{day}T10:00:00+00:00",
        "action": "campaign_paused",
        "platform": _PLATFORM,
    }
    fields.update(overrides)
    return ActionLogEntry(**fields)


def _state(
    path: Path,
    *entries: ActionLogEntry,
    daily: dict[str, dict[str, Any]] | None = None,
) -> Path:
    platforms = (
        None
        if daily is None
        else {_PLATFORM: PlatformState(account_id="123-456-7890", daily=daily)}
    )
    write_state_file(
        path,
        StateDocument(version="2", action_log=tuple(entries), platforms=platforms),
    )
    return path


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "v": 1,
        "ts": "2026-07-15T10:00:00+00:00",
        "session": "s" * 32,
        "tool": "google_ads_campaigns_list",
        "family": _PLATFORM,
        "mutating": False,
        "args": {"customer_id": "123"},
        "outcome": "ok",
        "duration_ms": 12,
        "batch_id": None,
    }
    record.update(overrides)
    return record


def _journal(path: Path, *records: dict[str, Any] | str) -> Path:
    log = path / "JOURNAL.jsonl"
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log


def _bucket(spend: float) -> dict[str, Any]:
    return {"spend": spend, "clicks": 3}


def _months_ending_today(count: int) -> list[str]:
    """``YYYY-MM`` labels for the ``count`` months ending in the frozen one."""
    last = _TODAY.year * 12 + _TODAY.month - 1
    return [
        f"{(last - back) // 12:04d}-{(last - back) % 12 + 1:02d}"
        for back in reversed(range(count))
    ]


def _archive_one_day_per_month(state: Path, months: list[str]) -> None:
    for month in months:
        history.archive_platform_daily(
            state, _PLATFORM, "123-456-7890", {f"{month}-01": _bucket(1.0)}
        )


def _spy_on_archive(monkeypatch) -> list[tuple[Any, Any]]:
    """Record the window every ``read_daily_archive`` call is handed.

    The bound has to be pinned where it is APPLIED, not only on what came
    back: a handler that read every month file and then filtered would
    return the same days at many times the cost.
    """
    from mureo.mcp import _handlers_history

    asked: list[tuple[Any, Any]] = []
    real = _handlers_history.read_daily_archive

    def spy(path, platform, since=None, until=None):
        asked.append((since, until))
        return real(path, platform, since, until)

    monkeypatch.setattr(_handlers_history, "read_daily_archive", spy)
    return asked


# ---------------------------------------------------------------------------
# Registration and classification
# ---------------------------------------------------------------------------


class TestTheToolIsServedAndReadOnly:
    def test_the_context_family_now_exports_fifteen_tools(self) -> None:
        from mureo.mcp import tools_mureo_context

        assert len(tools_mureo_context.TOOLS) == 15
        assert _TOOL in {tool.name for tool in tools_mureo_context.TOOLS}

    def test_it_is_not_classified_as_a_mutation(self) -> None:
        """The whole design rests on this: a ``_query`` suffix is not in the
        mutating list, so no strategy reminder and no injected rationale."""
        from mureo.core.strategy_reminder import is_mutating_builtin_tool

        assert is_mutating_builtin_tool(_TOOL) is False

    def test_the_served_schema_has_no_injected_reason(self) -> None:
        from mureo.mcp import server

        served = {tool.name: tool for tool in server._ALL_TOOLS}
        assert "reason" not in served[_TOOL].inputSchema["properties"]

    def test_the_outcome_enum_covers_every_verdict_the_hook_writes(self) -> None:
        """The schema offers the journal's outcome vocabulary. A verdict
        the dispatcher can write but the enum does not list is a filter an
        agent is refused for asking, on a value that is really there."""
        import inspect
        import re

        from mureo.mcp._journal_hook import JOURNAL_OUTCOMES, JournalledCall

        source = inspect.getsource(JournalledCall)
        written = set(re.findall(r'self\.outcome(?:, self\.reason)? = "(\w+)"', source))
        assert written
        assert written <= set(JOURNAL_OUTCOMES)

    def test_the_schema_refuses_an_unknown_property(self) -> None:
        from mureo.mcp import server

        served = {tool.name: tool for tool in server._ALL_TOOLS}
        assert served[_TOOL].inputSchema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# The echoed query
# ---------------------------------------------------------------------------


class TestTheQueryIsEchoed:
    async def test_the_defaults_are_stated_not_implied(self, workspace) -> None:
        _state(workspace / "STATE.json")
        payload = await _call({})

        assert payload["query"] == {
            "sources": ["action_log", "journal"],
            "limit": HISTORY_QUERY_DEFAULT_LIMIT,
            "since": None,
            "until": None,
            "platform": None,
            "campaign_id": None,
            "entity_type": None,
            "entity_id": None,
            "batch_id": None,
            "tool": None,
            "outcome": None,
            "kind": None,
            "mutations_only": False,
            "failures_only": False,
        }

    async def test_only_the_requested_sources_are_returned(self, workspace) -> None:
        _state(workspace / "STATE.json")
        payload = await _call({"sources": ["action_log"]})

        assert "action_log" in payload
        assert "journal" not in payload
        assert "daily" not in payload
        assert "reports" not in payload

    async def test_the_filters_come_back_as_given(self, workspace) -> None:
        _state(workspace / "STATE.json")
        payload = await _call(
            {
                "sources": ["action_log"],
                "since": "2026-07-01",
                "until": "2026-07-31",
                "platform": _PLATFORM,
                "campaign_id": "c-1",
                "entity_type": "ad_group",
                "entity_id": "g-1",
                "limit": 3,
            }
        )
        query = payload["query"]
        assert query["since"] == "2026-07-01"
        assert query["until"] == "2026-07-31"
        assert query["platform"] == _PLATFORM
        assert query["entity_type"] == "ad_group"
        assert query["limit"] == 3


# ---------------------------------------------------------------------------
# action_log
# ---------------------------------------------------------------------------


class TestActionLogSource:
    async def test_entries_carry_their_index_in_the_full_log(self, workspace) -> None:
        _state(
            workspace / "STATE.json",
            _entry("2026-07-01", campaign_id="c-1"),
            _entry("2026-07-02", campaign_id="c-2"),
            _entry("2026-07-03", campaign_id="c-1"),
        )
        payload = await _call({"sources": ["action_log"], "campaign_id": "c-1"})
        section = payload["action_log"]

        assert [entry["index"] for entry in section["entries"]] == [0, 2]
        assert section["matched"] == 2
        assert section["returned"] == 2
        assert section["truncated"] is False

    async def test_the_newest_entries_win_when_more_matched_than_the_limit(
        self, workspace
    ) -> None:
        _state(
            workspace / "STATE.json",
            *(_entry(f"2026-07-{day:02d}") for day in range(1, 11)),
        )
        section = (await _call({"sources": ["action_log"], "limit": 3}))["action_log"]

        assert section["matched"] == 10
        assert section["returned"] == 3
        assert section["truncated"] is True
        assert [entry["index"] for entry in section["entries"]] == [7, 8, 9]

    async def test_the_date_window_is_inclusive_on_both_ends(self, workspace) -> None:
        _state(
            workspace / "STATE.json",
            *(_entry(f"2026-07-{day:02d}") for day in range(1, 6)),
        )
        section = (
            await _call(
                {
                    "sources": ["action_log"],
                    "since": "2026-07-02",
                    "until": "2026-07-04",
                }
            )
        )["action_log"]

        assert [entry["index"] for entry in section["entries"]] == [1, 2, 3]

    async def test_the_platform_filter_is_exact(self, workspace) -> None:
        _state(
            workspace / "STATE.json",
            _entry("2026-07-01"),
            _entry("2026-07-02", platform="meta_ads"),
        )
        section = (await _call({"sources": ["action_log"], "platform": "meta_ads"}))[
            "action_log"
        ]

        assert [entry["platform"] for entry in section["entries"]] == ["meta_ads"]

    async def test_the_entity_pair_matches_both_halves(self, workspace) -> None:
        _state(
            workspace / "STATE.json",
            _entry("2026-07-01", entity_type="ad_group", entity_id="g-1"),
            _entry("2026-07-02", entity_type="ad_group", entity_id="g-2"),
            _entry("2026-07-03", entity_type="ad_set", entity_id="g-1"),
        )
        section = (
            await _call(
                {
                    "sources": ["action_log"],
                    "entity_type": "ad_group",
                    "entity_id": "g-1",
                }
            )
        )["action_log"]

        assert [entry["index"] for entry in section["entries"]] == [0]

    async def test_the_batch_filter_selects_one_change_set(self, workspace) -> None:
        _state(
            workspace / "STATE.json",
            _entry("2026-07-01", batch_id="b-1"),
            _entry("2026-07-02", batch_id="b-2"),
        )
        section = (await _call({"sources": ["action_log"], "batch_id": "b-2"}))[
            "action_log"
        ]

        assert [entry["batch_id"] for entry in section["entries"]] == ["b-2"]

    async def test_a_missing_state_file_is_an_empty_answer(self, workspace) -> None:
        section = (await _call({"sources": ["action_log"]}))["action_log"]

        assert section["entries"] == []
        assert section["matched"] == 0
        assert section["state"] == "missing"

    async def test_a_present_state_file_is_not_marked_missing(self, workspace) -> None:
        _state(workspace / "STATE.json", _entry("2026-07-01"))
        section = (await _call({"sources": ["action_log"]}))["action_log"]

        assert "state" not in section


# ---------------------------------------------------------------------------
# journal
# ---------------------------------------------------------------------------


class TestJournalSource:
    async def test_a_missing_journal_still_names_the_file(self, workspace) -> None:
        section = (await _call({"sources": ["journal"]}))["journal"]

        assert section["records"] == []
        assert section["returned"] == 0
        assert section["truncated"] is False
        assert section["path"].endswith("JOURNAL.jsonl")

    async def test_the_tool_filter_is_exact(self, workspace) -> None:
        _journal(
            workspace,
            _record(tool="google_ads_campaigns_list"),
            _record(tool="rollback_apply"),
        )
        section = (await _call({"sources": ["journal"], "tool": "rollback_apply"}))[
            "journal"
        ]

        assert [r["tool"] for r in section["records"]] == ["rollback_apply"]

    async def test_failures_only_drops_the_successful_calls(self, workspace) -> None:
        _journal(
            workspace,
            _record(),
            _record(outcome="denied", reason="read-only mode"),
        )
        section = (await _call({"sources": ["journal"], "failures_only": True}))[
            "journal"
        ]

        assert [r["outcome"] for r in section["records"]] == ["denied"]

    async def test_the_outcome_filter_names_one_outcome(self, workspace) -> None:
        _journal(
            workspace,
            _record(outcome="denied"),
            _record(outcome="invalid_args"),
        )
        section = (await _call({"sources": ["journal"], "outcome": "invalid_args"}))[
            "journal"
        ]

        assert [r["outcome"] for r in section["records"]] == ["invalid_args"]

    async def test_mutations_only_keeps_the_declared_mutations(self, workspace) -> None:
        _journal(workspace, _record(), _record(mutating=True, tool="x_update"))
        section = (await _call({"sources": ["journal"], "mutations_only": True}))[
            "journal"
        ]

        assert [r["tool"] for r in section["records"]] == ["x_update"]

    async def test_a_builtin_platform_matches_the_record_family(
        self, workspace
    ) -> None:
        _journal(
            workspace,
            _record(family="google_ads"),
            _record(family="meta_ads", tool="meta_ads_campaigns_list"),
        )
        section = (await _call({"sources": ["journal"], "platform": "meta_ads"}))[
            "journal"
        ]

        assert [r["family"] for r in section["records"]] == ["meta_ads"]

    async def test_a_plugin_platform_matches_the_record_source(self, workspace) -> None:
        """A plugin record's family is ``plugin``; the distribution that
        supplied the tool is in ``source``, which is what the platform key
        names."""
        _journal(
            workspace,
            _record(family="plugin", source="mureo-lineyahoo-bridge", tool="mcp__a"),
            _record(family="plugin", source="mureo-logly-bridge", tool="mcp__b"),
        )
        section = (await _call({"sources": ["journal"], "platform": _PLUGIN}))[
            "journal"
        ]

        assert [r["source"] for r in section["records"]] == ["mureo-lineyahoo-bridge"]

    async def test_the_campaign_filter_is_a_best_effort_argument_match(
        self, workspace
    ) -> None:
        _journal(
            workspace,
            _record(args={"campaign_id": "c-1"}),
            _record(args={"campaign_id": "c-2"}, tool="other"),
        )
        section = (await _call({"sources": ["journal"], "campaign_id": "c-1"}))[
            "journal"
        ]

        assert [r["args"]["campaign_id"] for r in section["records"]] == ["c-1"]

    async def test_the_entity_filter_reads_the_typed_argument(self, workspace) -> None:
        _journal(
            workspace,
            _record(args={"ad_group_id": "g-1"}),
            _record(args={"ad_group_id": "g-2"}, tool="other"),
            _record(args={"id": "g-1"}, tool="third"),
        )
        section = (
            await _call(
                {
                    "sources": ["journal"],
                    "entity_type": "ad_group",
                    "entity_id": "g-1",
                }
            )
        )["journal"]

        assert [r["tool"] for r in section["records"]] == [
            "google_ads_campaigns_list",
            "third",
        ]

    async def test_the_date_window_filters_records(self, workspace) -> None:
        _journal(
            workspace,
            _record(ts="2026-06-30T23:00:00+00:00"),
            _record(ts="2026-07-01T00:30:00+00:00", tool="kept"),
            _record(ts="2026-08-01T00:30:00+00:00", tool="late"),
        )
        section = (
            await _call(
                {
                    "sources": ["journal"],
                    "since": "2026-07-01",
                    "until": "2026-07-31",
                }
            )
        )["journal"]

        assert [r["tool"] for r in section["records"]] == ["kept"]

    async def test_more_matches_than_the_limit_are_truncated_newest_first(
        self, workspace
    ) -> None:
        _journal(workspace, *(_record(tool=f"t-{i}") for i in range(10)))
        section = (await _call({"sources": ["journal"], "limit": 2}))["journal"]

        assert [r["tool"] for r in section["records"]] == ["t-8", "t-9"]
        assert section["returned"] == 2
        assert section["truncated"] is True

    async def test_an_unparseable_line_is_counted_not_fatal(self, workspace) -> None:
        _journal(workspace, _record(), "{half a line")
        section = (await _call({"sources": ["journal"]}))["journal"]

        assert len(section["records"]) == 1
        assert section["skipped_lines"] == 1

    async def test_the_scan_stops_at_the_tail_bound(self, workspace) -> None:
        """25 000 lines in, 20 000 scanned: the journal is unrotated and a
        query must not grow with it."""
        log = workspace / "JOURNAL.jsonl"
        overshoot = HISTORY_QUERY_JOURNAL_SCAN_LINES + 5_000
        log.write_text(
            "".join(
                json.dumps(_record(tool=f"t-{i}")) + "\n" for i in range(overshoot)
            ),
            encoding="utf-8",
        )
        section = (await _call({"sources": ["journal"], "limit": 1}))["journal"]

        assert section["scanned_lines"] == HISTORY_QUERY_JOURNAL_SCAN_LINES
        assert [r["tool"] for r in section["records"]] == [f"t-{overshoot - 1}"]
        assert section["truncated"] is True


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------


class TestDailySource:
    async def test_it_refuses_a_query_with_no_platform(self, workspace) -> None:
        _state(workspace / "STATE.json")
        assert "platform" in await _refusal({"sources": ["daily"]})

    async def test_the_archive_and_the_document_are_one_series(self, workspace) -> None:
        state = _state(
            workspace / "STATE.json",
            daily={"2026-08-01": _bucket(10.0), "2026-08-02": _bucket(11.0)},
        )
        history.archive_platform_daily(
            state,
            _PLATFORM,
            "123-456-7890",
            {"2026-07-30": _bucket(1.0), "2026-07-31": _bucket(2.0)},
        )
        section = (await _call({"sources": ["daily"], "platform": _PLATFORM}))["daily"]

        assert list(section["days"]) == [
            "2026-07-30",
            "2026-07-31",
            "2026-08-01",
            "2026-08-02",
        ]
        assert section["platform"] == _PLATFORM
        assert section["returned"] == 4
        assert section["skipped_files"] == []

    async def test_the_document_wins_for_a_day_in_both(self, workspace) -> None:
        """The archive holds what a write was about to drop; STATE.json holds
        what it kept. A day in both is the document's."""
        state = _state(workspace / "STATE.json", daily={"2026-07-31": _bucket(99.0)})
        history.archive_platform_daily(
            state, _PLATFORM, "123-456-7890", {"2026-07-31": _bucket(1.0)}
        )
        section = (await _call({"sources": ["daily"], "platform": _PLATFORM}))["daily"]

        assert section["days"]["2026-07-31"]["spend"] == 99.0

    async def test_the_window_bounds_both_halves(self, workspace) -> None:
        state = _state(
            workspace / "STATE.json",
            daily={"2026-08-01": _bucket(10.0), "2026-08-05": _bucket(12.0)},
        )
        history.archive_platform_daily(
            state,
            _PLATFORM,
            "123-456-7890",
            {"2026-07-01": _bucket(1.0), "2026-07-31": _bucket(2.0)},
        )
        section = (
            await _call(
                {
                    "sources": ["daily"],
                    "platform": _PLATFORM,
                    "since": "2026-07-31",
                    "until": "2026-08-01",
                }
            )
        )["daily"]

        assert list(section["days"]) == ["2026-07-31", "2026-08-01"]

    async def test_the_newest_days_win_when_truncated(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        history.archive_platform_daily(
            state,
            _PLATFORM,
            "123-456-7890",
            {f"2026-07-{day:02d}": _bucket(float(day)) for day in range(1, 11)},
        )
        section = (
            await _call({"sources": ["daily"], "platform": _PLATFORM, "limit": 2})
        )["daily"]

        assert list(section["days"]) == ["2026-07-09", "2026-07-10"]
        assert section["truncated"] is True

    async def test_an_unreadable_month_is_named_not_swallowed(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        history.archive_platform_daily(
            state, _PLATFORM, "123-456-7890", {"2026-07-01": _bucket(1.0)}
        )
        (workspace / "history" / "daily" / "2026-06.json").write_text(
            "{not json", encoding="utf-8"
        )
        section = (await _call({"sources": ["daily"], "platform": _PLATFORM}))["daily"]

        assert section["skipped_files"] == ["2026-06.json"]
        assert list(section["days"]) == ["2026-07-01"]

    async def test_a_dateless_query_reads_only_the_default_lookback(
        self, workspace, monkeypatch
    ) -> None:
        """Thirty months archived, no window asked for: twelve are opened.

        The archive is selected by file NAME, so the bound is what keeps a
        dateless question off every month a long-lived account ever had —
        the one source with no cap of its own until now.
        """
        state = _state(workspace / "STATE.json")
        _archive_one_day_per_month(state, _months_ending_today(30))
        asked = _spy_on_archive(monkeypatch)

        section = (
            await _call({"sources": ["daily"], "platform": _PLATFORM, "limit": 200})
        )["daily"]

        assert section["window"] == {
            "since": "2025-10-01",
            "until": None,
            "defaulted": True,
        }
        assert asked == [(date(2025, 10, 1), None)]
        assert list(section["days"]) == [
            f"{month}-01"
            for month in _months_ending_today(
                HISTORY_QUERY_DAILY_DEFAULT_LOOKBACK_MONTHS
            )
        ]

    async def test_an_explicit_since_reaches_past_the_default_lookback(
        self, workspace, monkeypatch
    ) -> None:
        state = _state(workspace / "STATE.json")
        months = _months_ending_today(30)
        _archive_one_day_per_month(state, months)
        asked = _spy_on_archive(monkeypatch)

        section = (
            await _call(
                {
                    "sources": ["daily"],
                    "platform": _PLATFORM,
                    "since": f"{months[0]}-01",
                    "limit": 200,
                }
            )
        )["daily"]

        assert section["window"] == {
            "since": f"{months[0]}-01",
            "until": None,
            "defaulted": False,
        }
        assert asked == [(date.fromisoformat(f"{months[0]}-01"), None)]
        assert list(section["days"]) == [f"{month}-01" for month in months]

    async def test_the_default_lookback_is_anchored_on_until(
        self, workspace, monkeypatch
    ) -> None:
        """``until`` without ``since`` counts the months back from ``until``.

        Anchoring on today instead would answer a question about last year
        with an empty window, which reads as "nothing happened".
        """
        state = _state(workspace / "STATE.json")
        _archive_one_day_per_month(state, _months_ending_today(30))
        asked = _spy_on_archive(monkeypatch)

        section = (
            await _call(
                {
                    "sources": ["daily"],
                    "platform": _PLATFORM,
                    "until": "2025-06-30",
                    "limit": 200,
                }
            )
        )["daily"]

        assert section["window"] == {
            "since": "2024-07-01",
            "until": "2025-06-30",
            "defaulted": True,
        }
        assert asked == [(date(2024, 7, 1), date(2025, 6, 30))]
        assert list(section["days"])[0] == "2024-07-01"
        assert list(section["days"])[-1] == "2025-06-01"

    async def test_the_default_lookback_bounds_the_document_too(
        self, workspace
    ) -> None:
        """The window the section reports is the window it answered from.

        A stale document day older than the lookback is left out rather
        than merged in beside archived days the same query refused to
        read — a series that contradicts its own stated window is worse
        than a short one.
        """
        _state(
            workspace / "STATE.json",
            daily={"2024-01-05": _bucket(7.0), "2026-09-01": _bucket(8.0)},
        )
        section = (
            await _call({"sources": ["daily"], "platform": _PLATFORM, "limit": 200})
        )["daily"]

        assert list(section["days"]) == ["2026-09-01"]

    async def test_a_missing_state_file_leaves_the_archive_readable(
        self, workspace
    ) -> None:
        history.archive_platform_daily(
            workspace / "STATE.json",
            _PLATFORM,
            "123-456-7890",
            {"2026-07-01": _bucket(1.0)},
        )
        section = (await _call({"sources": ["daily"], "platform": _PLATFORM}))["daily"]

        assert list(section["days"]) == ["2026-07-01"]
        assert section["state"] == "missing"


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


class TestReportsSource:
    async def test_it_refuses_a_reports_query_with_no_kind(self, workspace) -> None:
        _state(workspace / "STATE.json")
        assert "kind" in await _refusal({"sources": ["reports"]})

    async def test_a_kind_without_the_reports_source_is_refused(
        self, workspace
    ) -> None:
        _state(workspace / "STATE.json")
        message = await _refusal({"sources": ["action_log"], "kind": "weekly"})
        assert "kind" in message

    async def test_every_version_comes_back_oldest_first(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        for narrative in ("first", "second", "third"):
            history.append_report_history(state, "weekly", {"narrative": narrative})
        section = (await _call({"sources": ["reports"], "kind": "weekly"}))["reports"]

        assert [e["summary"]["narrative"] for e in section["entries"]] == [
            "first",
            "second",
            "third",
        ]
        assert section["kind"] == "weekly"
        assert section["returned"] == 3
        assert section["truncated"] is False

    async def test_the_newest_versions_win_when_truncated(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        for index in range(5):
            history.append_report_history(state, "weekly", {"n": index})
        section = (await _call({"sources": ["reports"], "kind": "weekly", "limit": 2}))[
            "reports"
        ]

        assert [e["summary"]["n"] for e in section["entries"]] == [3, 4]
        assert section["truncated"] is True

    async def test_a_corrupt_ledger_line_is_counted(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        history.append_report_history(state, "weekly", {"n": 1})
        ledger = workspace / "history" / "reports" / "weekly.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write("{half a line\n")
        section = (await _call({"sources": ["reports"], "kind": "weekly"}))["reports"]

        assert section["returned"] == 1
        assert section["skipped_lines"] == 1

    async def test_a_ledger_that_does_not_exist_is_an_empty_answer(
        self, workspace
    ) -> None:
        _state(workspace / "STATE.json")
        section = (await _call({"sources": ["reports"], "kind": "monthly"}))["reports"]

        assert section["entries"] == []
        assert section["returned"] == 0

    async def test_the_window_filters_on_recorded_at(self, workspace) -> None:
        state = _state(workspace / "STATE.json")
        history.append_report_history(state, "weekly", {"n": 1})
        ledger = workspace / "history" / "reports" / "weekly.jsonl"
        old = json.dumps(
            {
                "v": 1,
                "kind": "weekly",
                "recorded_at": "2020-01-01T00:00:00+00:00",
                "summary": {"n": 0},
            }
        )
        ledger.write_text(old + "\n" + ledger.read_text(encoding="utf-8"), "utf-8")

        recent = (
            await _call(
                {"sources": ["reports"], "kind": "weekly", "since": "2021-01-01"}
            )
        )["reports"]
        historic = (
            await _call(
                {"sources": ["reports"], "kind": "weekly", "until": "2020-12-31"}
            )
        )["reports"]

        assert [e["summary"]["n"] for e in recent["entries"]] == [1]
        assert [e["summary"]["n"] for e in historic["entries"]] == [0]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    async def test_an_until_before_the_since_is_refused(self, workspace) -> None:
        message = await _refusal({"since": "2026-07-31", "until": "2026-07-01"})
        assert "until" in message

    async def test_half_an_entity_pair_is_refused(self, workspace) -> None:
        message = await _refusal({"entity_type": "ad_group"})
        assert "entity_id" in message

    async def test_the_other_half_of_the_pair_is_refused_too(self, workspace) -> None:
        message = await _refusal({"entity_id": "g-1"})
        assert "entity_type" in message

    async def test_a_limit_over_the_cap_is_refused_by_the_schema(
        self, workspace
    ) -> None:
        message = await _refusal({"limit": HISTORY_QUERY_MAX_LIMIT + 1})
        assert "limit" in message.lower()

    async def test_an_unknown_source_is_refused_by_the_schema(self, workspace) -> None:
        message = await _refusal({"sources": ["everything"]})
        assert "sources" in message.lower()

    async def test_a_malformed_date_is_refused_by_the_schema(self, workspace) -> None:
        message = await _refusal({"since": "July"})
        assert "since" in message.lower()


# ---------------------------------------------------------------------------
# Several sources at once
# ---------------------------------------------------------------------------


class TestEverySourceAtOnce:
    async def test_each_source_is_bounded_by_the_same_limit(self, workspace) -> None:
        state = _state(
            workspace / "STATE.json",
            *(_entry(f"2026-07-{day:02d}") for day in range(1, 6)),
            daily={"2026-08-01": _bucket(1.0)},
        )
        history.archive_platform_daily(
            state,
            _PLATFORM,
            "123-456-7890",
            {f"2026-07-{day:02d}": _bucket(float(day)) for day in range(1, 6)},
        )
        for index in range(5):
            history.append_report_history(state, "weekly", {"n": index})
        _journal(workspace, *(_record(tool=f"t-{i}") for i in range(5)))

        payload = await _call(
            {
                "sources": ["action_log", "journal", "daily", "reports"],
                "platform": _PLATFORM,
                "kind": "weekly",
                "limit": 2,
            }
        )

        assert payload["action_log"]["returned"] == 2
        assert payload["journal"]["returned"] == 2
        assert payload["daily"]["returned"] == 2
        assert payload["reports"]["returned"] == 2
        assert all(
            payload[source]["truncated"] is True
            for source in ("action_log", "journal", "daily", "reports")
        )
