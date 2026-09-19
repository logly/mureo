"""History archives beside STATE.json (#758, phase 4a).

Two things STATE.json throws away by design:

- ``daily`` is trimmed to :data:`DAILY_RETENTION_DAYS` on **every** write, so
  the day that falls out of the window is gone — the document cannot answer
  "what did this account spend in July" two months later;
- ``reports[kind]`` is overwritten by every ``set_report``, so only the latest
  version of a report kind survives and nothing can show how a verdict moved.

Neither is a bug: the document is read and re-rendered on every mutation, so
it has to stay bounded. What was missing is somewhere for the trimmed and the
overwritten to GO. ``history/`` beside STATE.json is that place, and what
these tests pin is that the archive is written **before** the loss:

- the days a write is about to drop are archived first, under the state lock,
  and a failure to archive fails the whole write rather than quietly dropping
  them (an archive that can be skipped is not an archive);
- every version ``set_report`` writes is appended to the ledger, including
  the one that stays in STATE.json, so the ledger alone is the full series;
- a corrupt month file is **refused**, never overwritten — silently rewriting
  a file that failed to parse would delete history to tidy it;
- the pure document-level merge (``with_platform_daily``) keeps its #710
  contract: without an ``archive=`` it drops exactly as it always did.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mureo.context import history
from mureo.context.daily import (
    DAILY_RETENTION_DAYS,
    capped_platform_daily,
    dropped_platform_daily,
    with_platform_daily,
)
from mureo.context.errors import ContextFileError
from mureo.context.models import PlatformState, StateDocument
from mureo.context.state import (
    read_state_file,
    set_platform_daily,
    set_report,
    write_state_file,
)
from mureo.core.rotation import MAX_BYTES_ENV_VAR, sibling_files

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

_PLATFORM = "google_ads"
_OTHER = "meta_ads"
_ACCOUNT = "123-456-7890"

#: Frozen host "now": the daily writer refuses today and everything after it,
#: so a suite whose fixtures drift past midnight would refuse yesterday.
_NOW = datetime(2026, 8, 21, 9, 30, tzinfo=timezone(timedelta(hours=9)))
_TODAY = _NOW.date()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from mureo.core import clock

    monkeypatch.setattr(clock, "server_now", lambda: _NOW)


def _day(offset: int) -> str:
    """``offset`` days before the frozen today, as a ``YYYY-MM-DD`` key."""
    return (_TODAY - timedelta(days=offset)).isoformat()


def _bucket(spend: float) -> dict[str, Any]:
    return {"spend": spend, "clicks": 3}


def _days(offsets: range | list[int]) -> dict[str, dict[str, Any]]:
    return {_day(offset): _bucket(float(offset)) for offset in offsets}


def _collected(offsets: range | list[int]) -> dict[str, dict[str, Any]]:
    """Days that already carry a ``fetched_at``, so the writer leaves it."""
    return {
        day: {**bucket, "fetched_at": "2026-08-21T00:00:00+00:00"}
        for day, bucket in _days(offsets).items()
    }


def _state(tmp_path: Path) -> Path:
    fp = tmp_path / "STATE.json"
    write_state_file(fp, StateDocument(version="2"))
    return fp


def _month_file(tmp_path: Path, month: str) -> Path:
    return tmp_path / "history" / "daily" / f"{month}.json"


def _ledger(tmp_path: Path, kind: str) -> Path:
    return tmp_path / "history" / "reports" / f"{kind}.jsonl"


# ---------------------------------------------------------------------------
# The complement of the retention trim
# ---------------------------------------------------------------------------


class TestDroppedIsTheExactComplementOfKept:
    """``dropped_platform_daily`` must be the other half of
    ``capped_platform_daily`` — anything else means a write either archives a
    day it keeps (a duplicate) or drops one it never archived (a loss)."""

    @pytest.mark.parametrize("size", list(range(0, 61)))
    def test_kept_and_dropped_partition_the_map(self, size: int) -> None:
        daily = _days(range(size, 0, -1))
        kept = capped_platform_daily(daily)
        dropped = dropped_platform_daily(daily)

        assert set(kept) & set(dropped) == set()
        assert {**kept, **dropped} == daily
        assert len(dropped) == max(0, size - DAILY_RETENTION_DAYS)

    def test_the_dropped_days_are_the_oldest_ones(self) -> None:
        daily = _days(range(40, 0, -1))
        dropped = dropped_platform_daily(daily)
        assert sorted(dropped) == sorted(_days([40, 39, 38, 37, 36]))

    def test_a_dropped_bucket_is_the_value_that_was_stored(self) -> None:
        daily = _days(range(40, 0, -1))
        assert dropped_platform_daily(daily)[_day(40)] == _bucket(40.0)

    def test_an_undated_key_never_counts_and_is_never_dropped(self) -> None:
        daily: dict[str, dict[str, Any]] = {"summary": {"spend": 1.0}}
        daily.update(_days(range(DAILY_RETENTION_DAYS, 0, -1)))

        assert dropped_platform_daily(daily) == {}
        assert capped_platform_daily(daily) == daily

    def test_an_undated_key_survives_a_trim_that_drops_dated_ones(self) -> None:
        daily: dict[str, dict[str, Any]] = {"summary": {"spend": 1.0}}
        daily.update(_days(range(40, 0, -1)))

        dropped = dropped_platform_daily(daily)
        assert "summary" not in dropped
        assert len(dropped) == 5


# ---------------------------------------------------------------------------
# The pure merge keeps its #710 contract
# ---------------------------------------------------------------------------


class TestWithPlatformDailyStaysPure:
    def test_without_an_archive_it_drops_exactly_as_before(self) -> None:
        doc = with_platform_daily(
            StateDocument(version="2"), _PLATFORM, _ACCOUNT, _days(range(40, 0, -1))
        )
        assert doc.platforms is not None
        daily = doc.platforms[_PLATFORM].daily
        assert daily is not None
        assert len(daily) == DAILY_RETENTION_DAYS
        assert _day(40) not in daily

    def test_an_archive_is_called_once_with_the_dropped_days(self) -> None:
        seen: list[tuple[str, str, dict[str, Any]]] = []

        with_platform_daily(
            StateDocument(version="2"),
            _PLATFORM,
            _ACCOUNT,
            _days(range(40, 0, -1)),
            archive=lambda p, a, d: seen.append((p, a, d)),
        )

        assert len(seen) == 1
        platform, account_id, dropped = seen[0]
        assert (platform, account_id) == (_PLATFORM, _ACCOUNT)
        assert sorted(dropped) == sorted(_days([40, 39, 38, 37, 36]))

    def test_an_archive_is_not_called_when_nothing_is_dropped(self) -> None:
        seen: list[tuple[str, str, dict[str, Any]]] = []

        with_platform_daily(
            StateDocument(version="2"),
            _PLATFORM,
            _ACCOUNT,
            _days(range(5, 0, -1)),
            archive=lambda p, a, d: seen.append((p, a, d)),
        )

        assert seen == []

    def test_a_raising_archive_stops_the_merge(self) -> None:
        def _boom(platform: str, account_id: str, days: dict[str, Any]) -> None:
            raise OSError("no room")

        with pytest.raises(OSError, match="no room"):
            with_platform_daily(
                StateDocument(version="2"),
                _PLATFORM,
                _ACCOUNT,
                _days(range(40, 0, -1)),
                archive=_boom,
            )


# ---------------------------------------------------------------------------
# The daily archive on the STATE.json write path
# ---------------------------------------------------------------------------


class TestSetPlatformDailyArchivesWhatItTrims:
    def test_the_trimmed_days_land_in_the_month_file(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 20, -1)))
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(20, 0, -1)))

        doc = read_state_file(fp)
        assert doc.platforms is not None
        stored = doc.platforms[_PLATFORM].daily
        assert stored is not None
        assert len(stored) == DAILY_RETENTION_DAYS
        assert _day(36) not in stored

        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert archived["v"] == 1
        assert archived["month"] == "2026-07"
        block = archived["platforms"][_PLATFORM]
        assert block["account_id"] == _ACCOUNT
        assert sorted(block["days"]) == sorted(_days([40, 39, 38, 37, 36]))
        assert block["days"][_day(40)]["spend"] == 40.0

    def test_an_archived_bucket_keeps_its_fetched_at(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 0, -1)))

        block = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))[
            "platforms"
        ][_PLATFORM]
        stamped = block["days"][_day(40)]["fetched_at"]
        assert stamped.endswith("+00:00")

    def test_nothing_is_written_until_something_is_dropped(
        self, tmp_path: Path
    ) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(5, 0, -1)))
        assert not (tmp_path / "history").exists()

    def test_re_writing_the_same_days_changes_no_byte(self, tmp_path: Path) -> None:
        """Re-filing a day REPLACES it, so a re-run appends nothing and moves
        nothing. The buckets carry their own ``fetched_at`` here — one the
        writer does not re-stamp — so the comparison is of the archive's
        merge, not of two different collection times."""
        fp = _state(tmp_path)
        collected = _collected(range(40, 0, -1))
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=collected)
        first = _month_file(tmp_path, "2026-07").read_bytes()

        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=collected)
        assert _month_file(tmp_path, "2026-07").read_bytes() == first

    def test_two_platforms_share_one_month_file(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 0, -1)))
        set_platform_daily(fp, _OTHER, "act_999", days=_days(range(40, 0, -1)))

        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert sorted(archived["platforms"]) == sorted([_OTHER, _PLATFORM])
        assert archived["platforms"][_OTHER]["account_id"] == "act_999"
        assert len(archived["platforms"][_PLATFORM]["days"]) == 5

    def test_an_undated_key_already_on_disk_is_never_archived(
        self, tmp_path: Path
    ) -> None:
        fp = tmp_path / "STATE.json"
        stored: dict[str, dict[str, Any]] = {"summary": {"spend": 1.0}}
        stored.update(_days(range(40, 0, -1)))
        write_state_file(
            fp,
            StateDocument(
                version="2",
                platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT, daily=stored)},
            ),
        )

        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days([1]))

        doc = read_state_file(fp)
        assert doc.platforms is not None
        kept = doc.platforms[_PLATFORM].daily
        assert kept is not None and "summary" in kept
        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert "summary" not in archived["platforms"][_PLATFORM]["days"]

    def test_a_corrupt_month_file_refuses_the_write(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        month = _month_file(tmp_path, "2026-07")
        month.parent.mkdir(parents=True, exist_ok=True)
        month.write_text("{not json", encoding="utf-8")
        before = fp.read_bytes()

        with pytest.raises(ContextFileError) as exc:
            set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 0, -1)))

        # The refusal has to say what to DO: an operator who only learns that
        # a file is unreadable has no move that does not risk the history.
        message = str(exc.value)
        assert "2026-07.json" in message
        assert "move" in message
        assert "nothing in STATE.json was changed" in message
        assert fp.read_bytes() == before
        assert month.read_text("utf-8") == "{not json"

    def test_a_failing_archive_leaves_state_json_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(20, 0, -1)))
        before = fp.read_bytes()

        def _boom(path: Path, payload: dict[str, Any]) -> None:
            raise OSError("read-only history")

        monkeypatch.setattr(history, "_atomic_write_json", _boom)

        with pytest.raises(OSError, match="read-only history"):
            set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 20, -1)))

        assert fp.read_bytes() == before


class TestArchivePlatformDailyDirectly:
    def test_days_are_grouped_into_one_file_per_month(self, tmp_path: Path) -> None:
        written = history.archive_platform_daily(
            tmp_path / "STATE.json",
            _PLATFORM,
            _ACCOUNT,
            {"2026-06-30": _bucket(1.0), "2026-07-01": _bucket(2.0)},
        )

        assert [p.name for p in written] == ["2026-06.json", "2026-07.json"]
        june = json.loads(_month_file(tmp_path, "2026-06").read_text("utf-8"))
        assert list(june["platforms"][_PLATFORM]["days"]) == ["2026-06-30"]

    def test_a_day_this_call_supplies_replaces_the_stored_one(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "STATE.json"
        history.archive_platform_daily(
            state_path, _PLATFORM, _ACCOUNT, {"2026-07-01": _bucket(1.0)}
        )
        history.archive_platform_daily(
            state_path, _PLATFORM, _ACCOUNT, {"2026-07-01": _bucket(9.0)}
        )

        days = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))[
            "platforms"
        ][_PLATFORM]["days"]
        assert days["2026-07-01"] == _bucket(9.0)

    def test_other_days_and_other_platforms_survive_a_merge(
        self, tmp_path: Path
    ) -> None:
        state_path = tmp_path / "STATE.json"
        history.archive_platform_daily(
            state_path, _PLATFORM, _ACCOUNT, {"2026-07-01": _bucket(1.0)}
        )
        history.archive_platform_daily(
            state_path, _OTHER, "act_999", {"2026-07-02": _bucket(2.0)}
        )
        history.archive_platform_daily(
            state_path, _PLATFORM, _ACCOUNT, {"2026-07-03": _bucket(3.0)}
        )

        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert list(archived["platforms"][_PLATFORM]["days"]) == [
            "2026-07-01",
            "2026-07-03",
        ]
        assert list(archived["platforms"][_OTHER]["days"]) == ["2026-07-02"]

    def test_an_empty_map_writes_nothing(self, tmp_path: Path) -> None:
        assert (
            history.archive_platform_daily(
                tmp_path / "STATE.json", _PLATFORM, _ACCOUNT, {}
            )
            == []
        )
        assert not (tmp_path / "history").exists()

    def test_a_key_that_is_not_a_date_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a date"):
            history.archive_platform_daily(
                tmp_path / "STATE.json", _PLATFORM, _ACCOUNT, {"../../etc": {}}
            )
        assert not (tmp_path / "history").exists()

    def test_a_month_file_from_a_future_version_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A shape this version cannot merge is left alone, not rewritten in
        the shape it can: a newer mureo may have written it."""
        month = _month_file(tmp_path, "2026-07")
        month.parent.mkdir(parents=True, exist_ok=True)
        month.write_text(
            json.dumps({"v": 2, "month": "2026-07", "platforms": {}}),
            encoding="utf-8",
        )

        with pytest.raises(ContextFileError) as exc:
            history.archive_platform_daily(
                tmp_path / "STATE.json",
                _PLATFORM,
                _ACCOUNT,
                {"2026-07-01": _bucket(1.0)},
            )
        assert "version 2" in str(exc.value)
        assert "move" in str(exc.value)
        assert json.loads(month.read_text("utf-8"))["v"] == 2

    def test_a_platform_block_without_days_does_not_break_a_merge(
        self, tmp_path: Path
    ) -> None:
        month = _month_file(tmp_path, "2026-07")
        month.parent.mkdir(parents=True, exist_ok=True)
        month.write_text(
            json.dumps(
                {
                    "v": 1,
                    "month": "2026-07",
                    "platforms": {_PLATFORM: {"account_id": _ACCOUNT}},
                }
            ),
            encoding="utf-8",
        )

        history.archive_platform_daily(
            tmp_path / "STATE.json", _PLATFORM, _ACCOUNT, {"2026-07-01": _bucket(1.0)}
        )

        days = json.loads(month.read_text("utf-8"))["platforms"][_PLATFORM]["days"]
        assert list(days) == ["2026-07-01"]

    def test_a_month_file_holding_something_else_is_refused(
        self, tmp_path: Path
    ) -> None:
        month = _month_file(tmp_path, "2026-07")
        month.parent.mkdir(parents=True, exist_ok=True)
        month.write_text("[]", encoding="utf-8")

        with pytest.raises(ContextFileError, match="2026-07.json"):
            history.archive_platform_daily(
                tmp_path / "STATE.json",
                _PLATFORM,
                _ACCOUNT,
                {"2026-07-01": _bucket(1.0)},
            )


