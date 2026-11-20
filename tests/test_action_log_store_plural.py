"""``append_action_logs`` files several entries with one STATE.json write (#1018).

Each ``append_action_log`` call is a full locked read, render and atomic
write of a document that grows with every row, so filing N entries one by
one costs time quadratic in N. The plural entry point runs the same steps per
entry inside ONE locked mutation, so N entries cost one write and a failure
on any of them leaves the file exactly as it was.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import mureo.context.state_io as state_io
from mureo.context.action_log_store import append_action_logs
from mureo.context.batch import BatchError
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry, StateDocument
from mureo.context.ops_intent import bind_ops_intent
from mureo.context.state import (
    append_action_log,
    begin_batch,
    read_state_file,
    write_state_file,
)
from mureo.core import clock
from mureo.core.actor import bind_call_reason
from mureo.core.display_contract import ACTION_LOG_DISPLAY_TITLE_MAX_CHARS

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 11, 20, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "server_now", lambda: FROZEN)


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every ``write_state_file`` call made by the locked mutation."""
    calls: list[Path] = []
    real = state_io.write_state_file

    def _spy(path: Path, doc: StateDocument, **kwargs: Any) -> None:
        calls.append(path)
        real(path, doc, **kwargs)

    monkeypatch.setattr(state_io, "write_state_file", _spy)
    return calls


def _entry(tag: str, **extra: Any) -> ActionLogEntry:
    # Observed by default: the plural entry point files nothing else.
    extra.setdefault("origin", EXTERNAL_ORIGIN)
    return ActionLogEntry(
        timestamp="2026-11-20T08:00:00+00:00",
        action="google_ads_campaigns_update_status",
        platform="google_ads",
        campaign_id=tag,
        summary=tag,
        **extra,
    )


def _seeded(tmp_path: Path, name: str = "STATE.json") -> Path:
    path = tmp_path / name
    write_state_file(path, StateDocument(version="2", action_log=(_entry("seed"),)))
    return path


def test_several_entries_are_appended_in_order_with_one_write(
    tmp_path: Path, writes: list[Path]
) -> None:
    path = _seeded(tmp_path)

    written = append_action_logs(path, [_entry("a"), _entry("b"), _entry("c")])

    assert len(writes) == 1
    summaries = [e.summary for e in read_state_file(path).action_log]
    assert summaries == ["seed", "a", "b", "c"]
    assert [e.summary for e in written.action_log] == summaries


def test_no_entries_writes_nothing_and_returns_the_document_on_disk(
    tmp_path: Path, writes: list[Path]
) -> None:
    path = _seeded(tmp_path)
    before = path.read_bytes()

    returned = append_action_logs(path, [])

    assert writes == []
    assert path.read_bytes() == before
    assert returned == read_state_file(path)


def test_an_entry_over_the_display_bound_refuses_the_whole_call(
    tmp_path: Path, writes: list[Path]
) -> None:
    path = _seeded(tmp_path)
    before = path.read_bytes()
    too_long = _entry(
        "bad", display_title="x" * (ACTION_LOG_DISPLAY_TITLE_MAX_CHARS + 1)
    )

    with pytest.raises(ValueError):
        append_action_logs(path, [_entry("a"), too_long, _entry("c")])

    assert writes == []
    assert path.read_bytes() == before


def test_an_entry_of_mureos_own_refuses_the_whole_call(
    tmp_path: Path, writes: list[Path]
) -> None:
    """A change of mureo's own shares its decision only once written.

    Two of them in one write would each open a decision, so the plural entry
    point takes observed entries only and says which call to use instead.
    """
    path = _seeded(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="observed entries only"):
        append_action_logs(path, [_entry("a"), _entry("own", origin=None)])

    assert writes == []
    assert path.read_bytes() == before


def test_an_unknown_batch_id_refuses_the_whole_call(
    tmp_path: Path, writes: list[Path]
) -> None:
    path = _seeded(tmp_path)
    before = path.read_bytes()

    with pytest.raises(BatchError):
        append_action_logs(path, [_entry("a"), _entry("b", batch_id="no-such")])

    assert writes == []
    assert path.read_bytes() == before


def test_entries_stay_out_of_an_open_batch(tmp_path: Path) -> None:
    path = _seeded(tmp_path)
    begin_batch(path, label="monday")

    append_action_logs(path, [_entry("a"), _entry("b")])

    assert [e.batch_id for e in read_state_file(path).action_log[1:]] == [None, None]


def test_an_explicit_declared_batch_id_is_kept(tmp_path: Path) -> None:
    path = _seeded(tmp_path)
    batch = begin_batch(path, label="monday")

    append_action_logs(path, [_entry("a", batch_id=batch.batch_id), _entry("b")])

    members = [e.batch_id for e in read_state_file(path).action_log[1:]]
    assert members == [batch.batch_id, None]


def test_observed_entries_leave_the_calls_decision_slot_untouched(
    tmp_path: Path,
) -> None:
    """Only a change of mureo's own marks the call as having written one.

    A tool call that files observed entries and then records nothing of its
    own must still read as a call that changed nothing.
    """
    path = _seeded(tmp_path)

    with (
        bind_call_reason("polling before the daily check"),
        bind_ops_intent() as intent,
    ):
        written = append_action_logs(path, [_entry("a"), _entry("b")])

    assert intent.slot.wrote_entry is False
    assert intent.slot.decision_id is None
    assert written.decisions == ()
    assert [e.reason for e in written.action_log[1:]] == [None, None]


def test_one_call_files_what_two_single_appends_would(tmp_path: Path) -> None:
    plural = _seeded(tmp_path)
    single = tmp_path / "single.json"
    shutil.copyfile(plural, single)
    a, b = _entry("a"), _entry("b")

    append_action_logs(plural, [a, b])
    append_action_log(single, a)
    append_action_log(single, b)

    assert read_state_file(plural).action_log == read_state_file(single).action_log
