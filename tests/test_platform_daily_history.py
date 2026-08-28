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

#710 made the same write usable by a document-level writer without
loosening any of that:

- :func:`~mureo.context.daily.with_platform_daily` is the whole merge
  minus the file, and :func:`~mureo.context.daily.capped_platform_daily`
  is the retention trim on its own — public, because a writer that lands
  ``daily`` inside its own atomic document write was reaching for a
  private name to apply the rule;
- ``as_of_date`` lets the caller say WHOSE today the completeness check is
  measured against. An ad account closes its day in the account's
  timezone, and on a UTC host in the small hours JST — when the nightly
  digest runs — a genuinely complete day was being refused.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.daily import capped_platform_daily, with_platform_daily
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
# The document-level write (#710)
# ---------------------------------------------------------------------------


class TestTheRetentionTrimIsPublic:
    """A writer that merges ``daily`` inside its OWN atomic document write
    still has to apply the retention rule. Until #710 the only way to do that
    was to import a private name, which makes a downstream nightly write
    hostage to a rename it has no say in."""

    def test_it_trims_to_the_cap_keeping_the_most_recent_days(self) -> None:
        trimmed = capped_platform_daily(
            {
                _day(offset): {"spend": float(offset)}
                for offset in range(1, DAILY_RETENTION_DAYS + 6)
            }
        )
        assert len(trimmed) == DAILY_RETENTION_DAYS
        assert _day(1) in trimmed
        assert _day(DAILY_RETENTION_DAYS) in trimmed
        assert _day(DAILY_RETENTION_DAYS + 1) not in trimmed

    def test_a_history_under_the_cap_is_returned_as_it_was(self) -> None:
        daily = {_day(2): {"spend": 1.0}, _day(1): {"spend": 2.0}}
        assert capped_platform_daily(daily) == daily

    def test_it_does_not_mutate_the_map_it_was_handed(self) -> None:
        daily = {
            _day(offset): {"spend": 1.0}
            for offset in range(1, DAILY_RETENTION_DAYS + 3)
        }
        capped_platform_daily(daily)
        assert len(daily) == DAILY_RETENTION_DAYS + 2

    def test_a_key_mureo_cannot_date_is_kept_and_does_not_count(self) -> None:
        daily: dict[str, dict[str, Any]] = {"LAST_WEEK": {"spend": 1.0}}
        daily.update(
            {
                _day(offset): {"spend": 1.0}
                for offset in range(1, DAILY_RETENTION_DAYS + 1)
            }
        )
        trimmed = capped_platform_daily(daily)
        assert trimmed["LAST_WEEK"]["spend"] == 1.0
        assert len(trimmed) == DAILY_RETENTION_DAYS + 1

    def test_the_private_name_still_resolves_to_it(self) -> None:
        """The old spelling is what a downstream writer imports today. It has
        to keep working across this release, or the fix that removes the
        coupling is itself the break it was meant to prevent."""
        from mureo.context.state import _capped_daily

        assert _capped_daily is capped_platform_daily