# ---------------------------------------------------------------------------
# The archive takes its own lock
# ---------------------------------------------------------------------------


class TestTheArchiveIsSerialised:
    """The archive is a read-modify-write on a file STATE.json's lock does not
    cover: the #710 downstream writer holds ITS OWN document lock, not this
    workspace's state lock, so two writers merging into one month would
    last-writer-wins a month of history away. Each month file therefore has
    its own sidecar lock — a different file from ``STATE.json.lock``, so the
    state route (which already holds that one) cannot deadlock on it."""

    def test_the_month_file_has_its_own_lock_beside_it(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 0, -1)))

        lock = tmp_path / "history" / "daily" / "2026-07.json.lock"
        assert lock.exists()
        assert lock != tmp_path / "STATE.json.lock"
        # ...and the write it guarded actually completed (no deadlock against
        # the state lock this call is already holding).
        assert _month_file(tmp_path, "2026-07").exists()

    def test_two_threads_into_one_month_keep_both_platforms(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without the lock this is the classic lost update: both threads read
        the same empty month, both merge their own platform into it, and the
        one that writes second erases the other."""
        state_path = tmp_path / "STATE.json"
        real_write = history._atomic_write_json

        def _slow_write(path: Path, payload: dict[str, Any]) -> None:
            # Widen the read-modify-write window so an unlocked merge loses.
            time.sleep(0.05)
            real_write(path, payload)

        monkeypatch.setattr(history, "_atomic_write_json", _slow_write)
        start = threading.Barrier(2)

        def _archive(platform: str, account_id: str, spend: float) -> None:
            start.wait(timeout=5)
            history.archive_platform_daily(
                state_path, platform, account_id, {"2026-07-01": _bucket(spend)}
            )

        threads = [
            threading.Thread(target=_archive, args=(_PLATFORM, _ACCOUNT, 1.0)),
            threading.Thread(target=_archive, args=(_OTHER, "act_999", 2.0)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()

        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert sorted(archived["platforms"]) == sorted([_OTHER, _PLATFORM])


class TestAMultiMonthArchiveThatFailsHalfway:
    def test_the_state_write_is_abandoned_and_the_retry_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A months-spanning trim writes one file per month, and there is no
        transaction across them. What must hold is the direction of the
        failure: the archive may be ahead of STATE.json, never behind it — so
        the document is left untouched and the same call, retried, converges
        rather than duplicating what the first attempt managed to write."""
        fp = tmp_path / "STATE.json"
        # Enough stored days that the trim drops a run spanning June AND July.
        stored = _collected(range(57, 1, -1))
        write_state_file(
            fp,
            StateDocument(
                version="2",
                platforms={_PLATFORM: PlatformState(account_id=_ACCOUNT, daily=stored)},
            ),
        )
        before = fp.read_bytes()
        real_write = history._atomic_write_json

        def _fail_on_the_second_month(path: Path, payload: dict[str, Any]) -> None:
            if path.name == "2026-07.json":
                raise OSError("disk full")
            real_write(path, payload)

        monkeypatch.setattr(history, "_atomic_write_json", _fail_on_the_second_month)

        with pytest.raises(OSError, match="disk full"):
            set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_collected([1]))

        # June was written, July was not, and the document did not move on.
        assert _month_file(tmp_path, "2026-06").exists()
        assert not _month_file(tmp_path, "2026-07").exists()
        assert fp.read_bytes() == before

        monkeypatch.setattr(history, "_atomic_write_json", real_write)
        june_before = _month_file(tmp_path, "2026-06").read_bytes()
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_collected([1]))

        assert _month_file(tmp_path, "2026-07").exists()
        # The month the first attempt already archived is re-merged, not
        # duplicated or re-stamped.
        assert _month_file(tmp_path, "2026-06").read_bytes() == june_before
        assert read_state_file(fp).platforms is not None


