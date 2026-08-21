"""Daily per-platform history in STATE.json (#690).

STATE.json kept exactly one rollup per canonical window, and every daily
collection overwrote it. The value it replaced was gone, so nothing in the
product could answer "was yesterday better than the day before?" — no
day-over-day delta, no trend line — even though every platform family
already ships a daily delivery report and daily-check's delivery-collapse
step already pulls those rows.

``PlatformState.daily`` is that missing history: one totals-shaped bucket
per ``YYYY-MM-DD``. What these tests pin:

- it is **optional and additive** — a document written before it existed
  parses unchanged and gains no key until something writes one;
- the writer **merges per date key** — the same day is replaced
  idempotently, and days a call does not mention survive it;
- **a day nobody collected is not written** — no zero-filling, because
  "not collected" and "collected, and the answer was zero" are different
  facts (the same rule ``not_collected`` exists for);
- **a partial day is refused**, before the file is touched: today is still
  being spent into, and half a day filed as a day is a false low forever;
- the history is **capped** at :data:`DAILY_RETENTION_DAYS` days on write,
  so an account collected every day for a year does not grow STATE.json
  without bound;
- the read side exposes the series **ascending with its gaps intact**, and
  computes the day-over-day delta only across two ACTUALLY consecutive
  days — a delta computed across a collection gap would be a made-up
  comparison presented as a measurement.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import PlatformState, StateDocument
from mureo.context.state import (
    DAILY_RETENTION_DAYS,
    parse_state,
    read_state_file,
    render_state,
    set_platform_daily,
    set_platform_metrics,
    set_platform_not_collected,
    set_report,
    write_state_file,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_PLATFORM = "google_ads"
_ACCOUNT = "123-456-7890"

#: The host's "now" every test in this file runs against. Frozen, because
#: the writer refuses today and everything after it, and a suite whose
#: fixtures drift past midnight would refuse yesterday's rows tomorrow.
_NOW = datetime(2026, 8, 21, 9, 30, tzinfo=timezone(timedelta(hours=9)))
_TODAY = _NOW.date()


def _day(offset: int) -> str:
    """``offset`` days before the frozen today, as a ``YYYY-MM-DD`` key."""
    return (_TODAY - timedelta(days=offset)).isoformat()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.core import clock

    monkeypatch.setattr(clock, "server_now", lambda: _NOW)


def _entry(path: Path) -> PlatformState:
    doc = read_state_file(path)
    assert doc.platforms is not None
    return doc.platforms[_PLATFORM]


# ---------------------------------------------------------------------------
# The field itself
# ---------------------------------------------------------------------------


class TestTheFieldIsOptionalAndAdditive:
    def test_a_document_written_before_the_field_parses_unchanged(self) -> None:
        doc = parse_state(
            json.dumps(
                {
                    "version": "2",
                    "platforms": {_PLATFORM: {"account_id": _ACCOUNT, "campaigns": []}},
                }
            )
        )
        assert doc.platforms is not None
        assert doc.platforms[_PLATFORM].daily is None

    def test_an_entry_without_it_emits_no_new_key(self) -> None:
        """Byte stability: a document that has never carried daily history
        must not gain a ``daily`` key just by being written back."""
        doc = StateDocument(
            version="2", platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT)}
        )
        assert "daily" not in json.loads(render_state(doc))["platforms"][_PLATFORM]

    def test_an_empty_map_emits_no_key_either(self) -> None:
        doc = StateDocument(
            version="2",
            platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT, daily={})},
        )
        assert "daily" not in json.loads(render_state(doc))["platforms"][_PLATFORM]

    def test_it_round_trips_when_set(self) -> None:
        doc = StateDocument(
            version="2",
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    daily={"2026-08-20": {"spend": 1200.0, "clicks": 42}},
                )
            },
        )
        restored = parse_state(render_state(doc))
        assert restored.platforms is not None
        assert restored.platforms[_PLATFORM].daily == {
            "2026-08-20": {"spend": 1200.0, "clicks": 42}
        }

    def test_the_stored_map_is_a_defensive_copy(self) -> None:
        supplied: dict[str, dict[str, Any]] = {"2026-08-20": {"spend": 1.0}}
        state = PlatformState(account_id=_ACCOUNT, daily=supplied)
        supplied["2026-08-20"]["spend"] = 999.0
        assert state.daily is not None
        assert state.daily["2026-08-20"]["spend"] == 1.0


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


class TestSetPlatformDaily:
    def test_it_creates_the_platform_entry_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        doc = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 1200.0}}
        )
        assert doc.platforms is not None
        entry = doc.platforms[_PLATFORM]
        assert entry.account_id == _ACCOUNT
        assert entry.daily is not None
        assert entry.daily[_day(1)]["spend"] == 1200.0

    def test_a_later_write_keeps_the_days_it_does_not_mention(
        self, tmp_path: Path
    ) -> None:
        """The whole point: yesterday's yesterday survives today's write."""
        path = tmp_path / "STATE.json"
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(2): {"spend": 10.0}})
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 20.0}})
        daily = _entry(path).daily
        assert daily is not None
        assert daily[_day(2)]["spend"] == 10.0
        assert daily[_day(1)]["spend"] == 20.0

    def test_the_same_day_written_twice_is_replaced_not_doubled(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 10.0}})
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 12.0}})
        daily = _entry(path).daily
        assert daily is not None
        assert daily[_day(1)] == {
            "spend": 12.0,
            "fetched_at": daily[_day(1)]["fetched_at"],
        }

    def test_a_day_nobody_collected_is_not_written(self, tmp_path: Path) -> None:
        """No zero-filling: a gap in the series is a fact about the
        collection, and inventing 0 for it would make a silent collector
        indistinguishable from an account that stopped spending."""
        path = tmp_path / "STATE.json"
        set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={_day(3): {"spend": 10.0}, _day(1): {"spend": 20.0}},
        )
        daily = _entry(path).daily
        assert daily is not None
        assert _day(2) not in daily

    def test_it_stamps_fetched_at_on_every_bucket_it_supplies(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={_day(1): {"spend": 1.0}, _day(2): {"spend": 2.0}},
        )
        daily = doc.platforms[_PLATFORM].daily
        assert daily is not None
        assert daily[_day(1)]["fetched_at"] == doc.last_synced_at
        assert daily[_day(2)]["fetched_at"] == doc.last_synced_at

    def test_a_supplied_fetched_at_is_relayed_verbatim(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={_day(1): {"spend": 1.0, "fetched_at": "2020-01-01T00:00:00+00:00"}},
        )
        daily = doc.platforms[_PLATFORM].daily
        assert daily is not None
        assert daily[_day(1)]["fetched_at"] == "2020-01-01T00:00:00+00:00"

    def test_a_day_it_merely_preserves_is_never_re_stamped(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        first = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={_day(2): {"spend": 10.0}}
        )
        stamped = first.platforms[_PLATFORM].daily[_day(2)]["fetched_at"]
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 20.0}})
        daily = _entry(path).daily
        assert daily is not None
        assert daily[_day(2)]["fetched_at"] == stamped

    def test_an_empty_map_leaves_the_stored_history_alone(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 1.0}})
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={})
        daily = _entry(path).daily
        assert daily is not None
        assert daily[_day(1)]["spend"] == 1.0

    def test_it_preserves_every_other_field_of_the_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_metrics(
            path,
            _PLATFORM,
            _ACCOUNT,
            totals={"spend": 25862.0},
            metrics_period="LAST_30_DAYS",
            periods={"LAST_30_DAYS": {"spend": 25862.0}},
        )
        set_platform_not_collected(path, _PLATFORM, _ACCOUNT, reason="token expired")
        set_report(path, "daily", {"narrative": "healthy"})
        doc = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 1.0}}
        )
        entry = doc.platforms[_PLATFORM]
        assert entry.totals["spend"] == 25862.0
        assert entry.metrics_period == "LAST_30_DAYS"
        assert entry.periods["LAST_30_DAYS"]["spend"] == 25862.0
        assert entry.not_collected is not None
        assert doc.reports == {"daily": {"narrative": "healthy"}}

    def test_it_shares_the_platform_key_guard(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 1.0}})
        with pytest.raises(ValueError, match=_PLATFORM):
            set_platform_daily(
                path, "meta_ads", _ACCOUNT, days={_day(1): {"spend": 1.0}}
            )


class TestDateKeysAreValidatedBeforeTheFileIsTouched:
    """Shape validation, and it runs OUTSIDE the lock — a refused write must
    leave the document exactly as it was, ``last_synced_at`` included."""

    @pytest.mark.parametrize(
        "key",
        [
            "2026-8-1",
            "20260801",
            "2026-08-01T00:00:00",
            "YESTERDAY",
            "last tuesday",
            "",
        ],
    )
    def test_a_key_that_is_not_a_date_is_refused(
        self, tmp_path: Path, key: str
    ) -> None:
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            set_platform_daily(path, _PLATFORM, _ACCOUNT, days={key: {"spend": 1.0}})
        assert not path.exists()

    def test_a_date_shaped_key_that_is_not_a_date_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="2026-02-30"):
            set_platform_daily(
                path, _PLATFORM, _ACCOUNT, days={"2026-02-30": {"spend": 1.0}}
            )

    def test_today_is_refused_because_it_is_still_being_spent_into(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path, _PLATFORM, _ACCOUNT, days={_TODAY.isoformat(): {"spend": 1.0}}
            )

    def test_a_future_day_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path, _PLATFORM, _ACCOUNT, days={_day(-1): {"spend": 1.0}}
            )

    def test_one_bad_key_refuses_the_whole_call(self, tmp_path: Path) -> None:
        """All-or-nothing: the caller still holds the figures and can re-file
        them, which is not true once half of them are on disk."""
        path = tmp_path / "STATE.json"
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(2): {"spend": 1.0}})
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValueError):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_day(1): {"spend": 2.0}, "yesterday": {"spend": 3.0}},
            )
        assert path.read_text(encoding="utf-8") == before


class TestRetention:
    def test_the_history_is_capped_at_the_retention_window(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        days = {
            _day(offset): {"spend": float(offset)}
            for offset in range(1, DAILY_RETENTION_DAYS + 11)
        }
        doc = set_platform_daily(path, _PLATFORM, _ACCOUNT, days=days)
        stored = doc.platforms[_PLATFORM].daily
        assert stored is not None
        assert len(stored) == DAILY_RETENTION_DAYS
        assert _day(1) in stored
        assert _day(DAILY_RETENTION_DAYS) in stored
        assert _day(DAILY_RETENTION_DAYS + 1) not in stored

    def test_the_cap_covers_the_collapse_detectors_baseline(self) -> None:
        """35 is 28 (``DEFAULT_BASELINE_DAYS``) plus margin, not a round
        number: the history has to outlive the baseline that reads it."""
        from mureo.analysis.delivery_collapse import DEFAULT_BASELINE_DAYS

        assert DAILY_RETENTION_DAYS > DEFAULT_BASELINE_DAYS

    def test_an_old_day_is_dropped_when_a_new_one_arrives(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={
                _day(offset): {"spend": 1.0}
                for offset in range(2, DAILY_RETENTION_DAYS + 2)
            },
        )
        assert _day(DAILY_RETENTION_DAYS + 1) in (_entry(path).daily or {})
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 2.0}})
        daily = _entry(path).daily
        assert daily is not None
        assert len(daily) == DAILY_RETENTION_DAYS
        assert _day(DAILY_RETENTION_DAYS + 1) not in daily
        assert _day(1) in daily

    def test_a_key_mureo_cannot_date_is_preserved_rather_than_dropped(
        self, tmp_path: Path
    ) -> None:
        """Reading stays tolerant of what is already on disk: a key the write
        guard would refuse today is still somebody's collected figures, and a
        retention sweep is not the place to delete them."""
        path = tmp_path / "STATE.json"
        write_state_file(
            path,
            StateDocument(
                version="2",
                platforms={
                    _PLATFORM: PlatformState(
                        account_id=_ACCOUNT, daily={"LAST_WEEK": {"spend": 1.0}}
                    )
                },
            ),
        )
        set_platform_daily(path, _PLATFORM, _ACCOUNT, days={_day(1): {"spend": 2.0}})
        daily = _entry(path).daily
        assert daily is not None
        assert daily["LAST_WEEK"]["spend"] == 1.0


# ---------------------------------------------------------------------------
# The dashboard wire
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_ctx() -> Iterator[None]:
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


def _summary(monkeypatch: pytest.MonkeyPatch, workspace: Path) -> dict[str, Any]:
    from mureo.core.runtime_context import default_runtime_context
    from mureo.web.reports import build_report_summary

    ctx = default_runtime_context(workspace=workspace)
    monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
    return build_report_summary()


def _write_daily(workspace: Path, daily: dict[str, dict[str, Any]]) -> None:
    write_state_file(
        workspace / "STATE.json",
        StateDocument(
            version="2",
            platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT, daily=daily)},
        ),
    )


@pytest.mark.usefixtures("_reset_ctx")
class TestTheWire:
    def test_the_row_carries_the_series_ascending(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(
            tmp_path,
            {
                _day(1): {"spend": 30.0},
                _day(3): {"spend": 10.0},
                _day(2): {"spend": 20.0},
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert [d["date"] for d in row["daily"]] == [_day(3), _day(2), _day(1)]
        assert [d["totals"]["spend"] for d in row["daily"]] == [10.0, 20.0, 30.0]

    def test_a_row_with_no_history_says_so_explicitly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An empty list and a ``None`` delta, never an absent key: the
        frontend reads one shape for every row."""
        _write_daily(tmp_path, {})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily"] == []
        assert row["daily_delta"] is None

    def test_a_gap_stays_a_gap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(tmp_path, {_day(3): {"spend": 10.0}, _day(1): {"spend": 30.0}})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert [d["date"] for d in row["daily"]] == [_day(3), _day(1)]

    def test_only_the_most_recent_week_reaches_the_browser(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(
            tmp_path,
            {_day(offset): {"spend": float(offset)} for offset in range(1, 21)},
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert [d["date"] for d in row["daily"]] == [
            _day(offset) for offset in range(7, 0, -1)
        ]

    def test_only_canonical_metric_keys_reach_the_browser(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Same whitelist discipline as ``totals``: a key a buggy or hostile
        writer slipped in never reaches the page."""
        _write_daily(tmp_path, {_day(1): {"spend": 1.0, "access_token": "EAAG-secret"}})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily"][0]["totals"] == {"spend": 1.0}

    def test_a_key_that_is_not_a_date_is_not_placed_on_the_timeline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(tmp_path, {"LAST_WEEK": {"spend": 1.0}, _day(1): {"spend": 2.0}})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert [d["date"] for d in row["daily"]] == [_day(1)]

    def test_the_delta_is_computed_server_side_from_the_last_two_days(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(
            tmp_path,
            {
                _day(2): {"spend": 100.0, "clicks": 10},
                _day(1): {"spend": 130.0, "clicks": 8},
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily_delta"]["from"] == _day(2)
        assert row["daily_delta"]["to"] == _day(1)
        assert row["daily_delta"]["metrics"]["spend"] == pytest.approx(30.0)
        assert row["daily_delta"]["metrics"]["clicks"] == -2

    def test_a_gap_between_the_last_two_days_makes_the_delta_unknown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Unknown, not computed: the two days are not neighbours, so the
        difference between them is not a day-over-day change."""
        _write_daily(tmp_path, {_day(3): {"spend": 100.0}, _day(1): {"spend": 130.0}})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily_delta"] is None

    def test_one_day_of_history_yields_no_delta(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(tmp_path, {_day(1): {"spend": 130.0}})
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily_delta"] is None

    def test_a_metric_only_one_of_the_two_days_carries_is_not_deltaed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(
            tmp_path,
            {
                _day(2): {"spend": 100.0},
                _day(1): {"spend": 130.0, "conversions": 4},
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily_delta"]["metrics"] == {"spend": pytest.approx(30.0)}

    def test_a_non_numeric_metric_is_not_deltaed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _write_daily(
            tmp_path,
            {
                _day(2): {"spend": "n/a", "result_indicator": "leads"},
                _day(1): {"spend": "n/a", "result_indicator": "leads"},
            },
        )
        (row,) = _summary(monkeypatch, tmp_path)["platforms"]
        assert row["daily_delta"] is None

    def test_the_series_rides_alongside_the_window_rollup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Daily history is not a window: selecting one must not replace or
        hide it."""
        write_state_file(
            tmp_path / "STATE.json",
            StateDocument(
                version="2",
                platforms={
                    _PLATFORM: PlatformState(
                        account_id=_ACCOUNT,
                        periods={"YESTERDAY": {"spend": 30.0}},
                        daily={_day(1): {"spend": 30.0}},
                    )
                },
            ),
        )
        from mureo.core.runtime_context import default_runtime_context
        from mureo.web.reports import build_report_summary

        ctx = default_runtime_context(workspace=tmp_path)
        monkeypatch.setattr("mureo.web.report_clients.get_runtime_context", lambda: ctx)
        (row,) = build_report_summary(period="YESTERDAY")["platforms"]
        assert row["totals"]["spend"] == 30.0
        assert [d["date"] for d in row["daily"]] == [_day(1)]


# ---------------------------------------------------------------------------
# The MCP path
# ---------------------------------------------------------------------------


class TestTheMcpTool:
    @pytest.fixture(autouse=True)
    def _cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        from mureo.core.runtime_context import reset_runtime_context

        reset_runtime_context()
        monkeypatch.chdir(tmp_path)
        yield tmp_path
        reset_runtime_context()

    async def _call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from mureo.mcp.tools_mureo_context import handle_tool

        result = await handle_tool("mureo_state_platform_daily_set", arguments)
        return json.loads(result[0].text)

    async def test_it_writes_the_days(self) -> None:
        payload = await self._call(
            {
                "platform": _PLATFORM,
                "account_id": _ACCOUNT,
                "days": {_day(1): {"spend": 1200.0}},
            }
        )
        stored = payload["platforms"][_PLATFORM]["daily"]
        assert stored[_day(1)]["spend"] == 1200.0
        assert stored[_day(1)]["fetched_at"]

    async def test_a_bucket_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(ValueError, match="days"):
            await self._call(
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {_day(1): 1200.0},
                }
            )

    async def test_days_is_required(self) -> None:
        with pytest.raises(ValueError, match="days"):
            await self._call({"platform": _PLATFORM, "account_id": _ACCOUNT})

    async def test_the_tool_is_registered_with_a_date_keyed_schema(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [t for t in TOOLS if t.name == "mureo_state_platform_daily_set"]
        assert tool.inputSchema["required"] == ["platform", "account_id", "days"]
        days = tool.inputSchema["properties"]["days"]
        # Date keys cannot be enumerated, so the shape is stated as a pattern
        # over the property NAMES rather than as a fixed property list.
        assert days["propertyNames"]["pattern"] == r"^\d{4}-\d{2}-\d{2}$"
        assert days["additionalProperties"]["type"] == "object"

    async def test_the_rules_are_stated_in_the_schema_the_agent_reads(self) -> None:
        """The dispatcher schema-validates before any handler runs, so mureo's
        own message is never reached on a refusal. The reason has to be in the
        description the model read before calling."""
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [t for t in TOOLS if t.name == "mureo_state_platform_daily_set"]
        text = tool.description + json.dumps(tool.inputSchema)
        assert "YYYY-MM-DD" in text
        # A complete past day only, and a day nobody collected is omitted
        # rather than written as zeros.
        assert "today" in text.lower()
        assert "omit" in text.lower()
        assert "zero" in text.lower()

    async def test_the_schema_refuses_a_key_that_is_not_a_date(self) -> None:
        from mureo.mcp.server import _validate_tool_input

        with pytest.raises(ValueError, match="days"):
            _validate_tool_input(
                "mureo_state_platform_daily_set",
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {"yesterday": {"spend": 1.0}},
                },
            )

    async def test_the_schema_accepts_a_date_key(self) -> None:
        from mureo.mcp.server import _validate_tool_input

        _validate_tool_input(
            "mureo_state_platform_daily_set",
            {
                "platform": _PLATFORM,
                "account_id": _ACCOUNT,
                "days": {"2026-08-20": {"spend": 1.0}},
            },
        )


# ---------------------------------------------------------------------------
# The skill that writes it
# ---------------------------------------------------------------------------


def test_daily_check_folds_the_rows_it_already_has_into_the_history() -> None:
    """Zero extra platform API calls: the delivery-collapse step already
    fetched the daily rows, and the step that discards them is where the
    history comes from."""
    body = (
        Path(__file__).resolve().parent.parent / "skills/daily-check/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "mureo_state_platform_daily_set" in body
    assert "no extra" in body.lower() or "zero extra" in body.lower()


def test_the_shipped_skill_copy_carries_the_step_too() -> None:
    root = Path(__file__).resolve().parent.parent
    source = (root / "skills/daily-check/SKILL.md").read_bytes()
    packaged = (root / "mureo/_data/skills/daily-check/SKILL.md").read_bytes()
    assert source == packaged