class TestTheDocumentLevelWriter:
    def test_it_merges_without_touching_the_filesystem(self, tmp_path: Path) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"),
            _PLATFORM,
            _ACCOUNT,
            {_day(1): {"spend": 1200.0}},
        )
        assert doc.platforms[_PLATFORM].daily[_day(1)]["spend"] == 1200.0
        assert list(tmp_path.iterdir()) == []

    def test_it_returns_a_new_document_and_leaves_the_input_alone(self) -> None:
        before = StateDocument(
            version="2",
            platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT, daily={})},
        )
        after = with_platform_daily(
            before, _PLATFORM, _ACCOUNT, {_day(1): {"spend": 1.0}}
        )
        assert after is not before
        assert before.platforms[_PLATFORM].daily == {}

    def test_it_merges_per_date_key_and_keeps_the_days_it_does_not_mention(
        self,
    ) -> None:
        first = with_platform_daily(
            StateDocument(version="2"), _PLATFORM, _ACCOUNT, {_day(2): {"spend": 1.0}}
        )
        second = with_platform_daily(
            first, _PLATFORM, _ACCOUNT, {_day(1): {"spend": 2.0}}
        )
        daily = second.platforms[_PLATFORM].daily
        assert daily[_day(2)]["spend"] == 1.0
        assert daily[_day(1)]["spend"] == 2.0

    def test_it_stamps_fetched_at_and_re_stamps_last_synced_at(self) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"), _PLATFORM, _ACCOUNT, {_day(1): {"spend": 1.0}}
        )
        assert doc.platforms[_PLATFORM].daily[_day(1)]["fetched_at"]
        assert doc.last_synced_at

    def test_it_preserves_every_other_field_of_the_entry(self) -> None:
        before = StateDocument(
            version="2",
            platforms={
                _PLATFORM: PlatformState(
                    account_id=_ACCOUNT,
                    totals={"spend": 25862.0},
                    metrics_period="LAST_30_DAYS",
                ),
                "meta_ads": PlatformState(account_id="act_999"),
            },
        )
        entry = with_platform_daily(
            before, _PLATFORM, _ACCOUNT, {_day(1): {"spend": 1.0}}
        ).platforms
        assert entry[_PLATFORM].totals["spend"] == 25862.0
        assert entry[_PLATFORM].metrics_period == "LAST_30_DAYS"
        assert entry["meta_ads"].account_id == "act_999"

    def test_it_applies_the_retention_trim(self) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"),
            _PLATFORM,
            _ACCOUNT,
            {
                _day(offset): {"spend": 1.0}
                for offset in range(1, DAILY_RETENTION_DAYS + 4)
            },
        )
        assert len(doc.platforms[_PLATFORM].daily) == DAILY_RETENTION_DAYS

    def test_it_refuses_a_day_that_is_not_over(self) -> None:
        with pytest.raises(ValueError, match="complete"):
            with_platform_daily(
                StateDocument(version="2"),
                _PLATFORM,
                _ACCOUNT,
                {_TODAY.isoformat(): {"spend": 1.0}},
            )

    def test_it_refuses_a_key_that_is_not_a_date(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            with_platform_daily(
                StateDocument(version="2"),
                _PLATFORM,
                _ACCOUNT,
                {"yesterday": {"spend": 1.0}},
            )

    def test_it_shares_the_platform_key_guard(self) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"), _PLATFORM, _ACCOUNT, {_day(1): {"spend": 1.0}}
        )
        with pytest.raises(ValueError, match=_PLATFORM):
            with_platform_daily(doc, "meta_ads", _ACCOUNT, {_day(1): {"spend": 1.0}})

    def test_the_path_based_write_produces_the_same_document(
        self, tmp_path: Path
    ) -> None:
        """One set of semantics, two entry points: the path-based mutator is a
        wrapper, so neither route can drift from the other."""
        path = tmp_path / "STATE.json"
        days = {_day(2): {"spend": 1.0}, _day(1): {"spend": 2.0}}
        written = set_platform_daily(path, _PLATFORM, _ACCOUNT, days=days)
        in_memory = with_platform_daily(
            StateDocument(version="2"), _PLATFORM, _ACCOUNT, days
        )
        assert written.platforms[_PLATFORM].daily.keys() == (
            in_memory.platforms[_PLATFORM].daily.keys()
        )
        assert [
            {k: v for k, v in bucket.items() if k != "fetched_at"}
            for bucket in written.platforms[_PLATFORM].daily.values()
        ] == [
            {k: v for k, v in bucket.items() if k != "fetched_at"}
            for bucket in in_memory.platforms[_PLATFORM].daily.values()
        ]


# ---------------------------------------------------------------------------
# Whose "today" the completeness check is measured against (#710)
# ---------------------------------------------------------------------------

#: The nightly-cron defect ``as_of_date`` exists for: a UTC host, an
#: Asia/Tokyo ad account, and a digest running in the small hours JST.
#: 01:30 on the 21st in Tokyo is still 16:30 on the 20th in UTC.
_JST = timezone(timedelta(hours=9))
_UTC_HOST_NOW = datetime(2026, 8, 20, 16, 30, tzinfo=timezone.utc)
_SERVER_TODAY = _UTC_HOST_NOW.date()
_ACCOUNT_TODAY = _UTC_HOST_NOW.astimezone(_JST).date()
_COMPLETE_DAY_JST = _ACCOUNT_TODAY - timedelta(days=1)