# ---------------------------------------------------------------------------
# Reading the daily archive back
# ---------------------------------------------------------------------------


class TestReadDailyArchive:
    def _seed(self, tmp_path: Path) -> Path:
        state_path = tmp_path / "STATE.json"
        for month, day in (("06", "15"), ("07", "01"), ("07", "20"), ("08", "05")):
            history.archive_platform_daily(
                state_path,
                _PLATFORM,
                _ACCOUNT,
                {f"2026-{month}-{day}": _bucket(float(day))},
            )
        history.archive_platform_daily(
            state_path, _OTHER, "act_999", {"2026-07-02": _bucket(2.0)}
        )
        return state_path

    def test_it_returns_one_platforms_days_in_order(self, tmp_path: Path) -> None:
        read = history.read_daily_archive(self._seed(tmp_path), _PLATFORM)
        assert list(read.days) == [
            "2026-06-15",
            "2026-07-01",
            "2026-07-20",
            "2026-08-05",
        ]
        assert read.skipped_files == ()

    def test_bounds_are_inclusive(self, tmp_path: Path) -> None:
        read = history.read_daily_archive(
            self._seed(tmp_path), _PLATFORM, date(2026, 7, 1), date(2026, 7, 20)
        )
        assert list(read.days) == ["2026-07-01", "2026-07-20"]

    def test_an_unknown_platform_reads_empty(self, tmp_path: Path) -> None:
        read = history.read_daily_archive(self._seed(tmp_path), "plugin:x:y")
        assert read.days == {}

    def test_no_archive_at_all_reads_empty(self, tmp_path: Path) -> None:
        read = history.read_daily_archive(tmp_path / "STATE.json", _PLATFORM)
        assert read.days == {} and read.skipped_files == ()

    def test_only_the_intersecting_months_are_opened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state_path = self._seed(tmp_path)
        opened: list[str] = []
        real = Path.read_text

        def _spy(self: Path, *args: Any, **kwargs: Any) -> str:
            opened.append(self.name)
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _spy)
        history.read_daily_archive(
            state_path, _PLATFORM, date(2026, 7, 2), date(2026, 7, 30)
        )

        assert opened == ["2026-07.json"]

    def test_an_unreadable_month_file_is_skipped_and_named(
        self, tmp_path: Path
    ) -> None:
        state_path = self._seed(tmp_path)
        _month_file(tmp_path, "2026-07").write_text("{oops", encoding="utf-8")

        read = history.read_daily_archive(state_path, _PLATFORM)
        assert list(read.days) == ["2026-06-15", "2026-08-05"]
        assert read.skipped_files == ("2026-07.json",)

    @pytest.mark.parametrize(
        ("payload", "case"),
        [
            ({"v": 2, "month": "2026-07", "platforms": {}}, "a newer version"),
            ({"month": "2026-07", "platforms": {}}, "no version at all"),
            ({"v": 1, "month": "2026-07"}, "no platforms map"),
            ({"v": 1, "month": "2026-07", "platforms": []}, "platforms not a map"),
        ],
    )
    def test_a_file_this_version_cannot_read_is_skipped_and_named(
        self, tmp_path: Path, payload: dict[str, Any], case: str
    ) -> None:
        """Reading is tolerant where writing is strict — but "tolerant" means
        SAID, not swallowed: a month this version cannot read is reported in
        ``skipped_files`` so the caller never presents a short series as the
        whole of it."""
        state_path = self._seed(tmp_path)
        _month_file(tmp_path, "2026-07").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        read = history.read_daily_archive(state_path, _PLATFORM)
        assert read.skipped_files == ("2026-07.json",), case
        assert list(read.days) == ["2026-06-15", "2026-08-05"]

    def test_a_file_that_is_not_a_month_is_ignored(self, tmp_path: Path) -> None:
        state_path = self._seed(tmp_path)
        (tmp_path / "history" / "daily" / "notes.txt").write_text("x", encoding="utf-8")

        read = history.read_daily_archive(state_path, _PLATFORM)
        assert read.skipped_files == ()
        assert len(read.days) == 4