def _anchor(days_ahead: int) -> date:
    """An anchor ``days_ahead`` days past the server's own date."""
    return _SERVER_TODAY + timedelta(days=days_ahead)


class TestTheCompletenessAnchor:
    @pytest.fixture(autouse=True)
    def _utc_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mureo.core import clock

        monkeypatch.setattr(clock, "server_now", lambda: _UTC_HOST_NOW)

    def test_the_scenario_really_is_the_collision(self) -> None:
        """Pins the setup, not the code: if the fixture instant ever stopped
        straddling midnight, the two tests below would pass for no reason."""
        assert _UTC_HOST_NOW.date() == _COMPLETE_DAY_JST
        assert _COMPLETE_DAY_JST + timedelta(days=1) == _ACCOUNT_TODAY

    def test_without_an_anchor_the_complete_jst_day_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The defect, kept as a test: the host clock says that date is today,
        so a day that closed nine hours ago in Tokyo is called partial."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
            )

    def test_the_accounts_own_today_lets_the_complete_day_through(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "STATE.json"
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
            as_of_date=_ACCOUNT_TODAY,
        )
        daily = doc.platforms[_PLATFORM].daily
        assert daily[_COMPLETE_DAY_JST.isoformat()]["spend"] == 1.0

    def test_the_document_level_writer_takes_the_anchor_too(self) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"),
            _PLATFORM,
            _ACCOUNT,
            {_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
            as_of_date=_ACCOUNT_TODAY,
        )
        assert _COMPLETE_DAY_JST.isoformat() in doc.platforms[_PLATFORM].daily

    def test_the_anchors_own_day_is_still_refused(self, tmp_path: Path) -> None:
        """The rule does not move: an anchor states whose today it is, it does
        not buy a partial day."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_ACCOUNT_TODAY.isoformat(): {"spend": 1.0}},
                as_of_date=_ACCOUNT_TODAY,
            )

    def test_a_day_after_the_anchor_is_still_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "STATE.json"
        later = (_ACCOUNT_TODAY + timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={later: {"spend": 1.0}},
                as_of_date=_ACCOUNT_TODAY,
            )

    def test_the_refusal_names_the_anchor_it_used(self, tmp_path: Path) -> None:
        """Two clocks can now say "today", so a message that does not say
        which one it meant sends the caller hunting the wrong one."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="as_of_date"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_ACCOUNT_TODAY.isoformat(): {"spend": 1.0}},
                as_of_date=_ACCOUNT_TODAY,
            )
        with pytest.raises(ValueError, match="server today"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
            )

    def test_a_datetime_is_narrowed_to_its_date(self, tmp_path: Path) -> None:
        """Resolving "now" in the account's timezone is what produces one, so
        handing it straight over is the obvious call and must not blow up in a
        comparison two frames down."""
        path = tmp_path / "STATE.json"
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
            as_of_date=_UTC_HOST_NOW.astimezone(_JST),
        )
        assert _COMPLETE_DAY_JST.isoformat() in doc.platforms[_PLATFORM].daily

    @pytest.mark.parametrize("anchor", ["2026-08-21", 20260821, object()])
    def test_something_that_is_not_a_date_is_refused(
        self, tmp_path: Path, anchor: Any
    ) -> None:
        """Including the ISO STRING: it compares against nothing, and a
        silently ignored anchor is the confusion this parameter removes."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError, match="as_of_date"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={_COMPLETE_DAY_JST.isoformat(): {"spend": 1.0}},
                as_of_date=anchor,
            )
        assert not path.exists()

    def test_omitting_it_keeps_the_behaviour_every_caller_had(
        self, tmp_path: Path
    ) -> None:
        """Backward compatibility, stated as a test: without an anchor the
        host clock is still the judge, and a day before it still lands."""
        path = tmp_path / "STATE.json"
        older = (_UTC_HOST_NOW.date() - timedelta(days=1)).isoformat()
        doc = set_platform_daily(
            path, _PLATFORM, _ACCOUNT, days={older: {"spend": 1.0}}
        )
        assert older in doc.platforms[_PLATFORM].daily


class TestTheAnchorIsBounded:
    """The anchor is the CALLER's self-report, and on the MCP route the caller
    is an LLM that inferred the date. Unbounded, ``as_of_date="2099-01-01"``
    makes every date this side of the century a "complete past day" — the rule
    this module exists to enforce, switched off by an argument."""

    @pytest.fixture(autouse=True)
    def _utc_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mureo.core import clock

        monkeypatch.setattr(clock, "server_now", lambda: _UTC_HOST_NOW)

    def test_the_bound_is_two_days(self) -> None:
        """Pinned as a value, not just used as one: civil offsets run UTC-12
        to UTC+14 — 26 hours — so an instant that is date D in one place is at
        most D+2 in another (22:00 on D at UTC-12 is 00:00 on D+2 at UTC+14).
        Widening this is a decision, not a refactor."""
        from mureo.context.daily import _MAX_ANCHOR_DAYS_AHEAD

        assert _MAX_ANCHOR_DAYS_AHEAD == 2

    def test_the_widest_real_timezone_gap_is_accepted(self, tmp_path: Path) -> None:
        """The boundary's inside edge: +2 is a date two places on Earth can
        genuinely disagree by, so it must go through."""
        path = tmp_path / "STATE.json"
        complete = (_SERVER_TODAY - timedelta(days=1)).isoformat()
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={complete: {"spend": 1.0}},
            as_of_date=_anchor(2),
        )
        assert complete in doc.platforms[_PLATFORM].daily

    def test_one_day_past_the_widest_gap_is_refused(self, tmp_path: Path) -> None:
        """The outside edge, on the very same call: +3 is not a timezone."""
        path = tmp_path / "STATE.json"
        complete = (_SERVER_TODAY - timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="as_of_date"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={complete: {"spend": 1.0}},
                as_of_date=_anchor(3),
            )
        assert not path.exists()

    def test_a_far_future_anchor_cannot_file_days_nobody_has_lived(
        self, tmp_path: Path
    ) -> None:
        """The reproduction, negated: an anchor 60 days out and rows dated 30
        days out — every one of them a day that has not happened."""
        path = tmp_path / "STATE.json"
        unlived = (_SERVER_TODAY + timedelta(days=30)).isoformat()
        with pytest.raises(ValueError, match="as_of_date"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={unlived: {"spend": 1.0}},
                as_of_date=_anchor(60),
            )
        assert not path.exists()

    def test_the_document_level_writer_is_bounded_too(self) -> None:
        """Both entry points, or the guard is a suggestion: a downstream
        writer calls this one directly."""
        unlived = (_SERVER_TODAY + timedelta(days=30)).isoformat()
        with pytest.raises(ValueError, match="as_of_date"):
            with_platform_daily(
                StateDocument(version="2"),
                _PLATFORM,
                _ACCOUNT,
                {unlived: {"spend": 1.0}},
                as_of_date=_anchor(60),
            )

    def test_the_refusal_names_both_dates(self, tmp_path: Path) -> None:
        """The caller stated one date and mureo compared it against another;
        a message carrying only one of them cannot be acted on."""
        path = tmp_path / "STATE.json"
        with pytest.raises(ValueError) as excinfo:
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={(_SERVER_TODAY - timedelta(days=1)).isoformat(): {"spend": 1.0}},
                as_of_date=_anchor(60),
            )
        message = str(excinfo.value)
        assert _anchor(60).isoformat() in message
        assert _SERVER_TODAY.isoformat() in message

    def test_an_anchor_in_the_past_is_left_alone(self, tmp_path: Path) -> None:
        """No bound in the other direction, on purpose: a past anchor only
        makes the check STRICTER — it can refuse a day, never admit one — so
        it is self-limiting, and a caller whose clock is behind learns it from
        an explicit refusal rather than from figures quietly dropped."""
        path = tmp_path / "STATE.json"
        long_ago = _SERVER_TODAY - timedelta(days=400)
        doc = set_platform_daily(
            path,
            _PLATFORM,
            _ACCOUNT,
            days={(long_ago - timedelta(days=1)).isoformat(): {"spend": 1.0}},
            as_of_date=long_ago,
        )
        assert doc.platforms[_PLATFORM].daily
        with pytest.raises(ValueError, match="complete"):
            set_platform_daily(
                path,
                _PLATFORM,
                _ACCOUNT,
                days={(_SERVER_TODAY - timedelta(days=1)).isoformat(): {"spend": 1.0}},
                as_of_date=long_ago,
            )


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

    async def test_the_anchor_is_declared_with_a_date_pattern(self) -> None:
        """``additionalProperties: false`` means an undeclared key is refused
        outright, so the parameter is unreachable until the schema carries
        it — and the pattern is what stops a free-text "today" from ever
        reaching the parse (#660)."""
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [t for t in TOOLS if t.name == "mureo_state_platform_daily_set"]
        anchor = tool.inputSchema["properties"]["as_of_date"]
        assert anchor["type"] == "string"
        assert anchor["pattern"] == r"^\d{4}-\d{2}-\d{2}$"
        # Optional: every caller written before it existed keeps working.
        assert "as_of_date" not in tool.inputSchema["required"]
        text = tool.description + json.dumps(tool.inputSchema)
        assert "timezone" in text.lower()

    async def test_the_dispatcher_refuses_an_anchor_that_is_not_a_date(self) -> None:
        from mureo.mcp.server import _validate_tool_input

        with pytest.raises(ValueError, match="as_of_date"):
            _validate_tool_input(
                "mureo_state_platform_daily_set",
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {"2026-08-20": {"spend": 1.0}},
                    "as_of_date": "today",
                },
            )

    async def test_a_date_shaped_anchor_that_is_not_a_date_is_refused(self) -> None:
        """The pattern cannot tell ``2026-02-30`` from a real date, and an
        anchor mureo cannot place must not quietly fall back to the host
        clock — that is the confusion the parameter removes."""
        with pytest.raises(ValueError, match="as_of_date"):
            await self._call(
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {_day(1): {"spend": 1.0}},
                    "as_of_date": "2026-02-30",
                }
            )

    async def test_the_anchor_reaches_the_write_through_the_real_dispatcher(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end on the defect: schema validation, gates and dispatch, on
        a UTC host writing an Asia/Tokyo account's finished day."""
        from mureo.core import clock
        from mureo.mcp.server import handle_call_tool

        monkeypatch.setattr(clock, "server_now", lambda: _UTC_HOST_NOW)
        arguments = {
            "platform": _PLATFORM,
            "account_id": _ACCOUNT,
            "days": {_COMPLETE_DAY_JST.isoformat(): {"spend": 1200.0}},
            "as_of_date": _ACCOUNT_TODAY.isoformat(),
        }
        result = await handle_call_tool("mureo_state_platform_daily_set", arguments)
        payload = json.loads(result[0].text)
        stored = payload["platforms"][_PLATFORM]["daily"]
        assert stored[_COMPLETE_DAY_JST.isoformat()]["spend"] == 1200.0

    async def test_without_the_anchor_that_same_call_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core import clock

        monkeypatch.setattr(clock, "server_now", lambda: _UTC_HOST_NOW)
        with pytest.raises(ValueError, match="complete"):
            await self._call(
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {_COMPLETE_DAY_JST.isoformat(): {"spend": 1200.0}},
                }
            )

    async def test_a_far_future_anchor_is_refused_through_the_real_dispatcher(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The route that matters most: the caller stating the date here is a
        model, and a mis-inferred year (or an injected one) must not be able
        to file dates nobody has reached as complete history. Schema
        validation and gates included — the anchor passes the ``YYYY-MM-DD``
        pattern, so nothing upstream of the write stops it."""
        from mureo.core import clock
        from mureo.mcp.server import handle_call_tool

        monkeypatch.setattr(clock, "server_now", lambda: _UTC_HOST_NOW)
        unlived = (_SERVER_TODAY + timedelta(days=30)).isoformat()
        with pytest.raises(ValueError, match="as_of_date"):
            await handle_call_tool(
                "mureo_state_platform_daily_set",
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": {unlived: {"spend": 1200.0}},
                    "as_of_date": _anchor(60).isoformat(),
                },
            )
        assert not (tmp_path / "STATE.json").exists()

    async def test_the_tool_states_that_the_anchor_is_checked(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        (tool,) = [t for t in TOOLS if t.name == "mureo_state_platform_daily_set"]
        anchor = tool.inputSchema["properties"]["as_of_date"]["description"]
        assert "2 days ahead" in anchor
        assert "refused" in anchor


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