# ---------------------------------------------------------------------------
# The report ledger
# ---------------------------------------------------------------------------


class TestSetReportKeepsEveryVersion:
    def test_every_write_appends_a_line_oldest_first(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "first"})
        set_report(fp, "daily", {"narrative": "second"})

        lines = _ledger(tmp_path, "daily").read_text("utf-8").splitlines()
        assert len(lines) == 2
        assert [json.loads(line)["summary"]["narrative"] for line in lines] == [
            "first",
            "second",
        ]

    def test_state_json_still_holds_only_the_latest(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "first"})
        set_report(fp, "daily", {"narrative": "second"})

        doc = read_state_file(fp)
        assert doc.reports == {"daily": {"narrative": "second"}}

    def test_each_kind_has_its_own_ledger(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "d"})
        set_report(fp, "weekly", {"narrative": "w"})

        assert _ledger(tmp_path, "daily").read_text("utf-8").count("\n") == 1
        assert _ledger(tmp_path, "weekly").read_text("utf-8").count("\n") == 1

    def test_the_entry_carries_the_session_and_a_utc_timestamp(
        self, tmp_path: Path
    ) -> None:
        from mureo.core.actor import session_id

        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "x"})

        entry = json.loads(
            _ledger(tmp_path, "daily").read_text("utf-8").splitlines()[0]
        )
        assert entry["v"] == 1
        assert entry["kind"] == "daily"
        assert entry["session_id"] == session_id()
        assert datetime.fromisoformat(entry["recorded_at"]).tzinfo is not None
        assert datetime.fromisoformat(entry["recorded_at"]).utcoffset() == timedelta(0)

    def test_the_client_is_omitted_when_unknown(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "x"})

        entry = json.loads(
            _ledger(tmp_path, "daily").read_text("utf-8").splitlines()[0]
        )
        assert "client" not in entry

    def test_the_client_is_recorded_when_known(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.core import actor

        monkeypatch.setattr(actor, "_client", "claude-code/1.2.3")
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "x"})

        entry = json.loads(
            _ledger(tmp_path, "daily").read_text("utf-8").splitlines()[0]
        )
        assert entry["client"] == "claude-code/1.2.3"

    def test_a_refused_summary_appends_nothing(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        with pytest.raises(ValueError):
            set_report(fp, "daily", {"narrative": "x" * 5000})
        assert not (tmp_path / "history").exists()

    def test_a_failing_append_leaves_state_json_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fp = _state(tmp_path)
        before = fp.read_bytes()

        def _boom(path: Path, payload: dict[str, Any]) -> None:
            raise OSError("no ledger")

        monkeypatch.setattr(history, "_append_json_line", _boom)

        with pytest.raises(OSError, match="no ledger"):
            set_report(fp, "daily", {"narrative": "x"})

        assert fp.read_bytes() == before
        assert read_state_file(fp).reports is None


class TestReportLedgerKindSafety:
    """An allowlist, not a blocklist: the kinds that may name a file are
    enumerated, so the next separator, drive letter or encoding trick nobody
    thought of is refused by default rather than by having been predicted."""

    @pytest.mark.parametrize(
        "kind",
        [
            "..",
            "../secrets",
            "..evil",
            "a..b",
            "a/b",
            "a\\b",
            "C:evil",
            "nul\x00kind",
            "with space",
            "über",
            "",
            "   ",
        ],
    )
    def test_a_kind_that_cannot_name_a_file_is_refused(
        self, tmp_path: Path, kind: str
    ) -> None:
        with pytest.raises(ValueError, match="report kind"):
            history.append_report_history(tmp_path / "STATE.json", kind, {"a": 1})
        assert not (tmp_path / "history").exists()

    @pytest.mark.parametrize("kind", ["daily", "weekly", "goal", "a_b-c.1"])
    def test_an_ordinary_kind_is_accepted(self, kind: str) -> None:
        assert history.validate_report_kind_path(kind) == kind

    def test_every_shipped_report_kind_passes(self) -> None:
        """The allowlist has to admit the vocabulary the tool enum offers, or
        a caller would be refused for using a kind mureo documents."""
        from mureo.core.report_kinds import REPORT_KINDS

        for kind in REPORT_KINDS:
            assert history.validate_report_kind_path(kind) == kind

    def test_the_same_rule_guards_the_reader(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="report kind"):
            history.read_report_history(tmp_path / "STATE.json", "../x", limit=5)

    def test_set_report_refuses_a_bad_kind_before_it_takes_the_lock(
        self, tmp_path: Path
    ) -> None:
        """Refused beside the summary validation, so a bad kind never opens
        STATE.json, never takes the state lock and never re-stamps anything."""
        fp = _state(tmp_path)
        before = fp.read_bytes()

        with pytest.raises(ValueError, match="report kind"):
            set_report(fp, "../escape", {"narrative": "x"})

        assert fp.read_bytes() == before
        assert not (tmp_path / "STATE.json.lock").exists()
        assert not (tmp_path / "history").exists()


class TestReadReportHistory:
    def _seed(self, tmp_path: Path, count: int) -> Path:
        fp = _state(tmp_path)
        for index in range(count):
            set_report(fp, "daily", {"narrative": f"v{index}"})
        return fp

    def test_the_newest_entries_are_returned_last(self, tmp_path: Path) -> None:
        fp = self._seed(tmp_path, 3)
        read = history.read_report_history(fp, "daily", limit=10)
        assert [e["summary"]["narrative"] for e in read.entries] == ["v0", "v1", "v2"]
        assert read.skipped_lines == 0

    def test_a_limit_keeps_only_the_newest(self, tmp_path: Path) -> None:
        fp = self._seed(tmp_path, 3)
        read = history.read_report_history(fp, "daily", limit=1)
        assert [e["summary"]["narrative"] for e in read.entries] == ["v2"]

    def test_since_drops_older_entries(self, tmp_path: Path) -> None:
        fp = self._seed(tmp_path, 2)
        today = datetime.now(timezone.utc).date()
        assert history.read_report_history(fp, "daily", limit=10, since=today).entries
        ahead = today + timedelta(days=1)
        assert (
            history.read_report_history(fp, "daily", limit=10, since=ahead).entries
            == ()
        )

    def test_a_timestamp_written_with_a_trailing_z_is_still_dated(
        self, tmp_path: Path
    ) -> None:
        """``2026-08-20T00:00:00Z`` is the spelling half the world writes and
        the one ``fromisoformat`` could not read before 3.11 — a ledger line
        carrying it must not silently fall out of every bounded query."""
        fp = _state(tmp_path)
        _ledger(tmp_path, "daily").parent.mkdir(parents=True, exist_ok=True)
        _ledger(tmp_path, "daily").write_text(
            json.dumps(
                {
                    "v": 1,
                    "kind": "daily",
                    "recorded_at": "2026-08-20T00:00:00Z",
                    "summary": {"narrative": "zulu"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        read = history.read_report_history(
            fp, "daily", limit=10, since=date(2026, 8, 20)
        )
        assert [e["summary"]["narrative"] for e in read.entries] == ["zulu"]
        assert (
            history.read_report_history(
                fp, "daily", limit=10, since=date(2026, 8, 21)
            ).entries
            == ()
        )

    def test_a_corrupt_line_is_counted_not_raised(self, tmp_path: Path) -> None:
        fp = self._seed(tmp_path, 1)
        with _ledger(tmp_path, "daily").open("a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        set_report(fp, "daily", {"narrative": "after"})

        read = history.read_report_history(fp, "daily", limit=10)
        assert [e["summary"]["narrative"] for e in read.entries] == ["v0", "after"]
        assert read.skipped_lines == 1

    def test_a_missing_ledger_reads_empty(self, tmp_path: Path) -> None:
        read = history.read_report_history(tmp_path / "STATE.json", "daily", limit=10)
        assert read.entries == () and read.skipped_lines == 0

    def test_a_limit_below_one_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="limit"):
            history.read_report_history(tmp_path / "STATE.json", "daily", limit=0)


# ---------------------------------------------------------------------------
# Rotation — the ledger is bounded per file, never in what it keeps (#758 p6)
# ---------------------------------------------------------------------------


class TestTheReportLedgerRotates:
    def test_a_full_ledger_is_retired_before_the_next_append(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        fp = _state(tmp_path)
        for index in range(12):
            set_report(fp, "daily", {"narrative": f"v{index}"})

        files = sibling_files(_ledger(tmp_path, "daily"))
        assert len(files) > 1, files
        assert all(path.stat().st_size > 0 for path in files)

    def test_nothing_is_lost_to_a_rotation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bound is on one file's size, never on the history kept."""
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        fp = _state(tmp_path)
        for index in range(12):
            set_report(fp, "daily", {"narrative": f"v{index}"})

        read = history.read_report_history(fp, "daily", limit=50)
        assert [e["summary"]["narrative"] for e in read.entries] == [
            f"v{index}" for index in range(12)
        ]
        assert read.skipped_lines == 0

    def test_the_limit_still_takes_the_newest_across_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MAX_BYTES_ENV_VAR, "400")
        fp = _state(tmp_path)
        for index in range(12):
            set_report(fp, "daily", {"narrative": f"v{index}"})

        read = history.read_report_history(fp, "daily", limit=2)
        assert [e["summary"]["narrative"] for e in read.entries] == ["v10", "v11"]

    def test_a_corrupt_line_in_a_rotated_file_is_counted_not_raised(
        self, tmp_path: Path
    ) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "live"})
        rotated = _ledger(tmp_path, "daily").with_name("daily.20260919T000000Z.jsonl")
        rotated.write_text("{not json\n", encoding="utf-8")

        read = history.read_report_history(fp, "daily", limit=10)
        assert [e["summary"]["narrative"] for e in read.entries] == ["live"]
        assert read.skipped_lines == 1

    def test_only_the_live_file_is_written_to(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rotated file is closed: an append after it must not reopen it."""
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "first"})
        ledger = _ledger(tmp_path, "daily")
        rotated = ledger.with_name("daily.20260919T000000Z.jsonl")
        ledger.rename(rotated)
        before = rotated.read_bytes()

        set_report(fp, "daily", {"narrative": "second"})

        assert rotated.read_bytes() == before
        read = history.read_report_history(fp, "daily", limit=10)
        assert [e["summary"]["narrative"] for e in read.entries] == [
            "first",
            "second",
        ]


# ---------------------------------------------------------------------------
# Permissions — the archive carries the same account figures STATE.json does
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
class TestArchiveFilesAreOwnerOnly:
    def test_a_month_file_is_0600(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_platform_daily(fp, _PLATFORM, _ACCOUNT, days=_days(range(40, 0, -1)))
        mode = stat.S_IMODE(os.stat(_month_file(tmp_path, "2026-07")).st_mode)
        assert mode == 0o600

    def test_a_report_ledger_is_0600(self, tmp_path: Path) -> None:
        fp = _state(tmp_path)
        set_report(fp, "daily", {"narrative": "x"})
        mode = stat.S_IMODE(os.stat(_ledger(tmp_path, "daily")).st_mode)
        assert mode == 0o600


class TestHistoryLayout:
    def test_the_directory_sits_beside_state_json(self, tmp_path: Path) -> None:
        assert history.history_dir(tmp_path / "STATE.json") == tmp_path / "history"

    def test_the_read_results_are_hashable(self, tmp_path: Path) -> None:
        """A frozen dataclass generates a ``__hash__`` from its fields, and
        these hold dicts — so hashing one would raise. Pinned because the
        failure would surface in a caller (a set, a cache key), not here."""
        daily = history.read_daily_archive(tmp_path / "STATE.json", _PLATFORM)
        reports = history.read_report_history(tmp_path / "STATE.json", "daily", limit=1)
        assert {daily, reports}


# ---------------------------------------------------------------------------
# The route a real MCP client takes
# ---------------------------------------------------------------------------


class TestTheMcpRouteArchivesToo:
    """``mureo_state_platform_daily_set`` reaches the archive through
    ``set_platform_daily`` and needs no wiring of its own — asserted here
    rather than assumed, through ``handle_call_tool`` (the path a client
    actually takes), because "needs no change" is exactly the kind of claim
    that stops being true silently."""

    @pytest.fixture(autouse=True)
    def _workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[Path]:
        from mureo.core.runtime_context import reset_runtime_context

        reset_runtime_context()
        monkeypatch.chdir(tmp_path)
        yield tmp_path
        reset_runtime_context()

    async def test_the_tool_call_archives_what_it_trims(self, tmp_path: Path) -> None:
        from mureo.mcp import server as server_mod

        await server_mod.handle_call_tool(
            "mureo_state_platform_daily_set",
            {
                "platform": _PLATFORM,
                "account_id": _ACCOUNT,
                "days": _days(range(40, 0, -1)),
            },
        )

        archived = json.loads(_month_file(tmp_path, "2026-07").read_text("utf-8"))
        assert sorted(archived["platforms"][_PLATFORM]["days"]) == sorted(
            _days([40, 39, 38, 37, 36])
        )
        stored = json.loads((tmp_path / "STATE.json").read_text("utf-8"))
        assert len(stored["platforms"][_PLATFORM]["daily"]) == DAILY_RETENTION_DAYS

    async def test_a_corrupt_month_file_comes_back_as_a_tool_error(
        self, tmp_path: Path
    ) -> None:
        """The handler translates ``ContextFileError`` into ``ValueError`` so
        the client sees a tool error rather than a server crash — and the
        document is left exactly as it was."""
        from mureo.mcp import server as server_mod

        await server_mod.handle_call_tool(
            "mureo_state_platform_daily_set",
            {
                "platform": _PLATFORM,
                "account_id": _ACCOUNT,
                "days": _days(range(20, 0, -1)),
            },
        )
        before = (tmp_path / "STATE.json").read_bytes()
        month = _month_file(tmp_path, "2026-07")
        month.parent.mkdir(parents=True, exist_ok=True)
        month.write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError) as exc:
            await server_mod.handle_call_tool(
                "mureo_state_platform_daily_set",
                {
                    "platform": _PLATFORM,
                    "account_id": _ACCOUNT,
                    "days": _days(range(40, 20, -1)),
                },
            )

        assert "2026-07.json" in str(exc.value)
        assert (tmp_path / "STATE.json").read_bytes() == before
        assert month.read_text("utf-8") == "{not json"

    async def test_the_report_tool_appends_a_ledger_line(self, tmp_path: Path) -> None:
        from mureo.mcp import server as server_mod

        await server_mod.handle_call_tool(
            "mureo_state_report_set",
            {"report": "daily", "summary": {"narrative": "through the dispatcher"}},
        )

        lines = _ledger(tmp_path, "daily").read_text("utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["summary"]["narrative"] == "through the dispatcher"
